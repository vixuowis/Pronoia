# FEVER 重做计划 — AI 金融事件分析工作台（对话式）

## 目标
重做一个开源的 AI 金融事件分析工作台：对话式交互（类 Claude for Science 的金融版），
功能封装为 Skills / Agents / Agent Team，数据用 akshare，LLM 用 Ark API (deepseek-v4-flash)。

## 约束与关键决策
- 原 FEVER 问题：模块平行堆砌、动作停留在 UI 状态层、无研究资产沉淀 → 新版以「对话 + 研究案例(Case)」为主轴
- 数据：akshare 免费接口（注意实测报告中 A股实时行情/板块接口在某些网络下不可用，需在本环境实测并做降级）
- LLM：ARK_API_URL=https://ark.cn-beijing.volces.com/api/coding/v3, model=deepseek-v4-flash
- 交付：可运行的全栈项目（FastAPI 后端 + React 前端），开源级 README

## 阶段
### Stage 1 — 调研（explore 子代理，并行）
- 1a. 读完 FEVER 产品设计文档 + FEVER GitHub 仓库现状（搞清哪里"做得不好"）
- 1b. 竞品调研：vibe trading、MiroFish、ai-hedge-fund、FinRobot、FinGPT、TradingAgents 等，提炼可借鉴的 Agent/Skill 设计
- 1c. akshare 在本环境实测可用接口清单（与飞书报告交叉验证）
输出：调研简报 + 功能清单 + 技术选型

### Stage 2 — 环境验证（主 agent 直接做）
- Ark API 连通性、akshare 安装与核心接口实测
输出：可用能力矩阵

### Stage 3 — 架构设计（主 agent）
- 后端：FastAPI + Agent 编排（事件分析 Agent 团队：事件发现/数据检索/分析/验证/报告）+ Skill 注册表 + SSE 流式对话
- 前端：React + Vite + Tailwind 对话式工作台（左侧会话/案例，中间对话流，右侧证据/数据面板）
- 数据流：用户提问 → 路由 Agent → 调用 akshare 工具 → LLM 综合 → 流式返回 + 结构化证据卡片
输出：架构蓝图（目录结构、API 契约、Agent/Skill 定义）

### Stage 4 — 后端构建（coder 子代理）
按蓝图实现，真实接入 Ark API + akshare，无 mock。

### Stage 5 — 前端构建（coder 子代理）
按蓝图实现对话式 UI，对接后端 SSE。

### Stage 6 — 端到端联调（主 agent + verifier）
真实提问全链路测试，修 bug，优化体验。

### Stage 7 — 交付
README（开源项目格式）、启动脚本、版本保存。
