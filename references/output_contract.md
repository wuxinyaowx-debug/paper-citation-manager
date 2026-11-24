# result.json 字段规范

`/app/output/result.json` 必须包含 `case.json` 中 `output_contract` 声明的全部字段（原样镜像，按实际结果填值），并含 `case_id`。`output_contract` 缺省时使用以下结构：

```json
{
  "case_id": "<来自 case.json>",
  "status": "complete | partial | failed",
  "deliverables": {
    "manuscript": "manuscript_cited.md 的路径",
    "references": "references.md 的路径",
    "extra": ["其他产物路径"]
  },
  "actions_completed": ["insert", "renumber", "dedup", "format", "verify", "consistency"],
  "source_mapping": [
    {
      "sentence": "正文中带引用的论断句原文摘录",
      "citation": "[3]",
      "entry_id": "e0007",
      "basis": "支撑依据：该文献的哪个结论/数据支撑此论断",
      "confidence": "high | medium | low"
    }
  ],
  "change_log": [
    {"action": "dedup", "detail": "e0002 并入 e0001，依据 doi_exact"},
    {"action": "insert", "detail": "第 3 段第 2 句插入 [4]，支撑效率数值"},
    {"action": "renumber", "detail": "旧 [5] -> 新 [2]，按首次出现顺序"}
  ],
  "verification": {
    "verified": 0, "mismatch": 0, "not_found": 0,
    "unverified": 0, "offline": 0,
    "report": "verify_report.json 的路径"
  },
  "uncertainty": [
    "无源论断：第 5 段『……』未找到可支撑文献，已标 [来源缺失]",
    "条目 e0011 无 DOI 且未能联网核验",
    "疑似同一文献的中英文题名条目 e0004/e0009 未自动合并，需人工确认"
  ],
  "needs_human_review": ["列出所有需人工确认的事项"],
  "limits": "若为 partial/failed，说明完成边界与失败原因"
}
```

## 填写规则

1. `status` 如实：`complete` = 任务要求的全部动作完成且一致性检查通过；`partial` = 部分动作完成或检查未通过，在 `limits` 说明；`failed` = 主产物未能生成，仍须说明原因与已完成的工作。
2. `source_mapping` 覆盖**每一条**正文引用；低置信（`low`）条目必须同时出现在 `needs_human_review`。
3. 不新增材料外事实：`basis` 只能援引文献库条目的题名、摘要（如材料提供）或原文内容，不得凭常识补写。
4. 快照可回溯：`/app/work/snapshot/` 保留原始稿件与文献库副本，`change_log` 的每一步可对应到快照与产物之间的差异。
5. 字数受限时优先保证 `case_id`、`status`、`deliverables`、`uncertainty` 完整。
