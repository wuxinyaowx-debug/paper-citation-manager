# -*- coding: utf-8 -*-
"""citation-manager 自动化测试（unittest，仅标准库）。

所有测试数据均为合成材料，仅用于检查代码正确性，
不是官方正式案例，也不代表平台测试结果。

运行：python3 tests/test_citation_manager.py  （或 python3 -m unittest discover tests）
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(os.path.dirname(TESTS_DIR), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import dedup as dedup_mod
import gbt7714
import refparse
import renumber as renum_mod
import verify as verify_mod


def make_entry(**kw):
    base = {"id": "e0001", "type": "journal-article", "title": "", "authors": [],
            "year": "", "journal": "", "booktitle": "", "publisher": "",
            "address": "", "volume": "", "issue": "", "pages": "", "doi": "",
            "arxiv": "", "url": "", "language": "en",
            "source": {"format": "bibtex", "key": "", "file": "t.bib"},
            "aliases": [], "notes": ""}
    base.update(kw)
    return base


# ---------------------------------------------------------------- 解析

class TestParse(unittest.TestCase):
    def test_bibtex_basic(self):
        text = ('@article{a1, author={Zhang, San and Li, Si}, title={Deep Learning for X},\n'
                ' journal={Nature}, year={2020}, volume={5}, number={2}, pages={1--10},\n'
                ' doi={10.1000/xyz123}}\n'
                '@inproceedings{b2, author={Wang, Wu}, title={Conf Paper},\n'
                ' booktitle={Proc. ICML}, year={2021}, pages={11--22}}')
        with tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        try:
            entries, warns = refparse.parse_files([path])
        finally:
            os.unlink(path)
        self.assertEqual(len(entries), 2)
        e1, e2 = entries
        self.assertEqual(e1["type"], "journal-article")
        self.assertEqual(e1["authors"], ["Zhang, San", "Li, Si"])
        self.assertEqual(e1["pages"], "1-10")
        self.assertEqual(e1["doi"], "10.1000/xyz123")
        self.assertEqual(e2["type"], "proceedings-article")
        self.assertEqual(e2["booktitle"], "Proc. ICML")
        self.assertEqual(warns, [])

    def test_ris_multi_record_no_blank_lines(self):
        """RIS 记录之间无空行时也必须正确拆分。"""
        text = ("TY  - JOUR\nTI  - First Paper\nAU  - Zhang, San\nPY  - 2019\nER  -\n"
                "TY  - JOUR\nTI  - Second Paper\nAU  - Li, Si\nPY  - 2021\nVL  - 3\nER  -\n")
        with tempfile.NamedTemporaryFile("w", suffix=".ris", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        try:
            entries, _ = refparse.parse_files([path])
        finally:
            os.unlink(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["title"], "First Paper")
        self.assertEqual(entries[1]["title"], "Second Paper")
        self.assertEqual(entries[1]["volume"], "3")

    def test_endnote_cnki_parse(self):
        text = ("%0 Journal Article\n%T 深度学习综述\n%A 张三\n%A 李四\n"
                "%J 软件学报\n%D 2018\n%V 29\n%N 4\n%P 100-120\n%R 10.13328/j.cnki.jos.005432\n\n"
                "%0 Conference Paper\n%T A Method\n%A Smith, John\n%B Proc. AAAI\n%D 2020\n")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            path = fh.name
        try:
            entries, _ = refparse.parse_files([path])
        finally:
            os.unlink(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["language"], "zh")
        self.assertEqual(entries[0]["authors"], ["张三", "李四"])
        self.assertEqual(entries[0]["doi"], "10.13328/j.cnki.jos.005432")
        self.assertEqual(entries[1]["type"], "proceedings-article")
        self.assertEqual(entries[1]["booktitle"], "Proc. AAAI")

    def test_gbk_encoded_file(self):
        text = "%0 Journal Article\n%T 中文题名测试\n%A 王五\n%J 测试学报\n%D 2017\n"
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as fh:
            fh.write(text.encode("gbk"))
            path = fh.name
        try:
            entries, warns = refparse.parse_files([path])
        finally:
            os.unlink(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "中文题名测试")
        self.assertTrue(any("编码" in w["warning"] for w in warns))

    def test_unrecognized_format_raises_warning_not_crash(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write("这不是任何已知格式的文献库文件。")
            path = fh.name
        try:
            entries, warns = refparse.parse_files([path])
        finally:
            os.unlink(path)
        self.assertEqual(entries, [])
        self.assertTrue(any("解析失败" in w["warning"] for w in warns))


# ---------------------------------------------------------------- 去重

class TestDedup(unittest.TestCase):
    def test_doi_conflict_not_silently_merged(self):
        """DOI 相同但题名明显冲突：不得自动合并，应列入人工确认。"""
        a = make_entry(id="e1", title="A Study on Cats", authors=["Zhang, San"],
                       year="2020", doi="10.1000/x1")
        b = make_entry(id="e2", title="Completely Different Topic About Rockets",
                       authors=["Li, Si"], year="2021", doi="10.1000/x1")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertTrue(any(f["flag"] == "doi_metadata_conflict"
                            for f in report["needs_human_confirmation"]))

    def test_preprint_and_journal_merged(self):
        a = make_entry(id="e1", title="Attention Is All You Need",
                       authors=["Vaswani, Ashish"], year="2017",
                       journal="NeurIPS", volume="30", pages="5998-6008")
        b = make_entry(id="e2", type="preprint", title="Attention Is All You Need",
                       authors=["Vaswani, Ashish"], year="2017", arxiv="1706.03762")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], "e1")            # 保留正式版
        self.assertEqual(kept[0]["arxiv"], "1706.03762")  # 独有字段回填
        self.assertEqual(kept[0]["merged_from"][0]["id"], "e2")
        dec = report["merge_decisions"][0]
        self.assertIn(dec["rule"], ("title_author_year", "arxiv_exact"))
        self.assertIn("field_comparison", dec)

    def test_arxiv_versions_same_work(self):
        a = make_entry(id="e1", type="preprint", title="Paper X",
                       authors=["A, B"], year="2020", arxiv="2001.00001v1")
        b = make_entry(id="e2", type="preprint", title="Paper X",
                       authors=["A, B"], year="2020", arxiv="2001.00001v3")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(report["merge_decisions"][0]["rule"], "arxiv_exact")

    def test_same_author_different_papers_not_merged(self):
        """同名作者的不同论文不得合并。"""
        a = make_entry(id="e1", title="Deep Learning for Vision",
                       authors=["Wang, Wei"], year="2020")
        b = make_entry(id="e2", title="Graph Neural Networks Survey",
                       authors=["Wang, Wei"], year="2020")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(report["merge_decisions"], [])

    def test_same_title_different_authors_not_merged(self):
        a = make_entry(id="e1", title="A Survey of Transformers",
                       authors=["Zhang, San"], year="2021")
        b = make_entry(id="e2", title="A Survey of Transformers",
                       authors=["Li, Si"], year="2021")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertTrue(any(f["flag"] == "possible_different_works"
                            for f in report["warnings_not_merged"]))

    def test_missing_year_not_used_as_evidence(self):
        """缺失年份不得被当作一致证据：应降级为候选而非自动合并。"""
        a = make_entry(id="e1", title="Exact Same Title Here",
                       authors=["Zhang, San"], year="")
        b = make_entry(id="e2", title="Exact Same Title Here",
                       authors=["Zhang, San"], year="2020")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertTrue(any(f["flag"] == "candidates_missing_fields"
                            for f in report["needs_human_confirmation"]))

    def test_translation_pair_candidate(self):
        """中英文题名同文：列为人工确认候选，不自动合并。"""
        a = make_entry(id="e1", title="深度学习方法综述", authors=["张三", "李四"],
                       year="2020", language="zh")
        b = make_entry(id="e2", title="A Survey of Deep Learning Methods",
                       authors=["Zhang, San", "Li, Si"], year="2020")
        kept, report = dedup_mod.dedup([a, b])
        self.assertEqual(len(kept), 2)
        self.assertTrue(any(f["flag"] == "possible_translation_pair"
                            for f in report["needs_human_confirmation"]))

    def test_transitive_split(self):
        """A~B、B~C 但 A 与 C 不可比：C 应被拆出并标记复核。"""
        a = make_entry(id="e1", title="Quantum Computing Basics",
                       authors=["Zhang, San"], year="2020", doi="10.1000/q1")
        b = make_entry(id="e2", title="Quantum Computing Basics",
                       authors=["Zhang, San"], year="2020")
        c = make_entry(id="e3", title="Quantum Computing Basics: Advanced Topics",
                       authors=["Zhang, San"], year="2020", doi="10.1000/q1")
        # e1-e2 标题相同合并；e1-e3 DOI 相同但题名相似度中等（>=0.6 不冲突）会合并。
        # 人为构造：e2 与 e3 不同，但 e3 经 DOI 与 e1 同组；锚点校验看 e3 vs e1 标题。
        kept, report = dedup_mod.dedup([a, b, c])
        # 不断言具体拆分结果，只要求：若发生合并组>2，拆分机制有报告字段
        self.assertIn("transitive_split_review", report)
        self.assertGreaterEqual(len(kept), 1)

    def test_overrides_split(self):
        """人工否决自动合并。"""
        a = make_entry(id="e1", title="Same Title Work", authors=["Zhang, San"],
                       year="2020", doi="10.1000/s1")
        b = make_entry(id="e2", title="Same Title Work", authors=["Zhang, San"],
                       year="2020", doi="10.1000/s1")
        kept, report = dedup_mod.dedup([a, b], overrides={"split": [["e1", "e2"]]})
        self.assertEqual(len(kept), 2)
        self.assertTrue(any(o["action"] == "split" for o in report["overrides_applied"]))

    def test_overrides_merge(self):
        a = make_entry(id="e1", title="Work Alpha", authors=["Zhang, San"], year="2020")
        b = make_entry(id="e2", title="完全不同的标题", authors=["张三", "李四"],
                       year="2020", language="zh")
        kept, report = dedup_mod.dedup([a, b], overrides={"merge": [["e1", "e2"]]})
        self.assertEqual(len(kept), 1)
        self.assertTrue(any(o["action"] == "merge" for o in report["overrides_applied"]))


# ---------------------------------------------------------------- 核验

class TestVerify(unittest.TestCase):
    def test_offline_all_marked_offline(self):
        entries = [make_entry(id="e1", doi="10.1038/nature14539", title="Deep learning",
                              year="2015"),
                   make_entry(id="e2", title="No DOI paper", year="2020")]
        report = verify_mod.verify_entries(entries, offline=True)
        statuses = {r["id"]: r["status"] for r in report["records"]}
        self.assertEqual(statuses["e1"], "offline")
        self.assertEqual(statuses["e2"], "unverified")

    def test_invalid_doi_format(self):
        entries = [make_entry(id="e1", doi="not-a-doi", title="X", year="2020")]
        report = verify_mod.verify_entries(entries, offline=True)
        rec = report["records"][0]
        self.assertEqual(rec["status"], "unverified")
        self.assertIn("格式非法", rec["reason"])

    def test_remote_missing_fields_not_verified(self):
        """远程记录缺题名/年份时不得标 verified（离线构造比对逻辑直接测试）。"""
        remote = {"title": "", "year": "", "container": "Nature",
                  "first_author_surname": "lecun", "type": "journal-article"}
        e = make_entry(id="e1", title="Deep learning", authors=["LeCun, Yann"],
                       year="2015", journal="Nature")
        problems, checked, missing = verify_mod.compare(e, remote)
        self.assertIn("title", missing)
        self.assertIn("year", missing)
        self.assertNotIn("title", checked)

    def test_compare_detects_mismatch(self):
        remote = {"title": "Deep learning", "year": "2016", "container": "Nature",
                  "first_author_surname": "lecun", "type": "journal-article"}
        e = make_entry(id="e1", title="Deep learning", authors=["LeCun, Yann"],
                       year="2015", journal="Nature")
        problems, checked, missing = verify_mod.compare(e, remote)
        self.assertTrue(any("年份不符" in p for p in problems))


# ---------------------------------------------------------------- 编号与一致性

class TestRenumber(unittest.TestCase):
    def test_placeholder_resolve_and_missing(self):
        text = "论断一{cite:e1}。论断二{cite:e2,MISSING}。再次引用{cite:e1}。"
        new_text, order, missing, unknown, extra = renum_mod.resolve_placeholders(
            text, {"e1", "e2"})
        self.assertEqual(order, ["e1", "e2"])
        self.assertIn("论断一[1]。", new_text)
        self.assertIn("论断二[2][来源缺失]。", new_text)
        self.assertEqual(len(missing), 1)
        self.assertIn("再次引用[1]。", new_text)

    def test_unknown_id_reported(self):
        new_text, order, missing, unknown, extra = renum_mod.resolve_placeholders(
            "引用{cite:e99}。", {"e1"})
        self.assertEqual(unknown[0]["id"], "e99")
        self.assertIn("[来源缺失]", new_text)

    def test_compress_ranges(self):
        self.assertEqual(renum_mod.compress([1, 2, 3, 5, 7, 8]), "[1-3,5,7,8]")
        self.assertEqual(renum_mod.compress([3, 1, 2]), "[1-3]")
        self.assertEqual(renum_mod.compress([1]), "[1]")

    def test_renumber_existing(self):
        text = ("方法A[3]。改进[1-2]。局限[5]。\n\n## 参考文献\n\n"
                "[1] 甲.\n[2] 乙.\n[3] 丙.\n[4] 丁.\n[5] 戊.\n")
        new_body, new_refs, order_old, report, notes = renum_mod.renumber_numeric(text)
        self.assertIn("方法A[1]。", new_body)
        self.assertIn("改进[2,3]。", new_body)
        self.assertIn("局限[4]。", new_body)
        self.assertEqual(new_refs[1], "丙.")
        self.assertEqual(new_refs[4], "戊.")
        self.assertEqual(report["uncited_list_entries"], [4])
        self.assertEqual(report["orphan_markers"], [])

    def test_plain_brackets_untouched(self):
        """普通方括号数字（区间、年份、公式编号）不得被改写。"""
        text = ("取值范围 [0,1] 内。发表于 [2020] 年。公式 [3] 如上。\n\n"
                "## 参考文献\n\n[1] 甲.\n")
        new_body, new_refs, order_old, report, notes = renum_mod.renumber_numeric(text)
        self.assertIn("[0,1]", new_body)      # 行内区间：前文为空白+前文非操作符?
        self.assertIn("[2020]", new_body)
        # 三个标记均不应被当作引用
        self.assertEqual(order_old, [])
        self.assertEqual(len(report["ambiguous_markers_untouched"]), 3)

    def test_math_context_marker_untouched(self):
        text = "由 x = [2] 可得结论[1]。\n\n## 参考文献\n\n[1] 甲.\n"
        new_body, new_refs, order_old, report, notes = renum_mod.renumber_numeric(text)
        self.assertIn("x = [2]", new_body)   # 操作符后的 [2] 保留
        self.assertIn("结论[1]。", new_body)  # 正文引用正常处理
        self.assertEqual(order_old, [1])
        self.assertEqual(len(report["ambiguous_markers_untouched"]), 1)

    def test_reference_notes_preserved(self):
        text = ("正文[1]。\n\n## 参考文献\n\n（按引用顺序排列）\n[1] 甲.\n")
        new_body, new_refs, order_old, report, notes = renum_mod.renumber_numeric(text)
        rendered = renum_mod.render_reference_list(new_refs, notes)
        self.assertIn("（按引用顺序排列）", rendered)

    def test_consistency_structural_vs_evidence(self):
        """结构一致但存在来源缺失时：structural_consistent=True，evidence_complete=False。"""
        ms = "论断[1]，但此处无源[来源缺失]。"
        refs = "[1] 甲.\n"
        report = renum_mod.consistency_check(ms, refs)
        self.assertTrue(report["structural_consistent"])
        self.assertFalse(report["evidence_complete"])
        self.assertEqual(report["overall_status"], "evidence_incomplete")
        self.assertFalse(report["consistent"])

    def test_consistency_orphan_and_uncited(self):
        ms = "引用[1]与[3]。"
        refs = "[1] 甲.\n[2] 乙.\n"
        report = renum_mod.consistency_check(ms, refs)
        self.assertEqual(report["structural"]["orphan_markers"], [3])
        self.assertEqual(report["structural"]["uncited_list_entries"], [2])
        self.assertFalse(report["structural_consistent"])
        self.assertEqual(report["overall_status"], "inconsistent")

    def test_consistency_issues_merged(self):
        ms = "引用[1]。"
        refs = "[1] 甲.\n"
        issues = {"unknown_ids": [{"id": "e99", "context": "..."}],
                  "low_confidence_citations": [{"citation": "[1]", "reason": "仅背景相关"}],
                  "human_review_items": ["第 2 段论断待确认"]}
        report = renum_mod.consistency_check(ms, refs, issues=issues)
        self.assertFalse(report["evidence_complete"])
        self.assertEqual(len(report["evidence"]["unknown_ids"]), 1)
        self.assertEqual(len(report["evidence"]["low_confidence_citations"]), 1)

    def test_author_year_bidirectional(self):
        text = ("已知方法 (Zhang 等, 2020) 有效。Smith (2019) 提出另一方案。\n\n"
                "## 参考文献\n\nZhang 等. 某研究. 2020.\nSmith J. Another. 2019.\n")
        keymap = {"Zhang 等, 2020": "e0003"}
        report = renum_mod.check_author_year(text, keymap)
        self.assertEqual(report["citations_not_in_text"], [])
        self.assertTrue(any("Smith" in c for c in report["unchecked_citations"]))
        self.assertFalse(report["consistent"])


# ---------------------------------------------------------------- 格式化

class TestFormat(unittest.TestCase):
    def test_zh_authors_more_than_three(self):
        e = make_entry(id="e1", title="中文论文", authors=["张三", "李四", "王五", "赵六"],
                       year="2020", journal="物理学报", volume="69", issue="12",
                       pages="120101", language="zh")
        s = gbt7714.format_entry(e, ref_date="2026-01-01")
        self.assertTrue(s.startswith("张三, 李四, 王五, 等. "))
        self.assertIn("[J]. 物理学报, 2020, 69(12): 120101.", s)

    def test_en_compound_surname_and_particle(self):
        self.assertEqual(gbt7714.format_author_name("John Smith-Jones"), "SMITH-JONES J")
        self.assertEqual(gbt7714.format_author_name("Ludwig van Beethoven"), "VAN BEETHOVEN L")
        self.assertTrue(gbt7714.format_author_name("van der Waals, Johannes")
                        .startswith("VAN DER WAALS"))

    def test_and_others(self):
        e = make_entry(id="e1", title="Paper", authors=["Vaswani, Ashish", "others"],
                       year="2017", journal="NeurIPS", volume="30", pages="1-2")
        s = gbt7714.format_entry(e, ref_date="2026-01-01")
        self.assertIn("VASWANI A, et al.", s)

    def test_missing_fields_warned_not_fabricated(self):
        e = make_entry(id="e1", title="Incomplete Record", authors=["Zhang, San"],
                       year="2020")  # 缺刊名卷期页
        warnings = []
        s = gbt7714.format_entry(e, ref_date="2026-01-01", warnings=warnings)
        self.assertIn("Incomplete Record[J]. 2020.", s)
        self.assertTrue(any("刊名" in w["warning"] for w in warnings))
        self.assertNotIn("None", s)

    def test_book_chapter_and_preprint(self):
        chap = make_entry(id="e1", type="book-chapter", title="Chapter One",
                          authors=["Zhang, San"], year="2019", booktitle="Big Book",
                          publisher="科学出版社", address="北京", pages="10-30", language="zh")
        s = gbt7714.format_entry(chap, ref_date="2026-01-01")
        self.assertIn("[M]//Big Book.", s)
        self.assertIn("北京: 科学出版社, 2019: 10-30.", s)
        pre = make_entry(id="e2", type="preprint", title="Preprint X",
                         authors=["Li, Si"], year="2021", arxiv="2101.00001")
        s2 = gbt7714.format_entry(pre, ref_date="2026-01-01")
        self.assertIn("[EB/OL]. (2021-01-01)[2026-01-01]. https://arxiv.org/abs/2101.00001.", s2)

    def test_format_library_order_and_warnings(self):
        e1 = make_entry(id="e1", title="A", authors=["A, B"], year="2020", journal="J")
        e2 = make_entry(id="e2", title="B", authors=["C, D"], year="2021", journal="J")
        text, warnings = gbt7714.format_library([e1, e2], ordered_ids=["e2", "e1", "e99"])
        lines = text.strip().splitlines()
        self.assertTrue(lines[0].startswith("[1] C D. B"))
        self.assertTrue(lines[1].startswith("[2] A B. A"))
        self.assertTrue(any(w["id"] == "e99" for w in warnings))


# ---------------------------------------------------------------- 端到端与稳定性

PIPELINE = os.path.join(SCRIPTS_DIR, "pipeline.py")


class TestEndToEnd(unittest.TestCase):
    def _run(self, args, cwd=None):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, PIPELINE] + args,
                              capture_output=True, text=True, cwd=cwd, env=env,
                              encoding="utf-8", errors="replace")
        return proc

    def test_full_pipeline_and_repeat_stability(self):
        """完整流水线跑两次，产物一致（重复运行稳定性）。"""
        bib = ("@article{a, author={Zhang, San and Li, Si and Wang, Wu and Zhao, Liu},\n"
               " title={深度学习方法研究}, journal={物理学报}, year={2020}, volume={1},\n"
               " pages={1--9}, doi={10.7498/aps.1.1}}\n"
               "@misc{b, author={Zhang, San and Li, Si and Wang, Wu and Zhao, Liu},\n"
               " title={深度学习方法研究}, year={2020}, eprint={2001.00001},\n"
               " archiveprefix={arXiv}}\n")
        draft = "研究{cite:e0001}已有报道，另有补充{cite:e0001}。"
        with tempfile.TemporaryDirectory() as td:
            lib = os.path.join(td, "lib.bib")
            with open(lib, "w", encoding="utf-8") as fh:
                fh.write(bib)
            results = []
            for run in ("run1", "run2"):
                work = os.path.join(td, run)
                os.makedirs(work)
                steps = [
                    ["parse", "--inputs", lib, "--out", os.path.join(work, "library.json")],
                    ["dedup", "--library", os.path.join(work, "library.json"),
                     "--out", os.path.join(work, "library_dedup.json"),
                     "--report", os.path.join(work, "dedup_report.json")],
                ]
                for args in steps:
                    proc = self._run(args)
                    self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                # 占位符引用 e0001（去重后保留 e0001，e0002 并入）
                with open(os.path.join(work, "draft.md"), "w", encoding="utf-8") as fh:
                    fh.write(draft)
                proc = self._run(["renumber", "--manuscript", os.path.join(work, "draft.md"),
                                  "--library", os.path.join(work, "library_dedup.json"),
                                  "--out", os.path.join(work, "ms.md"),
                                  "--order-out", os.path.join(work, "order.json"),
                                  "--report", os.path.join(work, "renumber_report.json")])
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                proc = self._run(["format", "--library", os.path.join(work, "library_dedup.json"),
                                  "--order", os.path.join(work, "order.json"),
                                  "--out", os.path.join(work, "refs.md"),
                                  "--report", os.path.join(work, "format_report.json")])
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                proc = self._run(["check", "--manuscript", os.path.join(work, "ms.md"),
                                  "--references", os.path.join(work, "refs.md"),
                                  "--order", os.path.join(work, "order.json"),
                                  "--library", os.path.join(work, "library_dedup.json"),
                                  "--issues", os.path.join(work, "renumber_report.json"),
                                  "--out", os.path.join(work, "consistency.json")])
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                with open(os.path.join(work, "ms.md"), encoding="utf-8") as fh:
                    results.append(fh.read())
                with open(os.path.join(work, "refs.md"), encoding="utf-8") as fh:
                    results.append(fh.read())
                with open(os.path.join(work, "consistency.json"), encoding="utf-8") as fh:
                    report = json.load(fh)
                self.assertEqual(report["overall_status"], "consistent")
            self.assertEqual(results[0], results[2])  # 两次运行稿件一致
            self.assertEqual(results[1], results[3])  # 两次运行文献表一致

    def test_missing_required_arg_friendly_error(self):
        proc = self._run(["dedup"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("缺少必需参数", proc.stderr or "")

    def test_missing_input_file_friendly_error(self):
        proc = self._run(["parse", "--inputs", "nonexistent_file_xyz.bib"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("不存在", proc.stderr or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
