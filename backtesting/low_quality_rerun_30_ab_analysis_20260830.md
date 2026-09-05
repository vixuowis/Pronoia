# 30 条低质量 Event Packet A/B 重跑分析

> 配对样本：30；Oracle：T3 strict，neutral 阈值 ±0.5%。

## 总体结果

| 指标 | v0 | claim-v2 | 差值 |
|---|---:|---:|---:|
| T3 strict ACC | 2/30 (6.7%) | 3/30 (10.0%) | +1 条 |
| Neutral | 27/30 (90.0%) | 25/30 (83.3%) | -2 条 |

## 配对胜负与翻转

- 方向不同：6/30。
- claim-v2 独赢：2；v0 独赢：1。
- 两版都对：1；两版都错：26。

| event_id | 分层 | T3 | v0 | claim-v2 | 结果 |
|---|---|---|---|---|---|
| `seed_cn_002843_event_e30b1661bb` | missing_symbol_non_etf | up | neutral | up | claim-v2 改对 |
| `seed_cn_600585__73df967246` | other_low_quality_control | up | neutral | up | claim-v2 改对 |
| `seed_cn_sh512760__5dbdee4e60` | etf_prefix_failure | down | down | neutral | v0 更好 |
| `seed_cn_sh513050__82c007028e` | etf_prefix_failure | up | down | neutral | 均错 |
| `seed_cn_sh516150__b903a88199` | etf_prefix_failure | up | neutral | down | 均错 |
| `seed_cn_sh516160__7ee13dfb0c` | etf_prefix_failure | up | neutral | down | 均错 |

## 按低质量类型

| 分层 | n | v0 ACC | claim-v2 ACC | v0 neutral | claim-v2 neutral |
|---|---:|---:|---:|---:|---:|
| etf_prefix_failure | 8 | 2/8 | 1/8 | 5/8 | 5/8 |
| missing_symbol_non_etf | 6 | 0/6 | 1/6 | 6/6 | 5/6 |
| macro_identity_or_template | 6 | 0/6 | 0/6 | 6/6 | 6/6 |
| earnings_missing_core | 5 | 0/5 | 0/5 | 5/5 | 5/5 |
| other_low_quality_control | 5 | 0/5 | 1/5 | 5/5 | 4/5 |

## Evidence Graph 与工具调用

| 指标（每事件均值） | v0 | claim-v2 |
|---|---:|---:|
| n_evidence | 13.57 | 14.90 |
| n_claim | 1.20 | 1.93 |
| n_missing | 1.80 | 1.43 |
| n_edges | 2.80 | 5.13 |
| n_supports | 1.67 | 3.67 |
| n_contradicts | 0.07 | 0.00 |

- **v0**：工具 588/864 成功（68.1%）；event-study 21/171 成功（12.3%）；失败 276 次。失败标签：{'ssl': 88, 'missing_symbol': 30, 'timeout': 82}。

- **claim-v2**：工具 690/1049 成功（65.8%）；event-study 14/185 成功（7.6%）；失败 359 次。失败标签：{'ssl': 96, 'missing_symbol': 43, 'timeout': 93}。

## 结论

- claim-v2 的 T3 strict ACC 净增 1 条，但 neutral 仍为 25/30，改善幅度很小。
- 平均单事件耗时：v0 478.9s；claim-v2 517.9s。
- ETF 错前缀已消失；剩余主要瓶颈是上游 packet 缺关键事实，以及行情源 timeout/SSL。
- 该样本是刻意抽取的低质量压力集，不代表自然分布上的总体 ACC。
