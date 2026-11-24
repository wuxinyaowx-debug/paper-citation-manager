# -*- coding: utf-8 -*-
"""verify.py — 经 Crossref API 核验带 DOI 条目的元数据真实性。

状态：verified / mismatch / not_found / unverified(无 DOI) / offline(网络不可用)。
离线时全部降级为 offline，绝不把未核验写成已核验。仅依赖标准库。
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CROSSREF = "https://api.crossref.org/works/"
TIMEOUT = 10
UA = {"User-Agent": "citation-manager/1.0 (mailto:anonymous@example.org)"}


def norm(t):
    return re.sub(r"[^0-9a-z一-鿿]+", "", (t or "").lower())


def check_doi(doi):
    url = CROSSREF + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)
    msg = data.get("message", {})
    title = (msg.get("title") or [""])[0]
    year = ""
    for key in ("published-print", "published-online", "issued"):
        parts = msg.get(key, {}).get("date-parts")
        if parts and parts[0]:
            year = str(parts[0][0])
            break
    container = (msg.get("container-title") or [""])[0]
    return {"title": title, "year": year, "container": container, "type": msg.get("type", "")}


def verify_entries(entries, offline=False):
    results = []
    network_down = offline
    for e in entries:
        rec = {"id": e["id"], "doi": e.get("doi", ""), "title": e.get("title", "")}
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", (e.get("doi") or "").strip().lower())
        if not doi:
            rec.update(status="unverified", reason="无 DOI，无法自动核验")
            results.append(rec)
            continue
        if network_down:
            rec.update(status="offline", reason="网络不可用或已指定 --offline")
            results.append(rec)
            continue
        try:
            remote = check_doi(doi)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                rec.update(status="not_found", reason="Crossref 无此 DOI 记录（疑似编造或 DOI 错误）")
            else:
                rec.update(status="offline", reason="HTTP %s" % exc.code)
            results.append(rec)
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            network_down = True
            rec.update(status="offline", reason="网络异常：%s" % exc)
            results.append(rec)
            continue
        problems = []
        if remote["title"] and norm(remote["title"]) != norm(e.get("title")):
            # 允许一方为另一方子串（副标题差异）
            a, b = norm(remote["title"]), norm(e.get("title"))
            if a not in b and b not in a:
                problems.append("题名不符：Crossref=「%s」" % remote["title"])
        if remote["year"] and e.get("year") and remote["year"] != str(e["year"]):
            problems.append("年份不符：Crossref=%s，条目=%s" % (remote["year"], e["year"]))
        rec["crossref"] = remote
        if problems:
            rec.update(status="mismatch", reason="；".join(problems))
        else:
            rec.update(status="verified", reason="题名与年份一致")
        results.append(rec)
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"summary": summary, "records": results}


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
