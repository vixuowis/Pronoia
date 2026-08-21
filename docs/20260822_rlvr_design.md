# RLVR 后训练方案设计 v1（2026-08-22）

> 分支：`rlvr`（已创建自 `main`）  
> 目标：用 **RL from Verifiable Reward**（基于真实市场 CAR 的可验证奖励信号）替代/增强纯 SFT+DPO，让方向判别模型直接对最终正确的前瞻判断负责，并在输出中保留结构化推理链。

---

## 0. 背景与定位

现有训练脚手架（[train_fever_v2.py](file:///workspace/backend/scripts/train_fever_v2.py)）已打通：

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

### 2.3 训练集构造方式

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

并复用 [train_fever_v2.py:L48-L88](file:///workspace/backend/scripts/train_fever_v2.py#L48-L88) 的 `stable_stratified_split_ids` 做 5-fold split（按 market×L2×ym 分层），产出：
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
- **复用现有管线**：现有 SFT 脚手架 [train_fever_v2.py:L143-L144](file:///workspace/backend/scripts/train_fever_v2.py#L143-L144) 的 LoRA r=16 配置、trl/peft 接口完全兼容，只改 `model_name` 一行。RLVR 阶段直接加载 SFT 的 LoRA 做 warm start。
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

#### 3.3.1 总体思路：推理链 = "CoT Reasoning Block"，夹在 Input 和 Final Verdict 之间

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
│  格式：中文分段标签，共 5 段                                    │
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
│    三选一：up / down / neutral                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  REWARD COMPUTATION（用 Oracle 计算，不回传模型训练）          │
│  • 方向匹配 reward（离散）                                     │
│  • 置信度校准 reward（连续）                                   │
│  • CAR 幅度加权（连续）                                        │
│  • 推理链一致性 penalty（可选离散）                            │
└─────────────────────────────────────────────────────────────┘
```

#### 3.3.2 推理链与现有 Team Pipeline 的映射关系

RLVR 训练的模型本质上是一个 **"轻量化方向判别器"**，对应 team pipeline 中两个位置的融合：

| RLVR 推理链分段 | 对应 Team Pipeline 中的角色 | 说明 |
|---|---|---|
| 【1. 关键信号提取】 | `announcement_classifier` + `market_research` 原始信号 | 从 event_text + T0 行情提取结构化信号 |
| 【2. 横向比较】 | Tier 2 skill `ar_decomposer` / `drift_context_analyzer` | AR 分解、漂移出尽系数、同比环比 |
| 【3. 反方与限制】 | deep_researcher 的 Claim 生成（"反方/限制"段落） | 对应 [roster.py:L199-L205](file:///workspace/backend/app/agents/roster.py#L199-L205) 的解读卡片 Step 3 |
| 【4. 置信度校准】 | synthesize 阶段 analyzer_scorecard.confidence | 对应 [team.py:L706-L744](file:///workspace/backend/app/agents/team.py#L706-L744) |
| 【5. 最终方向】 | router synthesize 输出的 `【最终方向】` | 对应 [team.py:L765-L769](file:///workspace/backend/app/agents/team.py#L765-L769) |

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

### 4.2 Reward 函数（四部分加权求和，总范围 [-1.5, +2.0]）

对一条 rollout（event → 推理链 → 方向 + confidence），reward 由 4 项线性加权：

#### R1：方向正确性（权重 0.5，范围 [-1, +1]）
```python
oracle = label_avg_all   # up / down / neutral
pred   = final_direction # up / down / neutral

if oracle == "neutral":
    R1 = +0.5 if pred == "neutral" else -0.5
else:  # oracle ∈ {up, down}
    if pred == oracle:     R1 = +1.0   # 方向正确
    elif pred == "neutral": R1 = -0.5  # 该判不判（用 neutral 逃避）
    else:                  R1 = -1.0   # 方向错误
```

#### R2：置信度校准（权重 0.3，范围 [-0.3, +0.3]）
只在 oracle ≠ neutral 且 pred ≠ neutral 时生效：
```python
if oracle != "neutral" and pred != "neutral":
    # 方向对时 confidence 越高奖励越多；方向错时 confidence 越高惩罚越重
    sign = +1.0 if pred == oracle else -1.0
    R2 = sign * (confidence - 0.5) * 0.6   # confidence=0.99 → +0.294，方向错的话 → -0.294
else:
    R2 = 0.0
```

#### R3：CAR 幅度加权（权重 0.15，范围 [0, +0.3]）
Oracle CAR 大的事件，正确判断的奖励更高（因为实战收益更大）：
```python
car_abs = abs(car_avg_all)
if (oracle != "neutral") and (pred == oracle):
    # 分段线性：|CAR|<0.5% → 0，0.5%~5% → 线性上升到 1，>5% → 饱和 1
    w = min(1.0, max(0.0, (car_abs - 0.005) / 0.045))
    R3 = 0.3 * w
else:
    R3 = 0.0
```

#### R4：推理链一致性检查（权重 0.05，范围 [-0.05, +0.05]）
用规则匹配（不需要额外 LLM）硬检查：
- 5 段标签是否齐全且顺序正确（【1.】【2.】【3.】【4.】【5.】）
- 【1.关键信号】中是否包含 ≥2 个数字/百分比
- 【5.最终方向】中的值是否与最终 pred_direction 完全一致
- 【4.置信度校准】中的数字和最终输出 confidence 差 ≤ 0.05

全部满足 → +0.05；任一违反 → -0.05。

#### 总 Reward
```python
reward = 0.5*R1 + 0.3*R2 + 0.15*R3 + 0.05*R4
```

**预期 reward 基准（随机模型）**：≈ (0.5*(0)) + 0 + 0 + (-0.05) ≈ **-0.05**  
**训练目标**：hold-out 平均 reward ≥ **+0.40**（对应非 neutral 准确率 ~70% + 置信度校准良好）。

---

## 5. 评估方案（固定 1000 条）

### 5.1 训练过程中的评估（每 epoch 一次）

用 [train_fever_v2.py:L172-L229](file:///workspace/backend/scripts/train_fever_v2.py#L172-L229) 的 `score-all` 同款逻辑，输出：

| 指标 | 计算方式 | RLVR 目标 |
|---|---|---|
| `acc_avg_all_strict`（主指标） | pred 与 label_avg_all 完全一致的比例，neutral 算错 | **≥ 65%**（SFT 基线约 55~60%） |
| `acc_avg_all_non_neutral` | 只在 oracle∈{up,down} 时计分（实战口径） | **≥ 75%** |
| `wilson_lo_95_acc_avg_all_strict` | Wilson 95% CI 下限 | **≥ 62%**（下限过线才是真过线） |
| `avg_reward_holdout` | 5000 训练集 5-fold hold-out 平均总 reward | **≥ +0.35** |
| `chain_valid_rate` | R4 检查通过率 | **≥ 90%** |
| `neutral_frac_pred` | 预测为 neutral 的比例 | **10%~20%**（避免滥用） |
| `conf_ece` | 置信度 ECE（Expected Calibration Error） | **≤ 0.08** |

### 5.2 与 SFT/DPO 的 A/B 对比（必须）

同一评估集上，同时跑：
1. **Baseline**：现有 SFT → DPO 的 5-fold 模型（已有的 `fever_dpo_fold*/last`）
2. **RLVR**：SFT 基座 → RLVR（GRPO）的 5-fold 模型
3. **Oracle**：`label_avg_all`（理论上限，≈100% ACC）
4. **Random**：按评估集 up/down/neutral 比例随机猜（≈ ACC 39%）

用 Wilson 95% CI 看 RLVR 对 DPO 的提升是否显著（`p < 0.05`，两样本比例 z-test）。

### 5.3 按 market / L2 分层过线标准

参考 `score-all` 的输出，每个 market / L2 分桶单独看：
- CN ≥ 63% ACC strict，US ≥ 68%（美股事件文本更结构化，预期高一点）
- 6 类 L2 中至少 4 类 strict ACC ≥ 60%，没有任何一类 < 50%

---

## 6. 实施路线图（rlvr 分支上的代码落地顺序）

```
Week 1：数据侧
  ① build_rlvr_train_dataset.py —— 按 2.2 的 12 层配额拉 5000 条 + 去重 + 打标签
  ② split_rlvr_5fold.py —— 复用 stable_stratified_split_ids 切 fold
  ③ 分布自检脚本（和评估集的 JS 散度 < 0.01）

Week 2：训练侧
  ④ rlvr/grpo_trainer.py —— 封装 trl.GRPOTrainer，实现 §4 的 reward 函数
  ⑤ rlvr/prompt_template.py —— 输入块 + 推理链 5 段格式模板（严格中文标签）
  ⑥ 跑 fold0 单 fold 小规模 smoke test（100 条，1 epoch，观察 reward 曲线上升）

Week 3：全量训练 + 评估
  ⑦ 5-fold 全量训练（每个 fold ~12~24h），产出 5 个 RLVR checkpoint
  ⑧ eval_rlvr_vs_baseline.py —— 统一拉 DPO baseline + RLVR + Oracle + Random 对比，
     输出完整指标表（ACC + Wilson CI + 分桶 + ECE + chain_valid_rate）
  ⑨ 可视化：RLVR vs DPO 的 ACC 柱状图 + reward 学习曲线

Week 4：推理侧接入 Team
  ⑩ rlvr_predictor.py —— 离线推理封装（load 5 个 checkpoint ensemble）
  ⑪ 在 team.py 的 _route_signals 之后注入 RLVR 结果（§3.3.3 的 Tier 1.5）
  ⑫ 端到端 bt run 1000 条，看 team_full 的 ACC 是否比 baseline 提升
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

## 8. 关键文件改动清单（rlvr 分支）

| 新增/修改 | 路径 | 说明 |
|---|---|---|
| 新增 | `backend/scripts/rlvr/build_rlvr_train_dataset.py` | 5000 条训练集构造 + 打标签 |
| 新增 | `backend/scripts/rlvr/grpo_trainer.py` | GRPO 训练主入口（对应 train_fever_v2.py 的 train-sft/train-dpo） |
| 新增 | `backend/scripts/rlvr/prompt_template.py` | 输入块 + 推理链 5 段模板 |
| 新增 | `backend/scripts/rlvr/reward_fn.py` | §4.2 的四组 reward 函数实现 |
| 新增 | `backend/scripts/rlvr/eval_rlvr_vs_baseline.py` | 1000 条评估集统一对比脚本 |
| 新增 | `backend/app/rlvr_predictor.py` | 推理侧 RLVR 模型封装（5-fold ensemble + 推理链输出） |
| 修改 | `backend/app/agents/team.py` | §3.3.3 的 Tier 1.5 注入点（可选，先训练后接入） |
| 新增 | `data/rlvr_train_v1_5000/` | 5000 条训练集（events/labels/distribution.json） |
| 修改 | 本文件 | `docs/20260822_rlvr_design.md` | 本文档，随实施迭代更新 |
