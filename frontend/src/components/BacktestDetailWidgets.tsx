import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  XCircle,
} from "lucide-react";
import type { BTRun, BTMetrics, BTSSEEvent, BTEventCatalogItem } from "../types";
import { cls, relTime } from "../utils";
import { DirBadge, EventStatusBadge, fmtPct } from "./BacktestDetailShared";

/* ===================================== 进度条卡片 ===================================== */

export function ProgressCard({ run, progress }: { run: BTRun | null; progress: number }) {
  if (!run) return null;
  const barColor =
    run.status === "failed" ? "bg-rise"
    : run.status === "done" ? "bg-jade"
    : run.status === "running" ? "bg-brand"
    : run.status === "paused" ? "bg-amber"
    : "bg-faint";

  return (
    <div className="rounded-card border border-edge bg-card shadow-card p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-[28px] font-bold tabular-nums text-ink">{progress}<span className="text-[16px] text-faint">%</span></span>
          <div className="text-[12.5px] text-mute">
            已完成 <span className="font-mono font-semibold text-ink">{run.done_events}</span>
            {" / "}
            <span className="font-mono">{run.total_events}</span> 事件
          </div>
        </div>
        <div className="flex flex-col items-end text-[11.5px] text-mute">
          <div>创建于 {run.created_at?.slice(5, 16).replace("T", " ")}</div>
          {run.started_at && <div>启动于 {run.started_at.slice(5, 16).replace("T", " ")}</div>}
          {run.finished_at && <div>结束于 {run.finished_at.slice(5, 16).replace("T", " ")}</div>}
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-edge/80">
        <div
          className={cls("h-full rounded-full transition-all duration-300", barColor)}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

/* ===================================== 指标网格 ===================================== */

export function MetricsGrid({ m }: { m: BTMetrics }) {
  const strict = m.acc_t3_strict;
  const nonNeu = m.acc_t3_non_neutral;
  const cards: MetricCardProps[] = [
    {
      title: "T+3 方向准确率 (Strict)",
      hint: "含中性；中性预测或Oracle中性均从分母剔除（§5 Wilson ≥70% 达标线）",
      acc: strict.acc,
      k: strict.k,
      n: strict.n,
      wilsonLo: strict.wilson_lo_95,
      threshold: 0.70,
      tone: strict.n > 0 && (strict.wilson_lo_95 ?? 0) >= 0.70 ? "good" : strict.acc >= 0.65 ? "warn" : "bad",
    },
    {
      title: "T+3 方向准确率 (Non-Neutral)",
      hint: "仅统计非中性预测（|CAR|≥阈值），反映真实方向判断能力",
      acc: nonNeu.acc,
      k: nonNeu.k,
      n: nonNeu.n,
      wilsonLo: nonNeu.wilson_lo_95,
      tone: nonNeu.acc >= 0.8 ? "good" : nonNeu.acc >= 0.65 ? "warn" : "bad",
    },
    {
      title: "中性预测占比",
      hint: `理想区间 15-20%；过高=过度保守；过低=假信号频发。当前样本量 ${m.total ?? 0}`,
      acc: m.neutral_ratio ?? 0,
      k: m.neutral_count ?? 0,
      n: m.total ?? 0,
      percentOnly: true,
      tone:
        (m.neutral_ratio ?? 0) >= 0.15 && (m.neutral_ratio ?? 0) <= 0.20 ? "good"
        : (m.neutral_ratio ?? 0) < 0.15 || (m.neutral_ratio ?? 0) > 0.30 ? "warn" : "neutral",
    },
    {
      title: "弃权（abstain）事件",
      hint: "5xx/429/超时重试失败被强制置 neutral 的样本（不计入 ACC 分母）",
      acc: m.total > 0 ? (m.abstain_count ?? 0) / m.total : 0,
      k: m.abstain_count ?? 0,
      n: m.total ?? 0,
      percentOnly: true,
      tone: (m.abstain_count ?? 0) === 0 ? "good" : (m.abstain_count ?? 0) <= 3 ? "warn" : "bad",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((c, i) => (
        <MetricCard key={i} {...c} />
      ))}
    </div>
  );
}

interface MetricCardProps {
  title: string;
  hint: string;
  acc: number;
  k: number;
  n: number;
  wilsonLo?: number | null;
  threshold?: number;
  tone: "good" | "warn" | "bad" | "neutral";
  percentOnly?: boolean;
}

function MetricCard({ title, hint, acc, k, n, wilsonLo, threshold, tone, percentOnly }: MetricCardProps) {
  const toneCls = {
    good: "border-jade/30 bg-jade-soft/30",
    warn: "border-brand/30 bg-brand-soft/30",
    bad:  "border-rise/30 bg-rise/5",
    neutral: "border-edge",
  }[tone];
  const pctColor = {
    good: "text-jade",
    warn: "text-brand",
    bad:  "text-rise",
    neutral: "text-ink",
  }[tone];

  return (
    <div className={cls("rounded-card border bg-card shadow-card p-4", toneCls)}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[12px] font-medium text-ink">{title}</div>
          <p className="mt-0.5 max-w-[240px] text-[10.5px] leading-relaxed text-faint">{hint}</p>
        </div>
      </div>
      <div className="mt-2.5 flex items-baseline gap-2">
        <span className={cls("font-mono text-[26px] font-bold tabular-nums", pctColor)}>
          {percentOnly || !Number.isNaN(acc) ? fmtPct(acc) : "—"}
        </span>
        {!percentOnly && wilsonLo != null && !Number.isNaN(wilsonLo) && (
          <span className="font-mono text-[11px] text-faint tabular-nums">
            Wilson lo {fmtPct(wilsonLo)}
            {threshold != null && (
              <span className={cls("ml-1", (wilsonLo ?? 0) >= threshold ? "text-jade" : "text-rise")}>
                / ≥ {fmtPct(threshold)}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="mt-1 font-mono text-[10.5px] text-mute tabular-nums">
        k={k} / n={n}
        {!percentOnly && threshold != null && wilsonLo != null && (
          (wilsonLo ?? 0) >= threshold
            ? <span className="ml-2 text-jade">✓ 达标</span>
            : <span className="ml-2 text-rise">✗ 未达标</span>
        )}
      </div>
    </div>
  );
}

/* ===================================== SSE 事件行 ===================================== */

export function SSEEventRow({ ev }: { ev: BTSSEEvent }) {
  const cfg: Record<string, { label: string; color: string }> = {
    hello:            { label: "订阅就绪",    color: "text-jade" },
    run_started:      { label: "回测启动",    color: "text-brand" },
    run_info:         { label: "状态同步",    color: "text-mute" },
    prediction:       { label: "预测完成",    color: "text-violet" },
    metrics_snapshot: { label: "指标快照",    color: "text-jade" },
    run_done:         { label: "回测完成",    color: "text-jade" },
    run_failed:       { label: "回测失败",    color: "text-rise" },
    run_cancelled:    { label: "回测取消",    color: "text-violet" },
  };
  const c = cfg[ev.type] ?? { label: ev.type, color: "text-mute" };
  const summary = summarizeSSE(ev);
  return (
    <li className="flex items-start gap-2 text-[11.5px]">
      <span className={cls("mt-0.5 shrink-0 font-mono text-[10px] font-medium uppercase tracking-wider", c.color)}>
        {c.label}
      </span>
      <span className="min-w-0 flex-1 truncate text-ink/85">{summary}</span>
    </li>
  );
}

function summarizeSSE(ev: BTSSEEvent): string {
  switch (ev.type) {
    case "hello":
      return `初始状态=${ev.status}，已完成 ${ev.done_events}/${ev.total_events}`;
    case "prediction":
      return [
        ev.symbol,
        ev.event_id ? `ev=${ev.event_id.slice(0, 8)}` : null,
        ev.prediction ? `dir=${ev.prediction.pred_direction} conf=${(ev.prediction.confidence ?? 0).toFixed(2)}` : null,
      ].filter(Boolean).join(" · ");
    case "metrics_snapshot":
      return `done=${ev.done_count} · strict=${fmtPct(ev.acc_t3_strict)} (lo ${fmtPct(ev.acc_t3_strict_lo)}) · non_neutral=${fmtPct(ev.acc_t3_non_neutral)}${ev.from_catchup ? " · 补发" : ""}`;
    case "run_done":
    case "run_failed":
    case "run_cancelled":
      return ev.message ?? ev.error ?? ev.type;
    default:
      return ev.message ?? "";
  }
}

/* ===================================== 事件目录行（CatalogRow） ===================================== */

export function CatalogRow({
  item,
  rowIdx,
  isOpen,
  onToggle,
}: {
  item: BTEventCatalogItem;
  rowIdx: number;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const p = item.prediction;
  const hasCkpt = !!p?.trajectory_ckpt;
  const rowClickable = true;
  const rowTitle =
    item.status === "pending"
      ? "点击查看事件元信息；等待回测调度执行"
      : item.status === "processing"
      ? "点击查看事件元信息；正在执行 Team 多 Agent 决策，等待中..."
      : hasCkpt
      ? "点击查看完整 trajectory 执行日志（含决策链）"
      : "点击查看本 case 详细信息";

  return (
    <tr
      className={cls(
        "border-b border-edge/60 transition",
        rowClickable ? "cursor-pointer" : "",
        isOpen ? "bg-brand-soft/15" : "hover:bg-edge/20",
        item.status === "processing" ? "bg-amber-soft/5" : "",
      )}
      onClick={onToggle}
      title={rowTitle}
    >
      <td className="px-2 py-2 text-center align-top">
        {isOpen
          ? <ChevronUp size={14} className="mx-auto text-brand" />
          : <ChevronDown size={14} className={cls("mx-auto", hasCkpt ? "text-brand/70" : "text-faint")} />}
      </td>
      <td className="px-2 py-2 font-mono text-[11px] text-faint tabular-nums align-top">{rowIdx}</td>
      <td className="px-4 py-2 align-top">
        <EventStatusBadge status={item.status} />
      </td>
      <td className="px-4 py-2 align-top">
        <div className="font-mono text-[12.5px] font-medium text-ink">{item.symbol ?? "—"}</div>
        <div className="font-mono text-[10px] text-faint">ev {item.event_id.slice(0, 14)}</div>
        {item.title && (
          <div className="mt-0.5 max-w-[360px] truncate text-[10.5px] text-faint" title={item.title}>
            {item.title}
          </div>
        )}
      </td>
      <td className="px-4 py-2 align-top">
        {item.market
          ? <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono text-[10.5px] text-mute">{item.market}</span>
          : <span className="text-faint">—</span>
        }
      </td>
      <td className="px-4 py-2 text-[12px] text-mute align-top">{item.event_type_l2 ?? "—"}</td>
      <td className="px-4 py-2 align-top">
        {p ? (
          <div className="flex items-center gap-1.5 flex-wrap">
            <DirBadge d={p.pred_direction} />
            {p.abstain && <span className="rounded bg-violet-soft px-1 py-0.5 text-[10px] text-violet">abstain</span>}
            {hasCkpt && (
              <span className="inline-flex items-center gap-0.5 rounded bg-jade-soft/40 px-1 py-0.5 text-[9.5px] text-jade" title="已写 trajectory ckpt 可展开查看">
                <FileText size={10} /> log
              </span>
            )}
          </div>
        ) : item.status === "processing" ? (
          <span className="inline-flex items-center gap-1 text-[10.5px] text-amber">
            <Loader2 size={10.5} className="animate-spin" />
            决策中...
          </span>
        ) : (
          <span className="text-[10.5px] text-faint">TBD</span>
        )}
      </td>
      <td className="px-4 py-2 font-mono text-[12px] tabular-nums align-top">
        {p && p.confidence != null
          ? (p.confidence * 100).toFixed(0) + "%"
          : <span className="text-faint">—</span>}
      </td>
      <td className="px-4 py-2 align-top">
        {p ? <DirBadge d={p.oracle_label_t3} /> : <span className="text-faint">—</span>}
      </td>
      <td className="px-4 py-2 font-mono text-[12px] tabular-nums align-top">
        {p && p.oracle_car_t3 != null
          ? <span className={cls((p.oracle_car_t3 ?? 0) >= 0 ? "text-fall" : "text-rise")}>
              {(p.oracle_car_t3 >= 0 ? "+" : "") + (p.oracle_car_t3 * 100).toFixed(2)}%
            </span>
          : <span className="text-faint">—</span>
        }
      </td>
      <td className="px-4 py-2 align-top">
        {p?.is_correct_t3 === true ? (
          <span className="inline-flex items-center gap-0.5 text-[11.5px] text-jade"><CheckCircle2 size={12}/> 正确</span>
        ) : p?.is_correct_t3 === false ? (
          <span className="inline-flex items-center gap-0.5 text-[11.5px] text-rise"><XCircle size={12}/> 错误</span>
        ) : p ? (
          <span className="text-[11.5px] text-faint">未对照</span>
        ) : (
          <span className="text-[11.5px] text-faint">—</span>
        )}
      </td>
      <td className="px-4 py-2 text-[11.5px] text-mute align-top">
        {p?.created_at ? (
          <>
            <div>{relTime(p.created_at)}</div>
            <div className="font-mono text-[10px] text-faint">{p.created_at.slice(5, 16).replace("T", " ")}</div>
          </>
        ) : item.event_time ? (
          <span className="text-faint">as-of {item.event_time.slice(0, 16).replace("T", " ")}</span>
        ) : (
          <span className="text-faint">—</span>
        )}
      </td>
    </tr>
  );
}