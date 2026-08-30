# 低质量 Event Packet 五类代表案例

> 样本来自 `low_quality_rerun_30_manifest_20260829.csv`。旧结果来自
> `_trajectory_ckpt_tf_cn_us_1000_v1`；新 A/B 结果仅在 trajectory 已落盘时列出。
> T3 标签按 `labels_cn_us_1000_v1.jsonl`，neutral 阈值为 ±0.5%。

## 1. ETF 前缀错误：SH515400

- event_id：`seed_cn_sh515400__c18575aa16`
- 事件：2024-01-01，并购/分拆/再融资
- title：中国上市公司定增/可转债/配股再融资公告
- event_text：`重组委 | 交易所 预期:会前一致 前值:过往批次`
- Packet 问题：标的是 ETF，却被包装为上市公司再融资；正文缺交易实体和动作。
- 旧工具问题：`event_study_skill` 6 次错误请求 `sz515400`；另有一次缺 symbol。
- 旧最终结果：neutral，confidence 0.50。
- 新 v0：down，confidence 0.63。
- 新 claim-v2：down，confidence 0.60。
- T3 真实结果：down，CAR = -3.589%。
- 结论：旧结果错误；ETF 前缀修复后两版均翻转为正确 down，是当前最明确的正向案例。

## 2. 缺 symbol：002843 泰嘉股份

- event_id：`seed_cn_002843_event_e30b1661bb`
- 事件：2025-01-07，财报超预期/不及预期
- title：泰嘉股份：2024年度业绩预告
- event_text：`泰嘉股份:2024年度业绩预告 | 002843 泰嘉股份 · 业绩预告`
- Packet 问题：只有公告标题，没有净利润、营收、同比或预期差。
- 旧工具问题：存在缺 symbol 和 timeout；另有多次按公司名查询失败。
- 旧最终结果：up，confidence 0.63；主要依据 T0 主动超额约 +5.94%，而非业绩正文。
- T3 真实结果：up，CAR = +6.757%。
- 新 v0：neutral，confidence 0.50。
- 新 claim-v2：up，confidence 0.68。
- 结论：claim-v2 正确出手，v0 被 neutral gate 截断；这是本轮 claim-v2 的明确独赢样本。

## 3. 宏观模板/身份缺失：US SHY · PCE

- event_id：`seed_us_shy__e6ea43b806`
- 事件：2024-01-01，通胀数据意外
- title：US PCE Price Index Release
- event_text：`PCE | BEA consensus: market prev: last`
- Packet 问题：actual、consensus、previous 全是占位符，无法判断 PCE 是否超预期。
- 旧工具表现：22 次工具调用全部成功，但成功取数不能补回 packet 中缺失的发布值与预期差。
- 旧最终结果：neutral，confidence 0.50。
- T3 真实结果：neutral，CAR = -0.211%。
- 新 v0：neutral，confidence 0.50。
- 新 claim-v2：neutral，confidence 0.50。
- 结论：结果正确，但不是 packet 变好了；模型因关键宏观值缺失而合理 abstain。这类问题需要上游补 actual/consensus/previous。

## 4. 财报缺核心字段：601166 兴业银行

- event_id：`seed_cn_601166__9addc06f1b`
- 事件：2024-01-05，财报超预期/不及预期
- title：中国三季报业绩快报汇总
- event_text：`三季报 | 公告 预期:市场 前值:上期`
- Packet 问题：标题泛化、正文为模板，没有公司业绩数字或预期差。
- 旧工具表现：36 次调用、无工具失败；问题来自输入语义，而非连接失败。
- 旧最终结果：down，confidence 0.60；模型把“略降”先验和 pre20 弱势作为主要证据。
- T3 真实结果：up，CAR = +1.381%。
- 新 v0：neutral，confidence 0.50。
- 新 claim-v2：neutral，confidence 0.50。
- 结论：旧结果错误。即使工具全部成功，缺少真实财报字段仍会迫使模型用先验填空，容易形成错误证据图。

## 5. 其他低质对照：600585 海螺水泥重组模板

- event_id：`seed_cn_600585__73df967246`
- 事件：2024-01-03，并购/分拆/再融资
- title：中国上市公司重大资产重组预案公告
- event_text：`重组委 | 交易所 预期:会前一致 前值:过往批次`
- Packet 问题：没有交易双方、交易动作、对价、稀释比例或阶段信息。
- 旧工具表现：23 次调用、无工具失败。
- 旧最终结果：neutral，confidence 0.52；完整回答中曾表达弱偏多，但结构化抽取最终被 neutral gate 截断。
- T3 真实结果：up，CAR = +3.133%。
- 新 v0：neutral，confidence 0.50。
- 新 claim-v2：up，confidence 0.60。
- 结论：claim-v2 正确出手，v0 仍被 neutral gate 截断；这是本轮 claim-v2 的第二个独赢样本。

## 小结

| 类别 | 旧结果 | T3 标签 | 旧结果是否正确 | 新 A/B |
|---|---|---|---|---|
| ETF 前缀错误 | neutral | down | 否 | v0/claim-v2 均改为 down，正确 |
| 缺 symbol | up | up | 是 | v0 neutral；claim-v2 up（正确） |
| 宏观模板 | neutral | neutral | 是 | 两版均 neutral（strict 口径仍算错） |
| 财报缺字段 | down | up | 否 | 两版均 neutral（错误） |
| 其他低质对照 | neutral | up | 否 | v0 neutral；claim-v2 up（正确） |
