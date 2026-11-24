# -*- coding: utf-8 -*-
"""gbt7714.py — 将规范化文献条目格式化为 GB/T 7714—2015 著录格式（顺序编码制）。

规则要点：
- 主要责任者不超过 3 个全部著录；超过 3 个著录前 3 个，后加 ", 等"（中文文献）或 ", et al"（西文文献）。
- 西文著者：姓用全称且字母全大写，名取首字母缩写（不加缩写点），如 EINSTEIN A。
- 文献类型标识：[J] 期刊 [M] 专著 [C] 会议录论文 [D] 学位论文 [R] 报告 [EB/OL] 网络/预印本。
- 期刊：作者. 题名[J]. 刊名, 年, 卷(期): 起止页.
- 会议：作者. 题名[C]//会议录名. 出版地: 出版者, 年: 起止页.（缺项省略对应段）
- 专著：作者. 书名[M]. 出版地: 出版者, 年.
- 学位论文：作者. 题名[D]. 城市: 培养单位, 年.
- 预印本/网络：作者. 题名[EB/OL]. (发布日期)[引用日期]. 获取路径.
"""
import datetime
import json
import re
import sys

CJK_RE = re.compile(r"[一-鿿]")


def is_cjk(text):
    return bool(text and CJK_RE.search(text))


def format_author_name(name):
    """单个著者 -> GB/T 7714 形式。"""
    name = re.sub(r"\s+", " ", name).strip().strip("{}")
    if not name:
        return ""
    if is_cjk(name):
        return name.replace(" ", "")
    if "," in name:  # "Family, Given Middle"
        family, given = name.split(",", 1)
        family, given = family.strip(), given.strip()
    else:  # "Given Middle Family"
        parts = name.split()
        family, given = parts[-1], " ".join(parts[:-1])
    initials = " ".join(p[0].upper() for p in re.split(r"[\s\-]+", given) if p and p[0].isalpha())
    family = re.sub(r"[{}]", "", family).upper()
    return "%s %s" % (family, initials) if initials else family


def format_authors(authors, zh):
    names = [format_author_name(a) for a in authors]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) > 3:
        tail = "等" if zh else "et al"
        return ", ".join(names[:3]) + ", " + tail
    return ", ".join(names)


def pages_norm(p):
    return re.sub(r"-+", "-", (p or "").strip())


def format_entry(e, ref_date=None):
    zh = e.get("language") == "zh" or is_cjk(e.get("title", ""))
    authors = format_authors(e.get("authors", []), zh)
    title = (e.get("title") or "").strip()
    year = str(e.get("year") or "").strip()
    etype = e.get("type", "other")
    s = (authors + ". " if authors else "") + title

    if etype == "journal-article":
        s += "[J]. "
        seg = (e.get("journal") or "").strip()
        tail = year
        if e.get("volume"):
            tail += ", " + e["volume"]
            if e.get("issue"):
                tail += "(%s)" % e["issue"]
        elif e.get("issue"):
            tail += ", (%s)" % e["issue"]
        pg = pages_norm(e.get("pages"))
        if pg:
            tail += ": " + pg
        s += (seg + ", " if seg else "") + tail + "."
    elif etype == "proceedings-article":
        s += "[C]//" + ((e.get("booktitle") or "会议录名待补").strip() + ". ")
        parts = []
        if e.get("address"):
            parts.append(e["address"])
        if e.get("publisher"):
            parts.append(e["publisher"])
        loc = ": ".join(parts)
        if loc:
            s += loc + ", "
        s += year
        pg = pages_norm(e.get("pages"))
        if pg:
            s += ": " + pg
        s += "."
    elif etype in ("book", "book-chapter"):
        s += "[M]. "
        parts = []
        if e.get("address"):
            parts.append(e["address"])
        if e.get("publisher"):
            parts.append(e["publisher"])
        s += ": ".join(parts) + (", " if parts else "") + year + "."
    elif etype == "thesis":
        s += "[D]. "
        parts = []
        if e.get("address"):
            parts.append(e["address"])
        if e.get("publisher"):
            parts.append(e["publisher"])
        s += ": ".join(parts) + (", " if parts else "") + year + "."
    elif etype == "report":
        s += "[R]. "
        parts = []
        if e.get("address"):
            parts.append(e["address"])
        if e.get("publisher"):
            parts.append(e["publisher"])
        s += ": ".join(parts) + (", " if parts else "") + year + "."
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
    else:  # online / other
        s += "[EB/OL]. "
        ref_date = ref_date or datetime.date.today().isoformat()
        if year:
            s += "(%s-01-01)[%s]. " % (year, ref_date)
        if e.get("url"):
            s += e["url"].rstrip("/") + "."
        elif e.get("doi"):
            s += "https://doi.org/%s." % e["doi"]

    if e.get("doi") and etype in ("journal-article", "proceedings-article", "book", "book-chapter"):
        s += " DOI: %s." % e["doi"]
    return re.sub(r"\s+", " ", s).strip()


def format_library(entries, ordered_ids=None, style="gbt7714", ref_date=None):
    """按 ordered_ids 顺序输出带编号的文献表；未指定则按给定顺序。"""
    by_id = {e["id"]: e for e in entries}
    ids = ordered_ids or [e["id"] for e in entries]
    lines = []
    for i, eid in enumerate(ids, 1):
        e = by_id.get(eid)
        if not e:
            continue
        lines.append("[%d] %s" % (i, format_entry(e, ref_date=ref_date)))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    order_path = sys.argv[sys.argv.index("--order") + 1] if "--order" in sys.argv else None
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    ordered = None
    if order_path:
        with open(order_path, encoding="utf-8") as fh:
            ordered = json.load(fh)
    text = format_library(entries, ordered_ids=ordered)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("已生成文献表 %d 条 -> %s" % (len(text.strip().splitlines()), out))
    else:
        print(text)
