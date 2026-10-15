# WWW 中稿论文实证分析：4 篇相似论文的写作风格与实验安排

> 基于真实检索到的 WWW 2025/2026 中稿论文全文分析，对比 PRONOIA 当前稿件（v0.2）。
> 检索日期：2026-10-15。

---

## 一、检索到的 4 篇高度相似中稿论文

| # | 论文 | 会议 | 与 PRONOIA 的相似点 |
|---|---|---|---|
| 1 | **Janus-Q: End-to-End Event-Driven Trading via Hierarchical-Gated Reward Modeling** (HKUST-GZ + IDEA) | arXiv 2026.02（目标 WWW 类会议） | **最相似**：事件驱动 + CAR 标签 + RL 奖励模型 + SFT→RL 两阶段 |
| 2 | **When Agents Trade: Live Multi-Market Trading Arena for LLM Agents (AMA)** | **WWW 2026 主会** | Arena 评测系统 + LLM Agent + 真实市场 |
| 3 | **HedgeAgents: A Balanced-aware Multi-agent Financial Trading System** | **WWW 2025 Companion** | 多 Agent 金融系统 + 真实市场部署 |
| 4 | **Ploutos: Towards Explainable Stock Movement Prediction with Financial LLM** (Microsoft) | **WWW 2025 Companion** | 股票走势预测 + 可解释性 + 多专家架构 |

**重要发现：** 金融 + LLM + Agent 是 WWW 近两年的活跃方向，AMA 甚至进了 2026 主会。赛道成立，但竞争也在加剧——Janus-Q 与 PRONOIA 的技术路线（事件→CAR→RL 奖励）几乎正面撞车，必须在写作中明确区分。

---

## 二、4 篇论文的结构解剖

### 2.1 Janus-Q（方法与 PRONOIA 最相似）

```
1. Introduction
   ├─ Figure 1：传统时序驱动 vs 事件驱动的范式对比图（第 1 页！）
   ├─ Challenge 1: Lack of Event–Market Granularity（数据粒度问题）
   ├─ Challenge 2: Misalignment Between Semantic Reasoning and Market Reality（语义-市场鸿沟）
   ├─ Table 1：现有金融事件数据集对比表（在 Introduction 里！）
   │   （列：Event Typing / Open Source / Sentiment / CAR / Domain / #Types / Size / Language）
   └─ 3 条贡献（数据集 + 框架 + 实验结果）

2. Related Work（只有 2 个小节！）
   ├─ 2.1 Event-Driven Modeling
   └─ 2.2 LLM for Trading

3. Methodology
   ├─ 3.1 Event Centric Data Construction（数据先行！）
   │   ├─ 3.1.1 Event-to-CAR Modeling
   │   └─ 3.1.2 Event Taxonomy and Sentiment Annotation
   └─ 3.2 Decision-Oriented Finetuning
       ├─ 3.2.1 Hierarchical-Gated Reward Modeling（总览）
       ├─ 3.2.2 Hard gate: Direction correctness
       ├─ 3.2.3 Soft gate: Event-type consistency
       ├─ 3.2.4 Trading reward: cost-aware PnL
       ├─ 3.2.5 Magnitude shaping and process reward
       └─ 3.2.6 Overall reward

4. Experiment Results
   ├─ 4.1 Setup / 4.2 Evaluation Objective / 4.3 Dataset & Metrics / 4.4 Baseline
   ├─ 4.5 RQ1: Baseline Comparison
   ├─ 4.6 RQ2: 组件消融 + RQ3: 奖励目标消融
   └─ 4.7 RQ4: Case Study（Human Alignment in Event Interpretation）

5. Conclusion

Appendix（内容量大）
   ├─ A.1 超参 + 数据集 + 指标细节
   ├─ A.2 事件实证研究（历史 CAR 统计、历史幅度、事件类型加权影响）
   ├─ A.3 风险模型设置
   ├─ A.4 敏感性分析（持有期、最大仓位比例）
   └─ A.5 全部 Prompts
```

**数据规模：** 62,400 篇专家标注新闻、10 类事件、CAR 标签。
**核心指标：** Sharpe Ratio（+102.0%）、方向准确率（+17.5%）、事件类型准确率（+18.2%）、最大回撤。
**基线：** 市场指数 + 时序模型 + vanilla LLM + 金融 LLM（四类基线！）。

### 2.2 AMA / When Agents Trade（WWW 2026 主会，系统与 PRONOIA 最相似）

```
1. Introduction
   └─ 问题：大多数研究"测模型不测 Agent"、周期短、资产少、数据未验证

2. Related Work（只有 2 个小节）
   ├─ 2.1 Benchmarking LLMs in Financial Domain
   └─ 2.2 Trading Agents and Live Benchmark

3. Agent Market Arena: Real-time trading and competition（系统章）
   ├─ 3.1 Market Intelligence Stream (MIS)
   ├─ 3.2 Agent Execution Protocol (AEP)
   └─ 3.3 Performance Analytics Interface (PAI)

4. Experiment Settings（独立一章，很短）

5. Results（全部 RQ 驱动）
   ├─ 5.1 RQ1: Performance of Agents in Live Trading
   ├─ 5.2 RQ2: Which Matters More: Agent Architecture or LLM Backbone? ← 核心系统问题
   ├─ 5.3 RQ3: Understanding Agents' Decision-Making Driven by Market Signals
   └─ 5.4 RQ4: Revealing the Influence of Agent Trading Styles and Patterns

6. Conclusion

Appendix: A. 质量控制细节 / B. Agent 执行协议 / C. 分析界面（Dashboard 截图）
```

**实验设计：** 4 种 Agent 架构 × 5 个 LLM backbone × 2 个市场（加密货币 + 股票），**实盘实时**运行。
**关键结论（WWW 喜欢的系统洞察）：** "Agent 框架对结果的区分度远大于模型 backbone"——一个可迁移的、超越本文的系统级发现。

### 2.3 HedgeAgents（WWW 2025 Companion）

```
1. Introduction
   ├─ Figure 1：PRUDEX 六维雷达图（第 1 页展示"我们全维度赢"）
   ├─ Figure 2：SOTA 模型在真实场景中 TR/SR/CR 大面积为负（动机图）
   └─ 贡献：70% 年化收益、3 年 400% 总回报、代码开源

2. Related Work（2 小节：Quantitative Finance / LLM-based Agent）

3. Proposed Method
   ├─ 3.1 Preliminaries / 3.2 Overall Framework
   ├─ 3.3 单 Agent 定义（23 工具、8 动作、3 记忆）
   └─ 3.4 多 Agent 协调（3 种会议机制）

4. Experiments
   ├─ 4.1 Datasets / 4.2 Metrics / 4.3 Implementation
   ├─ 4.4 Overall Performance Comparison
   ├─ 4.5 Ablation × 2（会议机制消融 + LLM backbone 消融）
   ├─ 4.6 Single-Asset Performance（无对冲对照）
   └─ 4.7 Visualization × 2（单 Agent 行为可视化 + 对冲专家行为可视化）← 专门一节！

5. Conclusions
```

**写作特点：** 结果数字直接写进 Introduction（"400% total return"）；Agent 行为**可视化**是独立实验小节；极端市场场景（暴跌、高频波动）单独评估。

### 2.4 Ploutos（WWW 2025 Companion，Microsoft）

- 双组件框架：PloutosGen（多专家多模态分析）+ PloutosGPT（生成可解释 rationale）
- 训练策略：rearview-mirror prompting（用历史数据+专家分析引导）+ dynamic token weighting
- 核心卖点：**rationale 的忠实性（faithfulness）**——解释必须真实反映模型决策依据，不是"听起来合理"

---

## 三、写作风格共性（这就是 WWW 的 taste）

### 3.1 结构层面的 6 条铁律

| 规律 | 证据 | PRONOIA 现状 |
|---|---|---|
| **1. Figure 1 必须是范式对比图，放第 1 页** | Janus-Q Fig 1（时序 vs 事件驱动）、HedgeAgents Fig 1（六维雷达图全胜） | ❌ PRONOIA 第 1 页纯文字 |
| **2. Introduction 里放数据集对比表** | Janus-Q Table 1：8 个数据集 × 8 个维度，"Ours"一行全勾 | ❌ 没有 |
| **3. 问题用 Ch1/Ch2 两个挑战框定** | Janus-Q、AMA 都是"两个挑战"结构 | ⚠️ PRONOIA 列了 3 个问题但偏学术 |
| **4. Related Work 只有 2 个小节** | 4 篇全部如此（领域 + 方法各一节） | ❌ PRONOIA 有 6 小节，严重超标 |
| **5. 实验全部 RQ 驱动** | RQ1 主对比 → RQ2 组件消融 → RQ3 奖励/机制消融 → RQ4 案例+人类对齐 | ❌ PRONOIA 按"规则回测/RLVR/消融"平铺 |
| **6. Appendix 承载所有细节** | 超参、敏感性分析、全部 Prompt、界面截图 | ⚠️ PRONOIA 附录偏薄 |

### 3.2 叙事风格共性

1. **数字进 Abstract 和 Introduction。** HedgeAgents："70% annualized return, 400% total return over 3 years"。Janus-Q："Sharpe +102.0%, direction accuracy +17.5%"。数字是最强的 hook。
2. **动机图讲"现有方法不行"。** HedgeAgents Figure 2：9 个基线在暴跌场景 8 个亏损——用图证明问题真实存在。
3. **每篇都有一个"超越本文"的系统级结论。** AMA："框架比 backbone 重要"。这是审稿人引用这篇论文的理由。
4. **诚实但不自贬。** 4 篇都承认局限，但都转化为 future work 或设计约束，不渲染失败。

---

## 四、实验安排共性

### 4.1 WWW 金融论文的标准实验矩阵

| 实验类型 | Janus-Q | AMA | HedgeAgents | PRONOIA 现状 |
|---|---|---|---|---|
| **主对比（RQ1）** | vs 指数+时序+vanilla LLM+金融LLM | 4 Agent × 5 backbone × 2 市场 | vs 9 个基线 | ⚠️ 仅 base/v6.1-b/v6.2 三个内部版本 |
| **交易指标** | Sharpe/TR/MDD | 收益/Sharpe/回撤 | TR/SR/CR/年化 | ❌ **没有！只有断言准确率** |
| **组件消融（RQ2）** | 每个 reward 分量 | 架构 vs backbone | 每种会议机制 | ✅ 有（reward 消融） |
| **机制消融（RQ3）** | 奖励目标多样性 | 决策驱动因素 | LLM backbone 替换 | ⚠️ 缺系统组件消融 |
| **案例+人类对齐（RQ4）** | 事件解读与人工判断一致性 | 交易风格分析 | 行为可视化 | ⚠️ 有案例但无人类对齐维度 |
| **敏感性分析** | 持有期、仓位比例（附录） | — | — | ❌ 没有 |
| **极端场景** | — | 多市场实时 | 暴跌/高波动专场 | ⚠️ 有 spike-crash 类型但未专场分析 |
| **可视化专节** | — | Dashboard | 独立 4.7 节 | ❌ 没有 |

### 4.2 实验量的"及格线"

从 4 篇反推 WWW 金融方向的实验量标准：

- **基线数量：** ≥ 4 类（指数/传统方法/通用 LLM/领域 LLM），总基线 6-10 个
- **主结果表：** 1-2 张大表（多模型 × 多指标）
- **消融表：** 2-3 张（组件 + 机制 + 目标）
- **图：** 4-7 个（范式图 + 架构图 + 结果图 + 行为可视化）
- **案例：** 1-2 个深度案例（带人类对齐或风格分析）
- **附录实验：** 敏感性分析 + 统计细节 + Prompt

---

## 五、PRONOIA 的具体差距与行动

### 差距 1（致命）：没有交易/投资指标

4 篇全部报告 PnL 类指标（Sharpe、收益、回撤）。PRONOIA 只有断言准确率（63.2%）、Brier、ECE——这是 ML 会议语言，不是 WWW 金融语言。

**行动（必须做）：** 把现有规则回测和断言结果翻译成交易指标：
- 用 v6.2 的断言输出构造一个简单组合策略（TRUE 侧做多强置信事件、FALSE 侧回避），报告 Sharpe、年化、最大回撤，与买入持有 + base 模型策略对比
- 哪怕结果一般也要放——AMA 的核心结论是"不同 Agent 风格差异巨大"，同样可以是 PRONOIA 的叙事
- 半天到一天的工作量，用现有 1,034 事件结算数据即可

### 差距 2（严重）：基线全是内部版本

base → v6.1-b → v6.2 是"自己跟自己比"。4 篇论文都比了外部系统。

**行动（必须做）：**
- 至少加 2 个外部 LLM 基线：GPT-4o/Claude 直接生成断言（zero-shot）、FinGPT 类金融 LLM
- 如果 API 成本受限，可以在 100-200 事件子集上跑，标注为 "subset evaluation"
- 加 1 个传统基线：历史同类事件查表法（ERC 的查表版）

### 差距 3（严重）：Related Work 6 小节 → 压到 2 小节

```
2.1 Event-Driven Financial Analysis（合并：事件研究 + 金融 LLM + 金融 RL）
2.2 LLM Agents with Verifiable Rewards（合并：Web agents + RAG + 工具使用 + RLVR）
```
WWW 的 Related Work 是"定位自己"，不是"综述领域"。省出的约 0.7 页全部让给实验。

### 差距 4（严重）：实验无 RQ 结构

**行动：** 重组为——
- **RQ1:** PRONOIA 的断言准确率与交易表现是否优于 LLM 基线？（主对比表 + 新交易指标）
- **RQ2:** PAV 契约与传导图各自贡献多少？（系统组件消融：去掉图、去掉断言、仅方向预测）
- **RQ3:** RLVR 各奖励分量的作用与失效模式？（现有消融 + reward hacking 分析）
- **RQ4:** 模型的失败模式与人类分析师判断是否对齐？（3 个案例重构：加"人类分析师在当时会如何判断"）

### 差距 5（中等）：缺 Figure 1 范式对比图 + 数据集对比表

**行动：**
- Figure 1：传统事件研究（事后描述）vs LLM 直接预测（无真值）vs PRONOIA（市场验证闭环）三方对比图，放第 1 页
- Table 1：对照 Janus-Q Table 1，做"金融事件分析系统对比"表（列：事件结构化/传导推理/逐条可验证/市场结算/开源/中文市场），ChFinAnn、DuEE-Fin、FNSPID、Janus-Q、Ours——直接借用 Janus-Q 的表格式，加我们的差异化列

### 差距 6（中等）：无敏感性分析与行为可视化

**行动（可选但加分）：**
- 附录加置信度阈值敏感性（0.5/0.6/0.7/0.8 阈值下准确率-覆盖率曲线——已有数据可直接画）
- 断言数量 vs 准确率的关系图（2-3 条断言最优，已有数据）

### PRONOIA 独有的、4 篇都没有的优势（要放大）

1. **逐条可验证断言（per-claim verification）。** Janus-Q 只验证方向和盈亏，PRONOIA 把预测拆成 3-6 条独立可结算断言——这是 RLVR 在金融上的独特落地，也是最强的差异化点。
2. **Reward hacking 的实证文档。** v6.1-b 训练奖励 +0.21 但 OOS -2.29pt——4 篇论文没有一篇敢这么写。对 WWW 审稿人这是"可复用的教训"，对标 AMA 的"框架 > backbone"。
3. **校准分析（Brier/ECE/reliability bins）。** 4 篇都没做概率校准。置信度 0.75-0.85 bin 实际只有 0.53-0.59——这个发现本身就是贡献。
4. **中文 A 股市场。** Janus-Q 也是中文数据（62,400 篇），但 PRONOIA 的传导图 + 事件类型覆盖是差异化。

---

## 六、与 Janus-Q 的正面区分（必须写进 Related Work）

| 维度 | Janus-Q | PRONOIA |
|---|---|---|
| 预测目标 | 交易动作（买/卖/仓位） | **可证伪断言集合**（方向+幅度+显著性+基准） |
| 验证粒度 | 整体 PnL | **逐条断言独立结算** |
| 奖励设计 | 层级门控（方向硬门 + 类型软门 + PnL） | 分层归一化奖励 + 语义护栏 + **reward hacking 实证** |
| 推理结构 | 单模型 CoT | **传导图 + Navigator-Searcher 多 Agent** |
| 失败分析 | 无 | **系统性负结果 + 校准分析** |
| 数据 | 62,400 篇新闻（私有标注） | 4,965 事件（**开源 pipeline 可复现**） |

写作建议：在 Related Work 末尾加一段 "Concurrent work Janus-Q..."，主动对比——审稿人很可能就是 Janus-Q 的审稿人，回避等于送死。

---

## 七、修订后的实验清单（按优先级）

| 优先级 | 实验 | 工作量 | 数据现状 |
|---|---|---|---|
| P0 | 断言→交易策略的 Sharpe/收益/回撤 | ~1 天 | 用现有 1,034 结算事件 |
| P0 | 外部 LLM 基线（GPT-4o zero-shot，子集） | ~0.5 天 | 需 API 调用 100-200 事件 |
| P0 | RQ 化重组（纯写作） | ~0.5 天 | 无需新实验 |
| P1 | 系统组件消融（去传导图/仅方向预测） | ~1 天 | 仅方向可从现有断言推导；去传导图需重跑 base 推理 |
| P1 | 置信度阈值-覆盖率敏感性曲线（附录） | ~2 小时 | 数据已有，纯画图 |
| P1 | 案例加"人类对齐"维度（纯写作） | ~0.5 天 | 无需新实验 |
| P2 | Figure 1 范式对比图 + Table 1 系统对比表 | ~0.5 天 | 纯制作 |
| P2 | 断言数量 vs 准确率图 | ~2 小时 | 数据已有 |

**总新增工作量约 3-4 天**，其中真正的"新实验"只有 P0 两项（交易指标 + 外部基线），其余都是现有数据的重组和可视化。实验量上，PRONOIA 的 1,034 OOS 事件 + 4,965 训练事件 + 3 模型版本 + 消融已经达到 WWW 及格线，缺的是**指标维度**和**对比广度**，不是数据规模。

---

## Sources

- [Janus-Q: End-to-End Event-Driven Trading via Hierarchical-Gated Reward Modeling (arXiv 2602.19919)](https://arxiv.org/html/2602.19919)
- [When Agents Trade: Live Multi-Market Trading Benchmark for LLM Agents (arXiv 2510.11695, WWW 2026)](https://arxiv.org/abs/2510.11695)
- [When Agents Trade (ACM DL, WWW 2026)](https://dl.acm.org/doi/pdf/10.1145/3774904.3792821?download=true)
- [HedgeAgents: A Balanced-aware Multi-agent Financial Trading System (WWW 2025 Companion)](https://arxiv.org/html/2502.13165)
- [Ploutos: Towards Explainable Stock Movement Prediction with Financial LLM (WWW 2025 Companion)](https://portal.acm.org/doi/10.1145/3701716.3715254)
- [Ploutos arXiv PDF](https://arxiv.org/pdf/2403.00782v1)
- [The Web Conference 2026 Accepted Papers - Industry Track](https://www2026.thewebconf.org/accepted/industry.html)
- [The Web Conference 2026 Accepted Papers - Research Tracks](https://www2026.thewebconf.org/accepted/research-tracks.html)
- [The Web Conference 2026 Full Schedule](https://www2026.thewebconf.org/program/full-schedule.html)
