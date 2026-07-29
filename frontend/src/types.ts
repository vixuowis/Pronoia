// 与后端 schemas 对齐的类型定义（docs/design.md §7/§8/§9）

export type Mode = "auto" | "agent" | "team";
export type RightTab = "artifacts" | "skills" | "team" | "logic";
export type ArtifactKind = "kline" | "line" | "table" | "evidence" | "report" | "graph";

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
