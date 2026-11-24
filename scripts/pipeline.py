# -*- coding: utf-8 -*-
"""pipeline.py — citation-manager 统一命令行入口。

子命令：
  parse     --inputs f1.bib f2.ris ... --out library.json
  dedup     --library library.json --out library_dedup.json --report dedup_report.json
  verify    --library library_dedup.json --out verify_report.json [--offline]
  renumber  --manuscript draft.md --library library_dedup.json [--mode placeholder|renumber|author-year]
            [--keymap keymap.json] --out manuscript_cited.md [--order-out order.json] [--report r.json]
  format    --library library_dedup.json [--order order.json] --style gbt7714 --out references.md
  check     --manuscript manuscript_cited.md --references references.md
            [--order order.json] [--library library_dedup.json] --out consistency_report.json

仅依赖 Python 3 标准库。各子命令亦可直接运行对应模块。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dedup as dedup_mod
import gbt7714
import refparse
import renumber as renum_mod
import verify as verify_mod


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _entries(data):
    return data["entries"] if isinstance(data, dict) else data


def _dump(obj, path):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)


def cmd_parse(argv):
    inputs = []
    if "--inputs" in argv:
        i = argv.index("--inputs") + 1
        while i < len(argv) and not argv[i].startswith("--"):
            inputs.append(argv[i])
            i += 1
    if not inputs:
        raise SystemExit("parse 需要 --inputs <文件...>")
    entries, warnings = refparse.parse_files(inputs)
    payload = {"entries": entries, "parse_warnings": warnings}
    _dump(payload, _arg(argv, "--out"))
    print("解析 %d 条，警告 %d 条" % (len(entries), len(warnings)))


def cmd_dedup(argv):
    data = _load(_arg(argv, "--library"))
    kept, report = dedup_mod.dedup(_entries(data))
    if isinstance(data, dict):
        data["entries"] = kept
    else:
        data = kept
    _dump(data, _arg(argv, "--out"))
    _dump(report, _arg(argv, "--report"))
    print("去重：%d -> %d 条；合并 %d 组；防误并提示 %d；待人工确认 %d" % (
        report["total_before"], report["total_after"], len(report["merge_decisions"]),
        len(report["warnings_not_merged"]), len(report["needs_human_confirmation"])))


def cmd_verify(argv):
    entries = _entries(_load(_arg(argv, "--library")))
    report = verify_mod.verify_entries(entries, offline="--offline" in argv)
    _dump(report, _arg(argv, "--out"))
    print("核验汇总：%s" % json.dumps(report["summary"], ensure_ascii=False))


def cmd_renumber(argv):
    with open(_arg(argv, "--manuscript"), encoding="utf-8") as fh:
        text = fh.read()
    mode = _arg(argv, "--mode", "placeholder")
    if mode == "placeholder":
        entries = _entries(_load(_arg(argv, "--library")))
        new_text, order, missing, unknown = renum_mod.resolve_placeholders(
            text, {e["id"] for e in entries})
        order_path = _arg(argv, "--order-out")
        if order_path:
            _dump(order, order_path)
        report = {"mode": mode, "cited_entries": len(order),
                  "missing_source_marks": missing, "unknown_ids": unknown}
    elif mode == "renumber":
        new_body, new_refs, order_old, report, _notes = renum_mod.renumber_numeric(text)
        report["mode"] = mode
        new_text = new_body.rstrip() + "\n\n## 参考文献\n\n" + renum_mod.render_reference_list(new_refs) + "\n"
    elif mode == "author-year":
        report = renum_mod.check_author_year(text, _load(_arg(argv, "--keymap")))
        report["mode"] = mode
        new_text = text
    else:
        raise SystemExit("未知模式：%s" % mode)
    out = _arg(argv, "--out")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    _dump(report, _arg(argv, "--report"))
    print("renumber(%s) 完成：%s" % (mode, json.dumps(
        {k: v for k, v in report.items() if k != "old_to_new"}, ensure_ascii=False)[:400]))


def cmd_format(argv):
    entries = _entries(_load(_arg(argv, "--library")))
    order = _load(_arg(argv, "--order")) if "--order" in argv else None
    text = gbt7714.format_library(entries, ordered_ids=order)
    out = _arg(argv, "--out")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("已生成文献表 %d 条" % len(text.strip().splitlines()))


def cmd_check(argv):
    with open(_arg(argv, "--manuscript"), encoding="utf-8") as fh:
        ms = fh.read()
    with open(_arg(argv, "--references"), encoding="utf-8") as fh:
        refs = fh.read()
    order = _load(_arg(argv, "--order")) if "--order" in argv else None
    library = _entries(_load(_arg(argv, "--library"))) if "--library" in argv else None
    report = renum_mod.consistency_check(ms, refs, order=order, library=library)
    _dump(report, _arg(argv, "--out"))
    print("一致性：%s；悬空编号 %d；未引条目 %d；缺口 %d；残留占位符 %d" % (
        "通过" if report["consistent"] else "未通过",
        len(report["orphan_markers"]), len(report["uncited_list_entries"]),
        len(report["numbering_gaps"]), len(report["unresolved_cite_placeholders"])))


COMMANDS = {
    "parse": cmd_parse, "dedup": cmd_dedup, "verify": cmd_verify,
    "renumber": cmd_renumber, "format": cmd_format, "check": cmd_check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])
