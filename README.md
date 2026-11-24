# citation-manager

面向 Agent 的学术参考文献与引用管理 Skill：以一份真实稿件 + 一份文献库为输入，完成**引用插入定位、编号连锁更新、文献去重归并、GB/T 7714—2015 格式转换、Crossref 来源核验、正文—文献一致性检查**六类动作，全程保留可回溯的证据映射与修改记录。

设计原则：机械工作交给脚本（零误差、可复算），判断工作交给 Agent（按规范留痕）；准确性优先于自动化率，无法确证的一律降级为候选/待复核，不静默合并、不冒充核验、不编造来源。

## 安装与运行要求

- Python ≥ 3.8，**仅标准库**，无需 pip 安装。
- `verify` 需联网访问 api.crossref.org；离线时自动降级为 `offline` 状态，不阻塞流程。
- 脚本相对自身所在目录解析路径，可在任意工作目录调用。

## 目录结构

仓库根目录即 Skill 根目录：

```
.
├── SKILL.md                        # Skill 本体（入口，YAML frontmatter）
├── README.md                       # 本说明
├── scripts/
│   ├── pipeline.py                 # 统一入口：parse/dedup/verify/renumber/format/check
│   ├── refparse.py                 # 解析 BibTeX / RIS / EndNote / CNKI 导出
│   ├── dedup.py                    # 分层去重（R1-R4，可解释、防误并、可人工否决）
│   ├── verify.py                   # Crossref 核验（六态状态机，可离线降级）
│   ├── renumber.py                 # 上下文安全的编号重排 + 结构/证据两层一致性
│   └── gbt7714.py                  # GB/T 7714—2015 著录（缺字段告警不编造）
├── references/
│   ├── placement_rules.md          # 引用插入位置与安全识别细则
│   ├── evidence_mapping.md         # 论断分类、证据等级、冲突证据处理
│   └── output_contract.md          # result.json 字段规范
├── examples/
│   └── minimal_example.md          # 最小调用示例（合成演示数据）
└── tests/
    └── test_citation_manager.py    # 39 个自动化测试（合成数据，unittest）
```

## 快速开始

```bash
cd <Skill 目录>
python3 tests/test_citation_manager.py   # 自查：39 个测试应全部通过
```

完整调用（评测环境路径；本地使用可替换为任意目录）：

```bash
SK=<Skill 目录>
mkdir -p /app/work/snapshot /app/output && cp -r /input/* /app/work/snapshot/

# 1. 解析文献库（支持 .bib/.ris/EndNote/CNKI 文本，可多个文件）
python3 $SK/scripts/pipeline.py parse \
    --inputs /app/work/snapshot/library.bib --out /app/work/library.json

# 2. 分层去重（人工复核候选后可用 --overrides 重跑）
python3 $SK/scripts/pipeline.py dedup \
    --library /app/work/library.json --out /app/work/library_dedup.json \
    --report /app/output/dedup_report.json

# 3. Crossref 核验（离线加 --offline）
python3 $SK/scripts/pipeline.py verify \
    --library /app/work/library_dedup.json --out /app/output/verify_report.json

# 4. Agent 按 references/evidence_mapping.md 为稿件插入 {cite:条目id} 占位符，
#    保存为 /app/work/draft_cited.md；无源论断标 {cite:MISSING}

# 5. 占位符 -> [n]，按首次出现顺序编号；文献表按同一顺序生成
python3 $SK/scripts/pipeline.py renumber \
    --manuscript /app/work/draft_cited.md --library /app/work/library_dedup.json \
    --out /app/output/manuscript_cited.md \
    --order-out /app/work/order.json --report /app/output/renumber_report.json
python3 $SK/scripts/pipeline.py format \
    --library /app/work/library_dedup.json --order /app/work/order.json \
    --out /app/output/references.md --report /app/output/format_report.json

# 6. 一致性终检（结构 + 证据两层状态）
python3 $SK/scripts/pipeline.py check \
    --manuscript /app/output/manuscript_cited.md --references /app/output/references.md \
    --order /app/work/order.json --library /app/work/library_dedup.json \
    --issues /app/output/renumber_report.json --out /app/output/consistency_report.json
```

最后按 `references/output_contract.md` 生成 `/app/output/result.json`（镜像 case.json 的 output_contract 字段）。

其他模式：

- 已有数字编号重排：`renumber --mode renumber --manuscript 稿件.md --out ...`
- 著者—出版年制校验：`renumber --mode author-year --keymap keymap.json --manuscript 稿件.md`
- 人工复核后强制/禁止合并：`dedup --overrides overrides.json`，格式 `{"merge":[["e0001","e0002"]],"split":[["e0003","e0004"]]}`

## 输入输出示例

输入（BibTeX 片段，合成数据）：

```bibtex
@article{zhang2020, author={张三 and 李四 and 王五 and 赵六},
  title={深度学习方法在材料筛选中的应用}, journal={物理学报},
  year={2020}, volume={69}, number={12}, pages={120101}, doi={10.7498/aps.69.20200123}}
```

输出（GB/T 7714—2015）：

```text
[1] 张三, 李四, 王五, 等. 深度学习方法在材料筛选中的应用[J]. 物理学报, 2020, 69(12): 120101. DOI: 10.7498/aps.69.20200123.
```

一致性报告（节选）：

```json
{
  "structural_consistent": true,
  "evidence_complete": false,
  "overall_status": "evidence_incomplete",
  "evidence": {"missing_source_count": 1}
}
```

`evidence_incomplete` 是诚实状态而非失败：存在 [来源缺失] 时 result.json 应写 `partial`。

## 支持的格式与文献类型

- 文献库输入：BibTeX、RIS（含无空行分隔多记录）、EndNote 标签、CNKI 导出（EndNote/Refworks 标签）；编码 UTF-8/GBK 自动识别。
- 稿件输入：Markdown/TXT；PDF 需先用平台工具提取文本。
- 目标规范：GB/T 7714—2015 顺序编码制（数值型）。
- 文献类型：期刊 [J]、会议 [C]//、专著 [M]、专著章节 [M]//、学位论文 [D]、报告 [R]、预印本/网络资源 [EB/OL]。

## 已知限制

- 来源核验只接入 Crossref；无 DOI 条目无法自动核验（标 `unverified`）。
- 中英文题名互译同文、同题不同文等复杂情况只列为人工确认候选，不自动合并。
- GB/T 7714 未覆盖标准/专利/古籍等类型（兜底 [EB/OL] 并告警）；编者/译者与析出责任者区分需要材料中存在相应字段。
- 著者—出版年制不改正文，只做双向一致性校验；keymap 由 Agent 生成。
- 中文语境下空格分隔的方括号数字（如"公式 [3]"）按保守策略不改写，列入人工确认。

## 测试方法

```bash
python3 tests/test_citation_manager.py
```

39 个测试覆盖：四种文献库格式解析与编码异常、DOI 冲突/预印本合版/中英文题名候选/同名不同文/缺字段降级等去重场景、离线核验与远程缺字段、占位符解析与未知 ID、既有编号重排与压缩、悬空/未引/缺口检测、普通方括号数字保护、著者—出版年制双向校验、格式化边界、端到端两次运行结果一致性、缺参数友好报错。测试数据全部为合成材料，不代表平台正式案例结果。

## 资源清单与约束

文本文件 14 个，总量约 90KB，满足 Harbor 限制（≤50 文件、单文件 ≤500KB、总量 ≤2MB、无符号链接、无第三方依赖）。

## 维护信息

版本 1.1（2026-11）。脚本无外部依赖，升级只需替换 `scripts/`；修改代码后请先跑测试套件再更新文档。仓库：https://github.com/wuxinyaowx-debug/paper-citation-manager
