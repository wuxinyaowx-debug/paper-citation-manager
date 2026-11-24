# 最小调用示例（示意，非正式案例结果）

以下输入与输出均为演示用合成材料，仅说明接口与流程。

## 输入

`demo/library.bib`（4 条，其中同一篇论文同时以 arXiv 预印本和期刊正式版出现）：

```bibtex
@article{vaswani2017,
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob},
  title  = {Attention Is All You Need},
  journal= {Advances in Neural Information Processing Systems},
  year   = {2017}, volume = {30}, pages = {5998--6008}
}
@misc{vaswani2017arxiv,
  author = {Vaswani, Ashish and others},
  title  = {Attention Is All You Need},
  eprint = {1706.03762}, archiveprefix = {arXiv}, year = {2017}
}
@article{zhang2020,
  author = {张三 and 李四 and 王五 and 赵六},
  title  = {深度学习方法在材料筛选中的应用},
  journal= {物理学报}, year = {2020}, volume = {69}, number = {12},
  pages = {120101}, doi = {10.7498/aps.69.20200123}
}
```

`demo/draft.md`（Agent 已完成引用定位，插入了占位符）：

```markdown
## 引言
Transformer 架构完全基于注意力机制，摒弃了循环结构{cite:e0001}。
深度学习已被用于加速材料筛选{cite:e0003}，但小样本下的泛化仍是难题{cite:MISSING}。
```

## 调用

```bash
cd <Skill 目录>
python3 scripts/pipeline.py parse --inputs demo/library.bib --out work/library.json
python3 scripts/pipeline.py dedup --library work/library.json --out work/library_dedup.json --report out/dedup_report.json
python3 scripts/pipeline.py verify --library work/library_dedup.json --out out/verify_report.json
python3 scripts/pipeline.py renumber --manuscript demo/draft.md --library work/library_dedup.json --out out/manuscript_cited.md --order-out work/order.json --report out/renumber_report.json
python3 scripts/pipeline.py format --library work/library_dedup.json --order work/order.json --out out/references.md --report out/format_report.json
python3 scripts/pipeline.py check --manuscript out/manuscript_cited.md --references out/references.md --order work/order.json --library work/library_dedup.json --issues out/renumber_report.json --out out/consistency_report.json
```

## 示意输出

`dedup_report.json` 摘要：`e0002`（arXiv 版）按规则 `title_author_year` 并入 `e0001`，保留期刊正式版，arXiv 号回填到保留条目；决策含 `field_comparison`（标题相似度、年份差、首作者）与 `reason`。

`manuscript_cited.md`：

```markdown
## 引言
Transformer 架构完全基于注意力机制，摒弃了循环结构[1]。
深度学习已被用于加速材料筛选[2]，但小样本下的泛化仍是难题[来源缺失]。
```

`references.md`：

```text
[1] VASWANI A, SHAZEER N, PARMAR N, et al. Attention Is All You Need[J]. Advances in Neural Information Processing Systems, 2017, 30: 5998-6008.
[2] 张三, 李四, 王五, 等. 深度学习方法在材料筛选中的应用[J]. 物理学报, 2020, 69(12): 120101. DOI: 10.7498/aps.69.20200123.
```

`consistency_report.json` 摘要：`structural_consistent: true`，`evidence_complete: false`，`overall_status: "evidence_incomplete"`（存在 1 处 `[来源缺失]`，已列入 `uncertainty` 待人工补充文献；result.json 的 `status` 应如实写 `partial`）。

> 以上为接口演示的示意输出，不代表任何正式测评案例的结果。
