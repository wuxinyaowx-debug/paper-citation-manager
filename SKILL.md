---
name: citation-manager
description: 学术稿件的参考文献与引用管理。当任务涉及在稿件中插入或定位引用、重排正文引用编号并同步文末文献表、合并重复文献条目（中英文题名、预印本与正式版、多数据库导出）、在 BibTeX/RIS/EndNote/CNKI 导出与 GB/T 7714—2015 之间转换格式、核验条目真实性与正文—文献一致性时使用。输入为一份真实稿件和一份文献库，输出为可继续编辑的成稿、同步的文献表和可逐条回溯的来源与修改记录。
---

# citation-manager：参考文献与引用管理

以一份真实稿件 + 一份真实文献库为输入，按案例要求完成六类动作：引用插入与定位（挂得对）、编号更新与交叉引用（编得顺）、文献去重与归并（收得净）、格式转换与字段补齐（转得准）、来源核验（核得真）、正文—文献一致性检查（对得上）。

## 1. 分工原则（先读这条）

- **脚本做机械工作**：解析、去重、编号、格式化、元数据核验、结构一致性——零误差、可复算。
- **Agent 做判断工作**：哪些论断需要来源、引哪条、证据是否充分——按 `references/evidence_mapping.md` 执行并逐条留痕。
- **只执行案例实际要求的动作**。三个案例的输入格式与动作组合可能不同：先读任务要求，不假定六类动作全做，不无意义改写原稿。
- **准确性优先于自动化率**：无法确证的合并、核验、匹配一律降级为候选/待复核，不静默处理。

## 2. 运行契约（平台固定）

- 输入：`/input/case.json` 与 `/input/task.md`；材料按案例提供。**先读真实文件，不按文件名或标签臆测内容。**
- 工作区：`/app/work`；原始输入先复制到 `/app/work/snapshot/` 再处理。
- 输出：`/app/output`，必含 `result.json`（含 `case_id` 与 case.json `output_contract` 声明的**全部字段**，按实际结果填值；字段规范见 `references/output_contract.md`）。
- 预算有限：每个阶段完成后立即落盘中问产物，先保诚实可用的部分结果，再改进。
- 脚本入口：`scripts/pipeline.py`（相对本 Skill 目录解析，不依赖当前工作目录），仅依赖 Python 3 标准库。下文 `$SK` 指本 Skill 目录。

## 3. 输入识别

- 文献库：BibTeX（.bib）、RIS（.ris）、EndNote/CNKI 标签文本（.enw/.txt），由 `parse` 自动识别；编码自动尝试 UTF-8/GBK。
- 稿件：Markdown/TXT 直接处理；PDF 用平台 PDF 工具提取为文本后再处理，并在 `uncertainty` 说明版式损失；解析失败逐文件记录，不得假装完整读取。
- case.json：提取 `case_id`、任务动作、目标规范（默认 GB/T 7714—2015 顺序编码制）、受众文体、`output_contract` 全部字段。

## 4. 流水线（按需取阶段，顺序执行）

**阶段 1 解析** → `/app/work/library.json`
```bash
python3 $SK/scripts/pipeline.py parse --inputs <文献库文件...> --out /app/work/library.json
```
解析失败的文件记入 `parse_warnings`，不阻塞其余文件。

**阶段 2 去重** → `/app/work/library_dedup.json` + `/app/output/dedup_report.json`
```bash
python3 $SK/scripts/pipeline.py dedup --library /app/work/library.json \
    --out /app/work/library_dedup.json --report /app/output/dedup_report.json
```
分层判据：R1 强标识符（DOI/arXiv，含元数据冲突检测）、R2 标题+作者+年份联合匹配、R3 低置信候选（只提示）、R4 复杂情况（中英文题名同文、同名不同文，只提示）。缺失字段不作一致证据；组内传递性误并自动拆出复核。你必须复核报告中的 `needs_human_confirmation`：确认合并的用 `--overrides`（格式 `{"merge":[[id1,id2]],"split":[[id1,id2]]}`）重跑一次并在 change_log 记录。

**阶段 3 核验** → `/app/output/verify_report.json`
```bash
python3 $SK/scripts/pipeline.py verify --library /app/work/library_dedup.json --out /app/output/verify_report.json
```
状态：verified / partial_verified / mismatch / not_found / unverified / offline。只有 Crossref 一个来源，离线自动降级，绝不冒充已核验。`mismatch`/`not_found` 条目由你判断修正或标待确认。

**阶段 4 引用插入与定位（Agent 判断）**
按 `references/evidence_mapping.md` 分类论断、判定证据等级，在论断句末标点前插入 `{cite:条目id}`（多引逗号分隔；无源论断 `{cite:MISSING}`）。同步撰写 `source_mapping` 草稿（句→条目→依据→置信度）。

**阶段 5 编号与格式化** → `/app/output/manuscript_cited.md` + `/app/output/references.md`
```bash
python3 $SK/scripts/pipeline.py renumber --manuscript /app/work/draft_cited.md \
    --library /app/work/library_dedup.json --out /app/output/manuscript_cited.md \
    --order-out /app/work/order.json --report /app/output/renumber_report.json
python3 $SK/scripts/pipeline.py format --library /app/work/library_dedup.json \
    --order /app/work/order.json --out /app/output/references.md \
    --report /app/output/format_report.json
```
已有数字编号的稿件改用 `--mode renumber`；著者—出版年制用 `--mode author-year --keymap keymap.json`（keymap 由你生成，格式见 `references/placement_rules.md`）。**order.json 是文献表顺序的唯一依据**：`format` 必须带 `--order`，保证未引用条目不进入最终文献表。报告中的 `ambiguous_markers_untouched` 逐条人工确认，不得擅自改写。

**阶段 6 一致性终检** → `/app/output/consistency_report.json`
```bash
python3 $SK/scripts/pipeline.py check --manuscript /app/output/manuscript_cited.md \
    --references /app/output/references.md --order /app/work/order.json \
    --library /app/work/library_dedup.json --issues /app/output/renumber_report.json \
    --out /app/output/consistency_report.json
```
输出两层状态：`structural_consistent`（编号结构）与 `evidence_complete`（证据充分性），综合为 `overall_status`。把低置信引用、待复核论断追加进 issues（`low_confidence_citations`、`human_review_items`）再终检一次，使证据状态如实。

**交付**：按 `references/output_contract.md` 写 `/app/output/result.json`。`overall_status=evidence_incomplete` 时 `status` 必须写 `partial`。

## 5. 异常处理

| 异常 | 处置 |
|-|-|
| 文献库损坏/格式不识 | 跳过并记录 `parse_warnings`，处理其余文件 |
| DOI 失败、无网络、限流 | 状态 `offline`，不阻塞后续；不重试超过脚本内置次数 |
| 条目歧义、字段冲突 | 保留候选，标 `needs_human_review`，写明冲突字段 |
| ambiguous 数字标记 | 保留原文，列入报告与人工复核 |
| 编号冲突（正文/列表基数不符） | 以正文首次出现顺序重排，被丢弃列表条目列入 `uncited_list_entries` |
| PDF 原稿 | 平台工具提取文本后处理，说明版式损失 |
| 无源论断 | `{cite:MISSING}` + `uncertainty`，禁止编造条目 |
| 脚本参数/文件错误 | 脚本给出中文提示并非零退出；修正后重跑，不要绕过 |

## 6. 交付前自查清单

- [ ] `result.json` 含 `case_id` 与 `output_contract` 全部字段，`status` 与实际相符
- [ ] `check` 报告无未解释的 orphan/uncited/gap/残留占位符；ambiguous 标记全部有结论
- [ ] 文献表只含被引用条目，顺序 = 正文首次出现顺序（order.json 真实完整）
- [ ] 每条合并决策有 rule + field_comparison + reason；候选与冲突已复核或标注
- [ ] 每条引用有证据映射；excerpt/页码只含真实读到的内容；低置信已入人工复核
- [ ] verified 与 offline/unverified 分明；not_found/mismatch 有处置结论
- [ ] 快照保留原始输入；change_log 可逐步回溯；成品可继续编辑

## 7. 资源与限制

- `scripts/`：pipeline.py（入口）、refparse.py、dedup.py、verify.py、renumber.py、gbt7714.py。
- `references/`：placement_rules.md（插入位置与安全识别）、evidence_mapping.md（论断分类与证据等级）、output_contract.md（result.json 规范）。
- `examples/minimal_example.md`：最小调用示例（合成演示数据）。
- `tests/test_citation_manager.py`：合成数据自动化测试（`python3 tests/test_citation_manager.py`），用于自查代码正确性，非平台测评结果。
- 限制：只核验 Crossref；中英文题名互译匹配需人工确认；PDF 版式不保真；著者—出版年制 keymap 由 Agent 生成；GB/T 7714 未覆盖标准/专利/古籍类型（兜底 [EB/OL] 并告警）。
