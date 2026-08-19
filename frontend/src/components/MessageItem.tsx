import { CheckCircle2, ListChecks, RotateCcw, ShieldCheck, User } from "lucide-react";
import { useMemo } from "react";
import type { Message, Part } from "../types";
import { agentColor, agentName } from "../names";
import { useStore } from "../store";
import ThinkingBlock, { type ThinkingSegment } from "./ThinkingBlock";
import ToolCallCard from "./ToolCallCard";
import ArtifactCard from "./ArtifactCard";
import LogicItemsPanel from "./LogicItemsPanel";
import Markdown from "./Markdown";

/**
 * 合并连续 parts 后的渲染项：
 * - thinking → 1 项（连续 thinking parts 合并为单段；串行下即"每个 expert 一段"）
 * - text_envelope → 同一 agent 的连续 text parts 聚合成一个分组容器
 * - single_text → 单段 text（保持原样 + agent 名牌）
 * - other → tool_call / artifact / agent_step
 */
type TextPart = Extract<Part, { type: "text" }>;
type RenderItem =
  | { kind: "thinking"; segments: ThinkingSegment[]; endIdx: number }
  | { kind: "text_envelope"; agent?: string; texts: TextPart[]; indexes: number[]; endIdx: number }
  | { kind: "single_text"; part: TextPart; index: number }
  | { kind: "other"; part: Part; index: number };

function mergeRenderItems(parts: Part[]): RenderItem[] {
  const items: RenderItem[] = [];

  type Buf =
    | { kind: "thinking"; segments: ThinkingSegment[] }
    | { kind: "text"; agent?: string; texts: TextPart[]; indexes: number[] };
  let buf: Buf | null = null;

  const flush = (i: number) => {
    if (!buf) return;
    if (buf.kind === "thinking") {
      if (buf.segments.length > 0) {
        items.push({ kind: "thinking", segments: buf.segments, endIdx: i - 1 });
      }
    } else {
      if (buf.texts.length === 1) {
        items.push({ kind: "single_text", part: buf.texts[0], index: buf.indexes[0] });
      } else if (buf.texts.length > 1) {
        items.push({
          kind: "text_envelope",
          agent: buf.agent,
          texts: buf.texts,
          indexes: buf.indexes,
          endIdx: i - 1,
        });
      }
    }
    buf = null;
  };

  parts.forEach((p, i) => {
    if (p.type === "thinking") {
      if (buf?.kind === "text") flush(i);
      if (buf?.kind === "thinking") {
        buf.segments.push({ agent: p.agent, text: p.text });
      } else {
        buf = { kind: "thinking", segments: [{ agent: p.agent, text: p.text }] };
      }
      return;
    }
    if (p.type === "text") {
      if (buf?.kind === "thinking") flush(i);
      if (buf?.kind === "text") {
        if (buf.agent === p.agent) {
          buf.texts.push(p);
          buf.indexes.push(i);
        } else {
          flush(i);
          buf = { kind: "text", agent: p.agent, texts: [p], indexes: [i] };
        }
      } else {
        buf = { kind: "text", agent: p.agent, texts: [p], indexes: [i] };
      }
      return;
    }
    flush(i);
    items.push({ kind: "other", part: p, index: i });
  });
  flush(parts.length);
  return items;
}

/** Agent Envelope：把同一 agent 的连续 text parts 包成一个分组容器 */
function AgentEnvelope({
  agent,
  texts,
  indexes,
  pending,
  lastTextIdx,
}: {
  agent?: string;
  texts: TextPart[];
  indexes: number[];
  pending: boolean;
  lastTextIdx: number;
}) {
  const agents = useStore((s) => s.agents);
  const color = agentColor(agent, agents);
  const name = agentName(agent, agents);
  const totalLen = texts.reduce((sum, t) => sum + t.text.length, 0);
  return (
    <div
      className="relative rounded-md border border-edge/60 bg-[#FBFAF8]/70 pl-3.5 pr-3 py-2.5 animate-fadeUp"
      style={{ borderLeftWidth: 3, borderLeftColor: color }}
    >
      {/* 顶部 agent 名牌 */}
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px]">
        <span
          className="h-2 w-2 rounded-full ring-2 ring-[#FBFAF8]"
          style={{ backgroundColor: color }}
        />
        <span className="font-semibold" style={{ color }}>
          {name}
        </span>
        <span className="text-faint text-[10.5px]">· {texts.length} 段 · {totalLen} 字</span>
      </div>
      {/* 多段正文 */}
      <div className="space-y-1.5">
        {texts.map((t, j) => {
          const origIdx = indexes[j];
          const isLastText = origIdx === lastTextIdx;
          return (
            <div key={j}>
              <Markdown text={t.text} />
              {pending && isLastText && (
                <span className="ml-0.5 inline-block h-[15px] w-[2.5px] translate-y-[2px] rounded-full bg-brand animate-blink" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** team 模式 agent_step 渲染：研究计划 / 专家完成 / 复核结论 */
function AgentStepView({ part }: { part: Extract<Part, { type: "agent_step" }> }) {
  const agents = useStore((s) => s.agents);

  if (part.phase === "plan" && part.plan?.length) {
    return (
      <div className="rounded-card border border-brand/25 bg-brand-soft/40 px-4 py-3 animate-fadeUp">
        <div className="mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-brand">
          <ListChecks size={14} />
          研究计划 · {part.plan.length} 个子任务并行
        </div>
        <ol className="space-y-1.5">
          {part.plan.map((p, i) => {
            const color = agentColor(p.agent, agents);
            return (
              <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-ink">
                <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span>
                  <span className="font-medium" style={{ color }}>
                    {agentName(p.agent, agents)}
                  </span>
                  <span className="text-mute"> — {p.task ?? p.question ?? ""}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  if (part.phase === "agent_start") {
    const color = agentColor(part.agent, agents);
    return (
      <div className="flex items-center gap-2 text-[12px] text-mute">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute h-full w-full animate-ping rounded-full" style={{ backgroundColor: `${color}99` }} />
          <span className="relative h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
        </span>
        <span style={{ color }} className="font-medium">{agentName(part.agent, agents)}</span>
        正在执行…
      </div>
    );
  }

  if (part.phase === "agent_done") {
    const color = agentColor(part.agent, agents);
    return (
      <div className="flex items-start gap-2 text-[12px] text-mute">
        <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-jade" />
        <span>
          <span className="font-medium" style={{ color }}>{agentName(part.agent, agents)}</span> 完成
          {part.note && <span className="text-faint"> — {part.note}</span>}
        </span>
      </div>
    );
  }

  if (part.phase === "verified") {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-jade/25 bg-jade-soft/60 px-3 py-2 text-[12px] text-jade">
        <ShieldCheck size={13} className="mt-0.5 shrink-0" />
        <span>
          <span className="font-medium">复核完成</span>
          {part.verdict && <span className="text-jade/80"> — {part.verdict}</span>}
          {part.note && <span className="text-jade/80"> — {part.note}</span>}
        </span>
      </div>
    );
  }

  return null;
}

export default function MessageItem({ message }: { message: Message }) {
  const agents = useStore((s) => s.agents);
  const retryLastMessage = useStore((s) => s.retryLastMessage);

  if (message.role === "user") {
    return (
      <div className="flex justify-end animate-fadeUp">
        <div className="flex max-w-[85%] items-start gap-2.5">
          <div className="rounded-card rounded-tr-sm border border-brand/20 bg-brand-soft px-4 py-3 shadow-card">
            <p className="whitespace-pre-wrap text-[14px] leading-[1.8] text-ink">{message.content}</p>
          </div>
          <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-card">
            <User size={14} />
          </span>
        </div>
      </div>
    );
  }

  // assistant：按 parts 时间序渲染
  const parts = message.parts ?? [];
  const useParts = parts.length > 0;
  // team 判定：流式消息带 mode；历史消息从 parts 推断（含计划/非主理人 agent）
  const isTeam =
    message.mode === "team" ||
    parts.some(
      (p) => {
        const agent = "agent" in p ? p.agent : undefined;
        return (p.type === "agent_step" && (p.phase === "plan" || (!!agent && agent !== "router"))) ||
               (!!agent && agent !== "router");
      },
    );
  let lastTextIdx = -1;
  parts.forEach((p, i) => {
    if (p.type === "text") lastTextIdx = i;
  });

  // 合并连续 parts：thinking 连续合并、text 同 agent 合并、other 原样
  const renderItems = useMemo(() => mergeRenderItems(parts), [parts]);

  return (
    <div className="animate-fadeUp">
      <div className="space-y-2.5">
        {useParts ? (
          renderItems.map((it) => {
            if (it.kind === "thinking") {
              const key = `${message.id}_think_${it.endIdx}`;
              return (
                <ThinkingBlock
                  key={key}
                  segments={it.segments}
                  streaming={message.pending && it.endIdx === parts.length - 1}
                />
              );
            }
            if (it.kind === "text_envelope") {
              const key = `${message.id}_env_${it.endIdx}`;
              return (
                <AgentEnvelope
                  key={key}
                  agent={it.agent}
                  texts={it.texts}
                  indexes={it.indexes}
                  pending={!!message.pending}
                  lastTextIdx={lastTextIdx}
                />
              );
            }
            if (it.kind === "single_text") {
              const p = it.part;
              const key = `${message.id}_${it.index}`;
              const color = p.agent ? agentColor(p.agent, agents) : undefined;
              const showBadge = !!p.agent && isTeam;
              return (
                <div key={key}>
                  {showBadge && (
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                      <span className="text-[12px] font-medium" style={{ color }}>
                        {agentName(p.agent, agents)}
                      </span>
                    </div>
                  )}
                  <Markdown text={p.text} />
                  {message.pending && it.index === lastTextIdx && (
                    <span className="ml-0.5 inline-block h-[15px] w-[2.5px] translate-y-[2px] rounded-full bg-brand animate-blink" />
                  )}
                </div>
              );
            }
            // other: tool_call / artifact / agent_step / logic_items
            const p = it.part;
            const key = `${message.id}_${it.index}`;
            if (p.type === "tool_call") {
              return <ToolCallCard key={key} part={p} showAgent={isTeam} />;
            }
            if (p.type === "artifact") {
              return <ArtifactCard key={key} artifactId={p.artifactId} kind={p.kind} title={p.title} />;
            }
            if (p.type === "logic_items") {
              return <LogicItemsPanel key={key} items={p.items} />;
            }
            if (p.type === "agent_step") {
              if (p.phase === "agent_start" && !message.pending) return null;
              return <AgentStepView key={key} part={p} />;
            }
            return null;
          })
        ) : (
          message.content && (
            <div>
              <Markdown text={message.content} />
              {message.pending && (
                <span className="ml-0.5 inline-block h-[15px] w-[2.5px] translate-y-[2px] rounded-full bg-brand animate-blink" />
              )}
            </div>
          )
        )}

        {message.pending && !useParts && !message.content && (
          <div className="flex items-center gap-2 text-[13px] text-mute">
            <span className="relative flex h-2 w-2">
              <span className="absolute h-full w-full animate-ping rounded-full bg-brand/60" />
              <span className="relative h-2 w-2 rounded-full bg-brand" />
            </span>
            {message.mode === "team" ? "研究团队正在规划任务…" : "正在思考…"}
          </div>
        )}

        {message.error && !message.pending && (
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => retryLastMessage()}
              className="flex items-center gap-1.5 rounded-md border border-edge bg-paper px-2.5 py-1 text-[12px] font-medium text-ink transition-colors hover:bg-brand-soft hover:text-brand"
            >
              <RotateCcw size={12} />
              重试
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
