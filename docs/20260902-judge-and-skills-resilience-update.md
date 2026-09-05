# 裁决器与 Skills 稳定性改动说明

## 1. 变更目的

本次提交合并两组已经在本地验证的改动：

1. 修正方向裁决语义，避免低 confidence 覆盖已有方向，并统一 benchmark-relative 收益方向。
2. 修复研究 Skills 的参数契约、证券解析、行情路由和父子超时竞争，降低“取数失败 → 空图谱 → neutral”的概率。

本次提交不包含 trajectory、逐样本裁决结果、标注包或 SFT 中间产物。

## 2. 裁决器改动

### 2.1 Confidence 与方向解耦

此前模型给出 `up/down` 后，如果 `confidence < 0.60`，运行时代码会强制改写为 `neutral`。现在：

- `pred_direction` 保留裁决器按证据净分给出的方向；
- `confidence` 只表达可靠程度；
- 只有执行完全失败时仍使用 `neutral` 作为系统兜底；
- trajectory 中继续保留 `conf_gate_applied` 字段，以兼容旧数据结构，但新版正常结果恒为 `false`。

### 2.2 T0 信号改为相对基准方向

评测目标是 benchmark-relative CAR，因此 `ar_decomposer` 现在使用：

```text
relative_return = stock_return - benchmark_return
```

方向由 `relative_return` 的符号与阈值决定。例如个股上涨 0.8%、基准上涨 1.5%，相对收益为 -0.7%，方向应为 `down`，不能按个股绝对上涨判为 `up`。

### 2.3 固定 Evidence Graph 的 1000 条裁决 A/B

| 指标 | legacy_v1 | no-conf-gate | 差值 |
|---|---:|---:|---:|
| T3 strict ACC | 33.90% | 34.20% | +0.30 pp |
| T3 三分类 exact | 44.20% | 44.60% | +0.40 pp |
| 出手 precision | 57.26% | 58.16% | +0.90 pp |
| 直接反向错误 | 166 | 160 | -6 |

配对 exact 中旧版独赢 9 条、新版独赢 13 条，McNemar `p=0.6291`。因此结果方向略有改善，但尚未达到统计显著，不能宣称裁决器已经稳定提升最终 ACC。

## 3. Skills 改动

### 3.1 父子 Skill 分层超时

新增以下配置：

| 配置 | 默认值 | 用途 |
|---|---:|---|
| `FEVER_SKILL_TIMEOUT` | 60s | 顶层 Skill |
| `FEVER_SKILL_SUB_TIMEOUT` | 30s | 普通原子子技能 |
| `FEVER_SKILL_SLOW_SUB_TIMEOUT` | 45s | 多数据源慢速子技能 |
| `FEVER_SKILL_COMPOSITE_SUB_TIMEOUT` | 50s | 嵌套组合 Skill |

子技能先于父技能结束，使组合 Skill 有时间汇总已成功的 sibling 结果，并明确返回 `degraded`，避免父子同时在 60 秒到期。

### 3.2 修复组合 Skill 的硬编码参数

对 `market_research`、`post_market_outlook`、`holder_research`、`macro_intel`、`news_intel` 等路径进行了 schema 对齐：

- 不再向板块、资金流工具传入不存在的 `symbol` / `indicator` 参数；
- 解禁明细改用实际注册的 `get_restricted_release_detail`；
- 宏观 topic 映射到 `get_macro(indicator=...)`；
- 公告接口支持有界 `limit`；
- 所有子技能失败时，组合 Skill 不再返回虚假的顶层成功。

### 3.3 统一证券解析

新增 `resolve_security` 与本地 `resolve_security_ref`：

- packet 已有明确 `symbol` 时完全绕过外部名称搜索；
- 支持 A 股、北交所、ETF、指数和美股 ticker；
- `stock_overview` 新增显式 `symbol` 和 `market` 参数；
- 只有缺少 symbol、仅有公司名称时才回退到 `search_stock`。

### 3.4 统一历史价格路由

新增共享 `price_data.py`，研究 Skills 与 backtest labeller 使用同一套证券分类和 OHLCV 标准化逻辑。

主要路由：

- CN 股票/ETF/指数：有 socket timeout 的腾讯单标的 K 线优先，AkShare ETF、指数、Sina/Tencent 路径作为 fallback；
- US：Yahoo 单代码 chart API 优先，`yfinance.download` 和 `akshare.stock_us_daily` 作为 fallback；
- provider 尝试记录在返回 meta 中，便于复核失败原因。

美股 `market_research` 默认只请求单标的历史价格，不再默认调用全市场 spot 或雪球公司信息。

## 4. 200 条历史高失败事件压力测试

样本从原 1000 条 trajectory 中按 `stock_overview` / `market_research` 失败调用数选取，CN/US 各 100 条；200 个事件对应 102 个唯一 market+symbol。

| Skill | 历史事件成功 | 修复后首轮 | 一次重试后 |
|---|---:|---:|---:|
| `stock_overview` | 16.5% | 100.0% | 100.0% |
| `market_research` | 45.0% | 99.5% | 100.0% |

其中 US `market_research` 从 2/100 提升至 100/100。唯一首轮失败为 `SH515180` 的瞬时 SSL 错误，隔离重试成功。

仍存在两个限制：

1. `stock_overview` 虽然核心价格 200/200 可用，但辅助财务接口仍使全部结果标记为 `degraded`，中位耗时约 30 秒。
2. 这 200 条只验证取数与解析能力，没有重新生成 Evidence Graph 或最终方向，因此不能据此声称事件预测 ACC 已提升。

## 5. 严格 as-of 限制

当前 `market_research` / `stock_overview` 的交互路径默认以运行当天作为行情截止日期。历史事件回测必须继续依赖严格 `as_of_packet` 和 `event_study_skill(as_of=True)`；在将普通行情 Skill 纳入历史预测前，应新增并强制传递 `as_of_date=event_time`。

在本次 200 条 Skill 压力测试中，199 条成功的 `market_research` 行情日期均晚于事件时间。因此这些结果只能用于成功率测试，不能直接用于历史事件预测 ACC 测试，否则会产生未来数据泄漏。

## 6. 验证与复现

核心单元测试：

```bash
PYTHONPATH=. backend/.venv/bin/python -m unittest \
  backend.tests.test_price_data \
  backend.tests.test_skills_composite \
  backend.tests.test_skill_timeouts \
  backend.tests.test_agent_and_team \
  backend.tests.test_direction_semantics -v
```

200 条 Skill 压力测试入口：

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  backtesting/run_skill_resilience_200.py \
  --per-market 100 --concurrency 2
```

固定 Evidence Graph 的裁决器 A/B 入口：

```bash
PYTHONPATH=. backend/.venv/bin/python \
  backtesting/run_judge_ab_1000_20260901.py
```

## 7. 后续建议

1. 为研究 Skills 增加 `as_of_date` 并在 backtesting engine 强制注入事件时间。
2. 将 `stock_overview` 的核心行情与辅助财务接口拆开，避免辅助源超时拖慢核心结果。
3. 在同一批 200 条事件上重新构图并预测，统计 strict ACC、exact ACC、wrong→right、right→wrong、neutral 占比和图谱质量，才能判断本次 Skills 修复是否改善最终事件预测。
