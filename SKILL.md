---
name: citation-manager
description: 学术稿件的参考文献与引用管理。当任务涉及在稿件中插入或定位引用、重排正文引用编号并同步文末文献表、合并重复文献条目（中英文题名、预印本与正式版、多数据库导出）、在 BibTeX/RIS/EndNote/CNKI 导出与 GB/T 7714—2015 等目标规范之间转换格式、核验条目真实性与正文—文献一致性时使用。输入为一份真实稿件和一份文献库，输出为可继续编辑的成稿、同步的文献表和可逐条回溯的来源与修改记录。
---

# citation-manager：参考文献与引用管理

围绕一份真实稿件 + 一份真实文献库，完成六类动作：引用插入与定位（挂得对）、编号更新与交叉引用（编得顺）、文献去重与条目归并（收得净）、格式转换与字段补齐（转得准）、来源核验（核得真）、正文—参考文献一致性检查（对得上）。

## 1. 适用条件与分工原则

- 适用：顺序编码制（GB/T 7714—2015 数值型）、著者—出版年制稿件；文献库为 BibTeX、RIS、EndNote 标签格式或 CNKI 导出文本。
- 分工原则：**机械性、可复核的工作交给脚本**（解析、去重、编号、格式化、元数据核验），**判断性工作由你完成**（哪些论断需要来源、引哪条文献、证据是否充分）。不要把判断工作伪装成脚本输出，也不要手工做脚本能零误差完成的工作。
- 全程留痕：每条引用的匹配依据、每一步改动、每个去重决策都写入 `/app/output` 下的映射与日志文件，使成品可回溯到原始稿件与文献库快照。

## 2. 运行契约（平台固定）

- 输入：`/input/case.json` 与 `/input/task.md`；稿件与文献库材料按题目随案例提供（可能在 `/input` 或题目声明的目录）。**先读真实文件，不要根据文件名或标签臆测内容。**
- 工作区：`/app/work`（中间产物：library.json、dedup_report.json 等）。
- 输出：`/app/output`，必须包含 `result.json`，其中包含 `case_id` 和 `case.json` 中 `output_contract` 声明的全部字段；如实填写 `status`、`sources`、`uncertainty`、修改记录。部分完成时必须说明边界，禁止编造。
- 资源预算有限：先保存诚实可用的部分结果，再逐步改进。

## 3. 总流程

按序执行，任一阶段失败仍交付已完成的诚实部分结果并记录异常。

**阶段 0：读取契约与快照输入**
1. 读 `/input/task.md` 与 `/input/case.json`，记录 `case_id`、任务动作清单、目标规范（默认 GB/T 7714—2015 顺序编码制）、`output_contract` 字段。
2. 定位稿件与文献库文件；将它们复制到 `/app/work/snapshot/`，后续所有改动基于副本，原件不动。

**阶段 1：解析文献库**
```bash
python3 scripts/pipeline.py parse --inputs <文献库文件...> --out /app/work/library.json
```
支持 `.bib`、`.ris`、EndNote 标签（`.enw`/`.txt`）、CNKI 导出（EndNote/Refworks 标签）。输出规范化条目（id、type、title、authors、year、venue、volume/issue/pages、doi、arxiv、source）。解析失败或字段缺失的条目照样保留，在 `parse_warnings` 中逐条说明。

**阶段 2：去重与条目归并**
```bash
python3 scripts/pipeline.py dedup --library /app/work/library.json --out /app/work/library_dedup.json --report /app/output/dedup_report.json
```
脚本按可解释判据合并：①DOI 精确一致；②arXiv 号一致；③规范化标题相似度 ≥0.95 且第一作者姓一致、年份差 ≤1（覆盖预印本 vs 正式版、中英文题名以外的同题异源）。标题相同但年份差 >1 时**不合并**，标记 `possible_different_works` 防误并。每条合并决策在报告中给出 `rule` 与 `evidence`，你可复核后人工否决（在报告中追加 `overridden: true` 并说明）。

**阶段 3：来源核验**
```bash
python3 scripts/pipeline.py verify --library /app/work/library_dedup.json --out /app/output/verify_report.json
```
有 DOI 的条目经 Crossref 核验题名、年份、容器名；无 DOI 或网络不可用时状态标为 `unverified` 并说明原因，**不得把未核验写成已核验**。发现元数据错配（题名/年份与 DOI 记录不符）时列入 `mismatch`，由你判断是否修正或标记待人工确认。

**阶段 4：引用插入与定位（判断工作，遵守第 4 节规则）**
逐句扫描稿件，识别需要来源支撑的论断句，在**句末标点之前**插入占位符 `{cite:条目id}`（一句多引用逗号分隔，如 `{cite:e0003,e0007}`）。不改动论断本身措辞；材料中找不到可支撑文献的论断，插入 `{cite:MISSING}` 并记录到 `result.json` 的 `uncertainty`。

**阶段 5：编号、同步与格式化**
```bash
python3 scripts/pipeline.py renumber --manuscript /app/work/draft_cited.md --library /app/work/library_dedup.json --out /app/output/manuscript_cited.md --style numeric
python3 scripts/pipeline.py format --library /app/work/library_dedup.json --style gbt7714 --out /app/output/references.md
```
`renumber` 将占位符按首次出现顺序转为 `[n]`（连续多个合并为 `[n-m]`），同步重排文末文献表，检出并报告：悬空编号（正文有列表无）、未被引用条目、编号缺口。已有数字编号的稿件用 `--mode renumber` 重排；著者—出版年制用 `--mode author-year`（需先生成 keymap，见 references/placement_rules.md）。

**阶段 6：一致性终检与交付**
```bash
python3 scripts/pipeline.py check --manuscript /app/output/manuscript_cited.md --references /app/output/references.md --library /app/work/library_dedup.json --out /app/output/consistency_report.json
```
确认：每个正文编号在文献表存在且唯一、文献表无冗余条目、编号连续、每句带引用的论断与所引条目主题匹配（逐句判定，由你完成并写入报告 `claim_checks`）。最后写 `/app/output/result.json`。

## 4. 引用插入与论断匹配规则（挂得对、对得上）

1. **句级定位**：引用挂在需要来源的那一句话上，不挂整段末尾，不挂图注/表注附近。多句共用一源时逐句挂，不只在末句挂一次。
2. **可支撑才引**：所引文献的主题与结论须直接支撑该论断；仅有背景相关性不足以作为依据时，选择更贴切的条目或标 `{cite:MISSING}`。
3. **一引一据**：在 `source_mapping` 中为每条引用写 `sentence`（论断原文摘录）、`entry_id`、`basis`（支撑依据：该文献的哪个结论/数据）、`confidence`。
4. **不新增材料外事实**：只能引用文献库中存在的条目；确需库外来源时在 `uncertainty` 中说明并标待人工确认，禁止编造条目。
5. 综述性陈述（"已有大量研究表明……"）可挂 2—4 条代表性文献；具体数值、具体结论必须挂到原始出处。

## 5. 去重判据与防误并（收得净）

- 合并优先级：正式发表版 > 预印本；字段更全者优先。被合并条目的独有字段（如预印本 arXiv 号）回填到保留条目的 `aliases`/`notes`，不丢信息。
- 同姓同名作者的不同文献不得合并：判据 ③ 要求标题高度相似为第一条件，作者与年份只是闸门。
- 中英文题名同文：翻译相似度由你判断（脚本只对拉丁/汉字原文算相似度），确认后在 `dedup_report.json` 追加一条 `rule: "manual_title_translation"` 记录，写明两条 id 与判断依据。

## 6. 异常处理

| 异常 | 处置 |
|-|-|
| 文献库文件损坏/编码异常 | 尝试 UTF-8/GBK 解码；仍失败的文件跳过并在 `result.json.uncertainty` 记录文件名与错误 |
| DOI 解析失败、无网络 | 该批条目标 `unverified`，注明原因；不阻塞后续阶段 |
| 条目歧义（多候选、字段冲突） | 保留全部候选，标 `needs_human_review`，写明冲突字段 |
| 编号冲突（正文与列表基数不符） | 以正文首次出现顺序为准重排，被丢弃的列表条目列入报告 |
| 稿件格式不支持（如 PDF 原稿） | 先用平台 PDF 工具提取文本为 Markdown 再处理，并在输出中说明版式损失 |
| 材料缺口（论断无源可引） | `{cite:MISSING}` + `uncertainty` 记录，不编造 |

## 7. 自查清单（交付前逐项确认）

- [ ] `result.json` 含 `case_id` 与 `output_contract` 全部字段，`status` 如实（complete/partial/failed）
- [ ] 正文编号连续、与文末列表一一对应（check 报告 `orphan_markers` 与 `uncited_entries` 为空或已解释）
- [ ] 每条去重决策有 `rule` 与 `evidence`；误并风险条目已标记
- [ ] 每条引用有 `sentence→entry_id→basis` 映射；`MISSING` 引用全部列入 `uncertainty`
- [ ] 已核验条目与未核验条目状态分明，无冒充
- [ ] 成品稿件可继续编辑（Markdown/文本），未确认处有明显标注
- [ ] 快照目录保留原始输入，可回溯

## 8. 资源清单与限制

- `scripts/`：`pipeline.py`（总入口，含 parse/dedup/verify/renumber/format/check 子命令）、`refparse.py`、`dedup.py`、`verify.py`、`renumber.py`、`gbt7714.py`。仅依赖 Python 3 标准库（verify 需联网访问 api.crossref.org，离线自动降级）。
- `references/`：`placement_rules.md`（插入位置与著者—出版年制细则）、`output_contract.md`（result.json 字段规范）。
- `examples/minimal_example.md`：最小调用示例（示意输出，非正式案例结果）。
- 限制：不做全文级语义查重；中英文题名互译匹配需人工确认；PDF 原稿的图表版式不保真。
