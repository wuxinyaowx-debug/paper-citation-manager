# -*- coding: utf-8 -*-
"""renumber.py — 引用编号重排、正文—文献表同步与一致性检查。

三种模式：
  placeholder  稿件中为 {cite:条目id} 占位符（可含 MISSING）-> 按首次出现顺序转 [n]
  renumber     稿件中已有数字编号 [n] -> 按首次出现顺序重排，并同步文末编号文献表
  author-year  著者—出版年制 -> 不改正文，双向校验正文引用与文末列表（需 --keymap）

安全原则：
  - 数字标记按上下文分类为 citation / ambiguous / skip；只有 citation 会被改写，
    ambiguous（行首、数学语境、疑似年份的大数字、Markdown 链接等）保留原文并报告。
  - 一致性检查区分 structural_consistent（编号结构）与 evidence_complete（证据
    充分性），来源缺失、未知 ID、低置信引用都使 evidence_complete 为 False。

仅依赖标准库。编号规则：连续 3 个及以上合并为 [n-m]，两个写作 [n,m]。
"""
import json
import re
import sys

CITE_RE = re.compile(r"\{cite:([^}]+)\}")
NUM_RE = re.compile(r"\[(\d+(?:\s*[,，\-–]\s*\d+)*)\]")
LIST_LINE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
MISSING_MARK = "[来源缺失]"
OPER_PREV = set("=+-*/^([{<~\\")
MAX_CITATION_NUM = 999  # 超过此值的“编号”按疑似年份/其他数字处理
CJK_RE = re.compile(r"[一-鿿]")

# 著者—出版年制候选引用
AY_PAREN_RE = re.compile(
    r"[（(]([A-Z][A-Za-z\-']+(?: (?:等|et al\.?|and [A-Z][A-Za-z\-']+|& [A-Z][A-Za-z\-']+))?"
    r"|[一-鿿]{2,4}等?)[,，]\s*(\d{4})[a-z]?[)）]")
AY_NARR_RE = re.compile(
    r"([A-Z][A-Za-z\-']+(?: (?:等|et al\.?))?|[一-鿿]{2,4}等)\s*[（(](\d{4})[a-z]?[)）]")


def expand_marker(body):
    """'1,3-5' -> [1,3,4,5]"""
    nums = []
    for part in re.split(r"[,，]", body):
        part = part.strip()
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            nums.extend(range(a, b + 1) if a <= b else [a])
        elif part.isdigit():
            nums.append(int(part))
    return nums


def compress(nums):
    """[1,2,3,5] -> '[1-3,5]'"""
    nums = sorted(set(nums))
    if not nums:
        return ""
    runs, start, prev = [], nums[0], nums[0]
    for x in nums[1:]:
        if x == prev + 1:
            prev = x
            continue
        runs.append((start, prev))
        start = prev = x
    runs.append((start, prev))
    parts = [str(a) if a == b else ("%d,%d" % (a, b) if b == a + 1 else "%d-%d" % (a, b))
             for a, b in runs]
    return "[" + ",".join(parts) + "]"


def split_reference_section(text):
    """切出文末文献表段落。返回 (正文, 文献表行dict{编号:行文本}, 文献表头部及说明行)。"""
    lines = text.splitlines()
    head_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s*(参考文献|references|bibliography)\s*$", ln, re.I) \
                or re.match(r"^\s*(参考文献|References|Bibliography)\s*$", ln):
            head_idx = i
    if head_idx is None:
        return text, {}, []
    body = "\n".join(lines[:head_idx])
    refs, notes = {}, []
    for ln in lines[head_idx:]:
        m = LIST_LINE_RE.match(ln)
        if m:
            refs[int(m.group(1))] = m.group(2)
        elif ln.strip():
            notes.append(ln)
    return body, refs, notes


# --------------------------------------------------------------- 引用标记上下文分类

def classify_marker(m, text):
    """判定 [n] 类标记是否为引用。返回 'citation' / 'ambiguous' / 'skip'。

    保守策略：上下文存疑时一律 ambiguous（保留原文并报告），不改写。"""
    after = text[m.end():m.end() + 1]
    if after == "(":      # Markdown 链接 [1](url)
        return "skip"
    k = m.start() - 1
    spaced = False
    while k >= 0 and text[k] in " \t":
        spaced = True
        k -= 1
    prev = text[k] if k >= 0 else "\n"
    if prev == "\\":      # LaTeX \[...\] 或转义
        return "skip"
    if prev in OPER_PREV or prev == "\n":   # 数学语境或行首（公式编号、列表）
        return "ambiguous"
    nums = expand_marker(m.group(1))
    if not nums:
        return "skip"
    # 引用编号从 1 开始；含 0 或超大数字（疑似年份 [2020]、区间 [0,1]）存疑
    if any(n > MAX_CITATION_NUM or n == 0 for n in nums):
        return "ambiguous"
    # 中文语境下空格分隔的方括号数字多为公式/图表编号（如 "公式 [3]"）；
    # 西文 "shown [1]." 仍视为引用
    if spaced and CJK_RE.match(prev):
        return "ambiguous"
    return "citation"


def scan_markers(text):
    """返回 (citation_matches, ambiguous_list)。ambiguous_list 含原文与上下文。"""
    citations, ambiguous = [], []
    for m in NUM_RE.finditer(text):
        kind = classify_marker(m, text)
        if kind == "citation":
            citations.append(m)
        elif kind == "ambiguous":
            ambiguous.append({"raw": m.group(0), "context": _context(text, m.start())})
    return citations, ambiguous


# --------------------------------------------------------------- placeholder 模式

def resolve_placeholders(text, library_ids):
    order, missing, unknown = [], [], []
    seen = set()

    def repl(m):
        ids = [x.strip() for x in m.group(1).split(",") if x.strip()]
        nums = []
        for eid in ids:
            if eid.upper() == "MISSING":
                missing.append({"context": _context(text, m.start())})
                continue
            if eid not in library_ids:
                unknown.append({"id": eid, "context": _context(text, m.start())})
                continue
            if eid not in seen:
                seen.add(eid)
                order.append(eid)
            nums.append(order.index(eid) + 1)
        if not nums:
            return MISSING_MARK
        suffix = MISSING_MARK if any(x.upper() == "MISSING" for x in ids) else ""
        return compress(nums) + suffix

    # 混合模式提示：在原稿（替换前）中检出既有数字编号，避免把刚生成的 [n] 误报
    body0, _, _ = split_reference_section(text)
    preexisting, pre_amb = scan_markers(body0)

    out, last = [], 0
    for m in CITE_RE.finditer(text):
        out.append(text[last:m.start()])
        out.append(repl(m))
        last = m.end()
    out.append(text[last:])
    new_text = "".join(out)
    report_extra = {
        "preexisting_numeric_markers": [m.group(0) for m in preexisting],
        "ambiguous_markers_untouched": pre_amb,
    }
    return new_text, order, missing, unknown, report_extra


def _context(text, pos, width=60):
    s = max(0, pos - width)
    return re.sub(r"\s+", " ", text[s:pos + width]).strip()


# --------------------------------------------------------------- renumber 模式

def renumber_numeric(text):
    body, refs, notes = split_reference_section(text)
    mapping, order_old = {}, []
    citations, ambiguous = scan_markers(body)

    def new_num(n):
        if n not in mapping:
            mapping[n] = len(mapping) + 1
            order_old.append(n)
        return mapping[n]

    out, last = [], 0
    for m in citations:
        out.append(body[last:m.start()])
        out.append(compress([new_num(n) for n in expand_marker(m.group(1))]))
        last = m.end()
    out.append(body[last:])
    new_body = "".join(out)

    orphans = [n for n in order_old if n not in refs]
    uncited = [n for n in refs if n not in mapping]
    new_refs = {mapping[n]: refs[n] for n in order_old if n in refs}
    report = {
        "orphan_markers": orphans,
        "uncited_list_entries": uncited,
        "ambiguous_markers_untouched": ambiguous,
        "old_to_new": {str(k): v for k, v in mapping.items()},
        "notes_preserved": notes,
    }
    return new_body, new_refs, order_old, report, notes


def render_reference_list(new_refs, notes=None, heading="## 参考文献"):
    parts = [heading]
    parts.extend(n for n in (notes or []) if not re.match(
        r"^\s{0,3}#{1,6}\s*(参考文献|references|bibliography)\s*$", n, re.I)
        and n.strip() not in ("参考文献", "References", "Bibliography"))
    parts.extend("[%d] %s" % (n, new_refs[n]) for n in sorted(new_refs))
    return "\n\n".join(parts[:1] + [p for p in parts[1:] if p.strip()]) + "\n"


# --------------------------------------------------------------- author-year 模式

def _norm_ay(name, year):
    name = re.sub(r"\s*(等|et al\.?)$", "", name).strip()
    return name, year


def check_author_year(text, keymap):
    """keymap: {"文中引用形式(如 'Zhang 等, 2020')": "e0003"}。双向校验。"""
    body, refs, notes = split_reference_section(text)
    not_in_text = [k for k in keymap if k not in body]

    covered, detected = set(), []
    for rx in (AY_PAREN_RE, AY_NARR_RE):
        for m in rx.finditer(body):
            name, year = _norm_ay(m.group(1), m.group(2))
            detected.append("%s, %s" % (name, year))
    for d in set(detected):
        surname = re.split(r"[\s,，]", d)[0]
        year = d[-4:]
        for k in keymap:
            if surname in k and year in k:
                covered.add(d)
                break
    unchecked = sorted(set(detected) - covered)

    return {
        "citations_not_in_text": not_in_text,
        "unchecked_citations": unchecked,
        "keymap_size": len(keymap),
        "list_entries": len(refs),
        "list_notes": notes,
        "consistent": not not_in_text and not unchecked,
    }


# --------------------------------------------------------------- 一致性检查

def consistency_check(manuscript, references_text, order=None, library=None, issues=None):
    """issues：来自 renumber 报告或 Agent 记录的问题清单，可含
    missing_source_marks / unknown_ids / low_confidence_citations / human_review_items。"""
    issues = issues or {}
    body, _, _ = split_reference_section(manuscript)
    citations, ambiguous = scan_markers(body)
    markers = sorted(set(n for m in citations for n in expand_marker(m.group(1))))

    refs = {}
    for ln in references_text.splitlines():
        m = LIST_LINE_RE.match(ln)
        if m:
            refs[int(m.group(1))] = m.group(2)
    ref_nums = sorted(refs)

    gaps = [n for n in range(1, (max(markers) if markers else 0) + 1) if n not in markers]
    unresolved = CITE_RE.findall(manuscript)
    structural = {
        "max_marker": max(markers) if markers else 0,
        "reference_list_count": len(ref_nums),
        "orphan_markers": [n for n in markers if n not in ref_nums],
        "uncited_list_entries": [n for n in ref_nums if n not in markers],
        "numbering_gaps": gaps,
        "unresolved_cite_placeholders": unresolved,
        "ambiguous_markers_untouched": ambiguous + issues.get("ambiguous_markers_untouched", []),
    }
    if order and library:
        lib_ids = {e["id"] for e in library}
        structural["library_entries_not_cited"] = sorted(lib_ids - set(order))

    missing_marks = list(issues.get("missing_source_marks", []))
    inline_missing = manuscript.count(MISSING_MARK)
    evidence = {
        "missing_source_marks": missing_marks,
        "missing_source_count": max(len(missing_marks), inline_missing),
        "unknown_ids": issues.get("unknown_ids", []),
        "low_confidence_citations": issues.get("low_confidence_citations", []),
        "human_review_items": issues.get("human_review_items", []),
    }

    structural_consistent = not (
        structural["orphan_markers"] or structural["uncited_list_entries"]
        or structural["numbering_gaps"] or structural["unresolved_cite_placeholders"]
        or structural["ambiguous_markers_untouched"])
    evidence_complete = not (
        evidence["missing_source_count"] or evidence["unknown_ids"]
        or evidence["low_confidence_citations"] or evidence["human_review_items"])
    if structural_consistent and evidence_complete:
        overall = "consistent"
    elif structural_consistent:
        overall = "evidence_incomplete"
    else:
        overall = "inconsistent"

    report = {
        "structural": structural,
        "evidence": evidence,
        "structural_consistent": structural_consistent,
        "evidence_complete": evidence_complete,
        "overall_status": overall,
        "consistent": structural_consistent and evidence_complete,
    }
    return report


# --------------------------------------------------------------- CLI

def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv):
    mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "placeholder"
    ms_path = argv[argv.index("--manuscript") + 1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    with open(ms_path, encoding="utf-8") as fh:
        text = fh.read()

    if mode == "placeholder":
        lib = _load_json(argv[argv.index("--library") + 1])
        entries = lib["entries"] if isinstance(lib, dict) else lib
        new_text, order, missing, unknown, extra = resolve_placeholders(
            text, {e["id"] for e in entries})
        order_out = argv[argv.index("--order-out") + 1] if "--order-out" in argv else None
        if order_out:
            with open(order_out, "w", encoding="utf-8") as fh:
                json.dump(order, fh, ensure_ascii=False, indent=2)
        report = {"mode": mode, "cited_entries": len(order),
                  "missing_source_marks": missing, "unknown_ids": unknown, **extra}
    elif mode == "renumber":
        new_body, new_refs, order_old, report, notes = renumber_numeric(text)
        report["mode"] = mode
        heading = notes[0] if notes and re.match(r"^\s{0,3}#", notes[0]) else "## 参考文献"
        new_text = new_body.rstrip() + "\n\n" + render_reference_list(new_refs, notes, heading)
        order = order_old
    elif mode == "author-year":
        keymap = _load_json(argv[argv.index("--keymap") + 1])
        report = check_author_year(text, keymap)
        report["mode"] = mode
        new_text = text
    else:
        raise SystemExit("未知模式：%s（可选 placeholder / renumber / author-year）" % mode)

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    rep_out = argv[argv.index("--report") + 1] if "--report" in argv else None
    if rep_out:
        with open(rep_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "old_to_new"},
                     ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main(sys.argv[1:])
