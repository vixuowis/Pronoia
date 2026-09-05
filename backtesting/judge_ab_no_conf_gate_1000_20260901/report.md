# 新旧裁决器固定 Evidence Graph 全量 A/B（2026-09-01）

> 两版读取同一事件 packet 与同一 Evidence Graph。旧版提示低 confidence 会被改为 neutral，且保留 `<0.60 → neutral` 后处理；新版将 confidence 与方向解耦。
> 1000 个历史 trajectory 中，985 条可取得原生 graph artifact；15 条用同次运行的 structured_extract + as-of packet 构成显式代理图，仅纳入敏感性分析。

## 原生 Evidence Graph（主结果）

| 指标 | 旧 legacy_v1 | 新 no-conf-gate | 差值 |
|---|---:|---:|---:|
| 有效样本 | 985 | 985 | — |
| T3 strict ACC | 333/985 (33.81%) | 336/985 (34.11%) | +0.30pp |
| T3 三分类 exact | 434/985 (44.06%) | 438/985 (44.47%) | +0.41pp |
| 非 neutral Oracle ACC | 41.73% | 42.11% | — |
| 方向覆盖率 | 59.09% | 58.68% | — |
| 出手 precision | 57.22% | 58.13% | — |
| False neutral | 302 | 305 | +3 |
| 直接反向错误 | 163 | 157 | -6 |
| confidence 硬闸触发 | 1 | 0 | — |

预测分布：旧版 `{'down': 320, 'neutral': 403, 'up': 262}`；新版 `{'down': 320, 'neutral': 407, 'up': 258}`。

配对 exact：两版都对 425；仅旧版对 9；仅新版对 13；两版都错 538；方向变化 32。
方向 Oracle 上的配对净胜负：旧版独赢 7，新版独赢 10；exact McNemar p=0.6291。

图谱概况：985 张，平均 claims 1.58、edges 3.32；零 claim 41；sufficient 525；代理图 0。

方向迁移：

- `neutral->neutral`: 390
- `down->down`: 309
- `up->up`: 254
- `neutral->down`: 10
- `down->neutral`: 10
- `up->neutral`: 7
- `neutral->up`: 3
- `down->up`: 1
- `up->down`: 1

## 全量（含16条代理图敏感性分析）

| 指标 | 旧 legacy_v1 | 新 no-conf-gate | 差值 |
|---|---:|---:|---:|
| 有效样本 | 1000 | 1000 | — |
| T3 strict ACC | 339/1000 (33.90%) | 342/1000 (34.20%) | +0.30pp |
| T3 三分类 exact | 442/1000 (44.20%) | 446/1000 (44.60%) | +0.40pp |
| 非 neutral Oracle ACC | 41.85% | 42.22% | — |
| 方向覆盖率 | 59.20% | 58.80% | — |
| 出手 precision | 57.26% | 58.16% | — |
| False neutral | 305 | 308 | +3 |
| 直接反向错误 | 166 | 160 | -6 |
| confidence 硬闸触发 | 1 | 0 | — |

预测分布：旧版 `{'down': 324, 'neutral': 408, 'up': 268}`；新版 `{'down': 324, 'neutral': 412, 'up': 264}`。

配对 exact：两版都对 433；仅旧版对 9；仅新版对 13；两版都错 545；方向变化 32。
方向 Oracle 上的配对净胜负：旧版独赢 7，新版独赢 10；exact McNemar p=0.6291。

图谱概况：1000 张，平均 claims 1.58、edges 3.29；零 claim 41；sufficient 525；代理图 15。

方向迁移：

- `neutral->neutral`: 395
- `down->down`: 313
- `up->up`: 260
- `neutral->down`: 10
- `down->neutral`: 10
- `up->neutral`: 7
- `neutral->up`: 3
- `down->up`: 1
- `up->down`: 1

## CN 分层

样本 700；strict ACC：旧 33.00% → 新 33.43%；exact：旧 43.14% → 新 43.86%；false-neutral：249 → 249。

## US 分层

样本 300；strict ACC：旧 36.00% → 新 36.00%；exact：旧 46.67% → 新 46.33%；false-neutral：56 → 59。

## 解释边界

- 本实验只测裁决器；Evidence Graph 固定，因此不衡量 `ar_decomposer` 修复对重新构图后的影响。
- 模型即使 `temperature=0` 也可能存在服务端非完全确定性；应以配对净胜负及 McNemar 检验判断，而不是只看少量翻转。
- 15 条代理图含历史结构化摘要，不等同于正式 Evidence Graph，因此主结论以 985 条原生图为准。
