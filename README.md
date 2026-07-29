# Pronoia

> **Hunt events. Trace echoes.**
> 对话式 AI 金融事件分析工作台：提问即研究。

Pronoia 是一个开源的对话式 AI 金融研究工作台。
主理人 Agent 调用 **akshare 真实数据技能**，流式输出结论，并把 K 线、事件研究曲线、
数据表、证据与研究报告**沉淀为可回看的研究资产**。深度问题可切换「研究团队」模式，
多专家 Agent 并行作业、复核员把关。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)]()
[![React](https://img.shields.io/badge/React-18-61dafb.svg)]()

---

## ✨ 特性

- **对话式研究工作台**：左栏研究案例（Case）、中栏对话流、右栏产出物面板。
  每个 Case 持久化（SQLite），刷新不丢，随时回看、继续追问。
- **15 个真实数据技能（Skill）**：日K行情、指数、板块、个股新闻、全局快讯、公告检索、
  财务摘要/指标、研报评级、龙虎榜、融资融券、宏观 CPI/PPI/PMI/GDP/国债收益率、
  **事件研究法（AR/CAR）**、股票搜索——全部走 akshare 免费接口，零 mock。
- **Agent 团队模式**：Planner 拆解任务 → 事件猎手 / 行情分析师 / 基本面分析师并行执行 →
  主理人综合 → 复核员逐条核对「数据事实 vs 模型推断」→ 流式输出。
- **产出物（Artifacts）体系**：工具结果自动生成 K线图、CAR曲线、数据表、证据卡片，
  对话内 handoff，右栏大视图查看；一键生成四段式研究报告（数据事实/分析推断/风险/免责声明）。
- **过程透明**：思考过程、每次工具调用的参数与结果、每个数字的来源接口（如
  `akshare.stock_news_em`）全部可见、可追溯。
- **密钥安全**：LLM Key 只存后端 `.env`，绝不下发浏览器。

## 🏗 架构

```
┌─────────────────────────── Frontend (React 18 + Vite + Tailwind) ───────────────────────────┐
│  Sidebar(Case列表) │ ChatPanel(消息流/工具卡/产出物卡) │ RightPanel(产出物·技能·团队)         │
│  zustand store ─── api.ts (fetch + ReadableStream 解析 SSE)                                  │
└──────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                           │ POST /api/chat (SSE) · REST /api/cases|skills|agents
┌──────────────────────────────────────────▼───────────────────────────────────────────────────┐
│                      Backend (FastAPI · 单进程 · SQLite 持久化)                               │
│  routes/chat.py ──► llm.run_agent()  流式 tool-call 循环（≤8轮）                              │
│                   └► agents/team.py  plan → fan-out(asyncio.gather) → synthesize → verify     │
│  skills/registry.py  @skill 注册表（统一 ok/data/meta/artifact 协议）                          │
│  skills/market·news·fundamentals·analysis ──► akshare / sina suggest（线程池+超时+降级）      │
│  db.py  cases / messages / artifacts 三表                                                    │
└──────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                           ▼
                            Ark LLM (OpenAI 兼容) · akshare 数据源
```

## 🚀 快速开始

```bash
cp .env.example .env        # 填入你的 ARK_API_KEY（或任意 OpenAI 兼容端点）
./start.sh                  # 后端 :8000 + 前端 :5173
```

Docker（单容器，后端托管前端构建产物）：

```bash
docker build -t fever . && docker run -p 8000:8000 fever
# 打开 http://localhost:8000
```

## 🧭 两种模式

| 模式 | 适用 | 链路 |
|---|---|---|
| ⚡ 快速问答 | 单一事实/单一标的查询 | 主理人 Agent + ≤8 轮工具循环 |
| 👥 深度研究团队 | 多维度深度问题 | Planner 拆 2~4 子任务 → 3 专家并行 → 综合 → 复核修正 |

试试这些问题：
- 「分析贵州茅台近一个月的事件与股价表现」
- 「对宁德时代做深度研究」（团队模式）
- 「用事件研究法看看 600519 在 2026-06-01 前后的超额收益」
- 「央行国债收益率最近怎么走？」

## 🧩 技能清单

`search_stock` `get_stock_daily` `get_index_daily` `get_sector_spot` `get_stock_news`
`get_global_news` `get_announcements` `get_financial_abstract` `get_financial_indicator`
`get_research_reports` `get_lhb` `get_margin` `get_macro` `event_study` `get_current_date`

> 注：本仓库针对网络环境做了数据源适配——东财行情类接口在部分网络不可用，
> 日K默认走新浪源、腾讯源兜底；不可用的接口已在设计中剔除，不会产生幻觉数据。

## 👥 Agent 花名册

主理人 Router · 事件猎手 Event Scout · 行情分析师 Market Analyst ·
基本面分析师 Fundamentals Analyst · 复核员 Verifier · 报告撰写员 Report Writer

## 🗺 路线图

工作台是 TTRL（Test-Time Reinforcement Learning）的产品地基：当输入、证据、结论、
复盘都被结构化记录后，接入「预测命中评估 → reward 计算 → calibration 更新 →
skill/prompt 策略更新」的长期自进化闭环。

- [x] P0 对话式研究闭环（提问→采证→产出物→Case 沉淀）
- [x] P0 事件研究法引擎（AR/CAR）
- [ ] P1 研究资产化：历史 Case 检索、证据有效性标注、复盘面板
- [ ] P1 事件监控与预警（定时任务 + 推送）
- [ ] P2 TTRL v0：命中率统计、calibration 面板
- [ ] P2 接入 Argus 深度采证引擎（见 v2 仓库归档）

## 📋 更新日志

- **3.8.2** · 2026-07-29 · 修补：品牌更名为 Pronoia，并统一首页推荐与团队研究体验
- **3.8.1** · 2026-07-19 · 修补：SkillsTab「对外技能」SectionHeader 改为卡片化标题块（jade 边框 + jade-soft 背景 + 数量徽章 + Agent 实际可调用 hint），视觉权重对齐三层模型 / 底层工具；删除 SectionHeader 死代码。
- **3.8.0** · 2026-07-19 · 功能：三层调度模型对齐：composite skill 改名为 skill（atomic 工具 = tool，对 LLM 不可见；skill 聚合多 atomic，对 LLM 可见；agent 只看 skill）。composite.py → skill.py。9 个 skill：event_study_skill / evidence_graph / financial_research / holder_research / macro_intel / market_research / news_intel / post_market_outlook / stock_overview。前端 SkillsTab 三层模型图示同步：tool(52) → skill(9) → agent(5) → team；CompositeSkillCard 改名为 SkillCard；types.ts 同步更新 category 类型。
- **3.7.0** · 2026-07-19 · 功能：补全 3 个 skill 的美股分支：financial_research 走东财三大报表+财务指标+财报日历+雪球简介+yfinance 卖方研报；holder_research 走 yfinance 股东结构+内部人交易；market_research 在日K 之外追加美股实时行情和公司简介。新增 2 个 atomic tool：get_us_stock_holder（major/institutional/mutualfund holders+insider transactions）、get_us_stock_analyst（recommendations_summary+analyst_price_targets+earnings_estimate+earnings_history）。端到端 NVDA 实测：71% 机构持股、BlackRock 7.96% 持仓、61 位分析师看多、目标价均值 $302.31。
- **3.6.0** · 2026-07-19 · 功能：美股信息查询补全：新增 7 个 atomic tool（实时行情/公司简介/三大报表/财务指标/个股新闻/财报日历/SEC 文件），通过 stock_overview 和 news_intel 暴露给 LLM；search_stock 加 ticker 强信号修复 NVDA 错配高伟达 bug；接 yfinance 提供 Yahoo Finance 个股新闻 + SEC 8-K/10-Q 原文；前端 LogicCard 订阅 store 修复消息流按钮不刷新、GraphView 列表默认 + 节点排序、隐藏 internal 工具、删除冗余「仅深度研究」按钮。
- **3.5.0** · 2026-07-19 · 功能：美股支持补全：财务摘要/指标 K线派生、event_study/market_research/stock_overview 接受 ticker、search_stock 双路并查、_US_NAME_MAP 扩到 250 条
- **3.4.2** · 2026-07-19 · 修补：3.4.2: API 接口清理 — 移除前端 api.health/api.hotTopics（无人调用）；移除后端 /api/hot_topics 端点 + _build_hot_topics 热点缓存（前端已改用静态池）；修正 api.pinArtifact 返回类型 (Artifact) 与后端一致；SSEEvent 新增 team_members 字段以匹配后端 meta 事件。
- **3.4.1** · 2026-07-19 · 修补：3.4.1: 右栏展开态改为 absolute 浮层（z-30 + 左侧投影），不再 shrink-0 挤占聊天区布局。App.tsx 把 ChatPanel + RightPanel 套进 relative 容器让 absolute 生效。
- **3.4.0** · 2026-07-19 · 功能：3.4.0: 空态推荐改为 6 条（2 快速 + 2 专家 + 2 团队），顺序固定；「换一批」改为纯前端静态池洗牌（Fisher-Yates），瞬间完成（< 1ms），不再调后端。Agent 推荐自带 agent 字段，直接走单专家模式。修复 CHIP_PROMPTS 误写 ] 应为 \u007D 的语法错误。
- **3.3.1** · 2026-07-19 · 修补：3.3.1: 空态 hero 调整 — 「换一批」按钮从顶部下移到建议问题下方居中；移除「热点来源」提示行；「团队」徽章从描述行右侧移到左侧图标下方。
- **3.3.0** · 2026-07-19 · 功能：3.3.0: 左栏支持折叠为 w-11 细栏，与右栏对称。展开态 header 右上角加「◀」折叠按钮；折叠态保留 logo 缩写 + 新研究 + 案例计数 + 底部 tab 入口（技能/团队/逻辑库）。状态持久化到 localStorage。
- **3.2.5** · 2026-07-19 · 修补：3.2.5: 能力 chips 去掉 <标的> 占位符，改为从 15 只热门 A 股池随机抽一只填入示例 prompt（宏观类无标的保持原状）。
- **3.2.4** · 2026-07-19 · 修补：3.2.4: 能力 chips 改为可点击按钮，点击后通过 promptSeed 把对应技能的 prompt 模板填到 composer 的 textarea 并自动 focus；新增 store.promptSeed 作为跨组件通道。
- **3.2.3** · 2026-07-19 · 修补：3.2.3: 模式选项从「快速问答 / 单 Agent / 深度研究团队」缩短为「快速 / 专家 / 团队」；右侧 hint span 移除，原信息融合到各模式 placeholder 中。
- **3.2.2** · 2026-07-19 · 修补：3.2.2: 右栏 4 个 tab 改为 flex-1 等宽分布；激活态边框改为 transparent 兜底避免宽度跳变；缩小内边距和字号。
- **3.2.1** · 2026-07-19 · 修补：3.2.1: 逻辑库筛选 chip 改为可换行 + 加内/外间距，字不再挤。
- **3.2.0** · 2026-07-19 · 功能：team 模式新增可勾选团队成员：默认全选、可选择性去掉非 deep_researcher 专家；后端 run_team 支持 team_members 白名单，hard rule 保 deep_researcher 始终参与。
- **3.1.2** · 2026-07-19 · 修补：Agent 选择改用对话框（搜索 + 键盘导航 + 详情预览）；触发器缩小为 chip。
- **3.1.1** · 2026-07-19 · 修补：右栏默认折叠 + UI 状态持久化；单 Agent 模式下拉独立成行避免遮挡；新增版本自动管理脚本 `scripts/bump.py`。
- **3.1.0** · 2026-07-19 · 功能：单 Agent 模式直接调度专家、事件预测员（predictor）Agent 与 post_market_outlook 复合技能、产出物按类型分组、版本自动管理（`scripts/bump.py`）。
- **3.0.0** · 2026-07-18 · 重大：四层调度模型（Tool → Skill → Agent → Team）落地；akshare 真实数据接入；证据图与深度研究团队上线；研究逻辑库（Logic Library）闭环。

## ⚠️ 免责声明

本项目仅供学习与研究使用，所有输出不构成任何投资建议。
数据来自 akshare 免费公开接口，准确性以原始数据源为准。

## 📄 License

MIT
