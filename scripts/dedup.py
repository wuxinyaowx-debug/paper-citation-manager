# -*- coding: utf-8 -*-
"""dedup.py — 文献条目去重与归并，决策可解释、可人工否决。

判据（满足其一即合并，优先级从高到低）：
  R1 doi_exact            DOI 规范化后精确一致
  R2 arxiv_exact          arXiv 号一致（覆盖预印本 vs 正式版的情形之一）
  R3 title_author_year    规范化标题相似度 >= 0.95 且第一作者姓一致且年份差 <= 1
防误并：标题相同但年份差 > 1 -> 不合并，标记 possible_different_works。
中英文题名互译造成的同文：脚本无法判定，输出 candidates_title_loose 供人工确认。
"""
import difflib
import json
import re
import sys

TITLE_SIM_THRESHOLD = 0.95
LOOSE_THRESHOLD = 0.80  # 仅提示，不自动合并


def norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^0-9a-z一-鿿]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_doi(d):
    d = (d or "").lower().strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d


def first_author_surname(authors):
    if not authors:
        return ""
    a = authors[0]
    if re.search(r"[一-鿿]", a):
        return a.strip()[:1]  # 中文取姓氏首字（置于名前）
    if "," in a:
        return a.split(",", 1)[0].strip().lower()
    parts = a.split()
    return parts[-1].lower() if parts else ""


def year_int(y):
    m = re.match(r"\d{4}", str(y or ""))
    return int(m.group(0)) if m else None


def priority(e):
    """正式发表版 > 预印本；字段更全者优先。"""
    score = 0
    if e.get("doi"):
        score += 10
    if e.get("journal"):
        score += 5
    if e.get("volume") and e.get("pages"):
        score += 3
    if e["type"] == "preprint":
        score -= 5
    score += sum(1 for k in ("authors", "year", "issue", "publisher", "url") if e.get(k))
    return score


def merge_into(kept, other):
    """把 other 的缺失字段回填到 kept，记录来源别名。"""
    for k in ("doi", "arxiv", "url", "volume", "issue", "pages", "journal",
              "booktitle", "publisher", "address", "year"):
        if not kept.get(k) and other.get(k):
            kept[k] = other[k]
    if not kept.get("authors") and other.get("authors"):
        kept["authors"] = other["authors"]
    for alias_key in ("title",):
        if other.get(alias_key) and other[alias_key] != kept.get(alias_key):
            kept["aliases"].append(other[alias_key])
    kept.setdefault("merged_from", []).append({
        "id": other["id"], "file": other["source"].get("file"),
        "key": other["source"].get("key"),
    })


def dedup(entries):
    n = len(entries)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    decisions = []   # 合并决策日志
    warnings = []    # 防误并提示
    loose = []       # 低置信候选，供人工确认

    doi_idx, arxiv_idx = {}, {}
    for i, e in enumerate(entries):
        d = norm_doi(e.get("doi"))
        if d:
            if d in doi_idx:
                union(i, doi_idx[d])
                decisions.append({"rule": "doi_exact", "ids": [entries[doi_idx[d]]["id"], e["id"]],
                                  "evidence": "DOI=%s" % d})
            else:
                doi_idx[d] = i
        ax = re.sub(r"v\d+$", "", (e.get("arxiv") or "").strip())
        if ax:
            if ax in arxiv_idx:
                union(i, arxiv_idx[ax])
                decisions.append({"rule": "arxiv_exact", "ids": [entries[arxiv_idx[ax]]["id"], e["id"]],
                                  "evidence": "arXiv=%s" % ax})
            else:
                arxiv_idx[ax] = i

    norms = [norm_title(e.get("title")) for e in entries]
    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j) or not norms[i] or not norms[j]:
                continue
            sim = difflib.SequenceMatcher(None, norms[i], norms[j]).ratio()
            if sim < LOOSE_THRESHOLD:
                continue
            same_author = (first_author_surname(entries[i]["authors"]) ==
                           first_author_surname(entries[j]["authors"]) != "")
            yi, yj = year_int(entries[i].get("year")), year_int(entries[j].get("year"))
            ydiff = abs(yi - yj) if yi and yj else 0
            if sim >= TITLE_SIM_THRESHOLD and same_author and ydiff <= 1:
                union(i, j)
                decisions.append({
                    "rule": "title_author_year",
                    "ids": [entries[i]["id"], entries[j]["id"]],
                    "evidence": "标题相似度=%.3f，第一作者姓=%s，年份差=%d" % (
                        sim, first_author_surname(entries[i]["authors"]), ydiff),
                })
            elif sim >= TITLE_SIM_THRESHOLD and ydiff > 1:
                warnings.append({
                    "flag": "possible_different_works",
                    "ids": [entries[i]["id"], entries[j]["id"]],
                    "evidence": "标题相似度=%.3f 但年份差=%d，未合并" % (sim, ydiff),
                })
            else:
                loose.append({
                    "flag": "candidates_title_loose",
                    "ids": [entries[i]["id"], entries[j]["id"]],
                    "evidence": "标题相似度=%.3f，作者一致=%s，年份差=%s；需人工确认（可能为中英文题名同文）" % (
                        sim, same_author, ydiff if yi and yj else "未知"),
                })

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    kept_entries = []
    for members in groups.values():
        members.sort(key=lambda i: priority(entries[i]), reverse=True)
        kept = entries[members[0]]
        for i in members[1:]:
            merge_into(kept, entries[i])
        kept_entries.append(kept)

    # 重新分配稳定 id：保持被保留条目原 id，未变条目不变
    report = {
        "total_before": n,
        "total_after": len(kept_entries),
        "merge_decisions": decisions,
        "warnings_not_merged": warnings,
        "needs_human_confirmation": loose,
    }
    return kept_entries, report


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    rep = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    kept, report = dedup(entries)
    if isinstance(data, dict):
        data["entries"] = kept
        payload = data
    else:
        payload = kept
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    if rep:
        with open(rep, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print("去重：%d -> %d 条；合并决策 %d 条；防误并提示 %d 条；待人工确认 %d 条" % (
        report["total_before"], report["total_after"],
        len(report["merge_decisions"]), len(report["warnings_not_merged"]),
        len(report["needs_human_confirmation"])))
