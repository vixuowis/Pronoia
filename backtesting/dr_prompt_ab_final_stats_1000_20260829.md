# Deep Researcher Prompt A/B 最终报告（1000条）

## 完成状态与口径

- `deep_researcher_v0`：1000/1000 有效，0 error。
- `deep_researcher_claim_v2`：1000/1000 有效，0 error。
- 全部统计为1000条严格配对结果；两版使用相同 Evidence 输入。
- T3 标签分布：up=357、down=453、neutral=190。
- backtesting strict ACC 将 oracle-neutral 保留在分母且永不计正确；同时报告非 neutral ACC 和普通三分类 exact accuracy。

## 最终方向效果

| 指标 | v0 | claim-v2 | v2-v0 | 配对95% CI | McNemar p |
|---|---:|---:|---:|---:|---:|
| T3 strict ACC | **6.40%** | 5.40% | -1.00 pp | [-2.70,+0.70] pp | 0.295 |
| T3 非 neutral ACC（n=810） | **7.90%** | 6.67% | -1.23 pp | — | — |
| T3 普通三分类 exact | **23.60%** | 22.10% | -1.50 pp | [-3.50,+0.40] pp | 0.167 |
| avg_all strict ACC | **6.70%** | 6.00% | -0.70 pp | [-2.40,+1.00] pp | 0.500 |
| consensus66 strict ACC | **5.70%** | 5.20% | -0.50 pp | [-2.10,+1.10] pp | 0.625 |

claim-v2 在所有方向口径上点估计均低于 v0，但差异均不显著。不能声称稳定退化，也没有任何证据支持它改善了最终 ACC。

### T3 配对胜负/翻转

- strict：两边都正确22；仅v0正确42；仅claim-v2正确32；两边都错904。
- claim-v2 相对 v0 净少10条 strict 正确样本。
- 普通三分类：两边都正确177；仅v0正确59；仅claim-v2正确44；两边都错720。
- 164/1000（16.4%）样本的最终预测发生变化。

### 预测分布与核心错误

| 预测 | v0 | claim-v2 | 真实标签 |
|---|---:|---:|---:|
| up | 4.6% | 3.3% | 35.7% |
| down | 7.1% | 9.8% | 45.3% |
| neutral | **88.3%** | **86.9%** | 19.0% |

claim-v2 仅将 neutral 降低1.4pp，且新增方向主要流向 down。T3混淆显示：

- v0：up正确23、down正确41；false-neutral 711；直接反向35。
- claim-v2：up正确11、down正确43；false-neutral 702；直接反向54。

因此 claim-v2 少了9个 false-neutral，却多了19个反向错误；减少弃权并未带来更好的方向质量。

## Evidence Graph 质量

| 指标（均值） | v0 | claim-v2 | 配对差值 | 95% CI |
|---|---:|---:|---:|---:|
| Evidence | 10.669 | 10.669 | 0.000 | [-0.012,+0.012] |
| Claims | 2.302 | 2.713 | **+0.411** | [+0.360,+0.461] |
| Missing | 2.738 | 2.575 | **-0.163** | [-0.237,-0.088] |
| Edges | 8.126 | 9.167 | **+1.041** | [+0.682,+1.402] |
| Supports | 3.068 | 4.343 | **+1.275** | [+1.066,+1.485] |
| Contradicts | 0.011 | 0.148 | **+0.137** | [+0.109,+0.168] |
| Substantive claims | 1.641 | 2.261 | **+0.620** | [+0.534,+0.710] |
| Substantive claim rate | 71.33% | 83.65% | **+12.32 pp** | [+9.28,+15.37] pp |
| Atomic-title pass | 0.45% | 90.03% | **+89.58 pp** | [+88.12,+91.00] pp |
| Rationale complete | 99.90% | 99.60% | -0.30 pp | [-0.80,+0.10] pp |
| Audit findings | 15.289 | 5.572 | **-9.717** | [-10.072,-9.374] |

图谱结构改善显著且稳定：claim-v2 生成更多原子、实质 claims，支持/冲突边更丰富，missing 和 audit findings 更少。Evidence 数量完全相同，因此这是组织图谱能力的改善，不是输入差异。

`sufficient` 自报率从44.8%降至1.8%。该字段没有独立质量验证，只反映 prompt 的停止标准；claim-v2 更容易保持图谱开放，不能直接解释为质量降低，但说明两个版本的 stopping semantics 已不一致。

## 改善和退化来源

### 改善来源

1. Claim 原子化要求被稳定执行，atomic-title pass 提升近90pp。
2. Evidence 与 Claim 的实质连接更密集，supports 平均增加1.275条。
3. claim-v2 开始表达冲突证据，而 v0 几乎完全不使用 contradicts。
4. missing 略降，图谱审计问题显著减少。

### 未转化为ACC的原因

1. 方向没有成为 Claim 的显式结构字段；裁决器仍需从长文本推断符号。
2. `needs_more`/`sufficient=false` 被裁决器解释成无方向，造成约87%的 neutral。
3. system prompt 的“保守”与评分卡的“只有净分为0才neutral”冲突。
4. 净分过程没有强制结构化输出，模型可以跳过逐项打分直接弃权。
5. claim-v2 新增的明确判断明显偏向 down，并使 up→down 从16条增至38条。

## 结论与建议

最终结论是：**claim-v2 显著改善 Evidence Graph 的形式与结构，但没有改善最终方向 ACC。** 当前瓶颈已经从“图谱是否规范”转移到“图谱能否被方向裁决器消费”。

下一步优先做 judge-only A/B，不必重跑 Deep Researcher：为 Claim 增加 `direction/strength/time_horizon/evidence_quality`，强制裁决器返回 `up_score/down_score/net_score/decisive_claim_ids`，再由代码按净分确定性映射 up/down/neutral。降低 neutral 的同时必须监控新增方向判断 precision，避免继续把 false-neutral 转成反向错误。

共同误判代表案例另见 `dr_prompt_ab_both_wrong_cases_final_20260829.md`。
