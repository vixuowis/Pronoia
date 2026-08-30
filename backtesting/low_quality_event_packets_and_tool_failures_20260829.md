# 低质量事件Packet清单与外部取数失败诊断

- 总样本：1000
- 低质量packet候选：**880（88.0%）**
- 严重度：{'medium': 236, 'high': 644}。high=模板/身份/类型冲突；medium=事件身份有效但缺关键正文或量化字段。
- 完整清单：`low_quality_event_packets_20260829.csv`
- 这是规则筛查候选，不是人工金标；正式剔除前应抽样复核。

## Packet问题分布

| 问题标签 | 样本数 |
|---|---:|
| 缺少可定向量化值 | 636 |
| 只有标题/正文过短 | 592 |
| 模板/占位字段 | 575 |
| 财报缺核心字段 | 200 |
| 并购缺交易实体/动作 | 106 |
| event_type与正文语义错配 | 59 |
| 标题与正文事件身份冲突 | 59 |
| 泛化汇总标题/非实体事件 | 34 |

### 市场与事件类型

- 市场：{'CN': 599, 'US': 281}
- 事件类型：{'财报超预期/不及预期': 220, '并购/分拆/再融资': 134, '公司指引上调/下调': 140, '政策利率调整': 106, '通胀数据意外': 140, '增长/就业数据意外': 140}

## Tool调用总体情况

- Tool calls：28418；成功：22351；失败：6067；失败率：21.3%
- 失败原因：`{'timeout>60s': 3416, 'other_failure': 1766, 'connection_error': 23, 'no_data_or_symbol_resolution': 853, 'parameter_error': 9}`
- 同一样本/技能先失败后成功：703组；所有重试都失败：1412组。

| Skill | Calls | Success | Failed | Failure rate | Timeout |
|---|---:|---:|---:|---:|---:|
| event_study_skill | 3927 | 1706 | 2221 | 56.6% | 477 |
| stock_overview | 2079 | 606 | 1473 | 70.9% | 630 |
| market_research | 3288 | 1923 | 1365 | 41.5% | 1365 |
| financial_research | 1307 | 934 | 373 | 28.5% | 373 |
| evidence_graph | 13334 | 12974 | 360 | 2.7% | 308 |
| holder_research | 655 | 483 | 172 | 26.3% | 172 |
| news_intel | 782 | 740 | 42 | 5.4% | 40 |
| macro_intel | 1125 | 1094 | 31 | 2.8% | 31 |
| evidence_ledger | 30 | 15 | 15 | 50.0% | 5 |
| post_market_outlook | 65 | 52 | 13 | 20.0% | 13 |
| search_stock | 13 | 12 | 1 | 7.7% | 1 |
| announcement_onepager | 9 | 8 | 1 | 11.1% | 1 |
| drift_context_analyzer | 899 | 899 | 0 | 0.0% | 0 |
| ar_decomposer | 632 | 632 | 0 | 0.0% | 0 |
| announcement_classifier | 245 | 245 | 0 | 0.0% | 0 |
| get_current_date | 28 | 28 | 0 | 0.0% | 0 |

## 根因判断

1. **硬超时是主要表面原因。** `execute_skill()` 对每次skill调用使用统一 `FEVER_SKILL_TIMEOUT`，默认60秒；同步handler放入线程后也受同一等待超时控制。
2. **上游数据源慢或限流。** market/stock/news/financial类skill依赖行情和公开数据provider；并发回填时请求集中，出现超时、YF限流、连接错误和无数据。
3. **重复调用放大拥塞。** 多个agent会以不同参数重复调用event study、market research和stock overview；虽然部分结果可共享，参数不同仍会新开请求。先失败后成功的组说明并非永久缺数，而是瞬时拥塞。
4. **标的解析与事件身份有问题。** ETF/指数格式（如SH516160）、美股泛化宏观事件、标题正文错配会让stock resolver、macro query或行情映射找不到正确对象。
5. **严格as-of禁止联网补救。** packet约束中 `web_search_allowed=false`，因此skill失败后不能用网页检索公告正文、宏观actual/consensus或SEC文件作为fallback。
6. **成功只记录preview而非payload。** trajectory中的tool trace经常只保存“返回1行”，后续Evidence seed也只带preview/source_data参数；真实数值即使成功取到，也可能没有被复制到Graph，表现成“工具成功但模型仍认为不可读”。
7. **Packet生成阶段已经丢信息。** 很多宏观/指引packet是占位模板，财报只有标题；外部取数不是补充信息，而是在承担重建整个事件的任务，失败概率和不确定性自然很高。

### Event study失败的直接根因

`{'timeout>60s': 477, '其他symbol/provider行情失败': 103, '其他': 17, '调用参数缺symbol/keyword': 571, '沪市ETF被错误规范化为sz前缀': 1053}`

其中最严重的不是网络：大量调用根本没有传 `symbol/keyword`；另一大类是上海ETF代码（51xxxx/56xxxx/58xxxx）被错误转换成 `sz` 前缀，例如 `SH516160 → sz516160`，随后新浪/腾讯provider均返回KeyError/IndexError。这是确定性的代码规范化bug。

## 建议修复顺序

1. 在进入回测前执行packet quality gate；缺事件身份、actual/consensus、公告正文的样本先进入backfill队列，不直接评分。
2. 将announcement/macro actual-consensus在离线数据准备阶段写入packet，避免运行期依赖外部provider。
3. 对event study行情做本地批量预计算与缓存，以 `(market,symbol,event_date,benchmark)` 为键；不要让每个agent重复在线取。
4. 为不同skill设置独立timeout和有限重试；行情读取可延长，但不要对同一provider高并发重试。
5. 对ETF/指数/美股ticker建立规范化映射，并在调用skill前验证symbol和benchmark。
6. tool trace与Evidence节点保存结构化关键payload，不只保存preview；至少保留T0、AR、pre5/pre20、actual/consensus/previous及来源时间。
7. 分开报告clean-packet reasoning ACC与all-packet end-to-end ACC。