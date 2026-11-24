# -*- coding: utf-8 -*-
"""verify.py — 经 Crossref API 核验带 DOI 条目的元数据真实性。

状态机：
  verified          DOI 有记录，且题名与年份均取得并一致
  partial_verified  记录存在，但远程缺少题名或年份等字段，只能核对部分字段
  mismatch          记录存在，题名/年份/首作者/容器名出现实质差异
  not_found         Crossref 返回 404（疑似编造条目或 DOI 错误）
  unverified        条目无 DOI 或 DOI 格式非法，无法自动核验
  offline           网络不可用、超时、限流或服务器错误（含 --offline）

原则：网络不可用绝不冒充核验成功；同一 DOI 只请求一次（运行内缓存）；
仅声明接入 Crossref，不假装接入其他数据库。仅依赖标准库。
"""
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CROSSREF = "https://api.crossref.org/works/"
TIMEOUT = 10
MAX_RETRIES = 2           # 429 限流时有限重试
RETRY_BACKOFF = 3         # 秒
UA = {"User-Agent": "citation-manager/1.1 (mailto:anonymous@example.org)"}

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def norm_doi(d):
    d = (d or "").lower().strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d


def norm(t):
    return re.sub(r"[^0-9a-z一-鿿]+", "", (t or "").lower())


def first_author_surname(authors):
    if not authors:
        return ""
    a = authors[0]
    if re.search(r"[一-鿿]", a):
        return a.strip()[:1]
    if "," in a:
        return a.split(",", 1)[0].strip().lower()
    parts = a.split()
    return parts[-1].lower() if parts else ""


def check_doi(doi):
    """返回 (record, None) 或 (None, (status, reason))。限流时有限重试一次。"""
    url = CROSSREF + urllib.parse.quote(doi)
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, ("not_found", "Crossref 无此 DOI 记录（疑似编造条目或 DOI 错误）")
            if exc.code == 429 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)
                continue
            if exc.code == 429:
                return None, ("offline", "Crossref 限流（HTTP 429），重试后仍失败")
            return None, ("offline", "Crossref 服务器错误（HTTP %s）" % exc.code)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return None, ("offline", "网络异常：%s" % exc)
    msg = data.get("message", {})
    title = (msg.get("title") or [""])[0]
    year = ""
    for key in ("published-print", "published-online", "issued"):
        parts = msg.get(key, {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    container = (msg.get("container-title") or [""])[0]
    authors = msg.get("author") or []
    first_surname = (authors[0].get("family", "") if authors else "").lower()
    return {
        "title": title, "year": year, "container": container,
        "first_author_surname": first_surname, "type": msg.get("type", ""),
    }, None


def compare(e, remote):
    """逐字段比对。返回 (problems, checked_fields, missing_remote_fields)。"""
    problems, checked, missing = [], [], []
    if remote["title"]:
        checked.append("title")
        a, b = norm(remote["title"]), norm(e.get("title"))
        if a and b and a != b and a not in b and b not in a:
            problems.append("题名不符：Crossref=「%s」，条目=「%s」" % (remote["title"], e.get("title")))
    else:
        missing.append("title")
    if remote["year"]:
        checked.append("year")
        if e.get("year") and remote["year"] != str(e["year"]):
            problems.append("年份不符：Crossref=%s，条目=%s" % (remote["year"], e["year"]))
    else:
        missing.append("year")
    if remote["first_author_surname"] and first_author_surname(e.get("authors", [])):
        checked.append("first_author")
        if remote["first_author_surname"] != first_author_surname(e["authors"]):
            problems.append("首作者姓不符：Crossref=%s，条目=%s" % (
                remote["first_author_surname"], first_author_surname(e["authors"])))
    if remote["container"] and e.get("journal"):
        checked.append("container")
        a, b = norm(remote["container"]), norm(e["journal"])
        if a and b and a != b and a not in b and b not in a:
            problems.append("刊名不符：Crossref=「%s」，条目=「%s」" % (remote["container"], e["journal"]))
    return problems, checked, missing


def verify_entries(entries, offline=False):
    results, cache = [], {}
    network_down = offline
    for e in entries:
        checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        rec = {"id": e["id"], "doi": e.get("doi", ""), "title": e.get("title", ""),
               "source": "crossref", "checked_at": checked_at}
        doi = norm_doi(e.get("doi"))
        if not e.get("doi"):
            rec.update(status="unverified", reason="无 DOI，无法自动核验")
            results.append(rec)
            continue
        if not DOI_RE.match(doi):
            rec.update(status="unverified", reason="DOI 格式非法：「%s」" % e.get("doi"))
            results.append(rec)
            continue
        rec["doi_normalized"] = doi
        if network_down:
            rec.update(status="offline", reason="网络不可用或已指定 --offline")
            results.append(rec)
            continue
        if doi in cache:
            remote, err = cache[doi]
            rec["note"] = "同一 DOI 已核验，复用本次运行缓存"
        else:
            remote, err = check_doi(doi)
            cache[doi] = (remote, err)
        if err:
            status, reason = err
            if status == "offline" and "网络异常" in reason:
                network_down = True  # 网络已断，后续条目不再逐一等待超时
            rec.update(status=status, reason=reason)
            results.append(rec)
            continue
        problems, checked, missing = compare(e, remote)
        rec["crossref"] = remote
        rec["fields_checked"] = checked
        if problems:
            rec.update(status="mismatch", reason="；".join(problems))
        elif missing:
            rec.update(status="partial_verified",
                       reason="Crossref 记录缺少字段（%s），仅核对了 %s" % (
                           ",".join(missing), ",".join(checked) or "无"))
        else:
            rec.update(status="verified", reason="已核对字段：%s" % ",".join(checked))
        results.append(rec)
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"source": "crossref", "summary": summary, "records": results}


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    offline = "--offline" in sys.argv
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    report = verify_entries(entries, offline=offline)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("核验汇总：%s" % json.dumps(report["summary"], ensure_ascii=False))
