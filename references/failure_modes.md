# 失败模式与前后对照（真实开发记录）

本文档沉淀本 Skill 开发中**真实发生、由测试捕获**的失败案例，作为前后对照证据。
每个案例含：失败现象、影响、修复方式、对应回归测试。所有材料为合成测试数据。

## 对照方法

同一份输入分别经 v1.0（初版）与 v1.1（当前版）处理，比较输出。
v1.0 的失败均由 `tests/test_citation_manager.py` 中的回归测试锁定，可重复复现。

## 案例 1：结构一致 ≠ 证据完整（对得上）

- **输入**：`论断[1]，但此处无源[来源缺失]。` + 1 条文献表。
- **v1.0 行为**：`consistent: true`——一致性检查只看编号结构，来源缺失不进入判定。
- **影响**：存在未解决引用的稿件被包装为"一致"，评测中会虚报任务完成度。
- **v1.1 修复**：三层状态 `structural_consistent / evidence_complete / overall_status`，
  来源缺失、未知 ID、低置信、待复核均使 `evidence_complete=false`，
  result.json 如实写 `partial`。
- **回归测试**：`test_consistency_structural_vs_evidence`、`test_consistency_issues_merged`。

## 案例 2：普通数字被误改（编得顺）

- **输入**：`取值范围 [0,1] 内。发表于 [2020] 年。公式 [3] 如上。由 x = [2] 可得结论[1]。`
- **v1.0 行为**：通用 `[n]` 正则把区间、年份、公式编号全部当引用重排。
- **影响**：原文被不可逆改错——这正是基础 Agent 手工重排时的同类高发错误。
- **v1.1 修复**：`classify_marker` 上下文分类，存疑标记保留原文并列入
  `ambiguous_markers_untouched` 交人工确认；只有紧贴文字、编号 1—999 的标记才改写。
- **回归测试**：`test_plain_brackets_untouched`、`test_math_context_marker_untouched`。

## 案例 3：无空行分隔的 RIS 记录被合并（收得净的前置）

- **输入**：两条 RIS 记录连续无空行（`ER  -` 后直接 `TY  -`）。
- **v1.0 行为**：按空行分块，两条记录解析为一条，字段混杂。
- **v1.1 修复**：逐行状态机，TY 开始、ER 结束，续行并入上一标签。
- **回归测试**：`test_ris_multi_record_no_blank_lines`。

## 案例 4：DOI 相同即静默合并（收得净）

- **输入**：两条 DOI 相同但题名完全不同（元数据录入错误）的条目。
- **v1.0 行为**：DOI 精确一致直接合并，错误元数据被静默吸收。
- **v1.1 修复**：题名相似度 <0.6 判为 `doi_metadata_conflict`，不合并、交人工确认；
  年份/作者缺失不再作为一致证据（降级为候选）。
- **回归测试**：`test_doi_conflict_not_silently_merged`、`test_missing_year_not_used_as_evidence`。

## 案例 5：远程缺字段也标 verified（核得真）

- **输入**：Crossref 记录存在但缺题名/年份的 DOI。
- **v1.0 行为**：缺字段不参与比对，条目被标 `verified`。
- **v1.1 修复**：新增 `partial_verified` 状态，记录 `fields_checked` 与缺失字段；
  只核验到部分字段时绝不标 `verified`。
- **回归测试**：`test_remote_missing_fields_not_verified`。

## 结论

五类失败中，案例 1、2、4、5 与基础 Agent 在同类任务上的典型错误同构
（重排误改、静默合并、虚报完成度）；本 Skill 的策略是把这些判断从"提示词要求"
下沉为"脚本强制 + 诚实状态"，使同一输入在重复运行下产出一致结果
（`test_full_pipeline_and_repeat_stability`）。这构成相对基础 Agent 的质量与
稳定性增益的直接证据点，正式增益数值以平台对照实验为准。
