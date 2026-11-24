# citation-manager 使用与方法说明

针对"参考文献与引用管理"的 Agent Skill：以一份真实稿件 + 一份文献库为输入，完成引用插入定位、编号连锁更新、文献去重归并、GB/T 7714—2015 格式转换、DOI 来源核验、正文—文献一致性检查六类动作，全程保留可回溯的来源映射与修改记录。

## 目录结构

```
submission/
├── SKILL.md                        # Skill 本体（入口，YAML frontmatter）
├── README.md                       # 本说明
├── scripts/
│   ├── pipeline.py                 # 统一命令行入口（parse/dedup/verify/renumber/format/check）
│   ├── refparse.py                 # 解析 BibTeX/RIS/EndNote/CNKI 导出
│   ├── dedup.py                    # 去重与条目归并（可解释判据）
│   ├── gbt7714.py                  # GB/T 7714—2015 著录格式
│   ├── renumber.py                 # 编号重排与一致性检查
│   └── verify.py                   # Crossref 元数据核验（可离线降级）
├── references/
│   ├── placement_rules.md          # 引用插入位置与样式细则
│   └── output_contract.md          # result.json 字段规范
└── examples/
    └── minimal_example.md          # 最小调用示例（示意输出）
```

## 依赖与运行环境

- Python ≥ 3.8，仅标准库；`verify` 需联网访问 api.crossref.org，离线时自动降级为 `offline` 状态。
- 脚本入口相对 Skill 目录，Agent 运行时先定位 SKILL.md 所在目录再调用 `scripts/`。
- 资源约束：文本文件 ≤ 50 个、单个 ≤ 500KB、总量 ≤ 2MB，本交付远小于上限。

## 完整调用流程（评测环境）

输入 `/input/case.json` 与 `/input/task.md`；工作区 `/app/work`；产物 `/app/output`。

```bash
SKILL=<Skill 安装目录>
# 1. 快照输入
mkdir -p /app/work/snapshot /app/output && cp -r /input/* /app/work/snapshot/

# 2. 解析文献库
python3 $SKILL/scripts/pipeline.py parse \
    --inputs /app/work/snapshot/<文献库文件> --out /app/work/library.json

# 3. 去重
python3 $SKILL/scripts/pipeline.py dedup \
    --library /app/work/library.json --out /app/work/library_dedup.json \
    --report /app/output/dedup_report.json

# 4. 核验
python3 $SKILL/scripts/pipeline.py verify \
    --library /app/work/library_dedup.json --out /app/output/verify_report.json

# 5. Agent 按 SKILL.md 第 4 节规则为稿件插入 {cite:条目id} 占位符，
#    保存为 /app/work/draft_cited.md；无源论断标 {cite:MISSING}
python3 $SKILL/scripts/pipeline.py renumber \
    --manuscript /app/work/draft_cited.md --library /app/work/library_dedup.json \
    --out /app/output/manuscript_cited.md --order-out /app/work/order.json \
    --report /app/output/renumber_report.json

# 6. 格式化文献表
python3 $SKILL/scripts/pipeline.py format \
    --library /app/work/library_dedup.json --order /app/work/order.json \
    --out /app/output/references.md

# 7. 一致性终检
python3 $SKILL/scripts/pipeline.py check \
    --manuscript /app/output/manuscript_cited.md --references /app/output/references.md \
    --order /app/work/order.json --library /app/work/library_dedup.json \
    --out /app/output/consistency_report.json
```

最后按 `references/output_contract.md` 生成 `/app/output/result.json`（镜像 case.json 的 output_contract 字段）。

## 关键方法

1. **去重判据（可解释、防误并）**：DOI 精确一致（R1）> arXiv 号一致（R2）> 标题相似度 ≥0.95 + 第一作者姓一致 + 年份差 ≤1（R3）。标题相同但年份差 >1 不合并并告警；低相似度（0.80–0.95）仅列为人工确认候选（覆盖中英文题名同文）。保留优先级：正式发表版 > 预印本，字段更全者优先；被合并条目的独有字段回填到保留条目。
2. **编号连锁更新**：占位符按首次出现顺序一次分配编号，`[n-m]` 区间压缩；`renumber` 模式对既有编号按同一规则重排并重排文末列表；`check` 检出悬空编号、未引条目、编号缺口与残留占位符。
3. **论断级匹配**：脚本负责机械一致性，Agent 负责判断——每条引用在 `source_mapping` 中记录 `sentence → entry_id → basis → confidence`，低置信与 `[来源缺失]` 进入 `needs_human_review`。
4. **GB/T 7714—2015 著录**：著者超 3 人取前 3 加"等/et al"；西文著者姓全大写 + 名首字母缩写；按文献类型输出 [J]/[M]/[C]//[D]/[R]/[EB/OL] 标识；期刊条目附 DOI。

## 适用范围与限制

- 适用：GB/T 7714—2015 顺序编码制与著者—出版年制稿件；BibTeX/RIS/EndNote/CNKI 导出文献库。
- 限制：不做全文语义查重；中英文题名互译匹配需人工确认；PDF 原稿需先提取为文本，版式不保真；著者—出版年制的 keymap 由 Agent 生成，脚本仅校验一致性。
- 失败处理：文献库解析失败逐文件记录不阻塞；无网络时核验全部降级为 `offline`；歧义条目保留候选并标注 `needs_human_review`；部分完成时 result.json 以 `partial` 如实报告。

## 维护信息

版本 1.0（2026-11）。脚本无外部依赖，升级只需替换 `scripts/`。本地自测样例见本仓库外层的 `demo_run/`（合成演示数据与运行产物，非正式测评输出）。
