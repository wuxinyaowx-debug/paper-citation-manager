# -*- coding: utf-8 -*-
"""renumber.py — 引用编号重排、正文—文献表同步与一致性检查。

三种模式：
  placeholder  稿件中为 {cite:条目id} 占位符（可含 MISSING）-> 按首次出现顺序转 [n]
  renumber     稿件中已有数字编号 [n] -> 按首次出现顺序重排，并同步文末编号文献表
  author-year  著者—出版年制 -> 不改正文，校验正文引用与文末列表一致（需 --keymap）
check 子命令独立提供一致性检查。

仅依赖标准库。编号规则：连续 3 个及以上合并为 [n-m]，两个写作 [n,m]。
"""
import json
import re
import sys

CITE_RE = re.compile(r"\{cite:([^}]+)\}")
NUM_RE = re.compile(r"\[(\d+(?:\s*[,，\-–]\s*\d+)*)\]")
LIST_LINE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
MISSING_MARK = "[来源缺失]"


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
    """切出文末文献表段落。返回 (正文, 文献表行dict{编号:行文本}, 头部说明行列表)。"""
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
        suffix = MISSING_MARK if len(ids) > len(nums) and any(x.upper() == "MISSING" for x in ids) else ""
        return compress(nums) + suffix

    out = []
    last = 0
    for m in CITE_RE.finditer(text):
        out.append(text[last:m.start()])
        out.append(repl(m))
        last = m.end()
    out.append(text[last:])
    return "".join(out), order, missing, unknown


def _context(text, pos, width=60):
    s = max(0, pos - width)
    return re.sub(r"\s+", " ", text[s:pos + width]).strip()


# --------------------------------------------------------------- renumber 模式

def renumber_numeric(text):
    body, refs, notes = split_reference_section(text)
    mapping, order_old = {}, []

    def repl(m):
        nums = expand_marker(m.group(1))
        new_nums = []
        for n in nums:
            if n not in mapping:
                mapping[n] = len(mapping) + 1
                order_old.append(n)
            new_nums.append(mapping[n])
        return compress(new_nums)

    new_body = NUM_RE.sub(repl, body)
    orphans = [n for n in order_old if n not in refs]
    uncited = [n for n in refs if n not in mapping]
    new_refs = {mapping[n]: refs[n] for n in order_old if n in refs}
    return new_body, new_refs, order_old, {
        "orphan_markers": orphans,
        "uncited_list_entries": uncited,
        "old_to_new": {str(k): v for k, v in mapping.items()},
    }, notes


def render_reference_list(new_refs):
    return "\n".join("[%d] %s" % (n, new_refs[n]) for n in sorted(new_refs))


# --------------------------------------------------------------- author-year 模式

def check_author_year(text, keymap):
    """keymap: {"文中引用形式(如 'Zhang 等, 2020')": "e0003"}。只做一致性报告。"""
    body, refs, notes = split_reference_section(text)
    found = {k: (k in body) for k in keymap}
    return {
        "citations_not_in_text": [k for k, v in found.items() if not v],
        "list_entries": len(refs),
        "notes": notes,
    }


# --------------------------------------------------------------- check 子命令

def consistency_check(manuscript, references_text, order=None, library=None):
    markers = sorted(set(n for m in NUM_RE.finditer(manuscript) for n in expand_marker(m.group(1))))
    refs = {}
    for ln in references_text.splitlines():
        m = LIST_LINE_RE.match(ln)
        if m:
            refs[int(m.group(1))] = m.group(2)
    ref_nums = sorted(refs)
    gaps = [n for n in range(1, (max(markers) if markers else 0) + 1) if n not in markers]
    report = {
        "max_marker": max(markers) if markers else 0,
        "reference_list_count": len(ref_nums),
        "orphan_markers": [n for n in markers if n not in ref_nums],
        "uncited_list_entries": [n for n in ref_nums if n not in markers],
        "numbering_gaps": gaps,
        "missing_placeholder_left": len(re.findall(MISSING_MARK, manuscript)) + len(CITE_RE.findall(manuscript)),
        "unresolved_cite_placeholders": CITE_RE.findall(manuscript),
    }
    if order and library:
        lib_ids = {e["id"] for e in library}
        report["library_entries_not_cited"] = sorted(lib_ids - set(order))
    ok = not (report["orphan_markers"] or report["uncited_list_entries"]
              or report["numbering_gaps"] or report["unresolved_cite_placeholders"])
    report["consistent"] = ok
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
        new_text, order, missing, unknown = resolve_placeholders(text, {e["id"] for e in entries})
        order_out = argv[argv.index("--order-out") + 1] if "--order-out" in argv else None
        if order_out:
            with open(order_out, "w", encoding="utf-8") as fh:
                json.dump(order, fh, ensure_ascii=False, indent=2)
        report = {"mode": mode, "cited_entries": len(order),
                  "missing_source_marks": missing, "unknown_ids": unknown}
    elif mode == "renumber":
        new_body, new_refs, order_old, report, notes = renumber_numeric(text)
        report["mode"] = mode
        new_text = new_body.rstrip() + "\n\n## 参考文献\n\n" + render_reference_list(new_refs) + "\n"
        order = order_old
    elif mode == "author-year":
        keymap = _load_json(argv[argv.index("--keymap") + 1])
        report = check_author_year(text, keymap)
        report["mode"] = mode
        new_text = text
    else:
        raise SystemExit("未知模式：%s" % mode)

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    rep_out = argv[argv.index("--report") + 1] if "--report" in argv else None
    if rep_out:
        with open(rep_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main(sys.argv[1:])
