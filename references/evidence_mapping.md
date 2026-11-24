# 论断级证据映射规范

本规范约束 Agent 的判断工作：哪些句子需要引用、证据是否充分、如何记录。
脚本负责机械一致性；论断—文献匹配由 Agent 依据本规范完成并留痕。

## 1. 论断分类与引用需求

| 类型 | 特征 | 是否需要引用 |
|-|-|-|
| 具体数据/统计结果 | 含数值、比率、性能指标 | 必须，挂原始出处 |
| 研究事实 | "X 被证实可抑制 Y" | 必须 |
| 他人方法/模型/数据集 | 指称具体工作 | 必须，首次指称处 |
| 领域现状 | "近年来……受到关注" | 需要，可挂 2—4 条代表性文献 |
| 对比性结论 | "A 优于 B" | 必须，挂直接比较的来源 |
| 争议性论断 | 存在学派分歧 | 必须，且需呈现多方证据（见第 4 节） |
| 常识性内容 | 教科书级定义 | 不需要 |
| 本文自己的工作 | 方法、实验、结果陈述 | 不需要 |

不得机械地为每句话插引用：一段中连续多句同属一个论断链且共用一源时，逐句标注；
过渡句、章节引导句不标注。

## 2. 证据匹配等级（evidence_status）

| 状态 | 含义 | 处置 |
|-|-|-|
| supported | 文献的结论/数据直接支撑该论断 | 正常使用 |
| partially_supported | 仅支撑论断的一部分（如只支撑方法不支撑数值） | 可用，注明未覆盖部分 |
| background_only | 主题相关但不能直接支撑论断 | 不得作为该论断的唯一来源；降置信度并列入人工复核 |
| contradicted | 文献结论与论断冲突 | 不得引用为支撑；按第 4 节处理冲突 |
| insufficient_evidence | 只读到摘要/题录，无法确认全文结论 | 标注证据范围，置信度不高于 medium |
| missing_source | 文献库中找不到可支撑条目 | `{cite:MISSING}` + uncertainty，禁止编造 |

**主题相关 ≠ 证据支撑**。判定 supported 必须能指出文献中的具体结论、数据或实验，
不能仅凭标题或关键词相似。

## 3. 证据映射记录（source_mapping 每项）

```json
{
  "sentence": "论断句原文摘录",
  "location": "第 2 节第 3 段",
  "citation": "[4]",
  "entry_id": "e0007",
  "entry_title": "所引文献题名",
  "evidence_status": "supported",
  "evidence_scope": "fulltext | abstract | metadata",
  "evidence_location": "页码或章节（仅当实际读到该页时填写，否则为 null）",
  "evidence_excerpt": "原文证据摘录（仅当实际读到时填写，否则为 null）",
  "basis": "支撑理由：该文献哪个结论/数据支撑此论断",
  "confidence": "high | medium | low",
  "needs_human_review": false
}
```

硬性规则：

1. `evidence_excerpt` 与 `evidence_location` 只允许填写**真实读到的内容**；只读到摘要时
   `evidence_scope` 必须为 `abstract`，不得声称已核验全文；只有题录时为 `metadata`，
   且 `evidence_status` 不得高于 `insufficient_evidence`。
2. `confidence: low` 或 `evidence_status` 为 background_only / contradicted /
   insufficient_evidence 的记录，`needs_human_review` 必须为 true，并同步出现在
   result.json 的 `needs_human_review` 中。
3. 低置信与人工复核清单须传给一致性检查：`check --issues renumber_report.json`
   之外，将低置信记录写入 issues JSON 的 `low_confidence_citations`，使
   `evidence_complete` 如实为 false。

## 4. 冲突证据处理

同一论断存在结论相反的多篇文献时：

1. 全部保留，分别记录证据映射（各自的 status 如实标注）。
2. 在 `uncertainty` 中说明冲突点：两篇文献各自的结论、样本/条件差异。
3. 不擅自裁决哪篇正确；不合并冲突文献；引用表述改为呈现分歧
   （如"X 被报道有效[5]，但也有研究未观察到该效应[6]"）。
4. 列入 `needs_human_review`。

## 5. 与一致性检查的衔接

`renumber.check` 输出两层状态：

- `structural_consistent`：编号、文献表、占位符结构层面一致。
- `evidence_complete`：无来源缺失、无未知 ID、无低置信引用、无待复核论断。
- `overall_status`：`consistent` / `evidence_incomplete` / `inconsistent`。

`evidence_incomplete` 不是失败，而是诚实状态：result.json 应如实写 `partial`
并列出待补充项，不得包装为 `complete`。
