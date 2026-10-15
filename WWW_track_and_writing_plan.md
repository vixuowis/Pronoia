# WWW 2027 Track 选择与写作方案（官方 CFP 核实版）

> 核实日期：2026-10-15。目标会议：ACM Web 2027 (WWW 2027)，Dublin，2027-05-10~14。
> 官方依据：https://www2027.thewebconf.org/research-track-papers/

---

## 一、官方硬约束（决定一切的三条）

| 约束 | 原文要点 | 对我们的影响 |
|---|---|---|
| **Web 相关性强制声明** | "Every submission must clearly state how the work is relevant to the Web and to the track **in the first page**." | 首页必须有实质性的 Web 相关性论证 |
| **⚠️ Desk-reject 条款** | "Submissions that **merely use a Web artifact** e.g. a dataset or a Web API or a social network – **rather than answering a specific Web-related scientific research challenge**, are out of scope and **will be desk-rejected**." | **头号风险**：当前稿件的 "我们用 akshare/yfinance API + 部署 Web 应用" 正是被点名的模式 |
| **首次 8 页自包含** | "For long paper, 8 pages as main paper, with additional pages for references and an optional Appendix, up to a maximum of 12 pages total. The first 8 pages should be self-contained, since reviewers are not required to read past that." | 所有关键内容必须在前 8 页，附录只放细节 |

**结论：当前 "Relevance to the Web" 小节（v2.tex L42-44）的写法是 desk-reject 高危。** 它讲的是"我们在 Web 上跑、用 Web API、做成 Web 应用"——即"使用 Web 制品"。必须重写为"回答一个 Web 特有的科学问题"。

---

## 二、Track 选择：推荐 Research Track

### 2.1 WWW 2027 可选 Track（官方列表）

- Brave New Ideas for the Future of the Web
- Web Economics and Digital Society
- Graph Algorithms and Modeling for the Web
- Responsible Web
- Search, Recommendation, and Retrieval-Augmented AI
- Security and Privacy
- Semantics and Knowledge
- Social Networks and Social Media
- **Web Infrastructure and Agentic Systems** ← 首选
- **User Modeling, Personalization and Agentic Web Users**
- Web Mining, Multimedia and Multilingual Content Analysis
- **Evaluation, Human Computation, and Resources** ← 备选
- **Industry Track**（独立 track，同样 10-25 截稿，算长/短文）

### 2.2 推荐结论

> **首选：Research Track → "Web Infrastructure and Agentic Systems"**
> **备选：Research Track → "Evaluation, Human Computation, and Resources"（若改为 benchmark-first 叙事）**

**理由：**

1. **先例已验证赛道。** AMA《When Agents Trade: Live Multi-Market Trading Arena for LLM Agents》作为 12 页长文被 WWW 2026 主会接收——"真实市场 + LLM Agent + 评测"这一方向在 Research Track 是明确 in-scope 的。
2. **稿件的主贡献是方法/架构**，不是商业落地。ERC 架构、PAV 逐条断言契约、market-verifiable RLVR、reward hacking 实证——这些都是 Research Track 的语言（novelty + rigor），不是 Industry Track 的语言（scale + business impact）。
3. **Industry Track 的隐性门槛是"真实规模"。** Industry 审稿人默认打折扣"研究原型/无真实用户"。我们目前没有用户量、留存、业务指标，13 版本的迭代故事撑不起 Industry 的 scale 要求，反而暴露短板。
4. **"Agentic Systems" track 是本届新设/重点方向**（对应 2026 的 agent 热潮），命中正好。

### 2.3 为什么在 "Agentic Systems" 与 "Evaluation/Resources" 之间选前者

| | Web Infrastructure and Agentic Systems | Evaluation, Human Computation, and Resources |
|---|---|---|
| 评判什么 | Agent 架构新颖性、系统设计、反馈闭环 | 基准/资源质量、可复现性、评测严谨性 |
| 我们最强资产 | ERC 架构 + market-verifiable 闭环 | 1,034 OOS 事件 + 多 horizon CAR + Strict/Lenient + Arena |
| 竞争密度 | 高（最热 track） | 中（相对冷） |
| 需要的改写 | 中（Web 相关性 + 架构前置） | 大（必须 benchmark-first 重构标题与结构） |

**决策规则：**
- 若保留 "Event-Driven Financial Reasoning with Market-Verifiable Rewards" 这个 method-first 标题 → 投 **Agentic Systems**
- 若改为 "X-Bench: A Market-Verifiable Benchmark for Event-Driven Financial Reasoning Agents" 这种 resource-first 标题 → 投 **Evaluation/Resources**（对标 AMA 的成功配方）

---

## 三、头号任务：重写 Web 相关性（防 desk-reject）

### 3.1 现状（高危）

> "PRONOIA is deployed as an open-source Web application where researchers interact through a conversational interface... This work sits at the intersection of Web-based AI agents, retrieval-augmented reasoning, and online market feedback loops."
> —— 这是"使用 Web 制品"的写法，正是 desk-reject 条款点名的模式。

### 3.2 改写原则：从"我们在 Web 上跑" → "Web 制造了这个科学问题"

必须论证：**如果没有 Web，这个问题不存在或不成立。**

可用的三条 Web 科学性论证：

1. **Web 是事件信息的唯一发布与传播基座，且其异构性制造了核心难题。**
   同一事件以公告、快讯、财报、社媒、宏观数据等形式分散发布于不同 Web 源，格式/时延/口径/可信度互不一致。PRONOIA 的 Perception 层要解决的正是"跨 Web 源重建事件状态并度量 surprise"——这是 Web 数据集成与可信度问题，不是应用问题。
2. **市场本身是 Web 中介的信息聚合系统，CAR 是 Web 数据的涌现产物。**
   "市场验证"之所以成立，是因为价格由 Web 上公开、持续更新的数据结算得出。PRONOIA 把 Web 数据流当作 reward 的物理来源——这就是 Web 上的在线/持续学习闭环，是 Web 尺度的 real-world feedback，18.7pp 的市场确认增益是这一闭环的证据。
3. **持续演化使离线评测失效，必须 Web 在线评测。**
   金融 Web 数据非平稳、实时更新，静态基准会快速过时。Arena 的价值在于 Web 上的持续、在线、横向评测——这正对应 "Evaluation, Human Computation, and Resources" 的科学关切。

### 3.3 写法位置

按官方要求**必须出现在第 1 页**。建议把当前独立的 \subsection{Relevance to the Web} 融进 Introduction：
- 第 1 段（场景痛点）末尾点出"这是 Web 制造的问题"
- 或保留一个精炼的 3-4 句段落在 Introduction 开头，但内容换成上面三条的科学性论证

---

## 四、8 页写作方案（Research Track，前 8 页自包含）

### 4.1 页面预算

| 页 | 内容 | 关键素材 |
|---|---|---|
| **p1** | Title + Abstract(≤150词) + Intro（含 Web 相关性）+ **Fig 1 范式对比图** + **Table 1 系统/数据集对比** + Ch1/Ch2 + 贡献 | 新建 Fig1、Table1 |
| **p2** | Related Work（**压到 2 小节**）+ System Overview + 架构图 | 现有 6 小节合并 |
| **p3** | Method I — ERC 四层（Perception→Reasoning→Decision→Evolution）+ ETP 三元组 | v2.tex Fig(erc) |
| **p4** | Method II — Propagation Graph + PAV 契约（3-6 断言）+ RLVR 奖励设计 | 现有 + 补设计决策 |
| **p5** | Deployment & Arena（**压缩为支撑节**）：85+ 技能、研究团队模式、Arena 协议 | 现有 System Description |
| **p6** | Experiments — Setup + **RQ1 主对比（含交易指标）** + RQ2 组件消融 | **需补交易指标 + 外部基线** |
| **p7** | Experiments — RQ3 奖励消融/reward hacking + RQ4 案例+人类对齐 | 现有 + 补人类对齐 |
| **p8** | Analysis（校准、失败分类）+ Lessons Learned + Conclusion | 现有 calibrate 数据 |
| p9-12 | References + Appendix | 超参、敏感性、Prompt、界面截图 |

### 4.2 六条写作铁律（源自 4 篇中稿论文）

1. **Fig 1 = 范式对比图，放第 1 页**：传统事件研究（事后描述）vs LLM 直接预测（无真值）vs PRONOIA（市场验证闭环）三方对比
2. **Table 1 放 Introduction**：对照 Janus-Q Table 1 格式，做"事件驱动金融系统对比"表（列：事件结构化/传导推理/逐条可验证/市场结算/开源/中文市场），ChFinAnn、DuEE-Fin、FNSPID、Janus-Q、Ours
3. **问题用 Ch1/Ch2 两挑战框定**（现有 3 个 Problem 压成 2 个）
4. **Related Work 只留 2 小节**：`2.1 Event-Driven Financial Analysis` + `2.2 LLM Agents with Verifiable Rewards`
5. **实验全部 RQ 驱动**：RQ1 主对比 → RQ2 组件消融 → RQ3 奖励消融/hacking → RQ4 案例+人类对齐
6. **细节全部下沉附录**：前 8 页只留结论与关键数字

### 4.3 必须新增的实验（详见 WWW_similar_papers_analysis.md）

| 优先级 | 内容 | 工作量 |
|---|---|---|
| P0 | 断言→交易策略：Sharpe/年化/最大回撤（用现有 1,034 结算事件） | ~1 天 |
| P0 | 外部 LLM 基线（GPT-4o zero-shot，100-200 事件子集） | ~0.5 天 |
| P1 | 系统组件消融（去传导图 / 仅方向预测） | ~1 天 |
| P1 | 置信度阈值-覆盖率敏感性曲线（数据已有，纯画图） | ~2 小时 |

### 4.4 与 Janus-Q 的正面区分（写进 Related Work 末尾）

Janus-Q 与 PRONOIA 技术路线撞车（事件→CAR→RL 奖励）。必须主动加一段 "Concurrent work: Janus-Q..." 做对比，突显我们的独有性：
- **逐条断言独立结算** vs Janus-Q 的整体 PnL
- **reward hacking 实证** vs 无
- **概率校准分析** vs 无
- **开源可复现 pipeline** vs 私有标注数据

---

## 五、时间线（硬截稿，无延期）

| 日期 | 事件 |
|---|---|
| **2026-10-18** | **Abstract 截稿（3 天后）** — 注意：官方禁止 placeholder/dummy abstract，必须是真实摘要 |
| **2026-10-25** | Full Paper 截稿（10 天后） |
| 2026-12-21 | 结果发布 |
| 2026-12-21~31 | Rebuttal |
| 2027-01-04 | Notification |
| 2027-01-31 | Final version |
| 2027-05-10~14 | 会议（Dublin） |

**建议：今天先把 Abstract 定稿并提交占位（必须真实内容），锁定 track 选择。**

---

## Six. 一句话结论

> **投 Research Track 的 "Web Infrastructure and Agentic Systems"。但比 track 更紧急的是把首页的 Web 相关性从"使用 Web 制品"改写成"Web 制造的科学问题"——否则无论投哪个 track 都会被 desk-reject。**
