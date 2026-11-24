# -*- coding: utf-8 -*-
"""refparse.py — 解析 BibTeX / RIS / EndNote 标签 / CNKI(Refworks) 导出为规范化 JSON。

仅依赖 Python 3 标准库。规范化条目结构见 normalize_entry()。
"""
import json
import os
import re
import sys

CJK_RE = re.compile(r"[一-鿿]")


def detect_language(text):
    return "zh" if text and CJK_RE.search(text) else "en"


# ---------------------------------------------------------------- BibTeX

def parse_bibtex(text):
    """简版 BibTeX 解析：支持 brace/quote 值、嵌套括号、多文件拼接。"""
    entries = []
    pos = 0
    while True:
        at = text.find("@", pos)
        if at < 0:
            break
        m = re.match(r"@\s*(\w+)\s*([({])", text[at:])
        if not m:
            pos = at + 1
            continue
        etype, opener = m.group(1).lower(), m.group(2)
        closer = ")" if opener == "(" else "}"
        i = at + m.end()
        depth = 1
        while i < len(text) and depth:
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
            i += 1
        body = text[at + m.end(): i - 1]
        pos = i
        if etype in ("comment", "preamble", "string"):
            continue
        entries.append((etype, _parse_bib_body(body)))
    return entries


def _parse_bib_body(body):
    key_end = body.find(",")
    key = body[:key_end].strip() if key_end >= 0 else body.strip()
    fields = {}
    rest = body[key_end + 1:] if key_end >= 0 else ""
    i = 0
    n = len(rest)
    while i < n:
        m = re.match(r"\s*(\w+)\s*=", rest[i:])
        if not m:
            break
        name = m.group(1).lower()
        i += m.end()
        while i < n and rest[i] in " \t\n":
            i += 1
        if i < n and rest[i] == "{":
            depth = 1
            j = i + 1
            while j < n and depth:
                if rest[j] == "{":
                    depth += 1
                elif rest[j] == "}":
                    depth -= 1
                j += 1
            value = rest[i + 1: j - 1]
            i = j
        elif i < n and rest[i] == '"':
            j = i + 1
            while j < n and not (rest[j] == '"' and rest[j - 1] != "\\"):
                j += 1
            value = rest[i + 1: j]
            i = j + 1
        else:
            m2 = re.match(r"[^,\s]+", rest[i:])
            value = m2.group(0) if m2 else ""
            i += len(value)
        fields[name] = re.sub(r"\s+", " ", value).strip()
        comma = rest.find(",", i)
        i = comma + 1 if comma >= 0 else n
    return key, fields


BIB_TYPE_MAP = {
    "article": "journal-article",
    "inproceedings": "proceedings-article",
    "conference": "proceedings-article",
    "book": "book",
    "incollection": "book-chapter",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "misc": "other",
    "unpublished": "preprint",
    "techreport": "report",
    "online": "online",
}


def bib_to_entry(etype, key, fields):
    authors = [a.strip() for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
    journal = fields.get("journal", "")
    booktitle = fields.get("booktitle", "")
    arxiv = fields.get("eprint", "") if fields.get("archiveprefix", "").lower() == "arxiv" else ""
    if not arxiv:
        m = re.search(r"arxiv[:\s]*(\d{4}\.\d{4,5})", fields.get("url", "") + " " + fields.get("note", ""), re.I)
        arxiv = m.group(1) if m else ""
    etype_out = BIB_TYPE_MAP.get(etype, "other")
    if arxiv and not journal:
        etype_out = "preprint"
    return {
        "type": etype_out,
        "title": re.sub(r"[{}]", "", fields.get("title", "")),
        "authors": authors,
        "year": fields.get("year", ""),
        "journal": journal,
        "booktitle": booktitle,
        "publisher": fields.get("publisher", ""),
        "address": fields.get("address", fields.get("location", "")),
        "volume": fields.get("volume", ""),
        "issue": fields.get("number", ""),
        "pages": fields.get("pages", "").replace("--", "-"),
        "doi": fields.get("doi", "").strip().lower(),
        "arxiv": arxiv,
        "url": fields.get("url", ""),
        "source": {"format": "bibtex", "key": key, "bib_type": etype},
    }


# ---------------------------------------------------------------- RIS

RIS_TAG_MAP = {
    "TI": "title", "T1": "title", "AU": None, "A1": None,  # authors handled separately
    "PY": "year", "Y1": "year", "JO": "journal", "JF": "journal", "T2": "journal",
    "VL": "volume", "IS": "issue", "SP": "sp", "EP": "ep", "DO": "doi",
    "UR": "url", "PB": "publisher", "CY": "address", "BT": "booktitle",
}

RIS_TYPE_MAP = {
    "JOUR": "journal-article", "CONF": "proceedings-article", "CPAPER": "proceedings-article",
    "BOOK": "book", "CHAP": "book-chapter", "THES": "thesis", "RPRT": "report",
    "ELEC": "online", "UNPB": "preprint",
}


def parse_ris(text):
    entries = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if re.match(r"^[A-Z0-9]{2}  - ", ln)]
        if not lines:
            continue
        tags = {}
        for ln in lines:
            tag, val = ln[:2], ln[6:].strip()
            tags.setdefault(tag, []).append(val)
        if "TY" not in tags:
            continue
        entries.append(tags)
    out = []
    for tags in entries:
        e = {
            "type": RIS_TYPE_MAP.get(tags.get("TY", [""])[0], "other"),
            "title": (tags.get("TI") or tags.get("T1") or [""])[0],
            "authors": tags.get("AU", []) + tags.get("A1", []),
            "year": re.sub(r"\D.*$", "", (tags.get("PY") or tags.get("Y1") or [""])[0]),
            "journal": (tags.get("JO") or tags.get("JF") or [""])[0],
            "booktitle": (tags.get("BT") or (tags.get("T2") if tags.get("TY", [""])[0] in ("CONF", "CPAPER", "CHAP") else []) or [""])[0],
            "publisher": (tags.get("PB") or [""])[0],
            "address": (tags.get("CY") or [""])[0],
            "volume": (tags.get("VL") or [""])[0],
            "issue": (tags.get("IS") or [""])[0],
            "pages": "-".join(p for p in [(tags.get("SP") or [""])[0], (tags.get("EP") or [""])[0]] if p),
            "doi": (tags.get("DO") or [""])[0].lower(),
            "arxiv": "",
            "url": (tags.get("UR") or [""])[0],
            "source": {"format": "ris", "key": (tags.get("ID") or [""])[0]},
        }
        if e["type"] == "proceedings-article" and not e["booktitle"]:
            e["booktitle"], e["journal"] = e["journal"], ""
        out.append(e)
    return out


# ---------------------------------------------------------------- EndNote / CNKI 标签格式

ENW_TAG_MAP = {
    "%T": "title", "%A": "authors", "%J": "journal", "%B": "booktitle",
    "%D": "year", "%V": "volume", "%N": "issue", "%P": "pages",
    "%R": "doi", "%U": "url", "%I": "publisher", "%C": "address",
}

ENW_TYPE_MAP = {
    "Journal Article": "journal-article", "Conference Paper": "proceedings-article",
    "Conference Proceedings": "proceedings-article", "Book": "book",
    "Book Section": "book-chapter", "Thesis": "thesis", "Report": "report",
    "Web Page": "online", "Electronic Article": "journal-article",
}


def parse_enw(text):
    """EndNote 标签格式（CNKI 导出 EndNote 选项同为该格式）与 Refworks 标签。"""
    blocks = re.split(r"\n\s*\n", text)
    out = []
    for block in blocks:
        raw = {"authors": []}
        etype = ""
        for ln in block.splitlines():
            m = re.match(r"(%\w|RT |T1 |A1 |JF |JO |VL |IS |SP |OP |PB |PP |YR |DO |UR )\s*(.*)$", ln)
            if not m:
                continue
            tag, val = m.group(1), m.group(2).strip()
            if tag == "%0":
                etype = val
            elif tag == "RT ":
                etype = {"Journal": "Journal Article", "Confpaper": "Conference Paper"}.get(val, val)
            elif tag in ENW_TAG_MAP:
                k = ENW_TAG_MAP[tag]
                (raw.setdefault(k, []).append(val) if k == "authors" else raw.__setitem__(k, val))
            elif tag == "T1 ":
                raw["title"] = val
            elif tag == "A1 ":
                raw.setdefault("authors", []).append(val)
            elif tag in ("JF ", "JO "):
                raw["journal"] = val
            elif tag == "VL ":
                raw["volume"] = val
            elif tag == "IS ":
                raw["issue"] = val
            elif tag == "SP ":
                raw["pages"] = val
            elif tag == "OP ":
                raw["pages"] = (raw.get("pages", "") + "-" + val).strip("-")
            elif tag == "YR ":
                raw["year"] = val
            elif tag == "DO ":
                raw["doi"] = val.lower()
            elif tag == "UR ":
                raw["url"] = val
            elif tag == "PB ":
                raw["publisher"] = val
        if not raw.get("title"):
            continue
        e = {
            "type": ENW_TYPE_MAP.get(etype, "other"),
            "title": raw.get("title", ""),
            "authors": raw.get("authors", []),
            "year": raw.get("year", ""),
            "journal": raw.get("journal", ""),
            "booktitle": raw.get("booktitle", ""),
            "publisher": raw.get("publisher", ""),
            "address": raw.get("address", ""),
            "volume": raw.get("volume", ""),
            "issue": raw.get("issue", ""),
            "pages": raw.get("pages", "").replace("--", "-"),
            "doi": raw.get("doi", ""),
            "arxiv": "",
            "url": raw.get("url", ""),
            "source": {"format": "endnote", "key": ""},
        }
        out.append(e)
    return out


# ---------------------------------------------------------------- 规范化与入口

def read_text(path):
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read(), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read(), "utf-8-replace"


def detect_format(path, text):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".bib" or re.search(r"@\w+\s*[({]", text):
        return "bibtex"
    if ext == ".ris" or re.search(r"^TY  - ", text, re.M):
        return "ris"
    if re.search(r"^%0 |^RT ", text, re.M):
        return "enw"
    raise ValueError("无法识别的文献库格式：%s" % path)


def normalize_entry(e, idx, path):
    e["id"] = "e%04d" % idx
    e["title"] = re.sub(r"\s+", " ", e.get("title", "")).strip().rstrip(".")
    e["authors"] = [re.sub(r"\s+", " ", a).strip() for a in e.get("authors", [])]
    e["year"] = str(e.get("year", ""))[:4]
    e["language"] = detect_language(e["title"])
    e["source"]["file"] = os.path.basename(path)
    e.setdefault("aliases", [])
    e.setdefault("notes", "")
    return e


def parse_files(paths):
    """返回 (entries, warnings)。"""
    entries, warnings = [], []
    idx = 1
    for path in paths:
        try:
            text, enc = read_text(path)
            fmt = detect_format(path, text)
            if fmt == "bibtex":
                raw = [bib_to_entry(t, k, f) for t, (k, f) in parse_bibtex(text)]
            elif fmt == "ris":
                raw = parse_ris(text)
            else:
                raw = parse_enw(text)
            if enc not in ("utf-8-sig", "utf-8"):
                warnings.append({"file": os.path.basename(path), "warning": "编码为 %s，已转换" % enc})
            for e in raw:
                if not e["title"] and not e["authors"]:
                    warnings.append({"file": os.path.basename(path), "warning": "跳过无题名无作者的条目"})
                    continue
                entries.append(normalize_entry(e, idx, path))
                idx += 1
        except Exception as exc:  # 文件级失败不阻塞其他文件
            warnings.append({"file": os.path.basename(path), "warning": "解析失败：%s" % exc})
    return entries, warnings


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    inputs = [a for a in sys.argv[1:] if not a.startswith("--") and a != out]
    ents, warns = parse_files(inputs)
    payload = {"entries": ents, "parse_warnings": warns}
    text_out = json.dumps(payload, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text_out)
        print("解析 %d 条，警告 %d 条 -> %s" % (len(ents), len(warns), out))
    else:
        print(text_out)
