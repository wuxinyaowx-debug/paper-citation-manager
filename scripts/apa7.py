# -*- coding: utf-8 -*-
"""apa7.py — 将规范化文献条目格式化为 APA 第 7 版参考文献格式。

覆盖：期刊论文、专著、专著章节、会议论文、预印本/网络资源。
规则要点：
- 著者：姓, 名首字母.（带点）；20 人以内全部列出，末位前加 &；
  超过 20 人列前 19 人后加省略号与末位著者（此处简化为告警提示人工核对）。
- 刊名与卷号用 Markdown 斜体标记（*...*），期号不斜体。
- 题名句读大小写（sentence case）不做自动转换，逐条告警提示人工核对，
  避免错误改写专有名词。
- 缺失字段不编造：省略对应部分并告警。

不能保证准确处理的情况：题名 sentence case 转换、期刊名缩写、
卷期缺省时的期号推断、非英文文献的译名标注（[In Chinese] 需人工确认）。
"""
import json
import re
import sys

CJK_RE = re.compile(r"[一-鿿]")
SURNAME_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di",
                     "da", "du", "la", "le", "ten", "ter", "het", "'t"}


def is_cjk(text):
    return bool(text and CJK_RE.search(text))


def split_person_name(name):
    name = re.sub(r"\s+", " ", name).strip().strip("{}")
    if not name:
        return "", ""
    if "," in name:
        family, given = name.split(",", 1)
        return family.strip(), given.strip()
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    i = len(parts) - 1
    while i - 1 >= 1 and parts[i - 1].lower().strip(".") in SURNAME_PARTICLES:
        i -= 1
    return " ".join(parts[i:]), " ".join(parts[:i])


def format_author_name(name):
    """APA 形式：Family, I. I.（中文姓名保持原样）。"""
    family, given = split_person_name(name)
    if not family:
        return ""
    if is_cjk(family + given):
        return (family + given).replace(" ", "")
    initials = " ".join(p[0].upper() + "." for p in re.split(r"[\s\-]+", given) if p and p[0].isalpha())
    return "%s, %s" % (family, initials) if initials else family


def format_authors(authors, warnings=None, eid=None):
    has_others = any(a.strip().lower() in ("others", "等") for a in authors)
    names = [format_author_name(a) for a in authors if a.strip().lower() not in ("others", "等")]
    names = [n for n in names if n]
    if not names:
        return ""
    if has_others and warnings is not None:
        warnings.append({"id": eid, "warning": "著者列表含 and others/等，APA 要求列全（≤20 人），请人工补全"})
    if len(names) > 20:
        if warnings is not None:
            warnings.append({"id": eid, "warning": "著者超过 20 人，APA 省略规则需人工核对"})
        names = names[:19] + ["..."] + [names[-1]]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def pages_norm(p):
    return re.sub(r"-+", "-", (p or "").strip())


def format_entry(e, warnings=None):
    warn = (lambda msg: warnings.append({"id": e.get("id"), "warning": msg})) \
        if warnings is not None else (lambda msg: None)
    authors = format_authors(e.get("authors", []), warnings, e.get("id"))
    if not authors:
        warn("缺少著者")
    title = (e.get("title") or "").strip()
    if not title:
        warn("缺少题名")
    elif not is_cjk(title):
        warn("题名句读大小写未自动转换，请人工核对")
    year = str(e.get("year") or "").strip() or "n.d."
    etype = e.get("type", "other")
    if authors and not authors.endswith("."):
        authors += "."   # 著者项与年份之间的句点（西文缩写自带句点，中文名需补）
    s = (authors + " " if authors else "") + "(%s). " % year

    if etype == "journal-article":
        s += title + ". "
        if not e.get("journal"):
            warn("期刊论文缺少刊名")
        else:
            s += "*%s*" % e["journal"].strip()
            if e.get("volume"):
                s += ", *%s*" % e["volume"]
                if e.get("issue"):
                    s += "(%s)" % e["issue"]
            elif e.get("issue"):
                s += ", (%s)" % e["issue"]
                warn("有期号但缺卷号")
            pg = pages_norm(e.get("pages"))
            if pg:
                s += ", " + pg
            s += "."
    elif etype == "proceedings-article":
        s += title + ". "
        if not e.get("booktitle"):
            warn("会议论文缺少会议录名")
        else:
            pg = pages_norm(e.get("pages"))
            s += "In *%s*%s. " % (e["booktitle"].strip(), " (pp. %s)" % pg if pg else "")
        if e.get("publisher"):
            s += e["publisher"] + "."
        else:
            s = s.rstrip()
    elif etype == "book-chapter":
        s += title + ". "
        if not e.get("booktitle"):
            warn("专著章节缺少专著题名")
        else:
            pg = pages_norm(e.get("pages"))
            s += "In *%s*%s. " % (e["booktitle"].strip(), " (pp. %s)" % pg if pg else "")
        if e.get("publisher"):
            s += e["publisher"] + "."
        else:
            warn("专著章节缺少出版者")
            s = s.rstrip()
    elif etype == "book":
        s += "*%s*. " % title if title else ""
        if e.get("publisher"):
            s += e["publisher"] + "."
        else:
            warn("专著缺少出版者")
            s = s.rstrip()
    elif etype == "thesis":
        s += "*%s* [%s]. " % (title, "Doctoral dissertation" if "phd" in
                              (e.get("notes") or "").lower() else "Thesis")
        if e.get("publisher"):
            s += e["publisher"] + "."
        else:
            warn("学位论文缺少培养单位")
            s = s.rstrip()
    elif etype == "report":
        s += "*%s*. " % title
        if e.get("publisher"):
            s += e["publisher"] + "."
        else:
            warn("报告缺少出版机构")
            s = s.rstrip()
    elif etype == "preprint":
        s += "*%s* [Preprint]. " % title
        if e.get("arxiv"):
            s += "arXiv. https://arxiv.org/abs/%s" % e["arxiv"]
        elif e.get("url"):
            s += e["url"].rstrip("/")
        elif e.get("doi"):
            s += "https://doi.org/%s" % e["doi"]
        else:
            warn("预印本缺少获取路径")
            s = s.rstrip()
    else:  # online / other
        s += "*%s*. " % title if title else ""
        if e.get("url"):
            s += e["url"].rstrip("/")
        elif e.get("doi"):
            s += "https://doi.org/%s" % e["doi"]
        else:
            warn("网络资源缺少获取路径")
            s = s.rstrip()

    if e.get("doi") and etype in ("journal-article", "proceedings-article",
                                  "book", "book-chapter"):
        s += " https://doi.org/%s" % e["doi"]
    return re.sub(r"\s+", " ", s).strip()


def format_library(entries, ordered_ids=None, style="apa7"):
    """APA 文献表不编号、按著者字母排序；ordered_ids 仅用于过滤被引用条目。"""
    if style != "apa7":
        raise ValueError("apa7 模块仅支持 apa7 目标规范")
    by_id = {e["id"]: e for e in entries}
    ids = ordered_ids or [e["id"] for e in entries]
    warnings = []
    items = []
    for eid in ids:
        e = by_id.get(eid)
        if not e:
            warnings.append({"id": eid, "warning": "引用顺序表中的条目不在文献库中"})
            continue
        items.append(format_entry(e, warnings=warnings))
    items.sort(key=lambda s: s.lower())   # APA 按首著者字母排序
    return "\n".join(items) + ("\n" if items else ""), warnings


if __name__ == "__main__":
    lib_path = sys.argv[sys.argv.index("--library") + 1]
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    with open(lib_path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data["entries"] if isinstance(data, dict) else data
    text, warnings = format_library(entries)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("已生成 APA7 文献表 %d 条，告警 %d 条" % (
        len([ln for ln in text.splitlines() if ln.strip()]), len(warnings)))
