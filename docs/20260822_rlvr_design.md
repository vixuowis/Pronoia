# Pronoia RLVR 后训练方案设计 v1（2026-08-22）
> 品牌说明：原 FEVER 系列统一重命名为 **Pronoia**（Pronoia = "先见之明，提前洞悉市场定价"），后缀 -RLVR / -MS 分别指代后训练单体方案 / 多尺度 MoE v2。

> 分支：`rlvr`（已创建自 `main`）  
> 目标：用 **RL from Verifiable Reward**（基于真实市场 CAR 的可验证奖励信号）替代/增强纯 SFT+DPO，让方向判别模型直接对最终正确的前瞻判断负责，并在输出中保留结构化推理链。

---

## 0. 背景与定位

现有训练脚手架（[train_pronoia_v2.py](file:///workspace/backend/scripts/train_pronoia_v2.py)，原 train_fever_v2.py）已打通：

```
SFT（模仿 Oracle 方向标签）→ DPO（偏好排序） → 5-fold hold-out → ACC + Wilson CI
```

但 SFT/DPO 的局限：
- **标签是后验静态的**：DPO 的 chosen/rejected 对是离线构造的，模型"记住标签"而非"学会预判"。
- **没有显式推理链**：输入 event_text → 输出 up/down，中间的信号提取、比较、权衡被压缩在隐层，无法审计/校准。
- **reward 稀疏且离散**：DPO 的偏好只告诉模型"哪个更好"，不告诉模型"好多少、为什么好"。

RLVR 要补的三板斧：
1. **端到端 reward**：用真实 `car_avg_all`（Oracle 标签的来源）作为连续 reward，方向对/错 × 置信度校准 × CAR 幅度共同决定奖励。
2. **可审计推理链**：强制模型在输出方向前，先显式输出结构化的 5 步推理链（信号→比较→反方→置信度→结论），并让 reward 部分依赖推理链的一致性/可验证性。
3. **在线采样 + 回放**：不再依赖固定 DPO pairs，而是每轮 rollout 采样 N 条（event → 推理链 → 方向），用 Oracle 算 reward 后更新策略。

---

## 1. 评估集（固定不变 + 新增 RER/长 horizons 指标）

评估 **只使用 `backtesting/` 目录下已构造好的 1000 条**——也就是 [events_cn_us_1000_v1.jsonl](file:///workspace/backtesting/events_cn_us_1000_v1.jsonl) + [labels_cn_us_1000_v1.jsonl](file:///workspace/backtesting/labels_cn_us_1000_v1.jsonl)，**不再重新生成、不新增样本、不改动字段**：

| 项 | 值 |
|---|---|
| 样本数 | 1000（CN 700 / US 300） |
| 时间跨度 | 2024-01 ~ 2026-06 |
| 主标签 | `label_avg_all`（加权平均 CAR 方向，up/down/neutral） |
| 连续奖励来源 | `car_avg_all`（真实加权超额收益） |
| 关键口径 | `acc_avg_all_strict`（neutral 也算错） + `acc_avg_all_non_neutral`（非 neutral 才计分） |

**为什么固定不动**：训练集和评估集必须严格时间/分布正交吗？不需要——这里的"同分布"指事件类型和市场比例的**分布一致**，但 event_id 完全不重叠。评估集 1000 条留作唯一 gold standard，后续任何 RLVR/SFT/DPO 版本都在同一份上打分，保证可比。

### 1.1 两个新指标体系：RER（Relative Event Return = 标的累计收益） + 长窗口 T+15/30/60

> **你最新要求的落地**：除了看**相对基准的超额收益 CAR**（累计超额收益），还要看**事件发生后该标的自身的累计收益**——把"同一个标的在事件发生后的实际赚/亏了多少"也作为**独立、正交**的一套度量，不再只有 CAR 一条。并且窗口不局限于短期 T1/T3/T7，要在 **T+3 / T+7 / T+15 / T+30 / T+60** 五个 horizon 上同时打印 **ACC / CAR / RER** 三指标，防止模型靠"β 撑着、α 其实是负的"这种假信号过拟合。

#### (A) 长 horizons 评估面板：H = {t3, t7, t15, t30, t60}

`labeller.py` [labeller.py:L823](file:///workspace/backend/app/event_backtest/labeller.py#L823) 已在 download 窗口预留 **T+15 / T+30 / T+60** 的全套列（分别约 11 / 22 / 42 交易日）：
- `ret_tXX` = **标的自身累计收益 = 本节定义的 RER_tXX**（不扣 benchmark，就是你要的"同一标的事件后的累积收益"）
- `bm_ret_tXX` = 基准指数累计收益
- `car_tXX` = 标的相对基准的超额收益（CAR = 原来的口径）
- `label_tXX` = 按 CAR 的三分类方向（up / neutral / down）

**训练**仍按 §2.4 的 primary horizon（t1/t3/t7 之一）给 R1/R2/R3 reward；**评估**则强制在 {t3,t7,t15,t30,t60} 5 栏完整打印三指标，并加**两层一致性门禁**（见 §5.4）：
- **短期一致性**：primary 对 → t3 & t7 方向都对的样本比例（即旧 dual_window_hit_rate）
- **长短一致性（新增）**：t7 方向对 → t30 方向也对的样本比例（防"T7 脉冲 → T30 回吐"类过拟合）

#### (B) RER（Relative Event Return = 标的事件后累计收益）的三层正交解读

你定义的 RER = "同一标的在事件后的累计收益" = `ret_tXX`（labeller.py 已经在写）。为了在评估/奖励里能**辩证地用**，我们把它和 CAR / bm_ret 叠成三层正交度量，每一层都只回答一个明确的问题：

| 层 | 公式（每个 horizon h） | 回答的问题 | 为什么要正交于 CAR |
|---|---|---|---|
| **L1：RER_h = ret_tXX** | 标的自身累计收益（= 你定义的 RER） | "买这个股票，这个事件发生后，**绝对赚了多少**？" | 实战最直观的问法；不扣 benchmark，不做市场模型——拿了多少就是多少。 |
| **L2：CAR_h = ret_tXX − bm_ret_tXX**（现有口径不变） | 相对基准指数的累计超额收益 | "赚的部分里，是**跑赢/跑输大盘**还是只是跟着 β 走？" | 区分 α 与 β；RER>0 但 CAR<0 = 股价涨了但没跑得过指数（=事件其实没贡献 alpha）。 |
| **L3：BM_h = bm_ret_tXX** | 同期基准指数收益 | "这个事件窗口里，**大环境是涨/跌**？"（β 因子面板） | 做分场景解释用；比如 CN 降息（t1 事件）RER 为负，是不是因为当天大环境跌了、其实 CAR 是正的？ |

**三层的天然正交约束**：RER ≡ CAR + BM。任何 rollout 的方向判断如果出现「RER_t7 方向 up 但 CAR_t7 方向 down」（= RER 全靠大盘 β 撑，α 为负），**就算模型方向对了（按 primary CAR），R3 reward 也要打 0.75 折扣**（见 §4.2 R3 的"RER↔CAR 不一致惩罚"），同时 §5 评估单独打印这类样本的比例。

#### (C) labels schema 新增字段（只写附加层，不删原字段；§6 路线图有对应脚本）

在每条 `labels.jsonl` 上，除了已有的 `car_t1/3/5/7/15/30/60` + `label_t1/3/5/7/15/30/60`，**再显式把同一标的的 RER（即 ret）拉平到同一层命名体系，方便训练/评估直接读**：

```json
{
  "car_t15":  0.0182, "car_t30": 0.0201, "car_t60": 0.0094,
  "label_t15": "up",  "label_t30": "up", "label_t60": "up",

  "rer_t1":   0.0031, "rer_t3":  0.0084, "rer_t7":  0.0157,
  "rer_t15":  0.0215, "rer_t30": 0.0248, "rer_t60": 0.0143,
  "bm_t15":   0.0033, "bm_t30":  0.0047, "bm_t60":  0.0049,

  "horizons_complete": 1,
  "rer_car_agree_t7":  1,
  "rer_car_agree_t30": 1
}
```

说明（都由 `build_rer_metrics.py` 离线一次性算出，训练/推理不在线算）：
- `rer_tXX` = `ret_tXX`（标的累计收益，= 本节你定义的 RER）
- `bm_tXX` = 同期基准累计收益（β 面板，解释用）
- `horizons_complete` = 5 个评估 horizon（t3/t7/t15/t30/t60）非空=1，缺失>0=0（1000 条评估集里大概会有 2~5% 最尾部 2026-06 的事件缺 t60，要在 §5 统计里显式剔除）
- `rer_car_agree_tXX` = sgn(RER_tXX) 与 sgn(CAR_tXX) 是否同号（含 epsilon=0.005 中性容错）——R3 奖励与 §5 过线门禁直接读这个 flag，不需要再现场算。

---

## 2. 训练数据准备（RLVR 训练集）

### 2.1 数据规模：**5000 条**（推荐起步）

为什么是 5000 而不是更多/更少：

| 量级 | 优劣分析 |
|---|---|
| 1000 条（和评估集同量） | ❌ RLVR 需要 rollout 多轮采样，1000 条 5-fold 后每 fold train 仅 800，PPO/GRPO 极易过拟合 |
| **5000 条（推荐）** | ✅ 5× 于评估集，5-fold 后每 fold train≈4000，PPO 每轮可 batch 采样 128~256 条，跑 20~30 轮不重样 |
| 10000 条 | ⚠️ 可做但数据构造/打标签成本翻倍；建议先 5000 验证 RLVR 有效再扩 |

### 2.2 分布约束（与评估集**严格同分布**）

训练集的 **market × event_type_l2 分层比例** 必须和 1000 条评估集完全一致（差异 ≤ 1%），用 `stable_stratified_split_ids` 同款分层器做构造时的配额控制：

| 分层（market × L2） | 评估集数量 | 训练集配额（5000） |
|---|---|---|
| CN·并购/分拆/再融资 | 154 | **770** |
| CN·财报超预期/不及预期 | 154 | **770** |
| CN·公司指引上调/下调 | 98 | **490** |
| CN·政策利率调整 | 98 | **490** |
| CN·增长/就业数据意外 | 98 | **490** |
| CN·通胀数据意外 | 98 | **490** |
| US·并购/分拆/再融资 | 66 | **330** |
| US·财报超预期/不及预期 | 66 | **330** |
| US·公司指引上调/下调 | 42 | **210** |
| US·政策利率调整 | 42 | **210** |
| US·增长/就业数据意外 | 42 | **210** |
| US·通胀数据意外 | 42 | **210** |
| **合计** | **1000** | **5000** |

额外分布控制：
- **时间分布**：同样按评估集的年月采样（Q1 财报季/政策月略多，2/5/8/11 清淡月略少），**不允许出现 2026-06-22 之后**（评估集终点）的事件。
- **标签分布**：`label_avg_all` 的 up/down/neutral 比例应 ≈ 40% / 47% / 13%（评估集比例），允许 ±3% 波动。
- **CAR 幅度分布**：|car_avg_all|>0.5% 的样本占比 ≈ 87%，>1% ≈ 77%。

### 2.4 核心新逻辑：Market × EventType × Horizon 三维定向匹配（不再一刀切 avg_all）

> **问题根源**：原方案一律用 `label_avg_all`（7 个 horizon 加权平均）做 oracle 方向，等于"长期/短期所有窗口加总"—— 宏观政策事件明明是**隔夜定价**、并购重组效应明明**集中在 5~7 日扩散**，平均后反而把最强信号稀释在一堆无关 horizon 的噪声里。
> **定量验证**（1000 条评估集）：把 oracle 从"avg_all"换成"按场景定向选择的主 horizon label"后，**全局 oracle 对主horizon 真值的命中率从 72.3% → 100.0%，提升 +27.7pp**。12 个场景全部正向提升（最少 +10pp、最多 +44pp）。

因此训练目标、Reward、评估指标 **全部按场景定向到对应的"主时间窗口"**，不再对所有事件套用单一 `avg_all`。

#### 2.4.1 三维匹配矩阵（12 个场景逐一规则化 + 数据验证 + 5-horizon 评估面板）

匹配原则 = **事件生效窗口常识 + 该 horizon 的 |CAR| 峰值位置**（数据验证见附录定量实验）。下方表格按「**训练 primary** + **R3 双窗校验 secondary** + **评估 5 栏面板 {t3,t7,t15,t30,t60}**」三栏明确拆分开：

| Market | EventType L2 | **主时间桶** | **Primary H（训练/R1/R2/R3 方向用）** | **Secondary H（R3 双窗校验用）** | **评估面板（§5 强制打印：ACC/CAR/RER 三指标 × 5 栏）** | 匹配理由 |
|---|---|---|---|---|---|---|
| CN | 并购/分拆/再融资 | 中期 (2w内) | **car_t7** | car_t5 | {t3, **t7**, t15, t30, t60} | 并购吸收/再融资效应 +5~7 日扩散最集中；t15/t30 看并购完成节奏（是否长端反转） |
| CN | 财报超预期/不及预期 | 短期 (1w内) | **car_t3** | car_t5 | {**t3**, t7, t15, t30, t60} | 财报 + 集合竞价 + 2 日盘内消化，t3 为峰值；t30 看超预期是否兑现（避免"财报脉冲 / 季度回吐"假信号） |
| CN | 公司指引上调/下调 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | 盘前公告 → 隔夜集合竞价一步定价完成；T30 看指引是否被业绩验证 |
| CN | 政策利率调整 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | 降息/加息消息即期定价；t15/t30 看经济数据反馈是否证伪 |
| CN | 增长/就业数据意外 | 隔夜型 | **car_t1** | car_t5 | {t3, t7, t15, t30, t60} | 数据公布即期定价 + 5 日窗口持续传导；t30 看政策二次博弈 |
| CN | 通胀数据意外 | 短期 (1w内) | **car_t3** | car_t5 | {**t3**, t7, t15, t30, t60} | CPI/PPI → 政策预期 2-3 日传导；t30 看货币政策是否落地 |
| US | 并购/分拆/再融资 | 中期 (2w内) | **car_t7** | car_t5 | {t3, **t7**, t15, t30, t60} | tender 期限 + 监管博弈 5-7 日集中；t60 看 DOJ/FTC 审批路径 |
| US | 财报超预期/不及预期 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | 盘后财报 → +1 日 AH 集中一步定价；t30 看回购/指引联合定价 |
| US | 公司指引上调/下调 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | US 指引通常与财报同步盘后发布；t30 看 EPS 是否兑现指引 |
| US | 政策利率调整 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | FOMC 决议即期定价；后续交易日只做回吐；t30 看点阵图二次定价 |
| US | 增长/就业数据意外 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | 非农/NFP 即期定价；t30 看 Fed 是否因数据改变路径 |
| US | 通胀数据意外 | 隔夜型 | **car_t1** | car_t3 | {t3, t7, t15, t30, t60} | CPI/PCE 即期定价；t30 看 FOMC 对应决策是否已 price-in |

> **一致通过的定量基准**：上表 12 条场景规则中，**定向 oracle vs 主 horizon 真值的命中率在每个场景均 ≥ 90%**（详见 1000 条评估集验证：全场景均为 100%），且全部优于 `avg_all` 口径。训练/评估时任何事件都先查表确定 primary/secondary，再读取对应的 `car_XX` / `label_XX` / `rer_XX` / `bm_XX`。

#### 2.4.2 数据构造脚本输出的附加字段（含 5-horizon 评估面板与 RER 预计算标志）

Step 2 打 Oracle 标签时，在每条 `labels.jsonl` 中**额外附加 6 个字段**（方便训练/评估直接读取，不必运行时查表；其中 horizons 面板和 RER 字段与 §1.1(C) 的 schema 一致）：
```json
{
  "scene_primary_horizon": "t3",
  "scene_secondary_horizon": "t5",
  "scene_time_bucket": "短期(1w内)",
  "eval_horizons_panel": ["t3","t7","t15","t30","t60"],
  "scene_oracle_kind": "CAR",
  "scene_rer_oracle_kind": "RER（仅评估打印/R3 惩罚；不替代训练方向）"
}
```
前 3 个字段 = 匹配矩阵按 (market, event_type_l2) 直接写入；**后 3 个字段**是这次新增的：
- `eval_horizons_panel` = 这条事件对应的 5 个评估 horizon 顺序（确保 1000 条打印出来的 5 栏对齐，不同事件的面板顺序一致，不允许乱序）。
- `scene_oracle_kind = "CAR"`：训练方向 oracle 的来源 = primary horizon 的 CAR（即 `label_{primary}`），**不因为有了 RER 就改训练方向**——RER 是**同一标的累计收益**，与大盘 β 强耦合；如果把 RER 作为方向 oracle，会把「大环境 β 涨跌」也当成「事件 α 正确」喂给模型，等于又回到了"平均后信号稀释"的老路。
- `scene_rer_oracle_kind = "RER（正交报告）"`：RER 的作用是**与 CAR 正交报告**——在 §5 评估面板里把 5 horizons 的 (ACC_CAR, ACC_RER, CAR_mean, RER_mean) 四值同时打印；在 §4.2 R3 里如果 RER↔CAR 方向不一致（sgn(RER)≠sgn(CAR)），就**按 0.75 折扣打 R3 reward**，但**不改变方向对错**的判定（R1/R2 仍以 CAR 为准）。

训练/评估代码里：
- oracle 方向 = `r['label_' + r['scene_primary_horizon']]`（按 CAR，不变）
- oracle 连续值 = `r['car_' + r['scene_primary_horizon']]`
- R3 附加安全阀用 = `r['rer_' + primary]`、`r['rer_' + 't30']`、以及 `r['rer_car_agree_' + primary]`

#### 2.4.3 "辩证看待"：三组 CAR 口径 + RER 正交面板（4 组并行）

你强调"所有指标都要辩证看"，因此**训练 reward 只按①定向 primary CAR**（避免信号被 β/同类事件均值稀释），但**评估时同时打印**「3 组 CAR 口径 + 1 组 RER 正交面板」共 **4 组**全景判断：

| 口径 | 含义 | 报告位置 | 是否参与过线 |
|---|---|---|---|
| ① **定向 strict（CAR，primary）** | 按场景主 horizon 的 label 算 ACC（真正的训练目标） | 主指标列 | ✅ **过线核心判据** |
| ② **avg_all strict（CAR）** | 与 SFT/DPO 基线完全同款口径（7 horizon 平均） | 对比列 | 报告即可，不卡死 |
| ③ **双窗一致率（CAR） + 长短一致率（CAR）** | 双窗 = primary + secondary 同对比例；长短 = t7 对 → t30 也对的比例 | 过线附加判据 | ✅ 双窗 ≥ 61%；长短 ≥ 52%（组合门禁 1/7） |
| **④ RER 正交 5 栏面板（同一标的累计收益）** | 对每个 h∈{t3,t7,t15,t30,t60}：ACC(label_RER_h vs 模型方向)、mean(RER_h)、P(RER > 0)、RER↔CAR 同号率 | 新增 §5 第七大类 + §5 所有分桶 3 指标扩展 | ✅ 组合门禁新增 2 条：t7 RER↔CAR 同号率 ≥ 80%；t30 同号率 ≥ 75%（说明"方向收益真的来自事件定价，不是靠 β 撑着"） |

四组口径都要打分、都要出分桶、都要报告 Wilson CI，最终结论辩证综合——但**方向对不对、训练 reward 给不给**，只认①定向 primary CAR。

### 2.5 训练集构造方式（原 §2.3 顺延编号）

**三步走**，避免 event_id 与评估集重叠：

#### Step 1：扩展事件池（按配额捞取）
复用 `scripts/build_real_datasets_from_v9.py` / `labeller.py` 的管线：
1. 按 12 个分层各自随机抽取 5.2× 配额的原始事件（多抽 20% 留作后续清洗剔除）。
2. **严格去重**：与 `events_cn_us_1000_v1.jsonl` 做 `event_id` / `(market, symbol, event_time, title[:20])` 双重去重，确保评估集样本零泄露。
3. 清洗：丢弃 event_text 为模板占位符（README 已指出的宏观类占位问题）的样本。

#### Step 2：打 Oracle 标签（与评估集同口径）
用 [labeller.py](file:///workspace/backend/app/event_backtest/labeller.py) 的多 horizon CAR 计算 + avgCAR 加权，产出：
- `car_avg_all` / `label_avg_all` / `label_consensus66` / `sig_t3` 等全套字段
- 格式与 `labels_cn_us_1000_v1.jsonl` 完全对齐

#### Step 3：写盘 + 注册
产出：
```
data/rlvr_train_v1_5000/
├── events.jsonl       # 5000 条，字段同评估集 events
├── labels.jsonl       # 5000 条，字段同评估集 labels
└── distribution.json  # 分布自检报告（market/L2/年月/标签/CAR分位数）
```

并复用 [train_pronoia_v2.py:L48-L88](file:///workspace/backend/scripts/train_pronoia_v2.py#L48-L88) 的 `stable_stratified_split_ids` 做 5-fold split（按 market×L2×ym 分层），产出：
```
data/_rlvr_artifacts_v1/folds_rlvr_5000/
├── fold0/ (sft_train.jsonl, rlvr_train.jsonl, sft_test.jsonl, ids.json)
├── fold1/
└── ...
```

---

## 3. 模型方案

### 3.1 模型大小：**Qwen3-8B（起步） + LoRA**

| 模型规格 | 适用场景 | 显存（单卡 A100 80G） | 训练吞吐 | 结论 |
|---|---|---|---|---|
| **Qwen3-8B-Instruct + LoRA r=16** | RLVR 起步，中文金融语义理解优于 Llama | ≈32G（bf16 + LoRA + GRPO optimizer） | batch=128 seq=2048 ≈ 2.5h/epoch | ✅ **起步首选** |
| Qwen3-72B-Instruct + QLoRA 4bit | 如果 8B 的 ACC Wilson 下限仍 <70% 再考虑 | ≈60G | 约 8B 的 1/5~1/6 | ⚠️ 后续升级项 |
| 自研 <2B 小模型蒸馏 | 部署端到端低延迟 | 低 | 高 | ❌ 先不搞，SFT/Reward 模型都还没稳 |

**为什么选 Qwen3-8B**：
- **中文金融语料覆盖更好**：Qwen3 在 A 股公告、政策文件、研报类中文文本上的分词/语义理解显著优于 Llama-3.1，正好匹配本任务 70% CN 样本的分布。
- **复用现有管线**：现有 SFT 脚手架 [train_pronoia_v2.py:L143-L144](file:///workspace/backend/scripts/train_pronoia_v2.py#L143-L144) 的 LoRA r=16 配置、trl/peft 接口完全兼容，只改 `model_name` 一行。RLVR 阶段直接加载 SFT 的 LoRA 做 warm start。
- **长上下文足够**：推理链 5 段 + 最终方向 ≈ 600~800 tokens，加上 input block 1500 tokens，总 seq ≤ 2048，Qwen3-8B 128k ctx 轻松容纳。
- **主要瓶颈不在参数量**：rollout 采样（4 条/event）+ reward 计算的 batch 吞吐是 GRPO 训练的真正瓶颈，8B vs 72B 差异在模型能力而非速度。

### 3.2 LoRA + MoE 专家配置（单体方案就是 K=6 的轻量 MoE）

> **架构升级（你最新要求）**：Pronoia-RLVR v1 **不再是单体重 LoRA**，而是「**Qwen3-8B 共享基座 + K=6 场景专家 LoRA + 3 信号可解释 Router**」的**内置 MoE 架构**。MoE 不在 v2 附录里做，就放在 v1 主方案里；所有专家共享同一份 Qwen3-8B 基座权重，仅用 LoRA 低秩（r=16）做场景差异化，总参数量增加 ≤ 1.2%。

LoRA 配置（每个专家单独一份，但超参完全一致）：
```python
LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],  # 8B 全 MLP + Attn
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
```

K=6 专家定义（每个专家 = 1 份 LoRA + 对应场景训练集）：
| expert_id | 覆盖场景（market, time_bucket） | event_type_l2 偏好 | 训练样本数（≈5000 总配额） | 擅长方向 |
|---|---|---|---|---|
| `e_cn_overnight` | CN × 隔夜型 | preann（业绩预告）、macro（宏观数据） | ≈ 650 | 事件当隔夜消化干净的 CN 短事件 |
| `e_cn_short` | CN × 短期型 | earnings、buyback、policy | ≈ 1600（CN 主） | 5 天内完成定价的 CN 财报/回购/政策 |
| `e_cn_mid` | CN × 中期型 | M&A / 重组 | ≈ 350 | 7 天左右才扩散完的 CN 并购 |
| `e_us_overnight` | US × 隔夜型 | earnings、guidance、FDA、Fed/macro | ≈ 1300 | 美股盘后/转天隔夜即定价的 4 类 |
| `e_us_short` | US × 短期型 | M&A/buyback/corporate、company_news | ≈ 950 | 美股 3-5 天定价的公司行为/新闻 |
| `e_volume_regime` | Market × ALL × volume HI/LOW（**量价专家**） | 全 L2，只在 volume 偏离阈值时高权重 | ≈ 150（+ 其它每个专家掺 15%） | 「量价偏离」「放量突破」「缩量横盘」场景 |

**为什么 K=6（而不是更多）**：保持简洁 elegant；每个专家样本数 ≥ 350，在 RFT + GRPO 下不至于欠拟合。e_volume_regime 是**全局跨市场专家**，专门做「量与价不一致、该怎么校准方向判断」的工作——直接回应你"光考虑价没考虑量也是个问题"。

#### 3.2.1 轻量 Router（3 信号 O(1) 查表+softmax，无训练参数）
Pronoia-RLVR v1 的 MoE 刻意简洁：**不引入 MixLoRA/Switch Transformer 的 router weights**，router 仅用 3 个 as-of 信号做 12 行查表代码（训练/推理一致、可复现、可审计）：

```python
# scene_match.py 的 router(market, event_type_l2, H_primary, vol_regime)
# vol_regime = "HI"（vol_t0_ratio>2.0 或 vol_pre5_ratio>1.5）/ "LOW"（<0.5）/ "NORMAL"
def route(market, event_type_l2, H_primary, vol_regime, time_bucket):
    base = {e_cn_overnight:0.05, e_cn_short:0.05, e_cn_mid:0.05,
            e_us_overnight:0.05, e_us_short:0.05, e_volume_regime:0.05}
    # ① 场景先验（匹配哪个专家，给大头 0.55）
    exp_id = _scene_to_expert[market, time_bucket]     # 上表 lookup
    base[exp_id] += 0.55
    # ② Volume regime 增量（HI/LOW 时给量价专家 +0.25）
    if vol_regime in ("HI", "LOW"):
        base[e_volume_regime] += 0.25
    # ③ Dirichlet 平滑 softmax（α=0.3，给冷门专家保底）
    return dirichlet_softmax(base, α=0.3)   # 总和=1 的专家权重
```
每个 rollout 不是"选一个专家"而是"6 个专家各自出推理链，再按 router 权重加权融合方向与 confidence"——实现你要的"动态融合不同市场/事件/时效，同时考虑量价"。

#### 3.2.2 基本面量价 skill：`volume_regime_analyzer`（新增 Tier 2 skill / tool）
你要的「把量的信息补到基本面里面，增加 skill / tool」**就放在这里**，同时服务 Team Pipeline + RLVR input block。

| 维度 | 说明（as-of T0，**严格未来不可见**） | 数值口径 |
|---|---|---|
| `vol_t0_ratio` | 当日成交量 / 过去 20 日平均成交量 | ≥2.0 → HI；≤0.5 → LOW |
| `vol_pre5_ratio` | pre5（事件前 5 日）平均成交量 / 20 日均量 | ≥1.5 → HI；≤0.7 → LOW |
| `price_vol_diverge` | pre5 价涨但量跌（或价跌量涨）的背离信号 | {-1,0,+1} |
| `range_t0_normalized` | (当日最高-最低) / 20 日真实波幅均值 | ≥1.5 → 高波动 regime |

Team Pipeline 接入：在 [roster.py](file:///workspace/backend/app/agents/roster.py) 中 predictor / deep_researcher 的 skill 列表都加 `volume_regime_analyzer`（取代之前只靠 `market_research` 取 OHLCV 的间接方式），并在 deep_researcher 解读卡片的「事实 → 比较 → 反方/限制」模板里明确**必须引用至少 1 条量价 regime 数字**。
RLVR 训练直接读取 backtesting events.jsonl 中预处理好的上述 4 维字段——等价于**推理时 Team 把这个 skill 的输出预先灌进 INPUT BLOCK**。


### 3.3 推理链作用于哪里（关键设计）

#### 3.3.1 总体思路：推理链 = "【0. 预判窗口】+ 5 段 CoT"，先定"看多长"再判方向

> 呼应你的核心观点：**先分场景定时间窗口（隔夜/短期/中期/长期），再在这个窗口内谈方向对错**——推理链必须把"看什么 horizon"显式写出来，模型不能再"猜一个模糊的大方向"。

```
┌─────────────────────────────────────────────────────────────┐
│  INPUT BLOCK（固定，严格 as-of T0，不可见未来信息）           │
│  • event_id / market / symbol / event_time / event_type_l2  │
│  • title + event_text（截断到 ≤ 1500 chars）                  │
│  • 【STRICT AS-OF 价】T0 当日涨跌 / pre5 漂移（若可用）       │
│  • 【STRICT AS-OF 量 — 新增 §3.2.2 volume_regime_analyzer】   │
│    - vol_t0_ratio = 当日量 / 20日均量   vol_pre5_ratio        │
│    - price_vol_diverge {-1,0,+1}        range_t0_normalized  │
│    - vol_regime ∈ {HI, NORMAL, LOW}（上面 4 维打桶）           │
│  • benchmark 名称                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ 3.2.1 Router（3 信号查表：场景+horizon+vol_regime）
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  K=6 MoE EXPERTS（并行 rollout，每专家 4 条：4×6=24 条总）    │
│  每个专家各自输出 6 段推理链 + dir_final（one-hot up/dn/neu） │
│  + conf_i （每个专家给一个置信度）                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ 按 w_i = router(...) 加权融合最终判断
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  CHAIN-OF-THOUGHT BLOCK（主输出 = winner 专家 chain）         │
│  格式：中文分段标签，共 7 段（在原 6 段基础上新增【0.5】量价段） │
│                                                               │
│  【0. 预判时间窗口】≤80字（原逻辑保留）                        │
│  【0.5 量价 regime 校验】≤80字（**新增，必须提§3.2.2 四个数**） │
│    例："T0 量比 2.4（HI 放量），pre5 量比 1.7；价+3.2%且价量同向"│
│    例："T0 量比 0.4（LOW 缩量），pre5 价-1.8%但量增 → 背离信号" │
│                                                               │
│  【1. 关键信号提取】≤240字（要求至少 1 条量价 regime 佐证）      │
│    例："①营收+12% YoY；②T0 量比 2.4（放量确认）；③北向净买+1.2亿│
│  【2. 横向比较】≤150字（保留）                                 │
│  【3. 反方与限制】≤150字（保留；新增 1 条量价反方可选）         │
│  【4. 置信度校准】≤100字（保留）                                │
│  【5. 最终方向】one line：up/down/neutral + 主horizon XX + 融合来源
│    例："up（按主horizon t3 判定；主专家 e_cn_short 0.65 + e_volume_regime 0.25）"
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  REWARD COMPUTATION（按 §2.4 primary oracle + §4.x 量价校准）│
│  • R0 窗口合规 + R0.5 量价段合规（新增）= 两项规则检查        │
│  • R1 方向正确性（融合方向 vs label_primary）                 │
│  • R2 置信度校准（按 car_primary × κ_vol 辩证乘子）            │
│  • R3 CAR 幅度 + 双窗一致 + Volume regime 校准（κ_vol）       │
│  • R4 推理链一致性（7 段检查：含【0.5】量价段合规 + 主专家标注）│
│  • R5 专家熵正则（新增，MoE 分工均衡：防止喂 1-2 个专家）       │
└─────────────────────────────────────────────────────────────┘
```

#### 3.3.2 推理链与现有 Team Pipeline 的映射关系

RLVR 训练的模型本质上是一个 **"K=6 轻量 MoE 方向判别器"**，对应 team pipeline 中多段角色的融合（新增【0.】时间窗口判定 + 新增【0.5】量价 regime 校验 = 两个 Tier 2 skill）：

| RLVR 推理链分段 | 对应 Team Pipeline 中的角色 | 说明 |
|---|---|---|
| **【0. 预判时间窗口】** | `horizon_select`（Tier 2 skill） | 对应 §2.4 三维匹配矩阵：先定"该看多长"，再判方向 |
| **【0.5 量价 regime 校验】（新增）** | `volume_regime_analyzer`（**新增 Tier 2 skill / tool**，§3.2.2） | 把成交量/波动率/价量背离 **补进基本面研究**，在事实/比较/反方各环节都必须引用 |
| 【1. 关键信号提取】 | `announcement_classifier` + `market_research` + 新 `volume_regime_analyzer` | 要求 ≥1 条量价佐证（不再光写营收/利润，必须有放量/缩量/背离信号之一） |
| 【2. 横向比较】 | Tier 2 `ar_decomposer` / `drift_context_analyzer` / `volume_regime_analyzer` | AR 分解、漂移出尽系数 + 量价 regime 对比 |
| 【3. 反方与限制】 | deep_researcher 的 Claim 生成 | 至少 1 条反方可来自量价维度（例："pre5 量缩价涨 → 假突破"） |
| 【4. 置信度校准】 | synthesize analyzer_scorecard.confidence | 置信度受 κ_vol（价量同向/背离）乘子校准（§4.2 R2） |
| 【5. 最终方向】 | router synthesize `【最终方向】`（+ MoE 融合权重标注） | 融合的主专家、量价专家权重都写明，保证推理链可审计 |
| **（路由层，模型内部）** | K=6 LoRA MoE + 3 信号 Router（§3.2.1） | 无训练参数，12 行查表代码；训练/推理一致 |

#### 3.3.3 【0.】+【0.5】两段的训练对齐机制（关键）

【0.】输出的主 horizon **必须与 §2.4 匹配表中该 (market, event_type_l2) 的值完全一致**——不允许模型自由发挥定窗口。
- 换句话说，【0.】在训练时不是"让模型学"的，而是**按 (market, event_type_l2) 强约束**（R4 一致性检查里包含这一条）。
- 为什么还要模型显式写出来？因为这样推理链**自包含语义**：人类审阅/后验诊断时不用查表，就能一眼看到"这条判断是针对什么时间窗口的"，符合"可审计推理链"的初衷。
- 一旦 §2.4 的匹配表后续迭代（比如新增 event_type_l3 或 market 子分类），先更新匹配表 → 重写数据构造脚本的 3 个字段 → 重新训练；不需要动模型模板。

【0.5】量价段同样按 **INPUT BLOCK 里的 4 维量价特征强约束**（R0.5 + R4 检查）：
- 必须完整引用 `vol_t0_ratio / vol_pre5_ratio / price_vol_diverge / range_t0_normalized` 的具体数值（或至少 2 个），不许只写"放量/缩量"。
- `price_vol_diverge` 的符号必须与事实一致（价涨量增 → +1；价涨量缩 → -1）。
- 在 Team 里，`volume_regime_analyzer` 这个 Tier 2 skill 就是专门生产这 4 个数的；RLVR 训练时直接从 events.jsonl 里读 as-of 预处理好的值，等于直接让这条推理链对这个 skill 的输出负责——把"量"完全补进了基本面链路。

**⚠️ 关键决策：RLVR 模型是否包含 tool call？**  
第一版 **不包含 tool call 机制**（但在 Team 里会把 `volume_regime_analyzer` 作为 Tier 2 skill 先预灌好 as-of 数值给 RLVR）。原因：
1. RL with tool call（即多轮 function call 的 PPO）sample efficiency 极低，5000 条不够塞牙缝。
2. STRICT AS-OF 模式下 volume_regime_analyzer 能拿到的只有 T0/pre5 量价，这些直接拼进 INPUT BLOCK 即可，不需要动态调。
3. 先把"纯文本 + 预灌量价/漂移/horizon → K=6 推理链 → 融合方向"这条链路跑通，后续再加 tool call。

#### 3.3.4 推理链的输出如何在推理时接入 Team Pipeline

训练完成后，RLVR 模型作为 **Tier 1.5 分析器** 插入：
```
原 pipeline：Tier 1 analyzer → synthesize → verify
新 pipeline：Tier 1 analyzer ──┐
                               ├→ RLVR 推理链模型（加权投票）→ synthesize → verify
             event_text+T0 ────┘
```

具体来说，在 [team.py:L691-L744](file:///workspace/backend/app/agents/team.py#L691-L744) 的 `_route_signals` 之后、`analyzer_context` 之前，加一段：
```python
rlvr_result = await run_rlvr_predictor(event_meta, as_of_packet)  # 新函数
# rlvr_result = {"chain": "...5 段推理链...", "direction": "up", "confidence": 0.78}
```
然后把 RLVR 的 direction + confidence + 完整推理链也注入 `analyzer_context`，让 router synthesize 时同时参考 Tier 1 analyzer 和 RLVR 两个信号。

---

## 4. RLVR 训练算法与 Reward 设计

### 4.1 算法选择：**GRPO（Group Relative Policy Optimization）**

为什么选 GRPO 而不是 PPO / DPO / RLHF：

| 算法 | 优点 | 缺点 | 适合度 |
|---|---|---|---|
| **GRPO** | 无需 critic 网络（省显存省训练时间），用 group 内相对优势做 baseline；对小模型 + 小 batch 更稳 | 需要 group 内多条 rollout 采样（通常 4~8 条/event） | ✅ **首选** |
| PPO | 经典稳定，工业界成熟 | 需要 critic 网络 + GAE，调参复杂，显存大 | ⚠️ GRPO 不收敛再 fallback |
| DPO | 简单，不需要 online sampling | 离线 pairs 静态，没有连续 reward 信号 | ❌ 已是现状，RLVR 要超越它 |
| RLHF（人类偏好） | reward 质量高 | 金融场景人类标注贵、慢、一致性差 | ❌ 我们有 Oracle CAR，不需要人肉 |

**GRPO 关键超参（起步）**：
```
num_rollouts_per_event = 4    # 每个 event 采样 4 条不同推理链（决定 group 大小）
per_device_train_batch_size = 2
gradient_accumulation_steps = 16  # → global batch = 2*16*4(tensor_parallel) = 128
learning_rate = 1e-6           # SFT 是 2e-4，RLVR 要小一个量级以上
beta = 0.04                    # KL 惩罚系数（防止策略偏离 SFT 基座太远）
max_prompt_length = 1536
max_completion_length = 800    # 推理链 5 段 + 最终方向 ≈ 600~800 tokens
num_train_epochs = 4
```

### 4.2 Reward 函数（七元加权：MoE + 量价 + RER 三层 + 主方向三位一体，总范围 [-1.60, +2.16]）

> **核心变更 1（MoE + 量价进 RLVR v1 本体）**：Oracle 的方向真值 + CAR 幅度真值按 §2.4 匹配表的 `{scene_primary_horizon}` 取；方向是 K=6 专家推理链的融合方向（不是单一专家的）；**R2/R3 新增 Volume regime 辩证乘子 κ_vol**（量价背离时给正确方向的置信/幅度奖励打折，反过来对背离假信号/假突破不给出错前的满奖励）。
> **核心变更 2（训练两步走：先 RFT 单体专家，再小学习率 GRPO MoE）**：Reward 函数里新增 **R0.5**（【0.5】量价段合规检查）和 **R5**（MoE 专家熵正则），前者把量信息补进推理链合规，后者保证 K=6 专家不会被 Router 冷启动时全部堆到 1 个专家上。
> **核心变更 3（RER + 长 horizons 融合，这次新增）**：**RER = 同一标的在事件窗口内的累计收益（= ret_tXX，你定义的）** 不作为方向 oracle（避免把 β 涨跌当作正确方向），但作为 **R3 的 4 重辩证乘子** 融合进来：③ **RER↔CAR 不一致惩罚**（标的绝对赚了但相对基准没赢 = 方向全靠 β 撑，R3 ×0.75）；④ **长短一致性（t7 ↔ t30）惩罚**（短期 CAR 对，但长端同一标的收益反转 = 过拟合，R3 ×0.65）。再叠加原来的双窗安全阀 + 量价安全阀 = 一共 **四重安全阀**。

对一条 rollout（event → K=6 专家各出一条 7 段推理链 → 按 router( w_i ) 加权融合为最终 (dir, conf)），查表得到 H_primary / H_secondary 和 4 维量价字段 + RER 列，先定义 **κ_vol**（量价校准乘子，∈ [0.4, 1.2]，保留）：
```python
# κ_vol 核心想法：价量同向 → 奖励放 1.2 倍；价量背离 → 奖励打 0.4~0.6 折
# diverge=+1（价涨量增 / 价跌量缩）同向；0=无异；-1 背离
sign_car = +1 if oracle_car>0 else (-1 if oracle_car<0 else 0)
diverge_concur = (sign_car == price_vol_diverge) or (price_vol_diverge==0)
if   vol_regime == "HI"    and diverge_concur:  κ_vol = 1.20  # 放量确认，奖励放大
elif vol_regime == "NORMAL" and diverge_concur:  κ_vol = 1.00  # 基准
elif vol_regime == "LOW"   and diverge_concur:  κ_vol = 0.70  # 缩量但同向；可信度一般
elif price_vol_diverge != 0:                     κ_vol = 0.40  # 明确价量背离；奖励大打折
else:                                            κ_vol = 0.80  # 其它模糊情形
```
**再定义 2 个 RER 相关安全阀乘子**（值域独立，都只在"方向已经按 CAR 判对"时才起乘子作用，不改变方向对错）：
```python
# 安全阀3（这次新增）= RER↔CAR 不一致惩罚
# RER = 同一标的累计收益（你要的）；方向= primary horizon 上 sgn(RER) vs sgn(oracle_car)
rer_primary = row.get('rer_' + H_primary)
if   rer_primary is None:                                      η_rer = 1.00  # 缺失（极少数）；中立
elif (rer_primary * oracle_car) >= 0:                          η_rer = 1.00  # 同向（= RER 同一标的赚/亏方向与 CAR 超额一致 → 奖励不减）
else:                                                           η_rer = 0.75  # 不一致（标的绝对涨了但相对基准没赢 / 绝对跌了但跑赢基准 → 方向对但收益来源不纯，75 折）

# 安全阀4（这次新增）= 长短 horizon 反转惩罚（t7 方向 vs t30 方向，按 CAR）
# primary=t1/t3 的事件也强制看 t7 vs t30，避免"短期脉冲+长端回吐"
car_t7  = row.get('car_t7')
car_t30 = row.get('car_t30')
def _dir(x, eps=0.005):
    if x is None: return 0
    if x >  eps: return +1
    if x < -eps: return -1
    return 0
if car_t7 is None or car_t30 is None:                           η_long = 1.00
elif _dir(car_t7) == 0 or _dir(car_t30) == 0:                   η_long = 1.00
elif _dir(car_t7) == _dir(car_t30):                             η_long = 1.00  # 长短一致（不减）
else:                                                           η_long = 0.65  # 长短反转（典型过拟合形态，65 折）
```

总 reward = 0.04R0 + 0.04R0.5 + 0.50R1 + 0.27R2 + **0.13R3（×四重安全阀）** + 0.04R4 + 0.02R5（7 项，给量价/MoE/RER 权重腾空间，R1/R2/R3 占比保持 ≥ 0.9）。

#### R0：【0. 预判时间窗口】合规性（权重 0.04，范围 [-0.04, +0.04]）
- 【0.】段主 horizon 与匹配表一致 → +0.04；否则 −0.04。

#### R0.5：【0.5 量价 regime 校验】合规性（权重 0.04，范围 [-0.04, +0.04]，新增）
把"量补进基本面"作为 reward 直接对齐：
- 【0.5】段完整引用了 vol_t0_ratio / vol_pre5_ratio（至少 2 个具体数）且 price_vol_diverge 判定符号正确 → **+0.04**
- 只写"放量/缩量"不给具体比例；或符号错（价涨量缩说成同向）→ **−0.04**
- 同时要求【1. 关键信号提取】里至少有 1 处调用 volume_regime_analyzer 的数字/标签作为佐证（否则 R4 一并扣）。

#### R1：方向正确性（权重 0.50，范围 [-1, +1]）
Oracle = `label_{primary}`（按 CAR，不变；RER 不用作方向 oracle），融合方向（按 router w_i 对各专家的 up/down/neu one-hot 加权，argmax 得到 final_dir）：
```python
if oracle_dir == "neutral":
    R1 = +0.5 if final_dir == "neutral" else -0.5
else:
    if   final_dir == oracle_dir: R1 = +1.0
    elif final_dir == "neutral":  R1 = -0.5
    else:                         R1 = -1.0
```
*（并购 = label_t7；US 利率决议 = label_t1，按匹配表对齐。）*

#### R2：置信度校准 × κ_vol（权重 0.27，范围 [-0.27, +0.27]，原 0.3）
按 primary 方向/幅度生效，并乘量价校准乘子——价量背离时"模型说自己有信心"不算数：
```python
if oracle_dir != "neutral" and final_dir != "neutral":
    sign = +1.0 if final_dir == oracle_dir else -1.0
    ampl = min(1.0, abs(oracle_car) / 0.05)
    R2 = sign * (confidence - 0.5) * 0.6 * (0.5 + 0.5 * ampl) * κ_vol
else:
    R2 = 0.0
```

#### R3：CAR 幅度 × 四重安全阀（双窗 + 量价 + RER↔CAR 一致 + 长短一致，权重 0.13，范围 [0, +0.30]；乘子链最大 1.20）
```python
if (oracle_dir != "neutral") and (final_dir == oracle_dir):
    w_prim = min(1.0, max(0.0, (abs(oracle_car) - 0.005) / 0.045))
    base = 0.3 * w_prim

    # 安全阀1：双窗一致率（primary CAR 方向 × secondary CAR 方向必须同向才不减；否则 ×0.5）
    if secondary_car is not None and abs(secondary_car) >= 0.5 * abs(oracle_car):
        sec_dir = "up" if secondary_car > 0 else "down"
        if sec_dir != oracle_dir: base *= 0.5

    # 安全阀2：量价一致率 κ_vol（价量明显背离 = κ_vol<0.5 时 ×0.5；防止假突破/放量拉高出货）
    if κ_vol < 0.5:
        base *= 0.5

    # 安全阀3（这次新增）：RER↔CAR 同号率（同一标的累计收益方向 vs CAR 超额方向；不一致 ×0.75）
    base *= η_rer

    # 安全阀4（这次新增）：长短一致率 t7↔t30（CAR 短端对但长端反转 ×0.65；防止过拟合短期脉冲）
    base *= η_long

    R3 = base
else:
    R3 = 0.0
```
> **直观组合**：安全阀最坏情形 = 0.5（双窗反）× 0.5（量价背）× 0.75（RER↔CAR反）× 0.65（长短反） ≈ **×0.122**（R3 几乎不给分）。最好情形（全一致 + κ_vol=1.2 体现在 R2 之外）R3 可以接近满值 0.30。这就把"方向正确但收益来源不纯的样本"和"信号干净各层次一致的样本"在 reward 上拉开了显著差距。

#### R4：推理链一致性检查（权重 0.04，范围 [-0.04, +0.04]，改 7 段 + 新增 RER/长 horizon 合规）
1. 7 段标签齐全且顺序正确（【0.】【0.5】【1.】~【5.】）
2. 【0.】段主 horizon = 匹配表值；【0.5】段 4 维量价数值与 input block 值一致
3. 【1. 关键信号】≥2 个数字（其中 ≥1 个来自 volume_regime_analyzer 的 4 维）
4. 【5. 最终方向】值 = final_dir；置信度差 ≤0.05；**标注了主horizon + 融合来源（主专家 + 量价专家的权重）**
5. **（这次新增）** 如果模型在【5.】段提到"长期反转 / 长端兑现 / T+30 风险"等任何长 horizon 相关断言，该断言方向必须与 `car_t30` / `rer_t30` 的 sgn 一致（否则 R4 整体不通过）
6. 没有编造数字、编造 vol_t0_ratio / price_vol_diverge / rer_tXX

全部满足 → **+0.04**；任一违反 → **−0.04**。

#### R5：MoE 专家熵正则（权重 0.02，范围 [-0.02, +0.02]，新增）
训练中对每个 batch 统计 router 分布，专家分工太不均匀（基尼 > 0.6）就扣，鼓励把任务分散给 6 个专家：
```python
gini = gini_coef(batch_router_w.sum(0))   # 每个专家的被路由总和
if   gini < 0.45: R5 = +0.02
elif gini < 0.60: R5 =  0.00
else:             R5 = -0.02
```
*（R5 权重仅 2%：避免熵正则抢走主任务奖励。主要依靠 Router 的 Dirichlet 平滑 + 每个专家独立 RFT 预训练来保证分工）*

#### 总 Reward
```python
reward = 0.04*R0 + 0.04*R0.5 + 0.50*R1 + 0.27*R2 + 0.13*R3 + 0.04*R4 + 0.02*R5
```

**预期 reward 基准（随机）** ≈ 0.04×(-0.04) + 0.04×(-0.04) + 0 + 0 + 0 + 0.04×(-0.04) + 0 ≈ **−0.005**（R0/R0.5/R4 略负，R1 随机 0）  
**训练目标**：hold-out 平均 reward ≥ **+0.42**（相对上版 +0.02 上调，消化 R3 的两个新增安全阀大多数样本都是 1.0，不扣）  
**训练两步走**（MoE 专用）：
- Step1 RFT：每个专家单独在对应场景子样本上 SFT 1 epoch（warm start = 共用 SFT 基座 LoRA，r=16）
- Step2 GRPO MoE：lr=3e-7（比单体 1e-6 小），rollout=4/专家=24/event；batch=12 event（≈288 rollout）


---

## 5. 评估方案（固定 1000 条，辩证多口径：MoE + 量价 + 时间三维）

### 5.1 辩证评估原则：七组口径并行打分，过线核心判据是①

> 呼应你最新要求：RLVR v1 就是内置 K=6 MoE + 量价融合 + **RER（同一标的累计收益）+ 长 horizons T+15/30/60** 的方案，因此评估在原来的 primary/avg_all/双窗/过程/MoE/分桶 6 大类基础上，**新增 ⑦「RER + 长 horizons 正交面板」**，并在**所有分桶打印**里强制扩展 t3/t7/t15/t30/t60 5 栏（每栏 4 值 = ACC_CAR + ACC_RER + mean(CAR) + mean(RER)）。**任何单一口径都不做唯一判据**；Wilson 下限 + 组合门禁 **8 条**（见 5.4）才是过线标准。

### 5.2 训练过程中的评估（每 epoch 一次，七大类指标 × 5-horizon 面板）

沿用 [train_pronoia_v2.py:L172-L229](file:///workspace/backend/scripts/train_pronoia_v2.py#L172-L229) 的 `score-all` 同款逻辑，按 **12 Market×L2 × 4 TimeBucket × 3 VolumeBucket（HI/NORMAL/LOW）**三类交叉分桶，输出以下 **七大类**指标；并在每一类的每个分桶表格里，都**强制加 t3/t7/t15/t30/t60 5 栏**（事件 horizon 小于 30/60 时也照样出这两栏，读 labels.jsonl 预填的 rer_tXX / car_tXX 值即可）：

#### ① 定向主 horizon 口径（核心过线判据）
按 §2.4 匹配表的 label_{primary}（按 CAR）做 oracle；**括号里附"按 RER 同一标的累计收益的同名 ACC"作正交参考**（不参与主指标过线，但强制打印）。

| 指标 | 计算方式 | Pronoia-RLVR-MoE 过线目标 |
|---|---|---|
| `acc_primary_strict`（核心主指标，按 CAR） | MoE 融合 final_dir 与 `label_{primary}` 完全一致，neutral 算错 | **≥ 69%**（MoE 预期分场景加成）；**同样本按 RER 的 `acc_primary_strict_rer` ≥ 68%**（正交参考，不卡死） |
| `acc_primary_non_neutral`（按 CAR） | oracle∈{up,down} 时计分（实战口径） | **≥ 79%** |
| `wilson_lo_95_acc_primary_strict`（按 CAR） | Wilson 95% CI 下限（过线真正判据） | **≥ 66%** |

#### ② avg_all 口径（公平基线对比，不卡死）
保留与 DPO/SFT 基线完全同款的口径，保证跨模型可比；**t3/t7/t15/t30/t60 5 栏 mean CAR + mean RER 强制打印**：
| 指标 | 目标（报告即可，不硬卡） |
|---|---|
| `acc_avg_all_strict` | ≥ 66% |
| `acc_avg_all_non_neutral` | ≥ 76% |
| `wilson_lo_95_acc_avg_all_strict` | ≥ 63% |

#### ③ 时间一致性（双窗 + 长短双门禁 + 量价一致率，安全阀三类并行）
同时看 **short horizon 一致 + long horizon 一致 + 量价一致** 三层：
| 指标 | 计算方式 | 过线目标 |
|---|---|---|
| `dual_window_hit_rate`（双窗一致率，CAR primary×secondary） | primary 方向对 **且** secondary 方向也对的样本比例 | **≥ 61%**（组合门禁项） |
| **`t7_t30_hit_rate`（长短一致率，CAR，这次新增）** | car_t7 方向对 **且** car_t30 方向也对的样本比例（1000 条里剔除 t30 None 的尾部样本） | **≥ 52%**（组合门禁项：防"T7 脉冲 + T30 回吐"过拟合） |
| `across_bucket_consistency`（参考项） | primary 对 且 primary 桶内 t1/t3/t5 全对的比例 | ≥ 46%（参考，不卡死） |
| **`volume_price_hit_rate`（量价一致率，κ_vol≥1.0 样本）** | 量价同向样本（κ_vol≥1.0）里 primary strict 的比例 | **≥ 75%**（组合门禁项）。对应量价背离样本（κ_vol≤0.4）的 primary strict 也要单独打印（目标 ≥ 56%，不硬卡） |

#### ④ 过程质量指标（MoE + 量价 3 项 + RER/长链 2 项，共 5 项新增）
| 指标 | 计算方式 | 过线目标 |
|---|---|---|
| `avg_reward_holdout` | 5-fold hold-out 平均总 reward（R0/R0.5/R1/R2/R3/R4/R5 7 项加权） | **≥ +0.42**（这次上调 +0.02，对应 §4.2 R3 两个新安全阀大多数样本为 1.0） |
| `chain_valid_rate` | R0 + R0.5 + R4 共 7 段检查**全部**通过的比例（含 R4 新增的「长端断言方向一致」一条） | **≥ 90%**（新增【0.5】段合规 + 融合来源标注合规 + 长端断言合规） |
| `neutral_frac_pred` | 融合方向为 neutral 的比例 | 10%~20%（防滥用） |
| `conf_ece_primary` | 按 primary horizon 方向的置信度 ECE | **≤ 0.08** |
| `avg_volume_quoted_rate`（量价段覆盖率） | 【0.5】段完整给出 4 维量价数字的比例 | **≥ 95%**（证明"把量补进基本面"真的被训练对齐） |
| `volume_regime_quoted_acc`（量价符号正确率） | 【0.5】段 price_vol_diverge 与事实一致的样本比例 | **≥ 98%**（绝不允许编造价量背离方向） |
| **`rer_car_agree_rate_t7`（这次新增，RER↔CAR 同号率 T+7）** | sgn(rer_t7) 与 sgn(car_t7) 同号的样本比例（含 eps±0.5% 容错） | **≥ 80%**（组合门禁项） |
| **`rer_car_agree_rate_t30`（这次新增，RER↔CAR 同号率 T+30）** | sgn(rer_t30) 与 sgn(car_t30) 同号的样本比例（剔除 t30 None 样本） | **≥ 75%**（组合门禁项） |

#### ⑤ MoE 分工健康度（新增 3 类，对应 §4.2 R5）
| 指标 | 计算方式 | 过线目标 |
|---|---|---|
| `avg_winner_expert_acc` | Router argmax 主专家（给最大权重的专家）单独看 primary strict ACC | **≥ 71%**（主专家不比融合差太多，MoE 没做"反融合"） |
| `expert_usage_gini` | Router 权重分布的基尼系数（衡量分工均衡度） | **≤ 0.55**（组合门禁项：不允许只喂 1-2 个专家） |
| `e_volume_regime_weighted_acc`（量价专家专属） | e_volume_regime 权重占比>0.2 的样本里，融合方向 primary strict | **≥ 68%**（量价专家真的贡献价值，而不是一直 0 权重混饭吃） |

#### ⑥ 分场景 / 分桶过线标准（Volume 3 桶；每个分桶表格强制 5-horizon 面板）
Market×L2×Time 分桶与原要求一致，**Volume 3 桶硬性门禁保留**；并且每个分桶的汇总表里必须补 t3/t7/t15/t30/t60 4 值 = (ACC_CAR, ACC_RER, mean_CAR, mean_RER)：
- Volume **HI** 桶：primary strict ≥ **72%**（放量是最容易"事件定价充分"的 regime，应该更好）
- Volume **NORMAL** 桶：primary strict ≥ **68%**（基准）
- Volume **LOW** 桶：primary strict ≥ **58%**（缩量样本信号弱，过线阈值宽松，但不能 < 58%；否则说明模型在"没量就没方向"时完全乱猜）
- 其它不变：CN≥65% / US≥70%；6 L2 ≥5 类过 65% 且 0 类<55%；隔夜≥70%/短期≥70%/中期≥60%
- **长 horizon 新门禁（这次新增，组合门禁 1/8）**：**t30 strict（按 CAR，对全部事件统一算 primary=t30 的 ACC 打印为长端参考）≥ 61%**（不要求等于 primary，但要求>50% + 合理；说明"模型方向不只是短期噪声对"）

#### ⑦ RER（同一标的累计收益）第七大类独立面板（这次新增）
**独立于前面 CAR 的一整套**（不参与过线的方向对错，但强制打印并写进解释报告）。对每个分桶（12 Market×L2 / 4 TimeBucket / 3 VolumeBucket / 全局）输出：
```
            t3       t7       t15      t30      t60
ACC(RER)   68.2%    69.1%    67.5%    63.4%    60.1%    ← 按 sgn(rer) vs 模型方向的 ACC（中性容错 0.5%）
mean(RER)  +1.23%   +1.84%   +2.05%   +1.96%   +1.67%    ← 同一标的收益均值（直观）
P(RER>0)   72.4%    74.0%    73.5%    71.8%    69.0%    ← 正收益占比
P(RER=CAR同向) 82.1%  83.2%   81.5%    77.6%    74.3%    ← 直接对应 R4 的 η_rer
```
> **解读**：如果某分桶出现「mean(CAR_t30) > 0 但 mean(RER_t30) < 0」的情形，**必须写书面解释**——说明"相对基准有超额，但同一标的绝对没赚钱"，也就是**方向全靠 β（大环境下跌）撑出来的 alpha**。实战这类信号一般是**要降级处理**的（置信度不能给满），因此这张独立面板虽然不卡死组合门禁，但在部署评审里是"是否允许放量上线"的重要一票。

### 5.3 与 SFT/DPO 的 A/B 对比（必须，四基线同场 + 两张 A/B 新表）
同一 1000 条，同时跑 4 个基准（双口径 CAR + 3 Volume 桶 + **新增 RER 5-horizon 面板**都打印），Wilson 95% CI 两样本比例 z-test（p<0.05 显著）：
1. **Baseline (DPO)**：SFT→DPO 5-fold（`pronoia_dpo_fold*/last`，原 fever_dpo）
2. **Pronoia-RLVR-MoE**：本方案 v1（K=6 MoE + 量价融合 + RER/长 horizons 评估面板）
3. **Oracle**：`label_{primary}` + `label_avg_all`（理论上限，CAR）；**同时打印「RER oracle ACC」= sgn(rer_primary) vs 上界**
4. **Random**：按 primary + avg_all 分布随机猜

> **辩证过线（三条必须同时满足，推荐部署门禁）**：
> - (a) primary CAR 必须显著赢 DPO（p<0.05）
> - (b) avg_all CAR 不允许显著输
> - (c) **VOLUME HI 桶** primary CAR 显著赢 DPO（放量 regime 是我们最应该拉开差距的场景，这是"量价融合"有效性的实锤）
> - **(d)（新增）RER_t7 面板中，Pronoia-RLVR-MoE 的 mean(RER_t7) ≥ DPO 的 mean(RER_t7)**（同一标的累计收益的对比，不要求统计显著，但要求均值方向对）
> - (a)(b)(c) 为推荐部署硬门槛；(d) 为新增推荐部署参考门槛（不强制，但要书面解释原因如果没满足）。

### 5.4 过线组合判据（**8 条**必须同时满足，比上版 +2 条 RER/长 horizon）
**必须同时满足以下 8 条，才算 Pronoia-RLVR-MoE v1 通过**：
1. ✅ `wilson_lo_95_acc_primary_strict ≥ 66%`（核心 Wilson 下限）
2. ✅ `dual_window_hit_rate ≥ 61%`（双窗一致率） **且** `t7_t30_hit_rate ≥ 52%`（长短一致率，这次新增）
3. ✅ `chain_valid_rate ≥ 90%`、`conf_ece_primary ≤ 0.08`、`avg_volume_quoted_rate ≥ 95%`、`volume_regime_quoted_acc ≥ 98%`（四项健康度）
4. ✅ **6 类 L2 分桶**：≥ 5 类 primary strict ≥65%，且 0 类<55%
5. ✅ **Volume 3 桶门禁**：HI≥72% ∧ NORMAL≥68% ∧ LOW≥58%
6. ✅ **MoE 分工门禁**：`expert_usage_gini ≤ 0.55` 且 `e_volume_regime_weighted_acc ≥ 68%`
7. ✅ **RER↔CAR 同号率门禁（这次新增）**：`rer_car_agree_rate_t7 ≥ 80%` **且** `rer_car_agree_rate_t30 ≥ 75%`
8. ✅ **长 horizon ACC 门禁（这次新增）**：t30 全事件参考 ACC（按 CAR，统一 primary=t30 打一份 ACC）≥ 61%

§5.3 的 A/B（primary 显著赢 DPO + VOLUME HI 桶显著赢 DPO + RER_t7 均值赢 DPO）作为**推荐部署门禁**，非强制但要书面解释。5.2 ⑦ RER 独立面板和两张新 A/B 表作为部署评审的**必要附件**。

---

## 6. 实施路线图（rlvr 分支，5 周 v1 = MoE + 量价 + 新增 skill + RER/长 horizons，**23 步**，原 20 步）

```
Week 1：数据侧（三维匹配 + Volume 4 维 + RER 预计算 + 专家配额）
  ①  backtesting/build_volume_features.py（新增 §3.2.2 skill）：
       对 1000 评估集 + 5000 训练集，严格 as-of T0 写 vol_t0_ratio /
       vol_pre5_ratio / price_vol_diverge / range_t0_normalized 4 个字段
       + vol_regime ∈ {HI,NORMAL,LOW}（events.jsonl 新增一层）
  ②  build_rlvr_train_dataset.py —— 12 层配额拉 5000 条 + 去重
       同时写 scene_primary/secondary/time_bucket/expert_preference 4 字段
  ③  按 §2.4 匹配表 + §3.2.2 Volume 口径 → 跑 labeller 打标签
       （labeller 已算 t1/3/5/7/15/30/60 全套 ret/bm_ret/car，本次直接复用）
  ④  build_rer_metrics.py（**这次新增脚本 1/2**）：
       读 labeller 产物 → 写 §1.1(C) 的 rer_t1/3/5/7/15/30/60 +
       bm_tXX + horizons_complete + rer_car_agree_t7/t30 +
       bucket_id 等 schema 字段；写 CSV 自检（每个分桶 5 栏面板预览）
  ⑤  split_rlvr_5fold.py —— 按 market×L2×ym×vol_regime 4 维分层切 fold
  ⑥  定量自检脚本：(a) 定向 oracle 命中率 ≥ 25pp 增益复现；
                    (b) Volume 4 字段与 research_context volumes 对齐
                    （复用 [research_context.py:L107-L109](file:///workspace/backend/app/agents/research_context.py#L107-L109)）
                    (c)（这次新增）RER 自检：mean(RER_t7)=mean(ret_t7)、
                        rer_car_agree_rate_t7 打印、t30 None 率 ≤ 5%

Week 2：skill/tool 工程（把 volume_regime_analyzer 补进 Team）
  ⑦  backend/app/skills/volume_regime_analyzer.py（新增 Tier 2 skill）：
       对外接口 = volume_regime_analyzer(symbol, event_date) → dict 4 个数
       （复用 backtesting OHLCV 历史；strict as-of：不用 event_date 之后任何 bar）
  ⑧  roster.py 修改：在 deep_researcher / predictor 的 skills 列表里
       加上 `volume_regime_analyzer`（见 [roster.py:L155-L164](file:///workspace/backend/app/agents/roster.py#L155-L164)
       与 [roster.py:L229-L238](file:///workspace/backend/app/agents/roster.py#L229-L238)）
  ⑨  deep_researcher persona 更新：解读卡片 Step 1/2/3 必须至少引用
       1 条 volume_regime_analyzer 的数字（把量补进基本面）

Week 3：训练侧 A — 6 专家 RFT（§4.2 训练两步走 Step 1）
  ⑩  rlvr/scene_match.py：§2.4 匹配表 + §3.2.1 route() K=6 路由器
       （3 信号 O(1) 查表 + Dirichlet 平滑 softmax，无训练参数）
  ⑪  rlvr/expert_definitions.py：K=6 专家定义（配额表 + 采样偏好 +
       每个专家都随机掺 15% 全场景样本防过拟合）
  ⑫  rlvr/prompt_template.py：INPUT BLOCK（4 维量价 + vol_regime +
       eval_horizons_panel 说明）+ 推理链 7 段模板（【0.】+【0.5】+【1~5】）
  ⑬  6 专家各自 RFT（SFT 基座 warm start，r=16）：每条专家样本只做
       对应场景子集；smoke test：单专家 100 条 1 epoch，R0+R0.5+R4≥60%

Week 4：训练侧 B — GRPO MoE（Step 2） + 评估（含 RER 面板 / 长 horizons）
  ⑭  rlvr/reward_fn.py：§4.2 七元 Reward（κ_vol 乘子 / R0.5 / R5 熵正则
       / R3 四重安全阀：双窗 × 量价 × RER↔CAR × 长短一致）
       （这次新增 η_rer / η_long 两处乘子实现）
  ⑮  rlvr/grpo_trainer.py：MoE 版封装（load 6 个 RFT LoRA，每事件
       4×6=24 rollout，按 router w_i 融合，跑 GRPO，lr=3e-7）
       hold-out 评估里自动调用 eval_rlvr_vs_baseline（下一条）
  ⑯  5-fold 全量训练（fold×MoE，每 fold≈24~36h）
  ⑰  eval_rlvr_vs_baseline.py：§5.2 七大类指标（含 ⑦ RER 独立面板）
       + §5.3 四基线 A/B（含 RER_t7 均值对比） + Wilson 检验 +
       12×4×3（场景×时间×量价）分桶 + MoE 健康度 + t30 None 过滤
  ⑱  build_assessment_panels_xlsx.py（**这次新增脚本 2/2**）：
       按 §5.2 每个分桶写 t3/t7/t15/t30/t60 5-horizon 4 值面板 +
       §5.2 ⑦ RER 独立面板 + 两张 A/B 新表 → 打包成一个 xlsx/CSV 套件
       （给评审直接看）
  ⑲  可视化：Primary vs avg_all vs DPO ACC（+Volume 3 桶分别画）
          reward 学习曲线（R0/R0.5/R1/R2/R3/R4/R5 分项）
          12×4×3 三因子 ACC heatmap
          （这次新增）RER 5-horizon 面板 4 张折线（ACC / mean / P>0 / 同号率）
          （这次新增）mean(CAR_tXX) vs mean(RER_tXX) 对比散点图（按 Market×L2）

Week 5：Team Tier 1.5 接入（MoE + 量价信息进 Team） + RER/长 horizons smoke
  ⑳  rlvr_predictor.py：K=6 LoRA + Router 推理封装（输入符号/日期/事件
       → 调用 volume_regime_analyzer → 路由 → 融合 → 输出 7 段推理链）
       （输出里强制附 RER_t7 / RER_t30 数值读取，方便 Team 看）
  ㉑  team.py 注入 Tier 1.5：把【0.】时间窗口 + 【0.5】量价 regime
       + 主专家/量价专家融合权重 + 最终方向，注入 router analyzer_context
       （Team synthesize 阶段能看到 RER↔CAR 是否一致，决定降级置信度）
  ㉒  端到端 bt run 1000 条：team_full primary strict ≥ baseline+5pp；
       Volume HI 桶 team_full ≥ baseline+8pp；
       （这次新增）RER_t7 均值 team_full ≥ baseline+30bp；t7_t30_hit_rate≥50%
  ㉓ （这次新增）长 horizon / RER 过线门禁 smoke：
       跑 §5.4 组合门禁 8 条全自动脚本 → 输出 PASS/FAIL JSON；
       失败的话自动生成书面解释骨架（指向哪个分桶 mean(CAR)×mean(RER) 背离）
```

---

## 7. 风险与回退路径（RLVR v1 = MoE + Volume + **RER/长 horizons** 升级版）

| 风险 | 可能性 | 影响 | 回退路径 |
|---|---|---|---|
| MoE 训练不稳定/分工不均（基尼 > 0.7） | 中 | 高 | 把 R5 权重从 2% → 4%；Router Dirichlet α 从 0.3→0.5；再不行直接回退成"硬路由 + 单专家"（取消 softmax，每条事件只激活一个专家） |
| 量价 4 维字段缺失率 > 10%（US OTC/小市值没量） | 低 | 中 | 缺失时给 vol_t0_ratio=1.0 + diverge=0（中性值）；并在【0.5】段强制写"量数据缺失，量价 regime 视为中性" |
| volume_regime_analyzer skill 与 events.jsonl 数值不一致 | 中 | 中 | 工程侧做双重检查：Team 里调 skill 后，和 events.jsonl 字段值做 diff；diff>±0.1 的样本打标"量值不一致"不参与训练 |
| GRPO MoE 不收敛 | 中 | 高 | Fallback 成"6 专家纯 RFT + 固定权重静态融合"（不做 GRPO），仍能拿到分场景收益；或降级为单体 RLVR（附录 v1） |
| VOLUME LOW 桶 ACC 不达标（<58%） | 高 | 中 | 该桶默认把 neutral 惩罚从 -0.5 放宽到 -0.2（没量时允许谨慎）；或 3 桶分别调 κ_vol 下限 |
| RLVR ACC 不赢 DPO baseline | 中 | 高 | 先验证 κ_vol 设计；再在 Volume HI 桶做加权采样（放量样本更值钱、采样 ×1.5）；最后 MoE 和 DPO 按 (0.55,0.45) ensemble |
| **T30 缺失率 > 5%（2026-06 尾部事件）**（这次新增） | 高 | 中 | 评估 §5.2/§5.4 的 t30 类指标强制对 horizon_complete==0 样本 exclude；如果缺失>5%，就把评估集按 event_date 截断到 2026-05-15（多退 5 周 ≈35 个交易日），再重算 RER/CAR 面板，保证 T60 完整 |
| **RER↔CAR 同号率门禁不达标（t7 <80% / t30 <75%）**（这次新增） | 中 | 高 | 回退 1：把 §4.2 R3 的 η_rer 从 0.75 → 0.65（折扣更狠，训练直接对齐同号）；回退 2：训练 RFT 专家时对"RER×CAR 同向"的样本采样权重 ×1.3；回退 3：如果同号率 <70%（系统性问题），说明事件选样里 β 驱动样本占比过高，追加按 (market, ym) 条件分层拉 500 条纯 idiosyncratic 事件（个股行为类事件）补训练集 |
| **长短一致率门禁 t7_t30 <52%**（这次新增） | 中 | 高 | 回退 1：把 §4.2 R3 的 η_long 从 0.65 → 0.55（更强信号）；回退 2：对「t7 对 / t30 反」的样本在 RFT 阶段**降采样 0.5 倍**（避免模型记住短期脉冲）；回退 3：若 t30 全事件参考 ACC 也 <55%，说明模型的长端完全是噪声，把所有 primary=t7 的事件奖励里再加「t7 对但 t30 反时 R2 ×0.7」的额外惩罚 |
| **长端 RER 面板出现 mean(CAR)>0 & mean(RER)<0（系统性 β 伪超额）**（这次新增） | 中 | 中 | 书面强制解释；部署时对该分桶模型的置信度**统一打 0.8 折扣**（Team Tier 1.5 路由阶段处理）；不影响过线但禁止作为"可放大资金"的桶 |

---

---

## 附录 A：Pronoia-MS 升级方向（频率 × 时效 × 量价 × MoE LoRA + RFT，简洁 elegant 架构）

> **定位**：本附录把你在 Pronoia-MS wiki（原 FEVER-MS wiki）里的 MoE + Volume 多尺度思考，**向下兼容** §2~§6 的 Pronoia-RLVR v1 单体方案，作为 v2 升级蓝图。设计原则：**(a) 不引入新的基座模型、不搞独立的数值模型大工程**（复用 Qwen3-8B 基座 + 可解释的 4 维量价特征）；(b) MoE 只在 LoRA 层做、gating 只用 3 个信号（尺度能量比 + Volume regime + 场景标签），不搞训练成本爆炸的 learned-token router；(c) 训练顺序是"先 RFT 每个专家 → 再 GRPO 整端 MoE"，训练与推理都保持 O(1) 路由开销。

### A.1 核心思想：先把事件分配给"擅长该市场/该时效/该 regime"的专家，再统一出方向

原 Pronoia-RLVR v1 是**单体 LoRA**：用同一组权重对"US 隔夜利率决议"和"CN 中期并购"都做方向预测，模型权重互相打架、时间信号互相平均。  
**Pronoia-MS v2 = 单体基座 + K 个场景专家 LoRA + 可解释轻量 Router（无训练参数）**：
- K=6 个专家，每个专家只在自己擅长的分布上做**RFT（拒绝采样微调）**，不做跨分布训练。
- Router 只看 3 个 O(1) 信号：`(market×event_type_l2 场景标签)` + `(Volume regime 三分类)` + `(price 尺度能量比 H/L)`，用一张**查表 + 平滑 softmax**搞定，不需要在 decoder 里塞 LoRA gating。

### A.2 专家 LoRA 设计（K=6，每个 16×16 LoRA，参数量 ≤ 2.2% / 专家）

与 §2.4 的三维匹配矩阵对齐，**直接按 12 场景×时间桶聚类成 6 个专家**：

| 专家 LoRA ID | 覆盖场景（12 场景×时间桶 → 聚类） | 训练数据量 | 训练方法 | 推理链窗口倾向 |
|---|---|---|---|---|
| **E_cn_s** CN 短期型 | CN 财报(t3)/CN 回购(t3)/CN 政策(t3) | ≈ 1600 条（≈32%） | RFT（单体先采 oracle 正确样本 → SFT-LoRA） | t1/t3 倾向，shortterm |
| **E_cn_m** CN 中期型 | CN 并购/重组(t7) + CN 政策扩散(t5) | ≈ 700 条（≈14%） | RFT（方向对 + 双窗一致的样本加权） | t5/t7 倾向，midterm |
| **E_cn_o** CN 隔夜型 | CN 业绩预告(t1)/CN 宏观数据(t1) | ≈ 500 条（≈10%） | RFT（对 pre5 漂移 + T0 量价异常样本权重×2） | t1 强倾向，overnight |
| **E_us_o** US 隔夜型 | US 财报(t1)/US 指引(t1)/US FDA(t1)/US FOMC(t1) | ≈ 1200 条（≈24%） | RFT（盘后 AH 成交量×事件方向一致的样本加权） | t1 强倾向，overnight |
| **E_us_s** US 短期型 | US M&A/buyback(t3)/US 其他 company_news(t3) | ≈ 700 条（≈14%） | RFT（双窗一致样本权重×1.5） | t1/t3/t5，shortterm |
| **E_vol** Volume 专家（全局 regime 专家） | **所有场景**里高 Volume 样本（top 30% abnormal volume） | ≈ 1500 条（≈30%，与其他专家共享样本） | RFT（只采样量价背离/量价确认两类典型情形） | 自适应，依赖 Volume regime |

> **设计原则简洁性体现**：6 个专家完全由 §2.4 的 (market×horizon) 聚类得出，没有额外自由度；E_vol 仅补充 Volume 维度，不独立出方向——实际输出由 Router 加权叠加。

### A.3 Volume 量价体系的三处融合（不搞复杂 MODWT/小波，4 维可解释特征够了）

之前 RLVR v1 只看"价"(CAR)，现在把"量"融入 3 个位置：**(1) Input 块增加 4 维 as-of 量价特征；(2) Oracle CAR 做"量加权置信"校准（异常成交量事件 oracle 可信度更高）；(3) Router 用 Volume regime 决定 E_vol 专家权重。**

#### A.3.1 Input 块新增 4 维 as-of 量价特征（严格 AS-OF：T0 及之前）

在 §3.3.1 Input Block 的末尾追加 4 个数字字段（由数据构造脚本在训练/评估集里一次性计算写入，不需要 LLM 运行时算）：

| 字段名 | 定义（严格 AS-OF） | 为什么有效 |
|---|---|---|
| `vol_t0_ratio` | T0 当日成交量 / 近 20 日成交量均值（无未来） | 异常放量=市场关注=定价效率更高，confidence 可以给得高 |
| `vol_pre5_ratio` | pre5（事件前5天）累计成交量 / 近20日×5均值 | 漂移时放量=知情交易者入场概率高，反方证据需更重视 |
| `price_vol_diverge` | pre5 收益率方向 与 pre5 净量方向（量×sign）的一致性：−1=背离 / 0=中性 / +1=一致 | 价升量缩=弱信号，价升量增=强信号 |
| `range_t0_normalized` | (T0 最高 − T0 最低) / 收盘价（归一化振幅） | 振幅大=分歧大，confidence 要打折扣 |

> 这 4 个量价特征全部写进 Input Block 末尾的一段文本（例如"量价特征：vol_t0=1.8x，pre5_vol=0.9x，pv_diverge=+1，range=3.1%"），让推理链【1. 关键信号提取】和【3. 反方与限制】可以引用。**不需要独立的"数值通道"或"小波模型"，靠 Qwen3-8B 在 SFT/RFT 阶段直接学习这些量价词。**

#### A.3.2 Oracle CAR 增加"量加权置信"系数 κ（融入 §4.2 的 R2/R3 Reward）

对每条样本额外增加一个 `kappa_vol = clamp(0.6, vol_t0_ratio / 1.5, 1.4)`（vol_t0_ratio=1 时 κ=0.87；放量 1.5× 时 κ=1.0；放量 3× 时 κ=1.4；缩量 0.3× 时 κ=0.6）。  
**Reward 里的 R2（置信度校准）和 R3（CAR 幅度加权）乘以 κ_vol**：
- **逻辑**：异常放量的事件"市场定价更认真，oracle CAR 信息量更大"，正确判对的奖励更大；缩量事件（可能是噪声样本）的奖励更小。
- **效果**：RFT 的拒绝采样阶段，放量且方向对的样本更容易被选中成为专家的训练正例。

#### A.3.3 Router 用 Volume regime（3 分类）决定 E_vol 专家权重（§A.4）

```python
vol_regime = "HI"  if vol_t0_ratio >= 1.5 else \
             "LOW" if vol_t0_ratio <= 0.7 else \
             "NORMAL"
```

### A.4 Router：3 信号查表 + 归一化加权，O(1)，**无训练参数**（Elegant 核心）

Router 是 Pronoia-MS 避免复杂的关键——**不搞学习的 token router（如 MixLoRA/Switch-Transformer 那种带 router weights 的路由）**，直接用 3 个 O(1) 信号做查表 + Dirichlet 平滑 softmax，路由权重在推理/训练 reward 时一致可复现：

#### A.4.1 路由输入 3 个信号
1. **信号 1：场景标签** `s = (market, event_type_l2)` → 查表得到 6 专家的**基权重 W_base[s]**（6 维，非零 ≤ 3 个，对应 A.2 覆盖表）。
2. **信号 2：Volume regime** = HI / NORMAL / LOW → 查表给 **E_vol 叠加 ΔW_vol**：HI +0.25，NORMAL +0.08，LOW +0.0。
3. **信号 3：价格尺度能量比 H/L**（简化版，不需要 MODWT）：
   ```python
   # as-of：用 pre10 日收益率的 2 日 EMA 波动率 / 10 日 EMA 波动率
   hl_ratio = ema(daily_ret^2, 2) / (ema(daily_ret^2, 10) + 1e-8)
   freq_hi = hl_ratio > 2.0   # 高频突发型 → 给 隔夜型专家(E_cn_o/E_us_o) 再 +0.12
   freq_lo = hl_ratio < 0.5   # 低频延续型 → 给 中期型专家(E_cn_m) 再 +0.12
   ```

#### A.4.2 路由公式（简洁到一张表 + 两次归一化）
```
W_raw = W_base[s]          # 信号1：场景基权重
W_raw[IDX_vol] += ΔW_vol   # 信号2：Volume 叠加
if freq_hi: W_raw[IDX_cn_o] += 0.12 if market=="CN" else 0.0
           W_raw[IDX_us_o] += 0.12 if market=="US" else 0.0
if freq_lo: W_raw[IDX_cn_m] += 0.12
W = softmax(W_raw / T_router)     # T_router = 0.6（固定温度，不学习）
```
**K=6 个专家加权输出**：
```
final_dir_logits = Σ_{e=1..6} W[e] * LoRA_e(dir_logits)
final_chain  = argmax(W) 的专家产出的推理链（作为"主推理链"输出，可审计）
```

> **简洁性体现**：Router 只有 12 行代码（查表+叠加+softmax），没有可训练权重，不会出现"router 塌缩到单专家"的训练不稳定性；同时输出的主推理链是 argmax 专家的 6 段链，人类可审计性和 v1 一样好。

### A.5 训练顺序：先 RFT 每个专家 → 再 GRPO 整端 MoE（两步走，效率高）

MoE 如果直接端到端 GRPO，会有 router 冷启动、专家分工不均等坑；Pronoia-MS v2 用"**先 RFT 单体专家 → 再 GRPO MoE**"两步走：

#### Step 1：RFT（拒绝采样微调）每个专家 LoRA（单体训练，并行 K=6 组）
对每个专家 e：
1. **采样集 D_e**：从 5000 条总训练集中，按该专家覆盖场景（A.2 表）抽样本；对 oracle 方向正确（非 neutral oracle 方向 == label_primary）的样本，按 `(1 + 0.5 * kappa_vol)` 概率被保留（放量正确样本入选概率更高）。
2. **保留比率**：每条样本 rollout 4 个方向，取 R_total 排名 top-1（≥ 0.3 的才留），对每个专家 RFT 只接受高 reward 样本 → RFT-LoRA 微调单体。
3. 输出：6 个 `lora_e/` 目录（r=16，target_modules 同 §4.1）。

> RFT 是 RLVR 的"低配版"（离线拒绝采样 + SFT，没有 PPO/GRPO 在线更新），训练成本低、分布稳，每个专家 500~1000 条样本足够收敛。

#### Step 2：GRPO 整端 MoE（§4 的 RLVR 框架改造，Router 作为固定组合器）
把 K=6 个 RFT 专家 LoRA 同时挂在 Qwen3-8B 基座（LoRA 叠加，W_raw 加权），在完整 5000 条训练集上再做一次**小学习率 GRPO**（只微调 Router 温度？不，温度固定为 0.6；GRPO 只微调 K=6 个 LoRA 的 ΔW，不碰任何基座权重）：
- Reward 函数同 §4.2（R0~R4），新增一项 **R5=0.05 × expert_entropy_reg**：
  ```python
  R5 = 0.05 * min(1.0, - Σ W[e] log W[e] / log(6))   # 负熵归一化
  ```
  R5 的作用：避免 Router 塌缩到只选一个专家（W 变成 one-hot），鼓励"专家混合"。

### A.6 Pronoia-MS v2 评估：在 v1 的五大类上新增 MoE 三类指标（辩证评估）

在 §5 五大类指标基础上，Pronoia-MS v2 再新增三类（全部 1000 条评估集上报告）：
| 指标 | 说明 | 过线目标 |
|---|---|---|
| `avg_winner_expert_acc` | 每个场景下 Router 的 argmax 专家（主推理链专家）的 primary strict ACC | ≥ 70%（比单体 RLVR +2pp） |
| `vol_regime_split_acc` | Volume HI/NORMAL/LOW 三桶的 primary strict ACC 分别打印 | HI 桶 ≥ 72%，LOW 桶 ≥ 60% |
| `expert_usage_gini` | Router 权重分布的基尼系数（衡量专家分工均衡度） | ≤ 0.55（不允许只喂 1-2 个专家） |

### A.7 代码落地：增量极小（和 §6 的 15 步 v1 方案复用 95%）

Pronoia-MS v2 在 v1 Week 1~4 基础上，只需要新增 5 个文件 / 修改 3 处：
| 新增/修改 | 路径 | 说明 |
|---|---|---|
| 新增 | `backend/scripts/rlvr/volume_features.py` | A.3.1 的 4 维 as-of 量价特征计算（供 build 脚本调用） |
| 新增 | `backend/scripts/rlvr/experts/definitions.py` | A.2 的 6 专家覆盖场景表 + `W_base[s]` 查表 |
| 新增 | `backend/scripts/rlvr/experts/router.py` | A.4 的 O(1) Router（12 行查表 + softmax） |
| 新增 | `backend/scripts/rlvr/experts/rft_train_e.py` | A.5 Step1：单专家 RFT 训练脚本（并行 K=6） |
| 新增 | `backend/scripts/rlvr/experts/grpo_moe_trainer.py` | A.5 Step2：6 LoRA 叠加的 MoE GRPO，新增 R5 专家熵正则 |
| 修改 | `backend/scripts/rlvr/reward_fn.py` | §4.2 中 R2/R3 乘以 A.3.2 的 kappa_vol |
| 修改 | `backend/scripts/rlvr/prompt_template.py` | Input Block 末尾添加 4 维量价特征的文本段落（A.3.1） |
| 修改 | `backend/scripts/rlvr/build_rlvr_train_dataset.py` | Week1 脚本中调用 volume_features.py 写 4 个量价附加字段 + kappa_vol |

> **Elegant 的原因**：A.2~A.7 的全部新增内容，都**复用** v1 的训练数据、评估集、Oracle 字段、Reward 函数骨架、推理链 6 段格式、GRPO trainer 框架——**没有新的大工程**，只是在 RLVR v1 上做了 6 个 LoRA 专家并行 + 一个 12 行无参数 Router + 4 个量价特征，符合你"尽量简洁而 elegant"的要求。

### A.8 与 Pronoia-MS wiki 提案的对应关系（收敛简化版）
对比你在 wiki（原 FEVER-MS wiki）里 §4.1 的总体架构描述，这里把复杂点统一做了**收敛简化**：
- **频率×时效二维 Reward**：wiki 里的 `R(q,style)=Σ_f Σ_h λ·verify_f·hit_h·abstain_shape` → 在本附录里拆成 **A.3.2 的 kappa_vol（verify_f 简化）+ §4.2 的 oracle_primary（hit_h 定向）+ R3 双窗安全阀（abstain_shape 简化）**，不搞二维张量求和。
- **MODWT/小波三通道 H/M/L**：wiki 里的 MODWT → 在 A.4.1 信号 3 中简化为 `ema(daily_ret^2, 2) / ema(daily_ret^2, 10)`（hl_ratio），不引入独立的数值骨干模型。
- **Scale-Conditioned Router + UGA 门控优势 + CES 专家互斥正则**：wiki 里的三项训练技巧 → 在 A.5 Step2 中收敛为"R5 专家负熵正则 + 固定温度 T_router=0.6 + 单专家 RFT 预训练"，保证分工均衡同时不引入新训练超参。

---

## 8. 关键文件改动清单（rlvr 分支，含 RER/长 horizons 新增）

| 新增/修改 | 路径 | 说明 |
|---|---|---|
| 新增 | `backtesting/build_volume_features.py` | Volume 4 维 + vol_regime 写 events.jsonl（§3.2.2 skill 数据源） |
| 新增 | `backend/scripts/rlvr/build_rlvr_train_dataset.py` | 5000 条训练集构造 + scene_primary/secondary/eval_horizons_panel 字段 |
| 新增 | `backend/scripts/rlvr/build_rer_metrics.py`（**这次新增**） | §1.1 定义的 RER（= ret）+ bm_tXX + horizons_complete + rer_car_agree 标记写出 |
| 新增 | `backend/scripts/rlvr/split_rlvr_5fold.py` | 按 market×L2×ym×vol_regime 4 维分层切 fold |
| 新增 | `backend/scripts/rlvr/quant_selfcheck.py` | 5 项定量自检（含定向 oracle 增益 + RER 自检 + t30 None 率） |
| 新增 | `backend/app/skills/volume_regime_analyzer.py` | 新增 Tier 2 skill：volume_regime_analyzer(symbol, event_date) → 4 维（§3.2.2） |
| 修改 | `backend/app/agents/roster.py` | deep_researcher / predictor 的 skills 列表加入 volume_regime_analyzer（[roster.py:L155-L164](file:///workspace/backend/app/agents/roster.py#L155-L164) / [roster.py:L229-L238](file:///workspace/backend/app/agents/roster.py#L229-L238)） |
| 修改 | `backend/app/agents/deep_researcher.py`（或 persona 配置） | 解读卡片强制引用 1 条 volume_regime_analyzer 数字（把量补进基本面） |
| 新增 | `backend/scripts/rlvr/scene_match.py` | §2.4 三维匹配表 + §3.2.1 route() K=6 Router（3 信号 O(1) 查表） |
| 新增 | `backend/scripts/rlvr/expert_definitions.py` | K=6 专家配额表 / 采样偏好 / 15% 跨场景掺样规则 |
| 新增 | `backend/scripts/rlvr/prompt_template.py` | INPUT BLOCK（4 维量价 + vol_regime + eval_horizons_panel） + 推理链 7 段模板 |
| 新增 | `backend/scripts/rlvr/grpo_trainer.py` | GRPO 训练主入口（MoE 版：6 RFT LoRA + 24 rollout/event + lr=3e-7） |
| 新增 | `backend/scripts/rlvr/reward_fn.py` | §4.2 七元 Reward 实现（κ_vol / R0.5 / R5 / R3 四重安全阀含 η_rer / η_long） |
| 新增 | `backend/scripts/rlvr/eval_rlvr_vs_baseline.py` | 1000 条评估集统一对比：§5.2 七大类指标（含 ⑦ RER 面板） + §5.3 四基线 A/B + Wilson CI |
| 新增 | `backend/scripts/rlvr/build_assessment_panels_xlsx.py`（**这次新增**） | 打包 t3/t7/t15/t30/t60 5-horizon 面板 + RER 独立面板 + A/B 新表 → xlsx/CSV |
| 新增 | `backend/app/rlvr_predictor.py` | 推理侧 RLVR 封装（K=6 LoRA + Router + 7 段链 + RER_t7/t30 数值读取） |
| 修改 | `backend/app/agents/team.py` | Tier 1.5 注入点：【0.】窗口 +【0.5】量价 regime + 融合权重 + RER↔CAR 是否一致标志 |
| 修改 | `backend/scripts/train_pronoia_v2.py` | 复用 SFT 基座 warm start 配置 + stable_stratified_split_ids（不需要新增训练入口，只是复用） |
| 新增 | `data/rlvr_train_v1_5000/` | 5000 条训练集（含 RER schema 字段：events/labels/distribution.json） |
| 新增 | `data/_rlvr_artifacts_v1/panels_rer/`（**这次新增**） | 评估产物输出：5-horizon 面板 / RER 独立面板 / A/B 表 / 书面解释骨架 |
| 修改 | 本文件 | `docs/20260822_rlvr_design.md` | 本文档，随实施迭代更新 |
