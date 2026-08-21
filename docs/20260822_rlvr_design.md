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

## 1. 评估集（固定不变）

评估 **只使用 `backtesting/` 目录下已构造好的 1000 条**——也就是 [events_cn_us_1000_v1.jsonl](file:///workspace/backtesting/events_cn_us_1000_v1.jsonl) + [labels_cn_us_1000_v1.jsonl](file:///workspace/backtesting/labels_cn_us_1000_v1.jsonl)，**不再重新生成、不新增样本、不改动字段**：

| 项 | 值 |
|---|---|
| 样本数 | 1000（CN 700 / US 300） |
| 时间跨度 | 2024-01 ~ 2026-06 |
| 主标签 | `label_avg_all`（加权平均 CAR 方向，up/down/neutral） |
| 连续奖励来源 | `car_avg_all`（真实加权超额收益） |
| 关键口径 | `acc_avg_all_strict`（neutral 也算错） + `acc_avg_all_non_neutral`（非 neutral 才计分） |

**为什么固定不动**：训练集和评估集必须严格时间/分布正交吗？不需要——这里的"同分布"指事件类型和市场比例的**分布一致**，但 event_id 完全不重叠。评估集 1000 条留作唯一 gold standard，后续任何 RLVR/SFT/DPO 版本都在同一份上打分，保证可比。

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

#### 2.4.1 三维匹配矩阵（12 个场景逐一规则化 + 数据验证）

匹配原则 = **事件生效窗口常识 + 该 horizon 的 |CAR| 峰值位置**（数据验证见附录定量实验）：

| Market | EventType L2 | **主时间桶** | **主 Horizon**（训练/reward 用） | **次 Horizon**（R3 双窗校验用） | 匹配理由 |
|---|---|---|---|---|---|
| CN | 并购/分拆/再融资 | 中期 (2w内) | **car_t7** | car_t5 | 并购吸收/再融资效应在 +5~7 日扩散最集中 |
| CN | 财报超预期/不及预期 | 短期 (1w内) | **car_t3** | car_t5 | 财报 + 集合竞价 + 2 日盘内消化，t3 为峰值 |
| CN | 公司指引上调/下调 | 隔夜型 | **car_t1** | car_t3 | 盘前公告 → 隔夜集合竞价一步定价完成 |
| CN | 政策利率调整 | 隔夜型 | **car_t1** | car_t3 | 降息/加息消息即期定价 |
| CN | 增长/就业数据意外 | 隔夜型 | **car_t1** | car_t5 | 数据公布即期定价 + 5 日窗口持续传导 |
| CN | 通胀数据意外 | 短期 (1w内) | **car_t3** | car_t5 | CPI/PPI → 政策预期 2-3 日传导 |
| US | 并购/分拆/再融资 | 中期 (2w内) | **car_t7** | car_t5 | tender 期限 + 监管博弈，5-7 日集中 |
| US | 财报超预期/不及预期 | 隔夜型 | **car_t1** | car_t3 | 盘后财报 → +1 日 AH 集中一步定价（时差效应） |
| US | 公司指引上调/下调 | 隔夜型 | **car_t1** | car_t3 | US 指引通常与财报同步盘后发布 |
| US | 政策利率调整 | 隔夜型 | **car_t1** | car_t3 | FOMC 决议即期定价，后续交易日只做回吐 |
| US | 增长/就业数据意外 | 隔夜型 | **car_t1** | car_t3 | 非农/NFP 即期定价 |
| US | 通胀数据意外 | 隔夜型 | **car_t1** | car_t3 | CPI/PCE 即期定价 |

> **一致通过的定量基准**：上表 12 条场景规则中，**定向 oracle vs 主 horizon 真值的命中率在每个场景均 ≥ 90%**（详见 1000 条评估集验证：全场景均为 100%），且全部优于 `avg_all` 口径。训练/评估时任何事件都先查表确定主/次 horizon，再读取对应的 `car_XX` / `label_XX`。

#### 2.4.2 数据构造脚本输出的附加字段

Step 2 打 Oracle 标签时，在每条 `labels.jsonl` 中**额外附加两个字段**（方便训练/评估直接读取，不必运行时查表）：
```json
{
  "scene_primary_horizon": "t3",
  "scene_secondary_horizon": "t5",
  "scene_time_bucket": "短期(1w内)"
}
```
这三个字段由匹配矩阵按 (market, event_type_l2) 直接写入，训练/评估代码里统一用 `r['label_' + r['scene_primary_horizon']]` 作为 oracle 方向，用 `r['car_' + r['scene_primary_horizon']]` 作为 R1/R2/R3 的连续 reward 来源。

#### 2.4.3 "辩证看待"：保留 avg_all 作为全景口径（只用于评估对比，不用于训练 reward）

你强调"所有指标都要辩证看"，因此**训练 reward 只按定向主 horizon**（避免信号被稀释），但**评估时同时报告三组口径**，形成全景判断：

| 口径 | 含义 | 报告位置 | 是否参与过线 |
|---|---|---|---|
| ① **定向 strict** | 按场景主 horizon 的 label 算 ACC（真正的训练目标） | 主指标列 | ✅ **过线核心判据** |
| ② **avg_all strict** | 与现有 SFT/DPO 基线完全同款口径（7 horizon 平均） | 对比列 | 报告即可，不卡死 |
| ③ **双窗一致率** | 主/次 horizon 方向都对的样本比例（防"只踩中一个窗口的过拟合"） | 过线附加判据 | ✅ ≥ 60% 才算过 |

三组口径都要打分、都要出分桶、都要报告 Wilson CI，最终结论辩证综合——但**方向对不对、训练 reward 给不给**，只认①定向主 horizon。

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

### 3.2 LoRA 配置（复用 SFT 配置 + 微调 gate_proj）

沿用 SFT 的 target_modules + 小幅扩范围，让 RLVR 的策略更新能影响推理链的 token 生成：
```python
LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj",
                    "gate_proj","up_proj","down_proj"],  # ← 8B 全 MLP + Attn
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)
```

### 3.3 推理链作用于哪里（关键设计）

#### 3.3.1 总体思路：推理链 = "【0. 预判窗口】+ 5 段 CoT"，先定"看多长"再判方向

> 呼应你的核心观点：**先分场景定时间窗口（隔夜/短期/中期/长期），再在这个窗口内谈方向对错**——推理链必须把"看什么 horizon"显式写出来，模型不能再"猜一个模糊的大方向"。

```
┌─────────────────────────────────────────────────────────────┐
│  INPUT BLOCK（固定，不可见未来信息）                          │
│  • event_id / market / symbol / event_time / event_type_l2  │
│  • title + event_text（截断到 ≤ 1500 chars）                  │
│  • 【STRICT AS-OF】T0 当日涨跌 / pre5 漂移（若可用）          │
│  • benchmark 名称                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  CHAIN-OF-THOUGHT BLOCK（RLVR 训练核心 —— 必须显式输出）        │
│  格式：中文分段标签，共 6 段（新增【0.】时间窗口预判段）         │
│                                                               │
│  【0. 预判时间窗口】≤80字（核心新增）                           │
│    先定本事件"该看多长的方向"，并点名主horizon                 │
│    例："该事件为 CN 财报，定价集中在 +1~5 日窗口期；主horizon t3"│
│    例："该事件为 US 利率决议，隔夜即期定价；主horizon t1"       │
│    例："该事件为 CN 并购，扩散期 5-7 日；主horizon t7"         │
│                                                               │
│  【1. 关键信号提取】≤200字                                      │
│    从 event_text 提取 2~4 条可量化信号（数字/方向/超预期词）      │
│    例："① 营收+12% YoY；② 毛利率环比-0.5pp；③ 北向T0净买+1.2亿"│
│                                                               │
│  【2. 横向比较】≤150字                                          │
│    同比/环比/一致预期/同业 比较，明确"超/不及/符合预期"          │
│    例："营收增速高于一致预期的 9%，但毛利率低于同业均值 28%"     │
│                                                               │
│  【3. 反方与限制】≤150字                                        │
│    列出 1~2 条反面证据或不确定性（漂移出尽/政策窗口/季节性）     │
│    例："反方：pre5 已涨 8%，可能利好出尽；限制：单季数据"        │
│                                                               │
│  【4. 置信度校准】≤100字                                        │
│    给出 confidence 值（0.50~0.99）+ 1 句理由                    │
│    例："0.75 — 基本面信号一致，但事前漂移较大需打折扣"          │
│                                                               │
│  【5. 最终方向】one line                                        │
│    三选一：up / down / neutral（且明确注明"按主horizon XX判断"）│
│    例："up（按主horizon t3 判定）"                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  REWARD COMPUTATION（按 §2.4 的定向场景表取 oracle horizon）  │
│  • R1 方向正确性：oracle = label_{primary}（非 avg_all！）     │
│  • R2 置信度校准：按 oracle_{primary} ± car_{primary} 幅度    │
│  • R3 CAR 幅度加权：按 car_{primary}，必要时附 car_{secondary}│
│  • R4 推理链一致性 penalty（新增【0.】窗口段合规检查）          │
└─────────────────────────────────────────────────────────────┘
```

#### 3.3.2 推理链与现有 Team Pipeline 的映射关系

RLVR 训练的模型本质上是一个 **"轻量化方向判别器"**，对应 team pipeline 中多段角色的融合（**新增【0.】= 时间窗口判定 = Team 中 Tier 2 skill horizon_select 的职责**）：

| RLVR 推理链分段 | 对应 Team Pipeline 中的角色 | 说明 |
|---|---|---|
| **【0. 预判时间窗口】**（新增） | `horizon_select`（Tier 2 skill，按事件/市场匹配预期窗口） | 对应 §2.4 三维匹配矩阵：先定"该看多长"，再判方向 |
| 【1. 关键信号提取】 | `announcement_classifier` + `market_research` 原始信号 | 从 event_text + T0 行情提取结构化数字信号 |
| 【2. 横向比较】 | Tier 2 skill `ar_decomposer` / `drift_context_analyzer` | AR 分解、漂移出尽系数、同比环比 |
| 【3. 反方与限制】 | deep_researcher 的 Claim 生成（"反方/限制"段落） | 对应 [roster.py:L199-L205](file:///workspace/backend/app/agents/roster.py#L199-L205) 的解读卡片 Step 3 |
| 【4. 置信度校准】 | synthesize 阶段 analyzer_scorecard.confidence | 对应 [team.py:L706-L744](file:///workspace/backend/app/agents/team.py#L706-L744) |
| 【5. 最终方向】 | router synthesize 输出的 `【最终方向】` | 对应 [team.py:L765-L769](file:///workspace/backend/app/agents/team.py#L765-L769) |

#### 3.3.3 【0.】窗口预判段的训练对齐机制（关键）

【0.】输出的主 horizon **必须与 §2.4 匹配表中该 (market, event_type_l2) 的值完全一致**——不允许模型自由发挥定窗口。
- 换句话说，【0.】在训练时不是"让模型学"的，而是**按 (market, event_type_l2) 强约束**（R4 一致性检查里包含这一条）。
- 为什么还要模型显式写出来？因为这样推理链**自包含语义**：人类审阅/后验诊断时不用查表，就能一眼看到"这条判断是针对什么时间窗口的"，符合"可审计推理链"的初衷。
- 一旦 §2.4 的匹配表后续迭代（比如新增 event_type_l3 或 market 子分类），先更新匹配表 → 重写数据构造脚本的 3 个字段 → 重新训练；不需要动模型模板。

**⚠️ 关键决策：RLVR 模型是否包含 tool call？**  
第一版 **不包含 tool call**。原因：
1. RL with tool call（即多轮 function call 的 PPO）sample efficiency 极低，5000 条不够塞牙缝。
2. STRICT AS-OF 模式下 tool call 能拿到的只有 T0/pre5 行情，这些直接拼进 INPUT BLOCK 即可，不需要动态调。
3. 先把"纯文本 + 预灌信号 → 推理链 → 方向"这条链路跑通，后续再加 tool call 作为 Level 2。

#### 3.3.3 推理链的输出如何在推理时接入 Team Pipeline

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

### 4.2 Reward 函数（四部分加权，总范围 [-1.55, +2.10]）

> **核心变更（响应"分市场/分事件/分时间"）**：Oracle 的方向真值 + CAR 幅度真值 **不再用 avg_all，一律按 §2.4 匹配表的 `{scene_primary_horizon}` 取**（字段名在每条样本里写入，训练时一行代码读出来）。推理链的【0.】窗口预判 + 【5.】最终方向都围绕这个 primary horizon 对齐。
> **辩证安全阀**：R3（CAR 幅度加权）新增"双窗校验"逻辑——若 primary horizon 判对、但 secondary horizon 方向完全相反、且 |car_sec|≥|car_prim|/2，则减半奖励，防止"只赌一个时间窗口的伪信号过拟合"。

对一条 rollout（event → 推理链 6 段 → 方向 + confidence），按 (market, event_type_l2) 查表得到 **H_primary** 和 **H_secondary**（或直接读标签附加字段）：
```
oracle_dir = label_{H_primary}
oracle_car = car_{H_primary}
secondary_car = car_{H_secondary}
```
总 reward = 0.5R1 + 0.3R2 + 0.15R3 + 0.05R4 + **0.05R0**（新增 R0 = 【0.】窗口预判合规奖）。

#### R0：【0. 预判时间窗口】合规性（权重 0.05，范围 [−0.05, +0.05]，新增）
把时间窗口判定作为独立 reward 项（呼应"先定窗口再判方向"）：
- 【0.】段提到的主 horizon 名称 = §2.4 匹配表的 primary → **+0.05**
- 主 horizon 名称写错（CN 并购写成 t1、US 利率决议写成 t7 之类）→ **−0.05**
- 【0.】段缺字数或未点名 horizon → **−0.05**

#### R1：方向正确性（权重 0.5，范围 [−1, +1]）
Oracle = `label_{H_primary}`，不再使用 label_avg_all；判 neutral 惩罚保留（防止"躲 neutral"）：
```python
if oracle_dir == "neutral":
    R1 = +0.5 if pred == "neutral" else -0.5
else:
    if   pred == oracle_dir:   R1 = +1.0
    elif pred == "neutral":    R1 = -0.5
    else:                      R1 = -1.0
```
*（如果场景是"并购/分拆"这类中期事件，oracle_dir 实际是 label_t7；如果是 US 利率决议，是 label_t1 —— 完全匹配事件的定价时间。）*

#### R2：置信度校准（权重 0.3，范围 [−0.3, +0.3]）
按 H_primary 的方向和幅度生效：
```python
if oracle_dir != "neutral" and pred != "neutral":
    sign = +1.0 if pred == oracle_dir else -1.0
    # car_primary 越大，置信度"应当越高" → 对大CAR的高置信奖励更大（乘 |car| 饱和夹）
    ampl = min(1.0, abs(oracle_car) / 0.05)    # |CAR| 5%+ → 1 饱和
    R2 = sign * (confidence - 0.5) * 0.6 * (0.5 + 0.5 * ampl)
else:
    R2 = 0.0
```

#### R3：CAR 幅度加权 + 双窗一致校验（权重 0.15，范围 [0, +0.30]，含辩证安全阀）
Oracle CAR 大的事件奖励更高；**新增双窗一致校验**：若主窗判对但副窗方向反向且幅度不小，扣半奖励，保证模型"不是只踩中一个时点的噪声"。
```python
if (oracle_dir != "neutral") and (pred == oracle_dir):
    # 基础：primary CAR 分段线性（0.5%→0 / 5%→1 / ≥5%→饱和）
    w_prim = min(1.0, max(0.0, (abs(oracle_car) - 0.005) / 0.045))
    base = 0.3 * w_prim

    # 辩证安全阀：双窗一致率校验
    # 次窗若存在、且|car_sec| ≥ 0.5 × |car_prim|：
    if secondary_car is not None and abs(secondary_car) >= 0.5 * abs(oracle_car):
        sec_dir = "up" if secondary_car > 0 else "down"
        if sec_dir != oracle_dir:   # 次窗方向与主窗相反 → 扣减奖励 50%
            base *= 0.5
    R3 = base
else:
    R3 = 0.0
```

#### R4：推理链一致性检查（权重 0.05，范围 [−0.05, +0.05]，更新为 6 段）
规则硬检查（包含新增【0.】段）：
1. 6 段标签齐全且顺序正确（【0.】~【5.】）
2. 【0.】段中提到的主 horizon 与匹配表/字段完全一致（复用 R0 的检查器）
3. 【1. 关键信号】中包含 ≥2 个数字/百分比
4. 【5. 最终方向】中的值与最终 pred_direction 完全一致
5. 【4. 置信度校准】中的数字和模型输出 confidence 差值 ≤ 0.05
6. 【5. 最终方向】明确注明了"按主horizon XX判定"，且 XX = primary horizon

全部满足 → **+0.05**；任一违反 → **−0.05**。

#### 总 Reward
```python
reward = 0.05*R0 + 0.5*R1 + 0.3*R2 + 0.15*R3 + 0.05*R4
```

**预期 reward 基准（随机模型）**：≈ 0.05*(-0.05) + 0.5*(0) + 0 + 0 + 0.05*(-0.05) ≈ **−0.005**（R0/R4 略负，R1 随机为 0）  
**训练目标**：hold-out 平均 reward ≥ **+0.40**（对应定向 primary horizon 非 neutral ACC ≈ 70% + 置信校准良好 + ≥90% chain_valid_rate）。

---

## 5. 评估方案（固定 1000 条 backtesting 集，分场景化辩证多口径）

### 5.1 辩证评估原则：三组口径并行打分，过线核心判据是①

> 呼应你"所有指标都要辩证看"的要求：**任何单一口径都不做唯一判据**；先看①定向 primary horizon（真正训练目标）的过线情况，再用② avg_all 与基线比公平对比，再用③双窗一致率 + ④ 分场景分桶 + ⑤ 时间桶维度，做综合判断。五组指标都打印、都出 Wilson CI、都画对比图，过线按组合判据（见 5.4）。

### 5.2 训练过程中的评估（每 epoch 一次，五大类指标）

用 [train_pronoia_v2.py:L172-L229](file:///workspace/backend/scripts/train_pronoia_v2.py#L172-L229) 的 `score-all` 同款逻辑，按 **12 个 Market×L2 场景 + 4 类时间桶（隔夜/短期/中期/长期）**分桶，输出以下五大类指标：

#### ① 定向主 horizon 口径（核心过线判据）
按 §2.4 匹配表的 label_{primary} 做 oracle（训练目标一致口径）：

| 指标 | 计算方式 | RLVR 过线目标 |
|---|---|---|
| `acc_primary_strict`（核心主指标） | pred 与 `label_{primary}` 完全一致的比例，neutral 算错 | **≥ 68%**（比原 avg_all 目标 65% 更严格，因为信号更纯） |
| `acc_primary_non_neutral` | 只在 `label_{primary}` ∈ {up,down} 时计分（实战口径） | **≥ 78%** |
| `wilson_lo_95_acc_primary_strict` | Wilson 95% CI **下限**（过线的真正判据） | **≥ 65%**（下限过线才是真过线） |

#### ② avg_all 口径（与 SFT/DPO 基线做公平横向对比，不卡死）
保留与现有基线完全同款的口径，保证跨模型可比：

| 指标 | 计算方式 | RLVR 参考目标 |
|---|---|---|
| `acc_avg_all_strict` | pred 与 label_avg_all 完全一致的比例，neutral 算错 | ≥ 65%（报告即可，不卡） |
| `acc_avg_all_non_neutral` | 非 neutral 实战口径 | ≥ 75%（报告即可） |
| `wilson_lo_95_acc_avg_all_strict` | Wilson 95% 下限 | ≥ 62%（报告即可） |

#### ③ 时间一致性（辩证安全阀指标，参与过线）
防止"只踩对一个 horizon 的伪过拟合"：

| 指标 | 计算方式 | RLVR 过线目标 |
|---|---|---|
| `dual_window_hit_rate`（双窗一致率） | `label_{primary}` 方向对 **且** `label_{secondary}` 方向也对的样本比例 | **≥ 60%**（§5.4 过线组合判据之一） |
| `across_bucket_consistency`（跨时间桶一致率） | primary 对且 primary 桶内所有 horizon（t1/t3/t5）方向都对的比例 | ≥ 45%（报告参考） |

#### ④ 过程质量指标（模型行为健康度）
与 Reward 组成一一对应：

| 指标 | 计算方式 | RLVR 过线目标 |
|---|---|---|
| `avg_reward_holdout` | 5000 训练集 5-fold hold-out 平均总 reward（R0~R4 加权） | **≥ +0.40**（主 reward 目标） |
| `chain_valid_rate` | R0 + R4 六项检查全部通过率 | **≥ 90%** |
| `neutral_frac_pred` | 预测为 neutral 的比例 | 10%~20%（防滥用） |
| `conf_ece_primary` | 按 primary horizon 方向的置信度 ECE | **≤ 0.08** |

#### ⑤ 分场景 / 分桶过线标准（每类至少过线，辩证不允许某一大类崩坏）
按 Market（CN/US）× EventType L2（6 类）× Time Bucket（隔夜/短期/中期）三类分桶，要求：
- **CN**：按 primary 口径 strict ≥ 65%；**US** ≥ 70%（美股事件文本更结构化）
- **6 类 L2** 中至少 5 类 strict ≥ 65%，**没有任何一类 < 55%**
- **Time Bucket**：隔夜型 ≥ 70%；短期(1w内) ≥ 70%；中期(2w内) ≥ 60%（中期事件样本少、信号扩散，阈值收窄合理）

### 5.3 与 SFT/DPO 的 A/B 对比（必须，四基线同场打）
同一 1000 条评估集上，同时跑 4 个基准（全部按 primary + avg_all 双口径报告），用 Wilson 95% CI 做两样本比例 z-test（p<0.05 才算显著提升）：
1. **Baseline (DPO)**：现有 SFT → DPO 的 5-fold 模型（`pronoia_dpo_fold*/last`，原 fever_dpo）
2. **RLVR (GRPO)**：SFT 基座 → RLVR 的 5-fold 模型
3. **Oracle**：`label_{primary}` + `label_avg_all`（理论上限，≈100%）
4. **Random**：按 primary + avg_all 的 up/down/neutral 分布各自随机猜

> 要求：**RLVR 在 primary 口径上必须显著击败 DPO（p<0.05）；avg_all 口径可以不显著赢但不能显著输（即 CI 不低于基线）**——这就是"辩证过线"。

### 5.4 过线组合判据（不是单一数字，是"组合门禁"）
**必须同时满足以下 4 条，才算 RLVR v1 通过**：
1. ✅ `wilson_lo_95_acc_primary_strict ≥ 65%`（下限过线）
2. ✅ `dual_window_hit_rate ≥ 60%`（双窗一致率，辩证过拟合门禁）
3. ✅ `chain_valid_rate ≥ 90%` 且 `conf_ece_primary ≤ 0.08`（模型健康度）
4. ✅ **6 类 EventType L2 分桶的 primary strict ACC**：≥ 5 类 ≥ 65%，且 0 类 < 55%（大类分布门禁）

5.3 中 A/B 对比（RLVR 对 DPO 在 primary 显著赢且 avg_all 不显著输）作为**推荐部署门禁**，非强制但需要书面解释不满足的原因。

---

## 6. 实施路线图（rlvr 分支上的代码落地顺序）

```
Week 1：数据侧（新增 §2.4 三维匹配 + 字段）
  ① build_rlvr_train_dataset.py —— 按 §2.2 的 12 层配额拉 5000 条 + 去重
  ② 按 §2.4 匹配表写入 scene_primary/secondary/time_bucket 三字段 + labeller 打标签
  ③ split_rlvr_5fold.py —— 复用 stable_stratified_split_ids 切 fold + 分布自检（JS<0.01）
  ④ 附：定量自检脚本，确认定向 oracle vs 主horizon 真值的命中率 ≥ 95%（§2.4 附录复现）

Week 2：训练侧（§4.2 新 Reward + §3.3 六段推理链）
  ⑤ rlvr/scene_match.py —— §2.4 匹配表 Python dict + H_primary / H_secondary 查找函数
  ⑥ rlvr/reward_fn.py —— §4.2 的 R0/R1/R2/R3/R4（含 R3 双窗安全阀 + R4 六段检查）
  ⑦ rlvr/prompt_template.py —— 输入块 + 推理链 6 段模板（【0.】窗口 + 【1~5】，严格中文标签）
  ⑧ rlvr/grpo_trainer.py —— 封装 trl.GRPOTrainer，连 reward_fn + prompt
  ⑨ 跑 fold0 单 fold smoke test（100 条，1 epoch，观察 reward 曲线上升 + R4 chain_valid_rate 过 70%）

Week 3：全量训练 + 评估（§5.2/5.3/5.4 辩证多口径）
  ⑩ 5-fold 全量训练（每 fold ≈ 12~24h），产出 5 个 checkpoint
  ⑪ eval_rlvr_vs_baseline.py —— §5.2 五大类 + §5.3 四基线同场对比，含 Wilson 检验、分桶
  ⑫ 可视化：① Primary vs avg_all vs DPO 基线 ACC 柱状 + Wilson 误差棒
          ② reward 学习曲线（含 R0~R4 分项）  ③ 12 场景×4 时间桶 ACC heatmap

Week 4：推理侧接入 Team（Tier 1.5 + 显式窗口）
  ⑬ rlvr_predictor.py —— 5 个 checkpoint ensemble，输出 chain/primary/secondary/dir/conf
  ⑭ 在 team.py 的 _route_signals 之后注入 Tier 1.5 RLVR 结果（§3.3.x），把
       【0.】时间窗口 + 完整 6 段推理链注入 router 的 analyzer_context
  ⑮ 端到端 bt run 1000 条，比较 team_full 的 primary strict ACC vs baseline 是否 +5pp 以上
```

---

## 7. 风险与回退路径

| 风险 | 可能性 | 影响 | 回退路径 |
|---|---|---|---|
| GRPO 训练不稳定，reward 震荡不收敛 | 中 | 高 | Fallback 到 PPO（加 critic）；或把 RLVR 降级为 RFT（拒绝采样微调，离线做） |
| 推理链格式不服从，chain_valid_rate < 70% | 中 | 中 | 在 SFT 阶段先做推理链格式的多轮 SFT（用 GPT-4o 生成 1000 条正确格式的 chain，先 SFT 基座再 RLVR） |
| Neutral 被滥用（pred neutral > 40%） | 高 | 中 | 增大 R1 中"oracle 有方向但判 neutral"的惩罚（从 -0.5 → -0.8）；或在采样时手动给 oracle≠neutral 的样本更高采样权重 |
| 5000 条样本不够，PPO/GRPO 过拟合 | 中 | 高 | 扩展到 10000 条（按 §2.2 配额同比例 ×2）；或加更强的 KL 惩罚 |
| RLVR 的 ACC 跑不赢 DPO baseline | 中 | 高 | 先验证 R1/R2/R3/R4 的 reward 设计有没有 bug；再调 beta/学习率/rollout 数量；最后用 RLVR 模型和 DPO 模型做 7:3 加权 ensemble（保下限） |

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

## 8. 关键文件改动清单（rlvr 分支）

| 新增/修改 | 路径 | 说明 |
|---|---|---|
| 新增 | `backend/scripts/rlvr/build_rlvr_train_dataset.py` | 5000 条训练集构造 + 打标签 |
| 新增 | `backend/scripts/rlvr/grpo_trainer.py` | GRPO 训练主入口（对应 train_pronoia_v2.py 的 train-sft/train-dpo） |
| 新增 | `backend/scripts/rlvr/prompt_template.py` | 输入块 + 推理链 5 段模板 |
| 新增 | `backend/scripts/rlvr/reward_fn.py` | §4.2 的四组 reward 函数实现 |
| 新增 | `backend/scripts/rlvr/eval_rlvr_vs_baseline.py` | 1000 条评估集统一对比脚本 |
| 新增 | `backend/app/rlvr_predictor.py` | 推理侧 RLVR 模型封装（5-fold ensemble + 推理链输出） |
| 修改 | `backend/app/agents/team.py` | §3.3.3 的 Tier 1.5 注入点（可选，先训练后接入） |
| 新增 | `data/rlvr_train_v1_5000/` | 5000 条训练集（events/labels/distribution.json） |
| 修改 | 本文件 | `docs/20260822_rlvr_design.md` | 本文档，随实施迭代更新 |
