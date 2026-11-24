# -*- coding: utf-8 -*-
"""gbt7714.py — 将规范化文献条目格式化为 GB/T 7714—2015 著录格式（顺序编码制）。

规则要点：
- 主要责任者不超过 3 个全部著录；超过 3 个著录前 3 个，后加 ", 等"（中文）或 ", et al"（西文）。
- 西文著者：姓全称且字母全大写，名取首字母缩写（不加缩写点），如 EINSTEIN A。
- 复合姓氏（Smith-Jones）与姓氏前缀（van / von / der / de 等）归属姓氏。
- "and others"（BibTeX）按超过 3 人处理。
- 类型标识：[J] 期刊 [M] 专著 [M]// 专著章节 [C]// 会议论文 [D] 学位论文 [R] 报告
  [EB/OL] 网络资源与预印本。
- 缺失字段不编造：省略对应著录段，同时在告警中逐条列出，供人工补全。

不能保证准确处理的情况：编者/译者与析出文献责任者的区分（缺少相应字段时
只能省略）、古籍/标准/专利等未实现类型（按 [EB/OL] 兜底并告警）。
"""
import datetime
import json
import re
import sys

CJK_RE = re.compile(r"[一-鿿]")
SURNAME_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di",
                     "da", "du", "la", "le", "ten", "ter", "het", "'t"}


def is_cjk(text):
    return bool(text and CJK_RE.search(text))


def split_person_name(name):
    """返回 (family, given)。处理 'Family, Given' 与 'Given … Family' 及姓氏前缀。"""
    name = re.sub(r"\s+", " ", name).strip().strip("{}")
    if not name:
        return "", ""
    if "," in name:
        family, given = name.split(",", 1)
        return family.strip(), given.strip()
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    # 从末尾向前收集小写姓氏前缀
    i = len(parts) - 1
    while i - 1 >= 1 and parts[i - 1].lower().strip(".") in SURNAME_PARTICLES:
        i -= 1
    family = " ".join(parts[i:])
    given = " ".join(parts[:i])
    return family, given


def format_author_name(name):
    """单个著者 -> GB/T 7714 形式。"""
    family, given = split_person_name(name)
    if not family:
        return ""
    if is_cjk(family + given):
        return (family + given).replace(" ", "")
    initials = " ".join(p[0].upper() for p in re.split(r"[\s\-]+", given) if p and p[0].isalpha())
    family = re.sub(r"[{}]", "", family).upper()
    return "%s %s" % (family, initials) if initials else family


def format_authors(authors, zh):
    has_others = any(a.strip().lower() in ("others", "等") for a in authors)
    names = [format_author_name(a) for a in authors if a.strip().lower() not in ("others", "等")]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) > 3 or has_others:
        head = names[:3] if len(names) > 3 else names
        tail = "等" if zh else "et al"
        return ", ".join(head) + ", " + tail
    return ", ".join(names)


def pages_norm(p):
    return re.sub(r"-+", "-", (p or "").strip())


def format_entry(e, ref_date=None, warnings=None):
    """格式化单条。warnings 为可选列表，用于收集缺字段告警。"""
    warn = (lambda msg: warnings.append({"id": e.get("id"), "warning": msg})) \
        if warnings is not None else (lambda msg: None)
    zh = e.get("language") == "zh" or is_cjk(e.get("title", ""))
    authors = format_authors(e.get("authors", []), zh)
    if not authors:
        warn("缺少主要责任者")
    title = (e.get("title") or "").strip()
    if not title:
        warn("缺少题名")
    year = str(e.get("year") or "").strip()
    if not year:
        warn("缺少年份")
    etype = e.get("type", "other")
    s = (authors + ". " if authors else "") + title

    if etype == "journal-article":
        s += "[J]. "
        if not e.get("journal"):
            warn("期刊论文缺少刊名")
        seg = (e.get("journal") or "").strip()
        tail = year
        if e.get("volume"):
            tail += ", " + e["volume"]
            if e.get("issue"):
                tail += "(%s)" % e["issue"]
        elif e.get("issue"):
            tail += ", (%s)" % e["issue"]
            warn("有期号但缺卷号")
        pg = pages_norm(e.get("pages"))
        if pg:
            tail += ": " + pg
        s += (seg + ", " if seg else "") + tail + "."
    elif etype == "proceedings-article":
        if not e.get("booktitle"):
            warn("会议论文缺少会议录名")
        s += "[C]//" + ((e.get("booktitle") or "").strip() + ". ")
        loc = ": ".join(p for p in (e.get("address"), e.get("publisher")) if p)
        if loc:
            s += loc + ", "
        s += year
        pg = pages_norm(e.get("pages"))
        if pg:
            s += ": " + pg
        s += "."
    elif etype == "book-chapter":
        if not e.get("booktitle"):
            warn("专著章节缺少专著题名")
        s += "[M]//" + ((e.get("booktitle") or "").strip() + ". ")
        loc = ": ".join(p for p in (e.get("address"), e.get("publisher")) if p)
        if loc:
            s += loc + ", "
        s += year
        pg = pages_norm(e.get("pages"))
        if pg:
            s += ": " + pg
        s += "."
    elif etype == "book":
        s += "[M]. "
        if not e.get("publisher"):
            warn("专著缺少出版者")
        loc = ": ".join(p for p in (e.get("address"), e.get("publisher")) if p)
        s += loc + (", " if loc else "") + year + "."
    elif etype == "thesis":
        s += "[D]. "
        if not e.get("publisher"):
            warn("学位论文缺少培养单位")
        loc = ": ".join(p for p in (e.get("address"), e.get("publisher")) if p)
        s += loc + (", " if loc else "") + year + "."
    elif etype == "report":
        s += "[R]. "
        loc = ": ".join(p for p in (e.get("address"), e.get("publisher")) if p)
        s += loc + (", " if loc else "") + year + "."
    elif etype == "preprint":
        ref_date = ref_date or datetime.date.today().isoformat()
        s += "[EB/OL]. "
        s += "(%s-01-01)[%s]. " % (year or "0000", ref_date)
        if e.get("arxiv"):
            s += "https://arxiv.org/abs/%s." % e["arxiv"]
        elif e.get("url"):
            s += e["url"].rstrip("/") + "."
        elif e.get("doi"):
            s += "https://doi.org/%s." % e["doi"]
        else:
            warn("预印本缺少获取路径（arXiv/URL/DOI 均无）")
            s = s.rstrip()
    else:  # online / other 兜底
        if etype not in ("online", "other"):
            warn("未实现的文献类型 %s，按 [EB/OL] 兜底" % etype)
        s += "[EB/OL]. "
        ref_date = ref_date or datetime.date.today().isoformat()
        if year:
            s += "(%s-01-01)[%s]. " % (year, ref_date)
        if e.get("url"):
            s += e["url"].rstrip("/") + "."
        elif e.get("doi"):
            s += "https://doi.org/%s." % e["doi"]
        else:
            warn("网络资源缺少获取路径")
            s = s.rstrip()

    if e.get("doi") and etype in ("journal-article", "proceedings-article",
                                  "book", "book-chapter"):
        s += " DOI: %s." % e["doi"]
    return re.sub(r"\s+", " ", s).strip()


def format_library(entries, ordered_ids=None, style="gbt7714", ref_date=None):
    """按 ordered_ids 顺序输出带编号的文献表。返回 (text, warnings)。"""
    if style != "gbt7714":
        raise ValueError("暂仅支持 gbt7714 目标规范")
    by_id = {e["id"]: e for e in entries}
    ids = ordered_ids or [e["id"] for e in entries]
    missing_ids = [eid for eid in ids if eid not in by_id]
    lines, warnings = [], []
    for eid in missing_ids:
        warnings.append({"id": eid, "warning": "引用顺序表中的条目不在文献库中"})
    for i, eid in enumerate(ids, 1):
        e = by_id.get(eid)
        if not e:
            continue
        lines.append("[%d] %s" % (i, format_entry(e, ref_date=ref_date, warnings=warnings)))
    return "\n".join(lines) + ("\n" if lines else ""), warnings


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    order_path = sys.argv[sys.argv.index("--order") + 1] if "--order" in sys.argv else None
    rep = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    ordered = None
    if order_path:
        with open(order_path, encoding="utf-8") as fh:
            ordered = json.load(fh)
    text, warnings = format_library(entries, ordered_ids=ordered)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if rep:
        with open(rep, "w", encoding="utf-8") as fh:
            json.dump({"format_warnings": warnings}, fh, ensure_ascii=False, indent=2)
    print("已生成文献表 %d 条，告警 %d 条" % (len(text.strip().splitlines()), len(warnings)))
