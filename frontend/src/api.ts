import type {
  AgentMeta,
  Artifact,
  CaseDetail,
  CaseItem,
  Mode,
  SkillMeta,
  SuggestionItem,
  SSEEvent,
} from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  skills: () => req<SkillMeta[]>("/skills"),
  agents: () => req<AgentMeta[]>("/agents"),
  suggestions: () => req<{ items: SuggestionItem[]; source: string; fallback: boolean }>("/suggestions"),
  cases: () => req<CaseItem[]>("/cases"),
  createCase: (title?: string) =>
    req<CaseItem>("/cases", { method: "POST", body: JSON.stringify(title ? { title } : {}) }),
  caseDetail: (id: string) => req<CaseDetail>(`/cases/${id}`),
  deleteCase: (id: string) => req<{ ok: boolean }>(`/cases/${id}`, { method: "DELETE" }),
  pinArtifact: (caseId: string, artifactId: string) =>
    // 后端 toggle_pin 返回完整 artifact（含最新 pinned 字段）
    req<Artifact>(`/cases/${caseId}/artifacts/${artifactId}/pin`, {
      method: "POST",
      body: "{}",
    }),
  genReport: (caseId: string) =>
    req<Artifact>(`/cases/${caseId}/report`, { method: "POST", body: "{}" }),
  logicAutoCheck: (item: {
    hypothesis: string;
    category?: string;
    scope?: string;
    horizon?: string;
    check?: string;
    question?: string;
  }) =>
    fetch(`${BASE}/logic/auto_check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    }).then(async (r) => {
      if (!r.ok) {
        let detail = `auto_check ${r.status}`;
        try {
          const j = await r.json();
          if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch { /* ignore */ }
        throw new Error(detail);
      }
      return (await r.json()) as {
        verdict: "verified" | "rejected" | "inconclusive" | "pending_scheduled" | "error";
        status: string;
        reasoning: string;
        evidence: Array<{ skill: string; args?: Record<string, unknown>; ok?: boolean; summary?: string }>;
        data_summary: string;
        next_check_at: string | null;
        ran_at: string;
      };
    }),
};

/** fetch 主动中止的标记（区别于真实网络错误），供 store 静默处理 */
export class StreamAbortedError extends Error {
  constructor() { super("stream-aborted"); this.name = "StreamAbortedError"; }
}

export interface StreamHandlers {
  onEvent: (ev: SSEEvent) => void;
  signal?: AbortSignal;
}

/**
 * SSE 客户端（design.md §7 / §10）：
 * fetch POST /api/chat + ReadableStream，按 `\n\n` 分帧、逐行 `data: {json}` 解析；
 * AbortSignal → 立即 reader.cancel()，不向 fetch 传 signal，
 * 避免浏览器把 in-flight 请求标记为 ERR_ABORTED 写到 Console。
 */
export async function streamChat(
  body: {
    case_id: string;
    message: string;
    mode: Mode;
    agent?: string | null;
    team_members?: string[] | null;
  },
  { onEvent, signal }: StreamHandlers,
): Promise<void> {
  // 进入前先看 signal；已 abort 则不发请求
  if (signal?.aborted) throw new StreamAbortedError();
  // 页面已隐藏（切 tab / 关闭 preview）时也别发请求 —— 浏览器随后会强 abort
  // 留下 net::ERR_ABORTED 噪音；不如直接 throw 让 store 静默收尾。
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    throw new StreamAbortedError();
  }

  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (!res.body) throw new Error("响应无流式内容");

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let aborted = false;

  // 监听外部 abort：立刻关闭 reader，fetch 自然结束（不会触发 ERR_ABORTED）
  if (signal) {
    if (signal.aborted) {
      reader.cancel().catch(() => undefined);
      throw new StreamAbortedError();
    }
    signal.addEventListener("abort", () => {
      aborted = true;
      reader.cancel().catch(() => undefined);
    }, { once: true });
  }

  const handleFrame = (frame: string) => {
    for (const line of frame.split("\n")) {
      const trimmed = line.trimEnd();
      if (!trimmed.startsWith("data:")) continue;
      const data = trimmed.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        onEvent(JSON.parse(data) as SSEEvent);
      } catch {
        // 忽略坏帧，不中断流
      }
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (aborted) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleFrame(frame);
        if (aborted) break;
      }
      if (aborted) break;
    }
  } catch (e) {
    if (aborted || (e instanceof DOMException && e.name === "AbortError")) {
      throw new StreamAbortedError();
    }
    throw e;
  }
  if (aborted) throw new StreamAbortedError();
  // 流末尾可能残留未以 \n\n 结尾的一帧
  if (buf.trim()) handleFrame(buf);
}
