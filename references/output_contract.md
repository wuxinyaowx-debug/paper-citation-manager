# result.json 字段规范

`/app/output/result.json` 必须包含 `case.json` 中 `output_contract` 声明的**全部字段**
（原样镜像，按实际结果填值），并含 `case_id`。**先读 case.json 的契约再写字段**；
契约缺省时使用以下默认结构，但不得用默认结构替代真实契约。

```json
{
  "case_id": "<来自 case.json>",
  "status": "complete | partial | failed",
  "deliverables": {
    "manuscript": "manuscript_cited.md 的路径（相对 /app/output）",
    "references": "references.md 的路径",
    "extra": ["dedup_report.json", "verify_report.json",
              "consistency_report.json", "renumber_report.json", "format_report.json"]
  },
  "actions_completed": ["insert", "renumber", "dedup", "format", "verify", "consistency"],
  "source_mapping": [
    {
      "sentence": "论断句原文摘录",
      "location": "章节位置",
      "citation": "[3]",
      "entry_id": "e0007",
      "entry_title": "所引文献题名",
      "evidence_status": "supported | partially_supported | background_only | contradicted | insufficient_evidence | missing_source",
      "evidence_scope": "fulltext | abstract | metadata",
      "evidence_location": "页码/章节，仅实际读到时填写，否则 null",
      "evidence_excerpt": "原文证据摘录，仅实际读到时填写，否则 null",
      "basis": "支撑理由",
      "confidence": "high | medium | low",
      "needs_human_review": false
    }
  ],
  "change_log": [
    {"action": "dedup", "detail": "e0002 并入 e0001，依据 doi_exact"},
    {"action": "insert", "detail": "第 3 段第 2 句插入 [4]，支撑效率数值"},
    {"action": "renumber", "detail": "旧 [5] -> 新 [2]，按首次出现顺序"}
  ],
  "verification": {
    "verified": 0, "partial_verified": 0, "mismatch": 0, "not_found": 0,
    "unverified": 0, "offline": 0,
    "report": "verify_report.json 的路径"
  },
  "consistency": {
    "structural_consistent": true,
    "evidence_complete": false,
    "overall_status": "evidence_incomplete",
    "report": "consistency_report.json 的路径"
  },
  "uncertainty": [
    "无源论断：第 5 段『……』未找到可支撑文献，已标 [来源缺失]",
    "条目 e0011 无 DOI，未能自动核验",
    "疑似中英文题名同文 e0004/e0009 未自动合并，需人工确认"
  ],
  "needs_human_review": ["列出所有需人工确认的事项"],
  "limits": "若为 partial/failed，说明完成边界与失败原因"
}
```

## 填写规则

1. **status 诚实**：`complete` = 案例要求的全部动作完成且 `overall_status` 为
   `consistent`；`evidence_incomplete`（如存在 [来源缺失]、低置信引用）必须写
   `partial`，不得包装为 `complete`；`failed` = 主产物未能生成，仍须说明原因
   与已完成工作。
2. **动作按案例要求执行**：`actions_completed` 只列案例实际要求且已完成的动作；
   案例未要求的动作不要无意义执行（不无故改写原稿）。
3. `source_mapping` 覆盖每一条正文引用，字段含义见
   `references/evidence_mapping.md` 第 3 节；`evidence_excerpt`/`evidence_location`
   只能填真实读到的内容。
4. 不新增材料外事实：`basis` 只能援引文献库条目的题录、摘要（如材料提供）或原文。
5. 快照可回溯：`/app/work/snapshot/` 保留原始输入副本；`change_log` 每一步可对应
   快照与产物间的差异。
6. 所有 `deliverables` 路径必须真实存在；字数受限时优先保证 `case_id`、`status`、
   `deliverables`、`uncertainty` 完整。
