# 情景编译器 v5 → v6：12 案例决策支持诊断

## 一句话结论

最稳健的结果是：在完全相同的 12 组已封存多智能体行动上，v6 将有效决策角色覆盖率从 75.0% 提升到 100.0%（+25.0 个百分点），且每例仍固定 4 条情景。

语义结果是混合的：严格合格率由 12.5% 到 18.8%，但质量均分 10.88→10.79；完整路径 Recall@4 均为 50.0%。由于语义双评一致性偏低，这些只作探索性诊断。

因此当前可支持的产品主张是“更完整地保留多方行动并形成可审计观察清单”，不是预测更准。

## 设计

- v5 与 v6 使用相同的冻结 D0 事实、模拟结果、结构化金融决策和固定 4 分支预算。
- 不重跑多智能体模拟，只替换情景编译器，因此差异可归因于编译层。
- 质量阶段不读取 outcome；每个版本单独绝对评分两次，消除 X/Y 左右位置偏差。
- 生成与质量产物冻结后才读取匿名事件结果；路径覆盖同样独立评两次。

## 主要数字

| 指标 | v5 | v6 |
|---|---:|---:|
| 有效决策角色覆盖率 | 75.0% | 100.0% |
| 绝对质量均分（满分20） | 10.88 | 10.79 |
| 严格合格情景率 | 12.5% | 18.8% |
| 完整事件路径 Recall@4 | 50.0% | 50.0% |
| 含部分命中的 Recall@4 | 62.5% | 66.7% |

质量配对：v6 胜 6，v5 胜 5，平 1；v6 非劣率 58.3%。

路径覆盖配对：v6 胜 4，v5 胜 4，平 4。

## 评审稳定性

| 指标 | v5 | v6 |
|---|---:|---:|
| 质量分数差 ≤1 的重复一致率 | 83.3% | 98.3% |
| 分支布尔标签重复一致率 | 67.1% | 73.8% |
| 路径状态重复一致率 | 58.3% | 58.3% |

分支布尔标签与路径状态一致率都低于 80% 护栏，因此质量和路径指标统一标为探索性/描述性；覆盖率不依赖模型裁判。

## 解释边界

- This diagnostic was registered after v5 retrospective results were known.
- It isolates compiler versions, not the value of the full simulation system.
- The operator knew historical outcomes, although v6 generation and quality judging never open them.
- The same economical model family generates and judges outputs; results require future independent validation.
- Scenario quality and path recall are decision-support metrics, not forecast calibration or trading returns.

## 新增开销

- 完成调用：122；失败：0；tokens：395,595。
- 供应商估算费用：0.02942644。
- 开发账本：v6 编译/重试 26 次，质量评审 48 次，路径评审 48 次。
- 从最终封存产物干净重跑且无语义重试时预计 108 次；本次额外调用来自发现并修复缺失标题、摘要和连贯性字段的契约漏洞。

## 逐案例

| 案例 | v5质量 | v6质量 | 质量胜者 | v5完整命中 | v6完整命中 |
|---|---:|---:|---:|---:|---:|
| blind_airline_activist_campaign_025 | 11.0 | 11.5 | v6 | 1 | 2 |
| blind_airline_merger_block_023 | 6.5 | 7.5 | v6 | 2 | 2 |
| blind_airline_restructuring_031 | 11.0 | 12.0 | v6 | 0 | 1 |
| blind_alzheimers_drug_review_026 | 14.0 | 10.5 | v5 | 0 | 1 |
| blind_autonomous_permit_suspension_032 | 13.0 | 8.5 | v5 | 0 | 0 |
| blind_bank_control_capital_022 | 14.0 | 13.5 | v5 | 1 | 1 |
| blind_foreign_steel_acquisition_block_030 | 9.5 | 10.5 | v6 | 1 | 1 |
| blind_grocery_merger_injunction_029 | 6.0 | 10.0 | v6 | 2 | 2 |
| blind_healthcare_cyber_disruption_024 | 8.0 | 9.5 | v6 | 2 | 1 |
| blind_search_antitrust_liability_028 | 12.0 | 11.5 | v5 | 1 | 1 |
| blind_security_update_outage_027 | 14.5 | 14.5 | tie | 1 | 0 |
| blind_semiconductor_ceo_transition_033 | 11.0 | 10.0 | v5 | 1 | 0 |

## 复现

```bash
make compiler-diagnostic-report
```

该命令只汇总已封存产物，不产生模型费用。完整重跑必须显式允许计费。
