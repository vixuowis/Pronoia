# WWW 投稿 · Pronoia 论文资产盘点

> **目标会议**: WWW（The Web Conference / ACM WebConf）
> **盘点日期**: 2026-10-15
> **核心主题**: Event-Driven Financial Reasoning with LLM Agents — 从 Speed Alpha 到 Cognitive Alpha

---

## 一、项目本体：Pronoia

### 1.1 定位
**对话式 AI 金融事件分析工作台** —— "Hunt events. Trace echoes."

- 主理人 Agent 调用真实数据技能（akshare / yfinance），流式输出结论
- 把 K 线、事件研究曲线、数据表与研究报告沉淀为可回看的研究资产
- 深度问题可切换「研究团队」模式：多专家 Agent 并行作业 + 复核员把关
- **核心卖点**：内置事件驱动回测平台 + Arena 横向评测

### 1.2 核心能力清单
| 能力 | 说明 |
|---|---|
| 对话式研究工作台 | Case 持久化（SQLite），刷新不丢，随时回看与追问 |
| 85+ 真实数据技能 | 行情 / 新闻 / 公告 / 财务 / 宏观 / 事件研究法（AR/CAR），零 mock |
| 研究团队模式 | Planner 拆解 → 多专家并行 → 综合 → 复核员逐条核对 |
| 产出物体系 | 工具结果自动生成图表、数据表、证据卡片、一键生成研究报告 |
| **事件驱动回测** | 真实事件 + Oracle T+3~T+60 CAR 标签，Strict/Lenient 双口径 ACC，Wilson CI |
| **Arena 横向评测** | 同数据集多 Run 一键比对 —— 排名 / 雷达图 / 显著性检验 / 头对头 / 成本-效果帕累托边界 |
| 密钥安全 | LLM Key 只存后端 `.env`，绝不下发浏览器 |

### 1.3 Repo 信息
- **地址**: `github.com/vixuowis/Pronoia`
- **最新版本**: v3.13.0 (2026-09-13)
- **License**: MIT
- **技术栈**: Python 3.10+ (后端) + React 18 (前端)
- **作者**: vixuowis（29 repos, bio: "Towards 100 billion agents' lifestyle."）

### 1.4 版本演进（关键节点）
| 版本 | 日期 | 重要更新 |
|---|---|---|
| v3.13.0 | 2026-09-13 | Arena 工作区、market_runtime、仓库治理 |
| v3.12.0 | 2026-08-21 | 回测中心重构（可插拔多指标、Arena 横向比对、帕累托图） |
| v3.11.0 | 2026-08-20 | **可插拔指标系统（18+ 指标）、Arena 评测平台** |
| v3.10.0 | 2026-08-19 | **多 horizon CAR 标签（T+3/7/15/30/60）、Strict/Lenient 双口径** |
| v3.9.0 | 2026-08-16 | Pronoia 核心回测框架确立 |

### 1.5 Repo 目录结构（顶层）
```
Pronoia/
├── backend/              # Python 后端（Agent、Skill、回测引擎）
├── backtesting/
│   ├── data/             # 回测数据集、K线缓存
│   └── rlvr/             # RLVR 训练相关
├── scripts/              # 运营管线脚本
├── docs/                 # 文档
├── share/ data/samples/  # 样例数据
├── .env.example
├── CHANGELOG.md
└── (大量实验脚本 *.py, 运行脚本 *.sh)
```

---

## 二、GPU 机器环境

### 2.1 连接信息
```
Host: connect.westd.seetacloud.com
Port: 12109
User: root
Pwd: En6mms06iDbK
```
⚠️ **必须通过代理连接**: `ProxyCommand nc -X connect -x 127.0.0.1:18080`

### 2.2 硬件
| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 × 1 |
| 显存 | 49140 MiB (~48 GB) |
| CUDA | 13.0 |
| Driver | 580.105.08 |

### 2.3 关键目录（~/）
| 路径 | 内容 |
|---|---|
| `~/Pronoia/` | ⭐ 主项目（含实验脚本、cases40.json、回测结果、run 脚本） |
| `~/pronoia/` | 早期版本（v3-v5 数据、prompt_template、papv 训练日志） |
| `~/pronoia.tar.gz` | 项目打包备份 |
| `~/Pronoia/pronoia_run/` | ⭐ 最新实验 Run 产物（v6-v62、SoftMoE、team trajectory） |
| `~/LLaMA-Factory/` | LoRA 微调框架 |
| `~/Qwen3-8B/` | 本地模型 |
| `~/grpo_trainer_lora_model/` | GRPO 训练出的 LoRA adapter |
| `~/miniconda3/` | Conda 环境（Python 在 `~/miniconda3/bin/python`） |

### 2.4 环境配置要点
- 本地 vLLM 启动: `~/Pronoia/start_vllm_server.sh` → `MAAS_API_URL=http://127.0.0.1:8000/v1`
- 模型: `qwen3-8b-local`（no-think 模板: `~/Pronoia/qwen3_nothink_template.jinja`）
- LLaMA-Factory + Unsloth + vLLM 环境已装

---

## 三、核心实验与数据

### 3.1 数据集概览
| 数据集 | 事件数 | 市场 | 说明 |
|---|---|---|---|
| **OOS Test** | **1034 events** | CN + US | ⭐ 主评测集，v61/v62/SoftMoE 都用它 |
| Cases40 | 40 cases | CN | 早期案例集 |
| 训练集 | 4137 events | - | `pronoia_run/data_v6_train` |
| `pronoia_run/data_v3/` | 原始公告 CSV | CN | 按日期归档的 notice_*.csv |

### 3.2 Case 数据格式（cases40.json 样例）
```json
{
  "side": "gain",
  "mkt": "CN",
  "sym": "300530",
  "date": "2024-12-17",
  "typ": "并购/分拆/再融资",
  "title": "领湃科技:衡阳弘新资产收购...",
  "body": "公告原文",
  "ctx": "Tier1 结构化分析（方向判断依据）",
  "gt": {
    "car_t3": -0.0721, "car_t7": -0.2008, "car_t15": -0.2417,
    "car_t30": -0.2769, "car_t60": ...,
    "car_t3_pvalue": 0.2994, "car_t7_pvalue": 0.0409
  },
  "base": "【0. 断言规划】【1. 断言列表】【2. 逻辑链】【3. 反方与风险】..."
}
```

### 3.3 评测指标体系
| 指标 | 含义 |
|---|---|
| **ACC** (Strict / Lenient) | 方向命中率（双口径） |
| Brier Score | 概率校准度 |
| ECE | Expected Calibration Error |
| Wilson CI | 置信区间 |
| `car_t3/7/15/30/60` | 多 horizon 累积超额收益标签 |
| `car_t*_pvalue` | 显著性 |
| 18+ 可插拔指标 | core / extended / breakdown 三级 |

### 3.4 实验结果（关键数据）

#### ⭐ v62 版本（最新主结果）
| 配置 | n_events | ACC | ΔACC | Brier | ECE |
|---|---|---|---|---|---|
| Base（vanilla prompt） | 1034 | 0.573 | — | 0.283 | 0.163 |
| **LoRA Adapter** | **1034** | **0.633** | **+0.060** | **0.255** | **0.107** |

#### v61 版本
| 配置 | n_events | ACC | ΔACC |
|---|---|---|---|
| Base | 1034 | 0.577 | — |
| LoRA Adapter | 1034 | 0.607 | +0.030 |

#### SoftMoE（Mixture-of-Experts）
| 配置 | n_events | Accuracy | Δ | ECE_10bin | Brier |
|---|---|---|---|---|---|
| Base | 1034 | 0.581 | — | — | — |
| **LoRA** | **1034** | **0.654** | **+0.073** | -0.054 | -0.040 |

#### 市场维度拆分（OOS）
| 市场 | Base ACC | LoRA ACC | n_events |
|---|---|---|---|
| **CN** | 0.586 | 0.657 | 910 |
| **US** | 0.520 | 0.587 | 124 |

#### Metric Prior v6（按指标族分解）
| 指标 | ACC | n |
|---|---|---|
| `car_t3` | 0.637 | 837 |
| `car_t15` | 0.580 | 814 |
| `car_t3_pvalue` | 0.835 | 701 |
| `ret_t7` | 0.524 | 517 |

#### 方向分布（OOS 1034 events）
- `top_gain` LoRA 比 base 大幅提升的 case（如领湃科技 300530）
- `top_regress` LoRA 不如 base 的 case（如丽人丽妆 605136）

---

## 四、综述 PDF：ERC 架构

### 4.1 基本信息
- **标题**: *Event-Driven Financial Analysis: Perception, Reasoning, Decision, and Evolution*
- **作者**: PRONOIA Team
- **页数**: 61 页
- **定位**: Survey / 架构论文

### 4.2 核心论点
事件驱动股票交易正在从 **Speed Alpha**（比别人更快拿到公告）转向 **Cognitive Alpha**（比市场更深刻地读懂公告含义与传导路径）。ERC（Event Reasoning Chain）是这场转变的核心架构原语。

### 4.3 ERC 四层解耦架构
```
┌──────────────────────────────────────────────────────┐
│  Layer 4: EVOLUTION      (Ch 7-9)                    │
│  市场验证 → 信用归因 → 策略更新 → 市场共进化            │
├──────────────────────────────────────────────────────┤
│  Layer 3: DECISION       (Ch 6)                      │
│  方向/时机/仓位/组合构建/订单执行                       │
├──────────────────────────────────────────────────────┤
│  Layer 2: REASONING      (Ch 5)                      │
│  传导假设构建 + 对抗性检验 + 价格已定价检测 + 世界模型   │
├──────────────────────────────────────────────────────┤
│  Layer 1: PERCEPTION     (Ch 4)                      │
│  异源披露 → 状态重建 → 事件内容/超预期度量               │
└──────────────────────────────────────────────────────┘
         ▲                      │
         └── Event-Transmission-Position (ETP) Triple ──┘
```

### 4.4 事件定义
> **事件 = 状态转移**，surprise 相对于 ex-ante 基准，而不是相对于上一状态。
>
> 例：公司指引从 $10–11B 下调到 $8–9B，市场预期 $8.5B → 大变化但小 surprise。

### 4.5 四代事件处理演进
| 代 | 方法 | 局限 |
|---|---|---|
| 1st | 分析师人工阅读 | 低容量、高 bias |
| 2nd | 关键词/Regex | 格式脆弱 |
| 3rd | 情绪/SUE 因子打分 | 丢失传导逻辑（"why" is lost） |
| 4th | LLM 语义理解 | 需要严格的验证锚 |

### 4.6 五大研究缺口（论文声称）
1. **Multi-agent superiority 缺乏严格 matched-budget 证明**
2. **Adversarial logic for priced-in information 模糊**
3. **JEPA 风格世界模型在金融场景的应用空白**
4. **Decision layer 端到端集成缺失**
5. **Agent evolution 的 financial grounding 缺失**

### 4.7 金融场景五大特有约束
- **ERC**: 逻辑链可追溯、可复现、可量化、可编辑
- **Auditability**: 满足内部交易法规
- **Tradability**: 锚定到可交易资产
- **Attributability**: 每层贡献可归因
- **Replayability**: point-in-time 回放

### 4.8 章节结构
| Ch | 主题 |
|---|---|
| 1 | Intro + 四代演进 + 五大约束 |
| 2 | 事件定义（状态转移、解析尺度、事件边界） |
| 3 | ERC 架构 + ETP 三元组 |
| 4 | Part I — Perception（异源重建、surprise 度量） |
| 5 | Part II — Reasoning（传导假设、反方检验、价格已定价、世界模型） |
| 6 | Part III — Decision（方向、仓位、执行） |
| 7-9 | Part IV — Evolution（版本演化、反馈归因、共进化评估） |
| — | 229 篇参考文献 |

---

## 五、WWW 投稿策略草案

### 5.1 为什么适合 WWW？
| WWW 评审关注点 | Pronoia 匹配度 |
|---|---|
| **Web-scale systems** | Arena 评测平台、85+ 数据源技能 |
| **LLM agents for web** | 对话式 Agent + 多专家协作 + 市场验证 |
| **Real-world impact** | 真实行情回测、金融市场锚定 |
| **New benchmarks** | OOS 1034 events + 多 horizon CAR 标签 + Strict/Lenient 双口径 |
| **Open challenges** | ERC 架构 + 五大研究缺口正好命中 |

### 5.2 建议论文结构（Draft）
```
Title: Event-Driven Financial Reasoning: An LLM Agent Architecture
       with Market-Verifiable Closed-Loop Evaluation

1. Introduction
   - Speed Alpha → Cognitive Alpha 的范式转变
   - 为什么 ERC 是必须的架构原语
   
2. Related Work  ← 综述 PDF 精简重写（Ch 2-3 + Part I-II 裁剪）
   - 事件抽取 & Perception（Survey Ch 4）
   - 金融 Reasoning & Multi-Agent（Survey Ch 5）
   - 回测 & Evaluation（Survey Ch 9 + 本文的实证）
   
3. Pronoia Architecture
   - 四层 ERC 实现细节（Perception → Reasoning → Decision → Evolution）
   - Arena 横向评测平台设计
   
4. Event-Driven Backtesting Benchmark
   - 1034 OOS events + 多 horizon CAR Oracle
   - Strict/Lenient 双口径 + Wilson CI
   
5. Experiments
   - RQ1: LoRA adapter 比 vanilla prompt 能否提升方向命中率？ → ✅ +6%
   - RQ2: Multi-agent team 模式 vs 单 Agent？（需要补充实验）
   - RQ3: 断言级校准 (Brier/ECE)？ → ✅ LoRA 同时提升 ACC 和校准
   - RQ4: 市场/指标族维度的可迁移性？
   
6. Ablation & Analysis
   - 按事件类型 / 市场 / 指标族拆分
   - top_gain / top_regress case study
   
7. Discussion ← 综述 PDF 的 Five Gaps 作为 Future Work
   - ERC 四层各自的开放问题
   
8. Conclusion
```

### 5.3 当前已有 vs 还缺什么
| 模块 | 状态 | 来源 |
|---|---|---|
| ERC 架构理论 | ✅ 完整 | 综述 PDF |
| Pronoia 系统实现 | ✅ 完整 | GitHub repo |
| OOS 1034 events 数据集 | ✅ 完整 | GPU 机器 `pronoia_run/` |
| v61/v62/SoftMoE 实验结果 | ✅ 有 | GPU 机器 eval_*_report.json |
| LoRA adapter | ✅ 有 | `grpo_trainer_lora_model/` + `Papv_v62_vanilla/` |
| Team 模式实验 | ⚠️ 需补充 | `team_traj_v4/` 有轨迹但缺 head-to-head 对比 |
| 图表（论文 Fig） | ❌ 待制作 | 雷达图、成本-效果帕累托图、Case study 可视化 |
| Related Work（WWW 风格） | ⚠️ 需改写 | 综述 PDF 太全太散，WWW 要聚焦 Web/Agent 视角 |

---

## 六、快速操作手册

### 6.1 SSH 连接（含代理）
```bash
python3 -c "
import paramiko
sock = paramiko.ProxyCommand('nc -X connect -x 127.0.0.1:18080 connect.westd.seetacloud.com 12109')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(hostname='connect.westd.seetacloud.com', port=12109, username='root', password='En6mms06iDbK', sock=sock)
stdin, stdout, stderr = c.exec_command('nvidia-smi | head -5')
print(stdout.read().decode())
c.close()
"
```

### 6.2 启动 vLLM（远程）
```bash
# on GPU machine
bash ~/Pronoia/start_vllm_server.sh
# 然后跑 Team forward pipeline
bash ~/Pronoia/run_team_forward.sh
```

### 6.3 关键结果文件路径速查
| 想找什么 | 远程路径 |
|---|---|
| v62 实验结果 | `~/Pronoia/pronoia_run/eval_papv_v62_t06_report.json` |
| v61 实验结果 | `~/Pronoia/pronoia_run/eval_papv_v61_report.json` |
| SoftMoE 结果 | `~/Pronoia/pronoia_run/eval_papv_softmoe_report.json` |
| OOS 分析 | `~/Pronoia/oos_analyze_out.json` |
| Metric prior | `~/Pronoia/pronoia_run/metric_prior_v6.json` |
| Cases40 | `~/Pronoia/cases40.json` |
| 训练数据 | `~/Pronoia/pronoia_run/data_v6_train/` |
| 测试数据 | `~/Pronoia/pronoia_run/data_v3/_raw/notice_*.csv` |
| Team trajectory | `~/Pronoia/pronoia_run/team_traj_v4/` |
| 回测数据（K线缓存） | `~/Pronoia/backtesting/data/kline_cache/` |

---

## 七、素材来源清单

| 来源 | 路径 | 内容 |
|---|---|---|
| GitHub Repo | `github.com/vixuowis/Pronoia` | 完整代码、README、CHANGELOG、架构文档 |
| GPU 远程 | `connect.westd.seetacloud.com:12109` | Pronoia 项目副本 + 全部实验产物 |
| 综述 PDF | `/workspace/.uploads/89414b9d-4c44-4f8d-925f-165a65276f8b_event_driven_financial_analysis_arxiv.pdf` | 61 页 ERC 架构综述（lit review 基础） |
| 本文档 | `/workspace/WWW_Paper_Asset_Inventory.md` | 当前盘点（就是这份） |
