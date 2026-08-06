// 与后端 schemas 对齐的类型定义（docs/20260729_design.md §7/§8/§9）

export type Mode = "auto" | "agent" | "team";
export type RightTab = "artifacts" | "skills" | "team" | "logic";
export type ArtifactKind = "kline" | "line" | "table" | "evidence" | "report" | "graph" | "simulation";

export interface SimulationJob {
  id: string;
  case_id: string;
  graph_artifact_id: string;
  gateway_job_id: string;
  status: "queued" | "running" | "cancelling" | "completed" | "partial" | "failed" | "cancelled";
  stage: string;
  progress: number;
  error?: string | null;
  artifact_id?: string | null;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
}

/** 左栏研究案例（POST /api/cases 返回时不带 message_count） */
export interface CaseItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

/** 产出物（artifact），payload 结构见 design.md §9 */
export interface Artifact {
  id: string;
  case_id: string;
  message_id?: string | null;
  kind: ArtifactKind;
  title: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any;
  pinned?: number;
  created_at: string;
}

/** 技能元信息 GET /api/skills */
export interface SkillMeta {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
  category?: "atomic" | "skill";
  internal?: boolean;
  composes?: string[];
}

/** Agent 花名册 GET /api/agents */
export interface AgentMeta {
  id: string;
  name: string;
  avatar_color: string;
  description: string;
  persona?: string;
  skills: string[];
}

export interface SuggestionItem {
  text: string;
  mode: Mode;
  icon_hint: "newspaper" | "sparkles" | "trending" | "landmark" | "candlestick" | "users";
  desc: string;
  query?: string;
  agent?: string;
}

/** team 模式 Planner 拆解的子任务 */
export interface PlanItem {
  agent: string;
  agent_name?: string;
  task?: string;
  question?: string;
}

/** 待验证推演（研究逻辑库条目，design.md §6.4）。
 *  status 闭环：
 *    pending（待验证）→ 等待用户/系统验证
 *    pending_scheduled（窗口未到）→ 自动验证后判定：horizon 还没到，记 next_check_at
 *    verified（已证实）→ 深度验证或人工标记
 *    rejected（已证伪）→ 深度验证或人工标记
 *    inconclusive（暂无法验证）→ 数据不足，下次再试
 *    dismissed（已忽略）→ 用户主动忽略 */
export type LogicStatus =
  | "pending"
  | "pending_scheduled"
  | "verified"
  | "rejected"
  | "inconclusive"
  | "dismissed";

/** 单次深度验证产出（写入 check_history） */
export interface LogicCheckEntry {
  at: string;
  verdict: LogicStatus | "error";
  reasoning: string;
  data_summary?: string;
  next_check_at?: string | null;
  evidence?: Array<{
    skill: string;
    args?: Record<string, unknown>;
    ok?: boolean;
    summary?: string;
  }>;
  /** 触发方式：auto（后端自动验证）/ manual（用户手动标记） */
  source: "auto" | "manual";
}

export interface LogicItem {
  id: string;
  case_id?: string | null;
  /** 当时所在 assistant 消息的 id，用于跳转/回溯 */
  message_id?: string | null;
  /** 用户原问题（用于再次验证时预填） */
  question?: string;
  hypothesis: string;
  category: string;
  probability: string;
  scope: string;
  horizon: string;
  check: string;
  status: LogicStatus;
  created_at: string;
  verified_at?: string | null;
  /** 验证后的简短备注（用户填） */
  verification_note?: string;
  /** 下次自动验证时间（pending_scheduled 必填） */
  next_check_at?: string | null;
  /** 上次自动验证时间 */
  last_check_at?: string | null;
  /** 所有验证记录（最新在前） */
  check_history?: LogicCheckEntry[];
}

/** assistant 消息由按时间序排列的 parts 组成（design.md §10 消息渲染） */
export type Part =
  | { type: "thinking"; agent?: string; text: string }
  | {
      type: "tool_call";
      id: string;
      agent?: string;
      skill: string;
      args?: Record<string, unknown>;
      status: "running" | "done" | "error";
      preview?: string;
      artifactId?: string;
    }
  | { type: "artifact"; agent?: string; artifactId: string; kind: ArtifactKind; title: string }
  | { type: "text"; agent?: string; text: string }
  | {
      type: "agent_step";
      phase: string;
      agent?: string;
      note?: string;
      plan?: PlanItem[];
      verdict?: string;
    }
  | { type: "logic_items"; items: LogicItem[] };

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agent?: string | null;
  mode?: Mode;
  parts?: Part[];
  created_at?: string;
  /** 流式期间为 true，用于渲染打字光标/停止逻辑 */
  pending?: boolean;
  error?: boolean;
  /** 具体错误信息，用于失败卡片展示 */
  errorMessage?: string;
}

/** SSE 事件（design.md §7） */
export interface SSEEvent {
  type:
    | "meta"
    | "thinking"
    | "token"
    | "tool_call"
    | "tool_result"
    | "artifact"
    | "agent_step"
    | "case_title"
    | "logic_items"
    | "done"
    | "error";
  case_id?: string;
  mode?: Mode;
  agent?: string;
  /** mode="team" 时透传的白名单（与请求体一致） */
  team_members?: string[] | null;
  delta?: string;
  id?: string;
  skill?: string;
  args?: Record<string, unknown>;
  ok?: boolean;
  preview?: string;
  artifact_id?: string | null;
  artifact?: Artifact;
  phase?: string;
  note?: string;
  plan?: PlanItem[];
  verdict?: string;
  title?: string;
  message_id?: string;
  message?: string;
  /** logic_items 事件携带的待验证推演条目 */
  items?: LogicItem[];
}

/**
 * GET /api/cases/{id} 响应中的历史消息。
 * tool_trace 后端可能已解析成数组，也可能是 JSON 字符串。
 */
export interface HistoryMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agent?: string | null;
  tool_trace?: string | Record<string, unknown>[] | null;
  created_at?: string;
}

export interface CaseDetail {
  case: CaseItem;
  messages: HistoryMessage[];
  artifacts: Artifact[];
}

/* ------- artifact payloads（design.md §9） ------- */

export interface KlinePayload {
  symbol?: string;
  dates: string[];
  ohlc: [number, number, number, number][]; // [open, close, low, high]
  volumes: number[];
  event_date?: string;
}

export interface LinePayload {
  title?: string;
  x: string[];
  series: { name: string; data: (number | null)[] }[];
  yname?: string;
}

export interface TablePayload {
  columns: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rows: any[][];
  note?: string;
}

export interface EvidenceItem {
  title: string;
  date?: string;
  source: string;
  url?: string;
  snippet: string;
}

export interface EvidencePayload {
  items: EvidenceItem[];
}

export interface ReportPayload {
  markdown: string;
}

/* ===================================== Backtest (P0) ===================================== */

export type BTRunner = "baseline" | "team_prompt" | "team_full";
export type BTStatus = "pending" | "running" | "paused" | "done" | "failed" | "cancelled";
export type BTDirection = "up" | "down" | "neutral";

export interface BTRun {
  id: string;
  name: string;
  status: BTStatus;
  runner: BTRunner | string;
  prompt_variant?: string | null;
  model_version?: string | null;
  events_path: string;
  labels_path?: string | null;
  out_path: string;
  ckpt_dir?: string | null;
  concurrency: number;
  total_events: number;
  done_events: number;
  /** 关联数据集（bt_datasets.id）：创建 Run 时可选指定，Arena 聚合时用来分组 */
  dataset_id?: string | null;
  /** 数据集名字：冗余字段，方便列表页直接显示 */
  dataset_name?: string | null;
  acc_t3_strict?: number | null;
  acc_t3_strict_lo?: number | null;
  acc_t3_non_neutral?: number | null;
  /** v2 可插拔指标完整字典（metrics_json 解析后产物） */
  metrics?: Record<string, BTMetricItem> | null;
  config?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_msg?: string | null;
}

export interface BTPredictionItem {
  id: string;
  run_id: string;
  event_id: string;
  symbol?: string | null;
  market?: string | null;
  event_type_l2?: string | null;
  pred_direction: BTDirection | string;
  confidence?: number | null;
  abstain: boolean;
  rationale?: string | null;
  oracle_label_t3?: BTDirection | string | null;
  oracle_car_t3?: number | null;
  is_correct_t3?: boolean | null;
  trajectory_ckpt?: string | null;
  created_at: string;
}

export type BTEventStatus = "pending" | "processing" | "done";

/** 事件目录：直接从 events JSONL 取完整事件清单 + 执行状态 + 已完成 prediction。
 *  Detail 页面一开始就可以渲染全部 N 条事件（pending/processing/done），
 *  而不是等 prediction 写入 DB 后才渲染。
 */
export interface BTEventCatalogItem {
  event_id: string;
  symbol?: string | null;
  market?: string | null;
  event_type_l2?: string | null;
  title?: string | null;
  event_time?: string | null;
  source_url?: string | null;
  event_text?: string | null;
  status: BTEventStatus;
  prediction?: BTPredictionItem | null;
}

/** bt_datasets 行：已注册数据集，用于创建回测时的 Data list 下拉 */
export interface BTDataset {
  id: string;
  name: string;
  path: string;
  labels_path?: string | null;
  total_events: number;
  by_market: Record<string, number>;
  by_type: Record<string, number>;
  by_symbol: Record<string, number>;
  date_range?: { min?: string; max?: string } | null;
  created_at?: string | null;
}

/** 单条 case 的完整详情：预测记录 + trajectory（team_full 才有）+ 事件元信息 */
export interface BTPredictionDetail {
  prediction: BTPredictionItem;
  trajectory: BTTrajectoryCkpt | null;
  /** 事件说明：后端从 ckpt.event_meta + as_of_packet 提取；含 event_text/title/source_url 等 */
  event_meta?: Record<string, unknown> | null;
}

/** trajectory ckpt JSON：team_full runner 每个 event 会写一个完整记录 */
export interface BTTrajectoryCkpt {
  generated_at?: string;
  wall_seconds?: number;
  event_id?: string;
  event_meta?: Record<string, unknown>;
  run_id?: string;
  model_version?: string;
  system_prompt_variant?: string;
  llm_trajectory_stats?: {
    n_sse_events?: number;
    n_sse_events_stored?: number;
    n_tokens_total?: number;
    n_tool_calls?: number;
    n_hypotheses?: number;
    n_final_chars?: number;
    agents_seen?: string[] | number;
  } | null;
  as_of_packet?: string;
  question_to_team?: string;
  structured_extract?: {
    direction?: string;
    confidence?: number;
    rationale?: string;
    conf_gate_applied?: boolean;
  } | null;
  team_final_state?: {
    content_full?: string;
    tool_trace?: Array<Record<string, unknown>>;
    hypotheses?: Array<Record<string, unknown>>;
  } | null;
  trajectory_sse_events?: Array<{
    type?: string;
    phase?: string;
    note?: string;
    [k: string]: unknown;
  }>;
  [k: string]: unknown;
}

export interface BTPredAccStat {
  acc: number;
  k: number;
  n: number;
  wilson_lo_95?: number | null;
  wilson_hi_95?: number | null;
}

/** v2: 可插拔单指标结果（来自 metrics_registry.MetricResult） */
export interface BTMetricItem {
  value: number | string | Record<string, unknown> | null;
  display_name: string;
  description: string;
  tier: "core" | "extended" | "custom";
  higher_is_better: boolean;
  breakdown?: Record<string, unknown>;
  meta?: Record<string, unknown>;
}

/** v2: 指标元信息（列表 GET /api/bt/metrics/defs 返回） */
export interface BTMetricDef {
  display_name: string;
  description: string;
  tier: "core" | "extended" | "custom";
  higher_is_better: boolean;
}

/** v2: GET /api/bt/runs/{rid}/metrics 返回完整结构 */
export interface BTMetricsV2 {
  run_id: string;
  primary_oracle_horizon: string;
  epsilon: number;
  n_total: number;
  metrics: Record<string, BTMetricItem>;
  // 向后兼容字段（保留老代码不崩）
  acc_t3_strict?: BTPredAccStat;
  acc_t3_non_neutral?: BTPredAccStat;
}

export interface BTMetrics {
  total: number;
  abstain_count: number;
  neutral_count: number;
  neutral_ratio?: number;
  acc_t3_strict: BTPredAccStat;
  acc_t3_non_neutral: BTPredAccStat;
  direction_recall?: Record<string, BTPredAccStat>;
  by_event_type?: Record<string, BTPredAccStat>;
  by_market?: Record<string, BTPredAccStat>;
}

export interface BTMetricsSnapshot {
  id: number;
  run_id: string;
  done_count: number;
  acc_t3_strict?: number | null;
  acc_t3_strict_lo?: number | null;
  acc_t3_non_neutral?: number | null;
  neutral_ratio?: number | null;
  created_at: string;
}

export interface BTSSEEvent {
  type:
    | "hello"
    | "heartbeat"
    | "run_started"
    | "run_info"
    | "prediction"
    | "metrics_snapshot"
    | "run_status_changed"
    | "run_done"
    | "run_failed"
    | "run_cancelled";
  run_id?: string;
  status?: BTStatus | string;
  done_events?: number;
  total_events?: number;
  from_catchup?: boolean;
  message?: string;
  // prediction 事件字段
  prediction?: BTPredictionItem;
  event_id?: string;
  symbol?: string;
  // metrics_snapshot 事件字段
  done_count?: number;
  acc_t3_strict?: number | null;
  acc_t3_strict_lo?: number | null;
  acc_t3_non_neutral?: number | null;
  neutral_ratio?: number | null;
  // run_status_changed 事件字段（pause/resume）
  from?: BTStatus | string;
  to?: BTStatus | string;
  reason?: string;
  error?: string;
}

/** prompt_variant 下拉选项（含具体 system prompt 全文） */
export interface BTPromptVariant {
  id: string;
  label: string;
  description: string;
  market_hint: string;
  prompt_text: string;
}

/** events.jsonl 计数 + 校验结果 */
export interface BTEventsCount {
  path: string;
  valid: boolean;
  count: number;
  message?: string | null;
}

/* ===================================== Arena 横向比对 ===================================== */

export type ArenaStatus = "ready" | "computing" | "done" | "failed";

/** bt_arenas 行 */
export interface ArenaItem {
  id: string;
  name: string;
  dataset_id?: string | null;
  dataset_name?: string | null;
  run_ids: string[];
  description?: string | null;
  config?: Record<string, unknown> | null;
  /** 创建时可选指定的指标列表（保存到 config.selected_metric_ids 后反序列化到此） */
  selected_metric_ids?: string[] | null;
  status: ArenaStatus | string;
  result?: ArenaComputeResult | null;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
}

/** Arena 计算结果（POST /api/arena/compute & arena.result 字段） */
export interface ArenaComputeResult {
  run_count: number;
  selected_metric_ids: string[];
  metric_defs: Record<string, BTMetricDef>;
  per_run: Record<
    string,
    {
      run_id: string;
      display_name: string;
      runner: string;
      prompt_variant: string;
      model_version: string;
      status: string;
      done_events: number;
      total_events: number;
      metrics: Record<string, BTMetricItem>;
      /* 成本 / 耗时（来自 bt_predictions tokens 字段聚合 + 估算） */
      tokens_in?: number | null;
      tokens_out?: number | null;
      tokens_total?: number | null;
      step_ms_total?: number | null;
      cost_usd_estimate?: number | null;
    }
  >;
  ranking: Record<
    string,
    Array<{ run_id: string; value: number | null; rank: number | null; display_name: string }>
  >;
  radar_chart: {
    axes: Array<{ metric_id: string; display_name: string }>;
    series: Array<{ run_id: string; label: string; values: (number | null)[] }>;
  };
  /**
   * Pairwise 显著性检验（后端按 metric 跑 McNemar / 置换检验）。
   * 嵌套结构：pairwise_tests[runA_id][runB_id].per_metric[metric_id] = {p_value, delta, winner, test_meta?}
   * 与 run-level 概览（如共同事件数）共存。前端可以直接矩阵式渲染。
   */
  pairwise_tests:
    | Record<
        string,
        Record<
          string,
          {
            shared_events?: number;
            per_metric: Record<
              string,
              {
                display_name?: string;
                p_value?: number | null;
                delta?: number | null;
                winner?: string | null; // runA_id / runB_id / "tie"
                test_name?: string;
                test_meta?: Record<string, unknown>;
              }
            >;
          }
        >
      >
    | null;
  /**
   * Head-to-Head 事件级对决：
   * - summary 每个 (runA, runB) 对的胜负平计数
   * - event_level 每一条共同事件、每个 Run 的预测、是否正确、该事件最佳 Run 列表
   */
  head_to_head:
    | {
        summary?: Record<
          string,
          { a_wins: number; b_wins: number; ties: number; shared: number }
        >;
        event_level: Array<{
          event_id: string;
          oracle?: string | null;
          per_run: Record<
            string,
            {
              prediction?: string | null;
              confidence?: number | null;
              correct?: boolean | null;
              abstain?: boolean | null;
            }
          >;
          best_runs?: string[];
        }>;
      }
    | null;
  /**
   * 综合得分：按 method 聚合多指标排名。每个 Run 的得分 + 全局排名。
   */
  composite_score: {
    method: "rank_average" | "z_score" | string;
    description: string;
    per_run_score: Record<string, { score: number; rank: number }>;
  } | null;
  /**
   * Pareto 成本/效果 二维散点图数据：
   *  - points：每个 run 一个散点（effect=效果越大越好，cost_tokens=总成本越小越好，on_pareto_frontier 标记是否在非支配边界上）
   *  - frontier_line：按 cost_tokens 排序的非支配点序列（用于连出"帕累托前沿"折线）
   *  - defaults：默认坐标映射（前端允许用户切换坐标轴）
   */
  pareto_chart:
    | {
        points: Array<{
          run_id: string;
          label: string;
          runner: string;
          prompt_variant: string;
          model_version: string;
          effect: number;
          effect_metric_id: string;
          cost_tokens: number;
          cost_usd: number;
          step_ms: number;
          composite_score?: number | null;
          on_pareto_frontier?: boolean | null;
        }>;
        frontier_run_ids: string[];
        frontier_line: Array<{ run_id: string | null; cost_tokens: number; effect: number }>;
        defaults: {
          y_axis: string;
          x_axis: string;
        };
      }
    | null;
}

/* ===================================== Live Log (debug) ===================================== */

/** 后端实时日志条目（来自 EventSource /api/admin/live-log）。
 *  ts 为 ISO 字符串，msg 为单行日志原文（含关键字标签如 TIMING/LLM/SKILL/LLM_JSON）。 */
export interface LogEntry {
  ts: string;
  msg: string;
}
