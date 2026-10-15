# WWW 2027 投稿策略分析：PRONOIA 论文差距与优化路线

> 基于 WWW (The Web Conference) 近年录取偏好、Industry Track 特点、以及 PRONOIA 当前稿件状态的深度分析。

---

## 一、WWW 会议的核心 Taste

### 1.1 WWW 到底要什么

WWW 不是纯 ML 会议（那是 NeurIPS/ICML），也不是纯 NLP 会议（那是 ACL/EMNLP），更不是纯金融会议。WWW 的核心定位是：

> **"Web 作为平台，产生了什么新的科学问题和技术挑战？"**

| 维度 | WWW 偏好 | 反例（不适合 WWW） |
|---|---|---|
| **问题来源** | Web 规模、Web 结构、Web 用户行为产生的独特问题 | 通用 ML 算法改进（无 Web 场景特异性） |
| **数据特性** | 异构、 noisy、大规模、实时、多模态 Web 数据 | 干净的小规模基准数据集 |
| **系统视角** | 端到端系统、用户交互、部署约束、真实反馈循环 | 纯算法、离线评估、无系统组件 |
| **影响评估** | 真实用户影响、业务指标、社会效应 | 仅学术指标（准确率、F1） |
| **方法论** | Web 挖掘、图挖掘、信息检索、推荐、NLP、Agent | 纯 CV、纯语音、纯机器人 |

### 1.2 WWW 2024-2026 热点方向

根据近年录取论文趋势，以下方向在 WWW 特别受欢迎：

1. **LLM Agents for Web Tasks** — WebArena、WorkArena、VisualWebArena 系列工作
2. **Retrieval-Augmented Generation (RAG)** — 特别是结构化检索、图检索、多跳推理
3. **Web-scale Knowledge Graphs** — 构建、补全、推理、应用
4. **User Behavior Modeling** — 点击流、会话、推荐、搜索
5. **Web Trust & Safety** — 虚假信息检测、偏见、隐私
6. **Conversational AI / Chatbots** — 任务导向对话、工具使用、多轮推理
7. **Time-series / Temporal Web Mining** — 趋势预测、事件检测、异常检测
8. **Multi-agent Systems on Web** — 协作、竞争、涌现行为

### 1.3 Industry Track 的特殊性

Industry Track 不是 "Research Track 的降级版"，而是有不同评价标准：

| 维度 | Research Track | Industry Track |
|---|---|---|
| **核心问题** | 科学贡献是什么？ | 系统解决了什么真实问题？ |
| **评估重点** | 方法新颖性、理论深度、实验严谨性 | 系统实用性、可扩展性、真实影响、工程挑战 |
| **失败容忍** | 低（方法必须 work） | 中（可以讨论失败和教训） |
| **篇幅分配** | Method > Experiments > Related Work | System > Lessons Learned > Case Studies |
| **图表偏好** | 算法图、实验结果图 | 系统架构图、部署截图、用户交互流程 |
| **写作风格** | 学术严谨 | 工程实用、讲故事、有教训 |

**Industry Track 经典结构：**
1. 问题背景（真实业务痛点）
2. 系统架构（怎么设计的，为什么这么设计）
3. 关键挑战与解决方案（工程难点，不是算法难点）
4. 部署与评估（真实环境，真实指标）
5. 经验教训（什么 work，什么不 work，为什么）

---

## 二、PRONOIA 当前稿件 vs WWW Taste 差距分析

### 2.1 当前稿件的优势（已经符合 WWW 的）

| 方面 | 现状 | WWW 契合度 |
|---|---|---|
| Web Relevance 段落 | ✅ 第 1 页有专门段落 | 高 — 明确连接 Web agents、RAG、在线反馈 |
| 系统部署 | ✅ 开源 Web 应用，85+ 数据技能 | 高 — Industry Track 核心要求 |
| 真实反馈循环 | ✅ 市场数据结算，非 LLM-as-judge | 高 — WWW 喜欢的 "real-world grounding" |
| 多 Agent 协作 | ✅ Navigator-Searcher 协议 | 中高 — 符合多智能体系统热点 |
| 图结构推理 | ✅ Propagation Graph | 高 — 图挖掘是 WWW 传统强项 |
| 负结果报告 | ✅ Reward hacking 文档 | 中高 — Industry Track 欣赏诚实教训 |
| 开源 | ✅ GitHub 仓库 | 高 — WWW 鼓励可复现性 |

### 2.2 关键差距（必须修复的）

#### 差距 1：Web 特性的深度不够

**问题：** 当前稿件主要讲 "金融 + LLM + RL"，Web 特性是 "贴上去" 的，不是 "长出来" 的。

**WWW 审稿人会问：**
- 这个问题为什么必须在 Web 环境下解决？
- Web 的什么特性（规模、异构性、实时性、噪声）使得传统方法失效？
- 如果没有 Web，这个问题还存在吗？

**当前稿件的弱点：**
- 数据主要来自 akshare/yfinance API，不是典型的 "Web 数据"（HTML、社交媒体、用户生成内容）
- 没有强调 Web 的实时性、异构性、噪声特性如何影响系统设计
- 缺少 Web 用户交互数据（研究者如何使用系统，行为日志）

**修复策略：**
1. **强化 Web 数据异构性**：强调公告、新闻、财报、宏观数据来自不同 Web 源，格式、质量、时效性差异巨大
2. **增加 Web 交互分析**：研究者通过 Web 界面与系统交互的会话数据、追问模式、案例复用率
3. **强调 Web 规模**：85+ 数据技能是 Web 级工具使用的体现，Arena 是 Web 级协作评测
4. **加入 Web 特有的挑战**：数据延迟、API 限流、源不一致、实时更新

#### 差距 2：Industry Track 的 "系统故事" 不够突出

**问题：** 当前稿件更像 Research Track（方法驱动），Industry Track 需要 "系统驱动"。

**当前结构 vs Industry Track 期望结构：**

| 章节 | 当前（Research 风格） | Industry Track 期望 |
|---|---|---|
| Introduction | 科学问题 + 方法贡献 | 业务痛点 + 系统价值 |
| Related Work | 学术文献综述 | 相关系统/产品对比 |
| System | 简单带过 | **核心章节**：架构、设计决策、工程挑战 |
| Experiments | 严格控制变量 | 真实环境部署 + 用户反馈 |
| Case Studies | 3 个案例 | **更多案例**：成功 + 失败 + 用户故事 |
| Lessons Learned | 分散在 Discussion | **独立章节**：什么 work，什么不 work |

**修复策略：**
1. **重组章节结构**：System Description 提前到 Related Work 之后，作为第 3 章
2. **增加 "Design Decisions" 子节**：每个关键设计选择（为什么用 DAG 不用树？为什么用 LoRA 不用全参数？为什么 3-6 条断言？）背后的工程权衡
3. **增加 "Deployment Challenges"**：真实部署中的问题（API 限流、数据延迟、用户误用、模型幻觉）
4. **增加 "User Stories"**：研究者如何使用系统的具体故事（不是抽象案例）

#### 差距 3：实验设计不符合 WWW 偏好

**问题：** 当前实验是 "ML 风格" 的（准确率、Brier、ECE），WWW 更喜欢 "系统风格" 的（端到端指标、用户影响、对比基线）。

**WWW 偏好的实验类型：**

| 类型 | 当前有 | 缺什么 |
|---|---|---|
| **端到端任务性能** | ✅ 断言准确率 | ❌ 完整研究任务完成率（如 "生成完整研究报告" 的成功率） |
| **对比基线** | ✅ Base vs v6.1-b vs v6.2 | ❌ 与其他系统的对比（FinHEAR、FinKario 等复现或引用） |
| **消融实验** | ✅ Reward 分量消融 | ❌ 系统组件消融（去掉 Arena、去掉传导图、去掉多 Agent） |
| **用户研究** | ❌ 无 | ❌ 研究者使用系统的效率提升、满意度 |
| **A/B 测试** | ❌ 无 | ❌ 在线 A/B（如不同 prompt 策略的效果） |
| **规模分析** | ❌ 无 | ❌ 数据规模/模型规模对性能的影响 |
| **错误分析** | ✅ 有（3 个案例） | ❌ 更系统的错误分类统计 |
| **效率指标** | ❌ 无 | ❌ 推理延迟、训练成本、API 调用成本 |

**修复策略：**
1. **增加端到端任务评估**：不是 "断言对不对"，而是 "这个研究任务完成得好不好"（人工评估或自动指标）
2. **增加系统对比**：引用或复现 2-3 个相关系统的结果，说明 PRONOIA 的优势
3. **增加组件消融**：证明每个系统组件（传导图、PAV、Arena、多 Agent）都有贡献
4. **增加效率指标**：训练时间、推理延迟、API 成本——Industry Track 关心这个
5. **增加用户反馈**：如果有真实用户使用数据，加入满意度/效率提升

#### 差距 4：写作风格太学术，不够 "讲故事"

**问题：** WWW Industry Track 欣赏 "工程叙事"——问题是什么、为什么这么难、我们怎么解决的、学到了什么。

**当前风格 vs WWW 偏好：**

| 方面 | 当前 | WWW 偏好 |
|---|---|---|
| 开头 | "Since Ball & Brown..."（学术史） | "Every day, thousands of financial analysts..."（场景痛点） |
| 问题陈述 | "Three fundamental problems block..."（抽象） | "An analyst reads 50 announcements/day but can deeply analyze 3..."（具体） |
| 方法介绍 | "We formalize events as state transitions..."（理论） | "The system first extracts structured events from Web announcements..."（流程） |
| 实验呈现 | 表格 + 数字 | 表格 + 数字 + **图**（趋势图、对比图、流程图） |
| 案例分析 | "Case 1 (Success)..."（标签化） | "On Jan 30, 2026, an analyst asked about Shengtong..."（叙事化） |
| 结论 | "Three takeaways..."（列表） | "Building this system taught us..."（反思） |

**修复策略：**
1. **重写 Introduction**：从一个具体场景开始（分析师的一天），引出痛点
2. **Method 部分加流程图**：系统如何处理一个具体事件（端到端流程）
3. **案例分析叙事化**：加入时间、人物、场景、冲突、解决
4. **Discussion 改为 Lessons Learned**："我们原以为 X，实际上 Y，因为 Z"

---

## 三、具体优化方案

### 3.1 结构重组（8 页 Industry Track 标准）

```
第 1 页：Title + Abstract + Introduction (含 Web Relevance)
  - 场景痛点开头（分析师困境）
  - 系统价值主张
  - Web 相关性（为什么这是 Web 问题）
  - 贡献列表（系统 + 方法 + 经验）

第 2 页：Related Work + System Overview
  - Related Work 压缩（学术文献 → 系统对比）
  - System Architecture 图（高层）
  - 核心设计决策预览

第 3-4 页：System Description（核心章节）
  - 3.1 部署平台（对话界面、85+ 技能、研究团队模式）
  - 3.2 Arena 评测系统（横向比对、统计严谨性）
  - 3.3 数据流水线（Web 源 → 结构化 → CAR 标签）
  - 3.4 关键设计决策（为什么 DAG？为什么 LoRA？为什么 3-6 断言？）
  - 3.5 工程挑战与解决方案（API 限流、数据延迟、幻觉控制）

第 5 页：Method（方法核心）
  - ERC 四层架构
  - Propagation Graph
  - PAV 契约
  - RLVR 训练

第 6 页：Experiments
  - 数据集与协议
  - 规则回测（骨架验证）
  - PAV-RLVR 主结果
  - 消融实验

第 7 页：Analysis + Case Studies
  - 按事件类型/指标族/horizon 分析
  - 3 个深度案例（叙事化）
  - 错误分类统计

第 8 页：Lessons Learned + Conclusion
  - 什么 work（市场确认、可证伪断言、长窗）
  - 什么不 work（残差修正、TRUE 侧动量、基准族）
  - 为什么（分析原因）
  - 未来方向
```

### 3.2 内容增强清单

#### 必须新增的内容

| 内容 | 位置 | 目的 | 篇幅 |
|---|---|---|---|
| **场景化开头** | Introduction 第 1 段 | 吸引 Industry Track 审稿人 | 0.3 栏 |
| **系统流程图** | System Description | 展示端到端处理流程 | 0.5 栏（图） |
| **设计决策子节** | System Description 3.4 | 展示工程权衡 | 0.8 栏 |
| **工程挑战子节** | System Description 3.5 | 展示真实部署问题 | 0.8 栏 |
| **组件消融实验** | Experiments | 证明每个组件贡献 | 0.5 栏（表格） |
| **效率指标表** | Experiments | 训练/推理成本、延迟 | 0.3 栏（表格） |
| **错误分类统计** | Analysis | 系统化的错误分析 | 0.5 栏（表格+图） |
| **用户交互流程** | System Description | 展示研究者如何使用 | 0.5 栏（图） |
| **Lessons Learned 独立章节** | Discussion | Industry Track 核心 | 1.0 栏 |

#### 必须压缩的内容

| 内容 | 当前 | 压缩到 | 原因 |
|---|---|---|---|
| Related Work 学术文献 | 6 小节 | 3-4 小节 | Industry Track 不重文献综述 |
| 方法理论细节 | 定义 + 公式 | 简化 | 保留核心，删除推导 |
| 实验统计细节 | 详细 bootstrap 描述 | 简化 | 保留关键数字，删除方法细节 |
| 未来工作 | 详细 P0-P3 | 简化 | 合并到 Lessons Learned |

### 3.3 图表优化

**当前 4 个图：**
1. ERC 四层架构图（好，保留）
2. Propagation Graph 示例（好，保留）
3. 数据流水线图（好，保留）
4. 实验结果柱状图（一般，可以更好）

**建议增加到 6-7 个图：**

| 图 | 类型 | 内容 | 位置 |
|---|---|---|---|
| Fig 1 | 系统架构图 | 端到端系统架构（前端 → 后端 → 数据 → 模型） | System Description |
| Fig 2 | ERC 架构图 | 四层架构（当前有） | Method |
| Fig 3 | 传导图示例 | 具体事件传导（当前有） | Method |
| Fig 4 | 用户交互流程 | 研究者提问 → 系统处理 → 结果呈现 | System Description |
| Fig 5 | 实验结果对比 | 多模型/多指标对比（当前有，优化） | Experiments |
| Fig 6 | 错误分析图 | 错误类型分布、按事件类型/指标族 | Analysis |
| Fig 7 | Arena 界面截图 | 实际系统界面（脱敏） | System Description |

### 3.4 实验增强方案

#### 实验 1：端到端研究任务评估（新增）

**任务：** "分析事件 X 对股票 Y 的影响，生成研究报告"

**评估维度：**
- 任务完成率（系统能否生成完整报告）
- 报告质量（人工评估：准确性、完整性、可读性）
- 时间效率（相比人工分析的时间节省）
- 用户满意度（5 分制）

**对比：**
- 人工基线（分析师手动分析）
- 无传导图版本（仅 LLM 直接回答）
- 无 PAV 版本（仅方向预测，无断言）
- 完整 PRONOIA

#### 实验 2：系统组件消融（新增）

| 配置 | 断言准确率 | 说明 |
|---|---|---|
| 完整系统 | 63.2% | 基线 |
| - Propagation Graph | ?% | 去掉图推理，仅 LLM |
| - PAV 契约 | ?% | 仅方向预测，无断言 |
| - RLVR 训练 | 57.3% | Base 模型 |
| - Arena 评测 | N/A | 不影响准确率，影响开发效率 |
| - 多 Agent | ?% | 单 Agent vs Navigator-Searcher |

#### 实验 3：效率与成本分析（新增）

| 指标 | 值 | 说明 |
|---|---|---|
| 训练时间 | 10-12h/条件 | 单 RTX 4090 |
| 推理延迟 | ?s/事件 | 端到端 |
| API 调用成本 | $?/事件 | akshare/yfinance/LLM |
| 内存占用 | ?GB | 训练/推理 |
| 并发支持 | ?事件/分钟 | 系统吞吐 |

#### 实验 4：错误分类统计（增强）

| 错误类型 | 数量 | 占比 | 示例 | 修复方向 |
|---|---|---|---|---|
| 动量偏见 | ? | ?% | 中金黄金案例 | 对冲断言机制 |
| 上游上下文污染 | ? | ?% | 中山公用案例 | 上下文自置信度 |
| 基准族外推 | ? | ?% | bm_ret_t15 0.498 | 基准族样例增强 |
| 置信度虚高 | ? | ?% | 0.75-0.85 bin 仅 0.53-0.59 | Platt 校准 |
| 格式错误 | ? | ?% | 15.8% 解析失败 | 推理侧重采样 |

---

## 四、写作风格优化

### 4.1 Introduction 重写示例

**当前（学术风格）：**
> Since Ball & Brown and Fama et al., the event study has been the cornerstone of empirical finance...

**优化后（场景风格）：**
> Every trading day, thousands of financial analysts face the same bottleneck: hundreds of corporate announcements flood in, but deep analysis of even a single event—reading the full filing, mapping transmission channels, quantifying surprise—takes hours. The result is a coverage-depth tradeoff: analysts either skim many announcements superficially or analyze few deeply. This tradeoff defines the boundary of event-driven alpha.
>
> Large Language Models promise to break this tradeoff. They can parse full announcements in seconds, detect nuanced guidance changes, and sketch cross-sector transmission chains. But three gaps block reliable deployment: (1) traditional event study methods are post-hoc descriptive, not forward-looking predictive; (2) LLM analyses lack external ground truth—"sounding reasonable" does not equal "actually correct"; and (3) no existing system closes the loop from prediction to market verification to model improvement.
>
> We present PRONOIA, an open-source Web platform that addresses all three gaps...

### 4.2 Case Study 叙事化示例

**当前（标签化）：**
> Case 2 (Failure): Zhongjin Gold Beat — all models wrong. 600489, 2026-01-28, beat. T0 limit-up +9.98%, pre20 +46% gain...

**优化后（叙事化）：**
> On January 28, 2026, Zhongjin Gold (600489) released a earnings beat announcement: net profit 48-54B, up 41.76-59.48% YoY, driven by gold price and volume increases. The market reacted immediately—T0 limit-up +9.98% with volume spike 2.03×.
>
> The as_of context available to the model contained a critical warning: "pre20 cumulative gain ~+46% + structured sell-the-news signal (-6.0) → mean-reversion risk, long-window weak upward, confidence lowered to 0.55." Yet all three models (base, v6.1-b, v6.2) produced nearly identical claims: car_t7 > 0 with confidence 0.72.
>
> The ground truth was brutal: car_t7 -14.1%, car_t30 -29.8%, car_t60 -45.6%. The stock had already priced in the good news; the announcement was the peak, not the starting point.
>
> This case reveals a systematic failure mode: when bullish text meets positive T0 reaction, the model's prior = momentum continuation. The A-share reality, however, is often mean reversion. The risk paragraph was cognitively correct—"sell-the-news" was explicitly noted—but behaviorally inert: no hedging claims were generated to express this risk.

### 4.3 Lessons Learned 章节示例

```markdown
## 8. Lessons Learned

Building and deploying PRONOIA over 6 months (13 versions, 1,034 OOS events, 4,965 training events) taught us several counterintuitive lessons:

### 8.1 What Works

1. **Market confirmation is the strongest purifier.** Both rule-based backtest (+18.7pp) and RLVR training (+5.9pt) confirm that using market posterior to filter priors is the single most effective signal. This validates the core PRONOIA proposition: ground reasoning in market feedback, not LLM self-assessment.

2. **Falsifiable claims are easier than momentum claims.** The model excels at FALSE-side assertions (70.9%) and long-horizon significance claims (79.1%), but struggles with TRUE-side momentum (53.0%) and short-horizon benchmark direction (49.8%). This asymmetry guides claim design: bet on falsifiability, hedge on momentum.

3. **Structured output contracts prevent reward hacking.** The PAV contract's claim-level decomposition made every reward component independently verifiable. When we weakened this guardrail (v6.1-b residual corrections), training reward improved (+0.21) but OOS accuracy dropped (-2.29pt). The lesson: training reward trend cannot validate reward components; OOS adjudication is the only mechanism.

### 8.2 What Doesn't Work

1. **Residual bias corrections don't correct bias.** We designed five correction terms targeting hard negatives, distribution residuals, and claim combination quality. None improved OOS performance; collectively they reduced accuracy by 2.29pt. The premise that "residual bias is correctable by prior" is unsupported at our training scale.

2. **Risk paragraphs are cognitively correct but behaviorally inert.** In failure cases, models correctly identified sell-the-news risk in their reasoning text but never translated this into hedging claims. Risk awareness without action mechanism is decoration, not intelligence.

3. **More claims ≠ better coverage.** 2-3 claims per event achieve best accuracy (0.690/0.656); 4+ claims drop to 0.569. The model overextends when forced to generate more assertions, diluting quality for quantity.

### 8.3 Surprises

1. **The strongest family is significance, not direction.** We expected CAR direction claims to be the model's strength. Instead, p-value significance claims achieved 79.1% accuracy (+17.7pt vs base)—the model is better at judging "will this event be statistically significant?" than "will this event move the stock up?"

2. **Long-horizon outperforms short-horizon.** Counter to efficient market intuition, t30 claims (75.3%) significantly outperform t15 (50.5%) and t7 (61.9%). Falsifiable long-horizon claims ("this event will not have significant 30-day impact") are easier to verify than short-horizon momentum ("this event will move the stock up in 7 days").

3. **The graph can only be used once.** Low-ACC event types (consumer boost 33.3%, spike-crash 31.6%, rate cuts 47.9%) prove that static lookup tables fail. Each event requires online reasoning over the propagation graph—motivating our investment in RLVR training rather than rule-based expansion.
```

---

## 五、时间线与优先级

### 剩余 10 天（10/15 → 10/25）

| 天数 | 任务 | 优先级 | 产出 |
|---|---|---|---|
| Day 1 (今天) | Abstract 压缩到 150 词 + 提交占位 | P0 | Abstract 定稿 |
| Day 2-3 | 结构重组 + System Description 扩写 | P0 | 第 3-4 页初稿 |
| Day 4-5 | 新增实验（端到端 + 组件消融 + 效率） | P1 | 第 6 页初稿 |
| Day 6-7 | Case Studies 叙事化 + Lessons Learned | P1 | 第 7-8 页初稿 |
| Day 8 | 全文润色 + 图表优化 | P2 | 完整初稿 |
| Day 9 | 内部审读 + 修改 | P2 | 修改稿 |
| Day 10 | 最终检查 + 提交 | P0 | 投稿版 |

### 如果时间不够（降级方案）

| 优先级 | 保留 | 放弃 |
|---|---|---|
| P0 | Abstract 150 词、结构重组、System Description、Lessons Learned | 新增实验、用户研究 |
| P1 | Case Studies 叙事化、图表优化 | 端到端任务评估 |
| P2 | 全文润色 | A/B 测试、规模分析 |

---

## 六、最终检查清单

### 投稿前必须确认

- [ ] Abstract ≤ 150 词
- [ ] 8 页正文 + 参考文献 + 附录 ≤ 12 页
- [ ] 匿名（无作者信息、无致谢、无机构标识）
- [ ] ACM sigconf 双栏格式
- [ ] 所有图表编号连续、引用正确
- [ ] 参考文献格式统一（ACM-Reference-Format）
- [ ] 无 "our previous work"、"we build on [X]" 等自引用泄露身份
- [ ] 代码链接匿名化（GitHub 仓库名不含作者信息）
- [ ] 系统截图脱敏（无内部数据、无用户信息）

### Industry Track 特别确认

- [ ] 第 1 页有明确的 "Relevance to the Web" 段落
- [ ] System Description 是核心章节（不是附录）
- [ ] 有真实部署数据（用户量、使用量、运行时间）
- [ ] 有工程挑战和解决方案（不是纯算法描述）
- [ ] 有 Lessons Learned（什么 work，什么不 work，为什么）
- [ ] 有失败案例分析（不是只讲成功）
- [ ] 有效率和成本指标（Industry Track 关心 ROI）

---

## 七、一句话总结

> **PRONOIA 的核心优势是 "真实市场反馈循环" 和 "开源 Web 部署"，这正好命中 WWW Industry Track 的 taste。当前稿件的主要差距是 "太像 Research Track"——需要把 System Description 变成核心章节，把 Experiments 从 "ML 风格" 转向 "系统风格"，把 Discussion 从 "学术讨论" 转向 "Lessons Learned"。10 天时间足够完成这个转变，关键是 Day 1 就提交 Abstract 占位，然后按优先级推进。**
