import { useEffect, useRef, useState } from "react";
import { ChevronDown, Pause, Play, Terminal, Trash2 } from "lucide-react";
import { useStore } from "../store";
import type { LogEntry } from "../types";
import { cls } from "../utils";

/** 日志行按关键字着色（在深色背景上）。
 *  优先级：[SLOW]/[VSLOW] > LLM_JSON > LLM > SKILL > TIMING > 默认。 */
function logColor(msg: string): string {
  if (/\[(VSLOW|SLOW)\]/.test(msg)) return "text-red-400";
  if (msg.includes("LLM_JSON")) return "text-amber-400";
  if (msg.includes("LLM")) return "text-blue-400";
  if (msg.includes("SKILL")) return "text-emerald-400";
  if (msg.includes("TIMING")) return "text-faint";
  return "text-zinc-300";
}

/** ISO → HH:MM:SS.mmm（本地时区），用于日志行首时间戳。 */
function fmtTs(ts: string): string {
  const t = new Date(ts.replace(" ", "T"));
  if (Number.isNaN(t.getTime())) return ts;
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const ss = String(t.getSeconds()).padStart(2, "0");
  const ms = String(t.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

/** 浮动 LLM 调用日志面板（debug 用）。
 *  从底部弹出，高度 240px；日志最新在上、等宽字体、深色背景。
 *  按关键字着色；顶部清空 / 暂停滚动 / 收起。
 *  自动滚到最新（顶部），用户向下滚动后自动暂停跟随，点「继续」回顶恢复。 */
export default function LiveLogPanel() {
  const logs = useStore((s) => s.liveLogs);
  const clearLiveLogs = useStore((s) => s.clearLiveLogs);
  const toggleLiveLog = useStore((s) => s.toggleLiveLog);

  const scrollRef = useRef<HTMLDivElement>(null);
  /** 用户是否向下滚动浏览历史（暂停自动跟随） */
  const [paused, setPaused] = useState(false);

  // 新日志到来时：未暂停则保持在顶部（最新）
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = 0;
  }, [logs.length, paused]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    // 用户向下滚离顶部 → 自动暂停跟随
    if (el.scrollTop > 4 && !paused) setPaused(true);
  };

  const resume = () => {
    setPaused(false);
    const el = scrollRef.current;
    if (el) el.scrollTop = 0;
  };

  return (
    <div className="absolute bottom-0 left-0 right-0 z-40 flex h-[240px] animate-fadeUp flex-col border-t border-edge bg-ink text-card shadow-pop">
      {/* 顶部工具栏 */}
      <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-3 py-1.5">
        <div className="flex items-center gap-2">
          <Terminal size={13} className="text-faint" />
          <span className="text-[12px] font-medium text-zinc-200">LLM 调用日志</span>
          <span className="rounded bg-white/10 px-1.5 py-px text-[10px] font-medium text-faint">
            {logs.length} 条
          </span>
          {paused && (
            <span className="text-[10px] font-medium text-amber-400">已暂停跟随</span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={clearLiveLogs}
            title="清空日志"
            className="rounded-md p-1.5 text-faint transition-colors hover:bg-white/10 hover:text-zinc-100"
          >
            <Trash2 size={13} />
          </button>
          <button
            onClick={paused ? resume : () => setPaused(true)}
            title={paused ? "继续跟随最新" : "暂停滚动"}
            className={cls(
              "rounded-md p-1.5 transition-colors hover:bg-white/10",
              paused ? "text-amber-400 hover:text-amber-300" : "text-faint hover:text-zinc-100",
            )}
          >
            {paused ? <Play size={13} /> : <Pause size={13} />}
          </button>
          <button
            onClick={toggleLiveLog}
            title="收起面板"
            className="rounded-md p-1.5 text-faint transition-colors hover:bg-white/10 hover:text-zinc-100"
          >
            <ChevronDown size={13} />
          </button>
        </div>
      </div>

      {/* 日志列表（最新在上） */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono text-[11.5px] leading-relaxed"
      >
        {logs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[11.5px] text-faint">
            等待日志…（连接 /api/admin/live-log）
          </div>
        ) : (
          logs.map((entry: LogEntry, i: number) => (
            <div
              key={`${entry.ts}-${i}`}
              className="flex items-start gap-2 px-3 py-px hover:bg-white/5"
            >
              <span className="shrink-0 select-none text-faint/70">{fmtTs(entry.ts)}</span>
              <span className={cls("whitespace-pre-wrap break-all", logColor(entry.msg))}>
                {entry.msg}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
