# 多智能体金融情景的决策支持价值：12 案例回顾性评测

## 一句话结论

旧 v5 多智能体产物没有在这组回顾性评测中优于单智能体：完整事件路径 Recall@4 为 33.3%，低于 A 的 41.7%；严格合格情景率为 10.4%，A 为 50.0%。

同时，质量分差在 10/12 个案例中随 X/Y 顺序翻转，路径状态双评一致率仅 62.5%；这些语义指标只能用于发现问题，不能作为确认性效果证据。

## 设计

- A：同一 DeepSeek 模型只读取冻结的 D0 事实、参与方和关系，独立生成 4 条情景。
- B：复用原正式实验在 outcome 解封前封存的多智能体情景；按预定规则选择首个含 4 条分支的种子。
- 两组都限制为 4 条，避免靠大量罗列提高命中率。
- 质量评审不读取 outcome，使用 X/Y 匿名标签并交换顺序评两次。
- 路径评审在情景与质量结果冻结后才读取 outcome，同样交换顺序评两次。
- 完整命中要求两次评审都判定 full；false 目标必须明确写出阻止、推迟或维持现状的机制。

## 主要数字

| 指标 | A：单智能体 | B：多智能体 |
|---|---:|---:|
| 匿名质量均分（满分20） | 13.54 | 12.58 |
| 严格合格情景率 | 50.0% | 10.4% |
| 完整事件路径 Recall@4 | 41.7% | 33.3% |
| 含部分命中的 Recall@4 | 66.7% | 54.2% |
| 至少一个完整命中的案例率 | 58.3% | 58.3% |

匿名质量配对：B 胜 0，A 胜 1，平 11；由于 83.3% 的案例发生顺序翻转，不报告该平局驱动的“非劣率”为有效结论。

路径覆盖配对：B 胜 3，A 胜 6，平 3；换序状态一致率 62.5%。

## 解释边界

这是回顾性方法验证：操作者在制定本协议前已经知道历史结果，尽管生成链路和质量评审没有读取 outcome。它适合验证指标、代码和产品叙事，不是新的确认性盲测。下一步应把完全相同的规则用于新选择且未解封的事件。

路径命中不等于概率校准，更不等于交易收益。情景模块的产品承诺应是：列出有限、可监测、可推翻的未来路径，并告诉用户接下来观察什么。

## 新增评测开销

- 完成模型调用：172；失败调用：12；tokens：713,381。
- 供应商返回的估算费用：0.05710477。
- 本轮复用已封存模拟，不包含重新运行 36 次多智能体模拟的成本与时延。

## 逐案例结果

| 案例 | 质量胜者 | A完整命中 | B完整命中 | 路径胜者 |
|---|---:|---:|---:|---:|
| blind_airline_activist_campaign_025 | tie | 0 | 1 | B |
| blind_airline_merger_block_023 | tie | 2 | 0 | A |
| blind_airline_restructuring_031 | tie | 1 | 0 | A |
| blind_alzheimers_drug_review_026 | tie | 0 | 0 | A |
| blind_autonomous_permit_suspension_032 | A | 1 | 1 | A |
| blind_bank_control_capital_022 | tie | 0 | 0 | A |
| blind_foreign_steel_acquisition_block_030 | tie | 1 | 1 | B |
| blind_grocery_merger_injunction_029 | tie | 2 | 2 | tie |
| blind_healthcare_cyber_disruption_024 | tie | 0 | 1 | B |
| blind_search_antitrust_liability_028 | tie | 0 | 0 | tie |
| blind_security_update_outage_027 | tie | 1 | 1 | tie |
| blind_semiconductor_ceo_transition_033 | tie | 2 | 1 | A |

## 复现

```bash
make decision-support-eval-report
```

该命令只根据已封存产物重新汇总，不产生模型费用。完整重新运行需要显式传入 `ALLOW_BILLABLE=1`。
