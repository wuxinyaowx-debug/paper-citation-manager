# -*- coding: utf-8 -*-
"""dedup.py — 文献条目分层去重与归并，决策可解释、防误并、可人工否决。

分层判据：
  R1 强标识符匹配：DOI 规范化一致 / arXiv 号一致（版本号 v1/v2 视为同一工作）。
     DOI 相同但双方题名均在且相似度 < 0.6 视为元数据明显冲突，不静默合并，
     标记 doi_metadata_conflict 交人工复核。
  R2 多字段联合匹配：规范化标题相似度 >= 0.95 且第一作者姓一致（双方均在）
     且双方年份均在且差 <= 1。
  R3 低置信候选：标题相似度 0.80-0.95，或标题高相似但作者/年份任一缺失。
     只提示，不自动合并。
  R4 复杂情况候选：中英文题名互译同文（题名语言不同 + 年份相同 + 作者数相同），
     或标题相同但年份差 > 1（同名不同文）。只提示，不自动合并。

防护：
  - 缺失字段不作为一致证据（年份/作者缺失即降级为候选）。
  - 传递性归并校验：组内成员必须与锚点（保留条目）直接可比，否则拆出并标记。
  - overrides 支持人工强制合并 / 禁止合并。

仅依赖标准库。
"""
import difflib
import json
import re
import sys

TITLE_SIM_THRESHOLD = 0.95
LOOSE_THRESHOLD = 0.80
CONFLICT_THRESHOLD = 0.60   # DOI 相同但题名相似度低于此值 -> 元数据冲突
ANCHOR_MIN_SIM = 0.90       # 传递性校验：成员与锚点的最低标题相似度

CJK_RE = re.compile(r"[一-鿿]")


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
    if CJK_RE.search(a):
        return a.strip()[:1]  # 中文姓名取首字（姓）
    if "," in a:
        return a.split(",", 1)[0].strip().lower()
    parts = a.split()
    return parts[-1].lower() if parts else ""


def year_int(y):
    m = re.match(r"\d{4}", str(y or ""))
    return int(m.group(0)) if m else None


def lang(t):
    return "zh" if t and CJK_RE.search(t) else "en"


def title_sim(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


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
    """把 other 的缺失字段回填到 kept，保留 other 的独有信息与完整来源。"""
    for k in ("doi", "arxiv", "url", "volume", "issue", "pages", "journal",
              "booktitle", "publisher", "address", "year"):
        if not kept.get(k) and other.get(k):
            kept[k] = other[k]
    if not kept.get("authors") and other.get("authors"):
        kept["authors"] = other["authors"]
    if other.get("title") and other["title"] != kept.get("title"):
        if other["title"] not in kept["aliases"]:
            kept["aliases"].append(other["title"])
    kept.setdefault("merged_from", []).append({
        "id": other["id"], "file": other["source"].get("file"),
        "key": other["source"].get("key"),
    })


def _field_cmp(ei, ej):
    ti, tj = norm_title(ei.get("title")), norm_title(ej.get("title"))
    yi, yj = year_int(ei.get("year")), year_int(ej.get("year"))
    si, sj = first_author_surname(ei["authors"]), first_author_surname(ej["authors"])
    return {
        "title_sim": round(title_sim(ti, tj), 3),
        "year_i": yi, "year_j": yj,
        "year_diff": abs(yi - yj) if yi and yj else None,
        "first_author_i": si or None, "first_author_j": sj or None,
        "same_first_author": bool(si and sj and si == sj),
        "doi": norm_doi(ei.get("doi")) or None,
    }


def dedup(entries, overrides=None):
    """overrides: {"merge": [[idA, idB], ...], "split": [[idA, idB], ...]}。

    返回 (kept_entries, report)。"""
    overrides = overrides or {}
    n = len(entries)
    id_to_idx = {e["id"]: i for i, e in enumerate(entries)}
    # forbid / force 一律按条目索引构造，避免 ID 与索引混用
    forbid = {frozenset(id_to_idx[x] for x in pair if x in id_to_idx)
              for pair in overrides.get("split", [])}
    forbid = {p for p in forbid if len(p) == 2}
    force = [pair for pair in overrides.get("merge", [])]
    overrides_applied = []

    parent = list(range(n))
    decision_of = {}   # frozenset({i,j}) -> decision dict

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def try_union(i, j, rule, evidence, cmp_info):
        key = frozenset((i, j))
        if key in forbid:
            overrides_applied.append({"action": "split", "ids": [entries[i]["id"], entries[j]["id"]],
                                      "reason": "人工否决自动合并（%s）" % rule})
            return False
        ri, rj = find(i), find(j)
        if ri == rj:
            return False
        parent[rj] = ri
        decision_of[key] = {"rule": rule, "ids": [entries[i]["id"], entries[j]["id"]],
                            "evidence": evidence, "field_comparison": cmp_info}
        return True

    decisions, warnings, loose = [], [], []

    # ---------- R1 强标识符 ----------
    doi_idx, arxiv_idx = {}, {}
    for i, e in enumerate(entries):
        d = norm_doi(e.get("doi"))
        if d:
            if d in doi_idx:
                j = doi_idx[d]
                cmp_info = _field_cmp(entries[j], e)
                if cmp_info["title_sim"] < CONFLICT_THRESHOLD and entries[j].get("title") and e.get("title"):
                    loose.append({
                        "flag": "doi_metadata_conflict",
                        "ids": [entries[j]["id"], e["id"]],
                        "evidence": "DOI 相同（%s）但题名相似度仅 %.3f，疑似元数据错误，未自动合并" % (
                            d, cmp_info["title_sim"]),
                        "field_comparison": cmp_info,
                    })
                else:
                    try_union(i, j, "doi_exact", "DOI=%s" % d, cmp_info)
            else:
                doi_idx[d] = i
        ax = re.sub(r"v\d+$", "", (e.get("arxiv") or "").strip())
        if ax:
            if ax in arxiv_idx:
                j = arxiv_idx[ax]
                cmp_info = _field_cmp(entries[j], e)
                try_union(i, j, "arxiv_exact", "arXiv=%s（版本号差异视为同一工作）" % ax, cmp_info)
            else:
                arxiv_idx[ax] = i

    # ---------- R2 多字段联合 / R3 低置信候选 / R4 复杂候选 ----------
    norms = [norm_title(e.get("title")) for e in entries]
    for i in range(n):
        for j in range(i + 1, n):
            if find(i) == find(j) or not norms[i] or not norms[j]:
                continue
            ei, ej = entries[i], entries[j]
            cmp_info = _field_cmp(ei, ej)
            sim = cmp_info["title_sim"]
            same_author = cmp_info["same_first_author"]
            ydiff = cmp_info["year_diff"]

            if sim >= TITLE_SIM_THRESHOLD:
                if ydiff is not None and ydiff > 1:
                    # R4：标题高度相同但年份差大 -> 同名不同文
                    warnings.append({
                        "flag": "possible_different_works",
                        "ids": [ei["id"], ej["id"]],
                        "evidence": "标题相似度=%.3f 但年份差=%d，未合并" % (sim, ydiff),
                        "field_comparison": cmp_info,
                    })
                elif not same_author and cmp_info["first_author_i"] and cmp_info["first_author_j"]:
                    # R4：标题高度相同但第一作者不同 -> 疑似同题不同文
                    warnings.append({
                        "flag": "possible_different_works",
                        "ids": [ei["id"], ej["id"]],
                        "evidence": "标题相似度=%.3f 但第一作者不同（%s vs %s），未合并" % (
                            sim, cmp_info["first_author_i"], cmp_info["first_author_j"]),
                        "field_comparison": cmp_info,
                    })
                elif ydiff is None or not cmp_info["first_author_i"]:
                    # R3：关键字段缺失，不作一致证据
                    loose.append({
                        "flag": "candidates_missing_fields",
                        "ids": [ei["id"], ej["id"]],
                        "evidence": "标题相似度=%.3f，但年份或作者缺失，无法确证同一文献，需人工确认" % sim,
                        "field_comparison": cmp_info,
                    })
                else:
                    try_union(i, j, "title_author_year",
                              "标题相似度=%.3f，第一作者姓=%s，年份差=%d" % (
                                  sim, cmp_info["first_author_i"], ydiff), cmp_info)
            elif sim >= LOOSE_THRESHOLD:
                # R3 低置信候选
                loose.append({
                    "flag": "candidates_title_loose",
                    "ids": [ei["id"], ej["id"]],
                    "evidence": "标题相似度=%.3f（低于自动合并阈值 %.2f），需人工确认" % (
                        sim, TITLE_SIM_THRESHOLD),
                    "field_comparison": cmp_info,
                })
            elif lang(ei.get("title")) != lang(ej.get("title")) \
                    and ydiff == 0 and len(ei["authors"]) == len(ej["authors"]) and ei["authors"]:
                # R4：中英文题名互译同文候选
                loose.append({
                    "flag": "possible_translation_pair",
                    "ids": [ei["id"], ej["id"]],
                    "evidence": "题名语言不同（zh/en）但年份相同、作者数相同，疑似中英文题名同文，需人工确认",
                    "field_comparison": cmp_info,
                })

    # ---------- 人工强制合并 ----------
    for pair in force:
        idxs = [id_to_idx.get(x) for x in pair]
        if len(idxs) == 2 and None not in idxs and find(idxs[0]) != find(idxs[1]):
            parent[find(idxs[1])] = find(idxs[0])
            decisions.append({"rule": "manual_override_merge", "ids": pair,
                              "evidence": "人工确认合并", "field_comparison": _field_cmp(
                                  entries[idxs[0]], entries[idxs[1]])})
            overrides_applied.append({"action": "merge", "ids": pair, "reason": "人工确认"})

    # ---------- 传递性归并校验 ----------
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    split_review = []
    final_groups = []
    for members in groups.values():
        if len(members) <= 2:
            final_groups.append(members)
            continue
        members.sort(key=lambda i: priority(entries[i]), reverse=True)
        anchor = members[0]
        in_group, out_group = [anchor], []
        for i in members[1:]:
            same_doi = norm_doi(entries[i].get("doi")) and \
                norm_doi(entries[i].get("doi")) == norm_doi(entries[anchor].get("doi"))
            same_arxiv = (re.sub(r"v\d+$", "", entries[i].get("arxiv") or "") and
                          re.sub(r"v\d+$", "", entries[i].get("arxiv") or "") ==
                          re.sub(r"v\d+$", "", entries[anchor].get("arxiv") or ""))
            sim = title_sim(norm_title(entries[i].get("title")), norm_title(entries[anchor].get("title")))
            if same_doi or same_arxiv or sim >= ANCHOR_MIN_SIM:
                in_group.append(i)
            else:
                out_group.append(i)
        if out_group:
            split_review.append({
                "flag": "transitive_split_review",
                "anchor_id": entries[anchor]["id"],
                "split_ids": [entries[i]["id"] for i in out_group],
                "evidence": "组成员与锚点不直接可比（DOI/arXiv 不同且标题相似度 < %.2f），"
                            "已拆出以防传递性误并，请人工复核" % ANCHOR_MIN_SIM,
            })
        final_groups.append(in_group)
        final_groups.extend([i] for i in out_group)

    # ---------- 归并 ----------
    kept_entries, merged_raw = [], []
    for members in final_groups:
        members.sort(key=lambda i: priority(entries[i]), reverse=True)
        kept = entries[members[0]]
        for i in members[1:]:
            merged_raw.append(entries[i])
            merge_into(kept, entries[i])
        kept_entries.append(kept)

    for dec in decision_of.values():
        i, j = (id_to_idx[x] for x in dec["ids"])
        if any(i in g and j in g for g in final_groups):
            kept_id = next(entries[g[0]]["id"] for g in final_groups if i in g)
            merged_id = dec["ids"][1] if dec["ids"][0] == kept_id else dec["ids"][0]
            dec["kept_id"] = kept_id
            dec["merged_id"] = merged_id
            dec["reason"] = "满足判据 %s，保留优先级较高条目 %s" % (dec["rule"], kept_id)
            decisions.append(dec)

    report = {
        "total_before": n,
        "total_after": len(kept_entries),
        "merge_decisions": decisions,
        "warnings_not_merged": warnings,
        "needs_human_confirmation": loose,
        "transitive_split_review": split_review,
        "overrides_applied": overrides_applied,
        "merged_raw": merged_raw,
    }
    return kept_entries, report


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    rep = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
    ovr = None
    if "--overrides" in sys.argv:
        with open(sys.argv[sys.argv.index("--overrides") + 1], encoding="utf-8") as fh:
            ovr = json.load(fh)
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    kept, report = dedup(entries, overrides=ovr)
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
    print("去重：%d -> %d 条；合并 %d 组；未合并告警 %d；待人工确认 %d；传递性拆分 %d" % (
        report["total_before"], report["total_after"], len(report["merge_decisions"]),
        len(report["warnings_not_merged"]), len(report["needs_human_confirmation"]),
        len(report["transitive_split_review"])))
