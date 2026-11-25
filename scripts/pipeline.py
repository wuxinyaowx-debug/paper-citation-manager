# -*- coding: utf-8 -*-
"""pipeline.py — citation-manager 统一命令行入口。

子命令：
  parse     --inputs f1.bib f2.ris ... [--out library.json]
  dedup     --library library.json [--out library_dedup.json] [--report dedup_report.json]
            [--overrides overrides.json]
  verify    --library library_dedup.json [--out verify_report.json] [--offline]
  renumber  --manuscript draft.md [--mode placeholder|renumber|author-year]
            [--library library_dedup.json] [--keymap keymap.json]
            [--out manuscript_cited.md] [--order-out order.json] [--report r.json]
  format    --library library_dedup.json [--order order.json] [--style gbt7714|apa7]
            [--out references.md] [--report format_report.json]
  check     --manuscript manuscript_cited.md --references references.md
            [--order order.json] [--library library_dedup.json] [--issues renumber_report.json]
            [--out consistency_report.json]

脚本路径相对于自身所在目录解析，不依赖当前工作目录。仅依赖 Python 3 标准库。
缺失必需参数时给出中文用法提示并以非零码退出。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apa7 as apa7_mod
import dedup as dedup_mod
import gbt7714
import refparse
import renumber as renum_mod
import verify as verify_mod


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def _req(argv, name, cmd, hint=""):
    if name not in argv or argv.index(name) + 1 >= len(argv):
        raise SystemExit("[%s] 缺少必需参数 %s。%s\n用 python3 pipeline.py 不带参数可查看全部子命令用法。"
                         % (cmd, name, hint))
    return argv[argv.index(name) + 1]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _entries(data):
    return data["entries"] if isinstance(data, dict) else data


def _dump(obj, path):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)


def _write_text(text, path):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def cmd_parse(argv):
    inputs = []
    if "--inputs" in argv:
        i = argv.index("--inputs") + 1
        while i < len(argv) and not argv[i].startswith("--"):
            inputs.append(argv[i])
            i += 1
    if not inputs:
        raise SystemExit("[parse] 缺少必需参数 --inputs <文献库文件...>")
    missing = [p for p in inputs if not os.path.isfile(p)]
    if missing:
        raise SystemExit("[parse] 输入文件不存在：%s" % "、".join(missing))
    entries, warnings = refparse.parse_files(inputs)
    _dump({"entries": entries, "parse_warnings": warnings}, _arg(argv, "--out"))
    print("解析 %d 条，警告 %d 条" % (len(entries), len(warnings)))


def cmd_dedup(argv):
    data = _load(_req(argv, "--library", "dedup"))
    overrides = _load(_arg(argv, "--overrides")) if "--overrides" in argv else None
    kept, report = dedup_mod.dedup(_entries(data), overrides=overrides)
    if isinstance(data, dict):
        data["entries"] = kept
    else:
        data = kept
    _dump(data, _arg(argv, "--out"))
    _dump(report, _arg(argv, "--report"))
    print("去重：%d -> %d 条；合并 %d 组；未合并告警 %d；待人工确认 %d；传递性拆分 %d" % (
        report["total_before"], report["total_after"], len(report["merge_decisions"]),
        len(report["warnings_not_merged"]), len(report["needs_human_confirmation"]),
        len(report["transitive_split_review"])))


def cmd_verify(argv):
    entries = _entries(_load(_req(argv, "--library", "verify")))
    report = verify_mod.verify_entries(entries, offline="--offline" in argv)
    _dump(report, _arg(argv, "--out"))
    print("核验汇总：%s" % json.dumps(report["summary"], ensure_ascii=False))


def cmd_renumber(argv):
    ms = _req(argv, "--manuscript", "renumber")
    if not os.path.isfile(ms):
        raise SystemExit("[renumber] 稿件文件不存在：%s" % ms)
    with open(ms, encoding="utf-8") as fh:
        text = fh.read()
    mode = _arg(argv, "--mode", "placeholder")

    if mode == "placeholder":
        entries = _entries(_load(_req(argv, "--library", "renumber",
                                     "placeholder 模式需要 --library")))
        new_text, order, missing, unknown, extra = renum_mod.resolve_placeholders(
            text, {e["id"] for e in entries})
        order_path = _arg(argv, "--order-out")
        if order_path:
            _dump(order, order_path)
        report = {"mode": mode, "cited_entries": len(order),
                  "missing_source_marks": missing, "unknown_ids": unknown, **extra}
    elif mode == "renumber":
        new_body, new_refs, order_old, report, notes = renum_mod.renumber_numeric(text)
        report["mode"] = mode
        heading = notes[0] if notes and notes[0].lstrip().startswith("#") else "## 参考文献"
        new_text = new_body.rstrip() + "\n\n" + renum_mod.render_reference_list(
            new_refs, notes, heading)
    elif mode == "author-year":
        report = renum_mod.check_author_year(
            text, _load(_req(argv, "--keymap", "renumber", "author-year 模式需要 --keymap")))
        report["mode"] = mode
        new_text = text
    else:
        raise SystemExit("[renumber] 未知模式：%s（可选 placeholder / renumber / author-year）" % mode)

    _write_text(new_text, _arg(argv, "--out"))
    _dump(report, _arg(argv, "--report"))
    print("renumber(%s) 完成：%s" % (mode, json.dumps(
        {k: v for k, v in report.items() if k != "old_to_new"},
        ensure_ascii=False)[:500]))


def cmd_format(argv):
    entries = _entries(_load(_req(argv, "--library", "format")))
    order = _load(_arg(argv, "--order")) if "--order" in argv else None
    style = _arg(argv, "--style", "gbt7714").lower()
    try:
        if style == "gbt7714":
            text, warnings = gbt7714.format_library(entries, ordered_ids=order, style=style)
        elif style in ("apa7", "apa"):
            text, warnings = apa7_mod.format_library(entries, ordered_ids=order, style="apa7")
        else:
            raise ValueError("不支持的目标规范：%s（可选 gbt7714 / apa7）" % style)
    except ValueError as exc:
        raise SystemExit("[format] %s" % exc)
    _write_text(text, _arg(argv, "--out"))
    _dump({"format_warnings": warnings}, _arg(argv, "--report"))
    print("已生成文献表 %d 条，告警 %d 条" % (
        len([ln for ln in text.splitlines() if ln.strip()]), len(warnings)))


def cmd_check(argv):
    ms_path = _req(argv, "--manuscript", "check")
    refs_path = _req(argv, "--references", "check")
    for p in (ms_path, refs_path):
        if not os.path.isfile(p):
            raise SystemExit("[check] 文件不存在：%s" % p)
    with open(ms_path, encoding="utf-8") as fh:
        ms = fh.read()
    with open(refs_path, encoding="utf-8") as fh:
        refs = fh.read()
    order = _load(_arg(argv, "--order")) if "--order" in argv else None
    library = _entries(_load(_arg(argv, "--library"))) if "--library" in argv else None
    issues = _load(_arg(argv, "--issues")) if "--issues" in argv else None
    report = renum_mod.consistency_check(ms, refs, order=order, library=library, issues=issues)
    _dump(report, _arg(argv, "--out"))
    print("总体状态：%s（结构一致=%s，证据完整=%s）；悬空 %d；未引 %d；缺口 %d；"
          "残留占位符 %d；来源缺失 %d；未知 ID %d" % (
              report["overall_status"], report["structural_consistent"],
              report["evidence_complete"],
              len(report["structural"]["orphan_markers"]),
              len(report["structural"]["uncited_list_entries"]),
              len(report["structural"]["numbering_gaps"]),
              len(report["structural"]["unresolved_cite_placeholders"]),
              report["evidence"]["missing_source_count"],
              len(report["evidence"]["unknown_ids"])))


COMMANDS = {
    "parse": cmd_parse, "dedup": cmd_dedup, "verify": cmd_verify,
    "renumber": cmd_renumber, "format": cmd_format, "check": cmd_check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(1)
    try:
        COMMANDS[sys.argv[1]](sys.argv[2:])
    except SystemExit:
        raise
    except FileNotFoundError as exc:
        raise SystemExit("[%s] 文件不存在：%s" % (sys.argv[1], exc.filename))
    except json.JSONDecodeError as exc:
        raise SystemExit("[%s] JSON 解析失败：%s" % (sys.argv[1], exc))
    except Exception as exc:  # 异常以可读形式呈现，不输出堆栈噪声
        raise SystemExit("[%s] 运行失败：%s: %s" % (sys.argv[1], type(exc).__name__, exc))
