# Deep Researcher 全量 A/B 与行情取数结论

## 一句话结论

**claim-v2 能显著改善 Evidence Graph 的结构组织，但没有改善最终方向准确率；当前端到端质量的首要瓶颈不是 Prompt，而是事件 Packet 与行情取数链路无法稳定提供可定向证据。整体而言，现有行情取数能力存在明显欠缺。**

## 1. 1000 条全量 Prompt A/B

两版均完成 1000/1000 条严格配对测试，使用相同 Evidence 输入，因此该部分隔离评估 Deep Researcher Prompt 的图谱组织能力。

### 最终方向

| 指标 | v0 | claim-v2 | v2 - v0 |
|---|---:|---:|---:|
| T3 strict ACC | **6.40%** | 5.40% | -1.00 pp |
| T3 非 neutral ACC | **7.90%** | 6.67% | -1.23 pp |
| T3 普通三分类 exact | **23.60%** | 22.10% | -1.50 pp |
| avg_all strict ACC | **6.70%** | 6.00% | -0.70 pp |
| consensus66 strict ACC | **5.70%** | 5.20% | -0.50 pp |

差异均未达到统计显著。claim-v2 没有证据表明改善最终 ACC，也不能据此认定稳定退化。

配对结果：

- strict：仅 v0 正确 42 条，仅 claim-v2 正确 32 条，claim-v2 净少 10 条。
- 164/1000 条最终预测发生变化。
- claim-v2 减少 9 个 false-neutral，但增加 19 个直接反向错误；减少弃权没有转化为更可靠的方向判断。

### Evidence Graph

| 图谱指标（均值） | v0 | claim-v2 | 差值 |
|---|---:|---:|---:|
| Evidence | 10.669 | 10.669 | 0.000 |
| Claims | 2.302 | 2.713 | **+0.411** |
| Missing | 2.738 | 2.575 | **-0.163** |
| Edges | 8.126 | 9.167 | **+1.041** |
| Supports | 3.068 | 4.343 | **+1.275** |
| Contradicts | 0.011 | 0.148 | **+0.137** |
| Substantive claim rate | 71.33% | 83.65% | **+12.32 pp** |
| Atomic-title pass | 0.45% | 90.03% | **+89.58 pp** |

结论：claim-v2 的改善是真实且稳定的，但属于“同一批证据如何组织成图”，不是“获得了更多有效证据”。

## 2. Neutral 与 false-neutral

| 预测分布 | v0 | claim-v2 | 真实标签 |
|---|---:|---:|---:|
| up | 4.6% | 3.3% | 35.7% |
| down | 7.1% | 9.8% | 45.3% |
| neutral | **88.3%** | **86.9%** | 19.0% |

Neutral 的主体不是多空证据抵消，而是模型认为 up/down 均无可计分证据：

| Neutral 类型 | v0 | claim-v2 |
|---|---:|---:|
| 明确 up=0、down=0 | 594（67.3%） | 581（66.9%） |
| 明确多空抵消 | 33（3.7%） | 24（2.8%） |

在真实方向为 up/down、但模型输出 neutral 的样本中：

| 指标 | v0 | claim-v2 |
|---|---:|---:|
| False-neutral | 711 | 702 |
| 明确 0:0 false-neutral | 480 | 467 |
| 其中：事件输入缺失 + 工具/行情取数失败 | **411（85.6%）** | **411（88.0%）** |
| 仅事件输入不完整 | 40 | 24 |
| 仅工具/行情链路失败 | 22 | 26 |
| 已有证据未完整进入图谱 | 3 | 2 |

这说明 false-neutral 的主要机制是“无证据可判”，不是裁决器面对冲突证据时过于保守。

## 3. Packet 与行情工具诊断

规则筛查发现 1000 条中有 880 条低质量 Packet 候选：

- 缺少可定向量化值：636 条。
- 只有标题或正文过短：592 条。
- 模板/占位字段：575 条。
- 财报缺核心字段：200 条。
- 并购缺交易实体/动作：106 条。

历史 trajectory 共记录 28,418 次工具调用，其中失败 6,067 次，失败率 21.3%。

| Skill | 调用 | 失败 | 失败率 |
|---|---:|---:|---:|
| event_study_skill | 3,927 | 2,221 | **56.6%** |
| stock_overview | 2,079 | 1,473 | **70.9%** |
| market_research | 3,288 | 1,365 | **41.5%** |
| financial_research | 1,307 | 373 | 28.5% |

event-study 的直接问题包括：

- 沪市 ETF 被错误规范化为 `sz` 前缀：1,053 次。
- 调用缺少 `symbol/keyword`：571 次。
- 调用超过 60 秒：477 次。
- 其他 symbol/provider 行情失败：103 次。

## 4. 本轮修复

本轮代码修改主要覆盖：

1. 50/51/52/56/58 开头的 ETF/LOF 规范化为沪市代码，并保留显式 SH/SZ 前缀。
2. event-study 缺少 symbol/date/benchmark 时，从事件元数据注入确定性默认值。
3. Tool trace 保存有界 `result_excerpt`，让关键数值能够进入 Evidence seed，而不只保存“返回 1 行”。
4. 为 Python/httpx 增加可选强制 IPv4；本机实测默认路径 ConnectTimeout，IPv4 后 Ark 直连 1.81 秒、SDK 3.03 秒返回。
5. 为非流式请求与完整 streaming round 增加应用层硬超时，避免本地代理 keepalive 导致无限等待。

## 5. 30 条低质量 Packet 全链路压力测试

修复后对 30 条低质量事件重新执行 v0/claim-v2 全链路 A/B，而不是复用旧 trajectory。

| 指标 | v0 | claim-v2 |
|---|---:|---:|
| T3 strict ACC | 2/30（6.7%） | 3/30（10.0%） |
| Neutral | 27/30（90.0%） | 25/30（83.3%） |
| Evidence / event | 13.57 | 14.90 |
| Claims / event | 1.20 | 1.93 |
| Edges / event | 2.80 | 5.13 |
| 工具成功率 | 68.1% | 65.8% |
| event-study 成功率 | 12.3% | 7.6% |

结果表明：

- ETF 错误 `sz5…` 前缀已降为 0，确定性映射修复有效。
- claim-v2 继续生成更丰富的 Claim 与边，但调用更多工具，也暴露更多 SSL/timeout/symbol alias 问题。
- 30 条中方向发生变化 6 条；claim-v2 独赢 2 条、v0 独赢 1 条，净提升只有 1 条。
- 低质量 Packet 压力集上 neutral 仍超过 83%，说明 Prompt 无法替代缺失的事实和不稳定的行情源。

## 6. 最终判断与优先级

当前系统的问题可以概括为：

> Evidence Graph 的“组织能力”已经得到改善，但行情和事件事实进入图谱的“供给能力”仍然不足。模型经常拿到模板 Packet，同时 event-study、stock overview、market research 又超时、SSL 失败或解析不到 symbol，最终只能形成 0:0 并输出 neutral。

因此，**现阶段继续微调 Deep Researcher Prompt 的边际收益有限；首要工作应是补强行情取数能力。**

建议优先级：

1. 在离线准备阶段补齐 actual/consensus/previous、公告正文、交易条款和财报核心字段。
2. 预计算并缓存 T0、AR、pre5/pre20，以 `(market, symbol, event_date, benchmark)` 为键，避免每个 Agent 在线重复请求。
3. 完善 numeric keyword → symbol、ETF/指数/ticker 归一化，并在调用前做参数验证。
4. 为行情提供多数据源 fallback、按 skill 独立超时与有限重试；避免同一 provider 高并发重试。
5. 持久化结构化行情 payload 和来源时间，保证 Deep Researcher 能把有效数值写入 signed Claim。
6. 分开报告 clean-packet reasoning ACC 与 all-packet end-to-end ACC，避免将数据问题误判为模型推理问题。
