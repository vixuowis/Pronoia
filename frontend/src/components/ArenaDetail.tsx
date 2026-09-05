import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Database,
  Eye,
  EyeOff,
  Loader2,
  Medal,
  RefreshCw,
  ScatterChart,
  Swords,
  Target,
  Zap,
} from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import type { ArenaComputeResult, ArenaItem, BTMetricDef, BTMetricItem } from "../types";
import { cls } from "../utils";

/* ===================================== 小工具 ===================================== */

const RUN_COLORS = [
  "#3b82f6", // blue
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#06b6d4", // cyan
  "#ec4899", // pink
  "#84cc16", // lime
];

function runColor(idx: number) {
  return RUN_COLORS[idx % RUN_COLORS.length];
}

function fmtMetric(v: number | string | Record<string, unknown> | null | undefined, digits = 3): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "object") return JSON.stringify(v).slice(0, 16);
  if (Number.isNaN(v)) return "—";
  if (v >= 1 || v <= -1) {
    return v.toFixed(Math.max(1, digits - Math.max(0, Math.floor(Math.log10(Math.abs(v)) + 1))));
  }
  return v.toFixed(digits);
}

/* ===================================== 雷达图 ===================================== */

function RadarChart({
  axes,
  series,
  metricDefs,
}: {
  axes: Array<{ metric_id: string; display_name: string }>;
  series: Array<{ run_id: string; label: string; values: (number | null)[] }>;
  metricDefs: Record<string, BTMetricDef>;
}) {
  const W = 520;
  const H = 460;
  const cx = W / 2;
  const cy = H / 2;
  const R = 160;
  const N = axes.length;
  if (N === 0) {
    return (
      <div className="grid h-[460px] place-items-center rounded-lg border border-dashed border-edgeDark/70 text-[12px] text-faint">
        无可用雷达轴指标
      </div>
    );
  }

  const rings = [0.25, 0.5, 0.75, 1.0];
  const angle = (i: number) => -Math.PI / 2 + (i / N) * Math.PI * 2;

  const axisPt = (i: number, r: number) => ({
    x: cx + Math.cos(angle(i)) * r,
    y: cy + Math.sin(angle(i)) * r,
  });

  const ringsSvg = rings.map((f) => {
    const pts = Array.from({ length: N }, (_, i) => {
      const p = axisPt(i, R * f);
      return `${p.x},${p.y}`;
    }).join(" ");
    return <polygon key={`ring-${f}`} points={pts} fill="none" stroke="var(--edge)" strokeDasharray="2 3" />;
  });

  const axesSvg = axes.map((_, i) => {
    const p = axisPt(i, R);
    return (
      <line
        key={`ax-${i}`}
        x1={cx}
        y1={cy}
        x2={p.x}
        y2={p.y}
        stroke="var(--edge)"
        strokeOpacity={0.6}
      />
    );
  });

  const labelsSvg = axes.map((ax, i) => {
    const p = axisPt(i, R + 22);
    const hib = metricDefs[ax.metric_id]?.higher_is_better ?? true;
    return (
      <g key={`lbl-${i}`}>
        <text
          x={p.x}
          y={p.y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="10.5"
          fill="var(--mute)"
          fontWeight={500}
        >
          {ax.display_name}
        </text>
        <text
          x={p.x}
          y={p.y + 12}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="9"
          fill={hib ? "var(--jade)" : "var(--rise)"}
          opacity={0.8}
        >
          {hib ? "↑ 越高越好" : "↓ 越低越好"}
        </text>
      </g>
    );
  });

  const seriesSvg = series.map((s, si) => {
    const color = runColor(si);
    const pts = s.values.map((v, i) => {
      const f = typeof v === "number" && !Number.isNaN(v) ? Math.min(1, Math.max(0, v)) : 0;
      const p = axisPt(i, R * f);
      return `${p.x},${p.y}`;
    }).join(" ");
    return (
      <g key={s.run_id}>
        <polygon
          points={pts}
          fill={color}
          fillOpacity={0.12}
          stroke={color}
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        {s.values.map((v, i) => {
          if (typeof v !== "number" || Number.isNaN(v)) return null;
          const f = Math.min(1, Math.max(0, v));
          const p = axisPt(i, R * f);
          return <circle key={`${s.run_id}-${i}`} cx={p.x} cy={p.y} r={2.8} fill={color} />;
        })}
      </g>
    );
  });

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto block w-full max-w-[560px]">
        {ringsSvg}
        {axesSvg}
        {seriesSvg}
        {labelsSvg}
        {/* 中心点 */}
        <circle cx={cx} cy={cy} r={1.6} fill="var(--faint)" />
      </svg>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-3 px-4">
        {series.map((s, si) => (
          <div key={s.run_id} className="inline-flex items-center gap-1.5 text-[11px] text-ink">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ background: runColor(si), opacity: 0.85 }}
            />
            <span className="max-w-[220px] truncate" title={s.label}>
              {s.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ===================================== 概览：综合得分 + 各指标排名表 ===================================== */

function OverviewPanel({ result }: { result: ArenaComputeResult }) {
  const { ranking, composite_score, metric_defs, per_run } = result;
  const metricIds = result.selected_metric_ids;

  const runIds = Object.keys(per_run);

  const compositeSorted = useMemo(() => {
    if (!composite_score) return [];
    const arr = Object.entries(composite_score.per_run_score).map(([run_id, v]) => ({
      run_id,
      score: v.score,
      rank: v.rank,
    }));
    arr.sort((a, b) => (b.rank ?? 99) - (a.rank ?? 99) > 0 ? -1 : 1);
    return arr;
  }, [composite_score]);

  return (
    <div className="space-y-5">
      {composite_score && compositeSorted.length > 0 && (
        <section>
          <div className="mb-2.5 flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-md bg-brand/10 text-brand">
              <Medal size={13} />
            </span>
            <div>
              <div className="text-[12.5px] font-semibold">综合得分（{composite_score.method}）</div>
              <div className="text-[10.5px] text-mute">{composite_score.description}</div>
            </div>
          </div>
          <div className="overflow-hidden rounded-lg border border-edgeDark/70 bg-card">
            <div className="flex items-center gap-3 p-3">
              {compositeSorted.map((row, idx) => {
                const max = Math.max(...compositeSorted.map((r) => r.score ?? 0));
                const ratio = max > 0 ? (row.score ?? 0) / max : 0;
                const color = runColor(runIds.indexOf(row.run_id));
                const info = per_run[row.run_id];
                return (
                  <div
                    key={row.run_id}
                    className="flex min-w-0 flex-1 flex-col rounded-md border border-edge/70 bg-edge/20 p-3"
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <div className="inline-flex items-center gap-1.5">
                        <span
                          className={cls(
                            "grid h-5 w-5 place-items-center rounded-full text-[10px] font-bold text-white",
                            idx === 0
                              ? "bg-amber"
                              : idx === 1
                              ? "bg-zinc-400"
                              : idx === 2
                              ? "bg-orange-400"
                              : "bg-edgeDark text-mute",
                          )}
                        >
                          {row.rank ?? idx + 1}
                        </span>
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: color }}
                        />
                        <span className="truncate text-[11.5px] font-medium" title={info?.display_name}>
                          {info?.display_name ?? row.run_id}
                        </span>
                      </div>
                      <div className="text-[13px] font-semibold tabular-nums text-ink">
                        {fmtMetric(row.score, 3)}
                      </div>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-edgeDark/40">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${Math.round(ratio * 100)}%`, background: color }}
                      />
                    </div>
                    <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[10px] text-mute">
                      <span className="truncate">{info?.runner ?? ""}</span>
                      <span className="truncate font-mono text-right">{info?.model_version ?? ""}</span>
                      <span className="truncate">{info?.prompt_variant ?? ""}</span>
                      <span className="text-right">
                        {info?.done_events ?? 0} / {info?.total_events ?? 0}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-jade/10 text-jade">
            <Target size={13} />
          </span>
          <div>
            <div className="text-[12.5px] font-semibold">各指标排名</div>
            <div className="text-[10.5px] text-mute">点击单元格可查看该 Run 的指标详情</div>
          </div>
        </div>
        <div className="overflow-x-auto rounded-lg border border-edgeDark/70 bg-card">
          <table className="min-w-full text-left text-[12px]">
            <thead className="bg-edge/40 text-[10.5px] uppercase tracking-wide text-faint">
              <tr>
                <th className="sticky left-0 z-10 bg-edge/60 px-3 py-2 font-medium">Run</th>
                {metricIds.map((mid) => {
                  const def = metric_defs[mid];
                  return (
                    <th
                      key={mid}
                      className="px-3 py-2 font-medium"
                      title={def?.description}
                    >
                      <div className="inline-flex items-center gap-1">
                        {def?.display_name ?? mid}
                        <span className="text-[9.5px] opacity-70">
                          {(def?.higher_is_better ?? true) ? "↑" : "↓"}
                        </span>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {runIds.map((rid, ri) => {
                const info = per_run[rid];
                const color = runColor(ri);
                return (
                  <tr key={rid} className="border-t border-edge/70 hover:bg-edge/30">
                    <td className="sticky left-0 bg-card px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
                        <div className="min-w-0">
                          <div className="truncate font-medium" title={info.display_name}>
                            {info.display_name}
                          </div>
                          <div className="truncate text-[10px] text-faint">
                            {info.runner} · {info.prompt_variant} · <span className="font-mono">{info.model_version}</span>
                          </div>
                        </div>
                      </div>
                    </td>
                    {metricIds.map((mid) => {
                      const rows = ranking[mid] ?? [];
                      const cell = rows.find((r) => r.run_id === rid);
                      const val = cell?.value;
                      const def = metric_defs[mid];
                      const hib = def?.higher_is_better ?? true;
                      let cellClass = "";
                      if (cell?.rank === 1) cellClass = hib ? "text-jade font-semibold" : "text-jade font-semibold";
                      else if (cell?.rank === runIds.length) cellClass = "text-rise/80";
                      return (
                        <td
                          key={mid}
                          className="px-3 py-2 tabular-nums"
                          title={def?.description}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className={cls("text-[10px] text-faint", cell?.rank === 1 && "text-amber font-semibold")}>
                              #{cell?.rank ?? "—"}
                            </span>
                            <span className={cellClass}>
                              {typeof val === "number" ? fmtMetric(val, 4) : "—"}
                            </span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ===================================== 显著性检验矩阵 ===================================== */

function SignificancePanel({ result }: { result: ArenaComputeResult }) {
  const { pairwise_tests, per_run } = result;
  const runIds = Object.keys(per_run);
  const metricIds = result.selected_metric_ids;
  const [curMetric, setCurMetric] = useState<string>(metricIds[0] ?? "");

  if (pairwise_tests == null || Object.keys(pairwise_tests).length === 0) {
    return (
      <div className="grid h-60 place-items-center rounded-lg border border-dashed border-edgeDark/70 text-[12px] text-faint">
        当前结果未包含显著性检验（需要在比对时提供事件级 labels）
      </div>
    );
  }

  const pvalThreshold = 0.05;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11.5px] font-medium">指标：</span>
        <div className="flex flex-wrap gap-1">
          {metricIds.map((mid) => (
            <button
              key={mid}
              onClick={() => setCurMetric(mid)}
              className={cls(
                "rounded-full border px-2 py-0.5 text-[10.5px] transition",
                curMetric === mid
                  ? "border-brand/50 bg-brand/10 text-brand"
                  : "border-edgeDark/70 text-mute hover:text-ink",
              )}
            >
              {result.metric_defs[mid]?.display_name ?? mid}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-edgeDark/70 bg-card">
        <table className="min-w-full text-left text-[12px]">
          <thead className="bg-edge/40 text-[10.5px] uppercase tracking-wide text-faint">
            <tr>
              <th className="px-3 py-2 font-medium">Run A \ Run B</th>
              {runIds.map((rid, i) => (
                <th key={rid} className="px-3 py-2 font-medium">
                  <div className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ background: runColor(i) }} />
                    <span className="max-w-[140px] truncate" title={per_run[rid].display_name}>
                      {per_run[rid].display_name}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runIds.map((a, ai) => (
              <tr key={a} className="border-t border-edge/70">
                <td className="px-3 py-2">
                  <div className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ background: runColor(ai) }} />
                    <span className="max-w-[160px] truncate font-medium" title={per_run[a].display_name}>
                      {per_run[a].display_name}
                    </span>
                  </div>
                </td>
                {runIds.map((b, _bi) => {
                  if (a === b) {
                    return (
                      <td key={b} className="px-3 py-2 bg-edge/20 text-center text-[10.5px] text-faint">
                        —
                      </td>
                    );
                  }
                  const m: any =
                    (pairwise_tests as any)[a]?.[b]?.per_metric?.[curMetric] ??
                    (pairwise_tests as any)[b]?.[a]?.per_metric?.[curMetric];
                  if (!m) {
                    return <td key={b} className="px-3 py-2 text-faint">—</td>;
                  }
                  const p: number | undefined = m.p_value;
                  const delta: number | undefined = m.delta;
                  const win: string | undefined = m.winner;
                  const sig = p !== undefined && p < pvalThreshold;
                  return (
                    <td key={b} className="px-3 py-2 tabular-nums">
                      <div
                        className={cls(
                          "rounded-md px-2 py-1.5 text-[11px]",
                          sig
                            ? win === a
                              ? "bg-jade/10 text-jade"
                              : win === b
                              ? "bg-rise/10 text-rise"
                              : "bg-amber/10 text-amber"
                            : "bg-edge/30 text-mute",
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">p={p !== undefined ? p.toFixed(p < 0.001 ? 3 : 2) : "—"}</span>
                          {delta !== undefined && (
                            <span className={cls(delta > 0 ? "text-jade" : delta < 0 ? "text-rise" : "")}>
                              Δ{delta > 0 ? "+" : ""}
                              {(delta * 100).toFixed(1)}%
                            </span>
                          )}
                        </div>
                        {sig && (
                          <div className="mt-0.5 text-[9.5px] opacity-80">
                            显著 {win === a ? "A 胜" : win === b ? "B 胜" : "平局"}
                          </div>
                        )}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-[11px] text-mute">
        显著性阈值 p &lt; {pvalThreshold}；对角线上方与下方对称：颜色由行 A（Run A）对列 B（Run B）的胜负方向着色。
      </div>
    </div>
  );
}

/* ===================================== 头对头事件级对决 ===================================== */

function HeadToHeadPanel({ result }: { result: ArenaComputeResult }) {
  const h2h: any = (result as any).head_to_head;
  if (!h2h || !Array.isArray(h2h.event_level) || h2h.event_level.length === 0) {
    return (
      <div className="grid h-60 place-items-center rounded-lg border border-dashed border-edgeDark/70 text-[12px] text-faint">
        当前比对未提供事件级 head_to_head 数据（需要在比对时提供 labels 列表）
      </div>
    );
  }

  const runIds = Object.keys(result.per_run);
  const [page, setPage] = useState(0);
  const PAGE = 20;
  const total = h2h.event_level.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE));
  const start = page * PAGE;
  const rows = h2h.event_level.slice(start, start + PAGE);

  return (
    <div className="space-y-4">
      {h2h.summary && (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          {Object.entries(h2h.summary as Record<string, any>).map(([key, s]) => (
            <div key={key} className="rounded-lg border border-edgeDark/70 bg-card p-3">
              <div className="mb-1 text-[11.5px] font-semibold">{key}</div>
              <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-mute">
                <span>A 胜</span>
                <span className="text-right tabular-nums text-jade">{s.a_wins ?? 0}</span>
                <span>B 胜</span>
                <span className="text-right tabular-nums text-rise">{s.b_wins ?? 0}</span>
                <span>平局</span>
                <span className="text-right tabular-nums">{s.ties ?? 0}</span>
                <span>共同事件</span>
                <span className="text-right tabular-nums">{s.shared ?? 0}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-edgeDark/70 bg-card">
        <table className="min-w-full text-left text-[12px]">
          <thead className="bg-edge/40 text-[10.5px] uppercase tracking-wide text-faint">
            <tr>
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">事件 ID</th>
              <th className="px-3 py-2 font-medium">Oracle</th>
              {runIds.map((rid, i) => (
                <th key={rid} className="px-3 py-2 font-medium">
                  <div className="inline-flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ background: runColor(i) }} />
                    <span className="max-w-[140px] truncate" title={result.per_run[rid].display_name}>
                      {result.per_run[rid].display_name}
                    </span>
                  </div>
                </th>
              ))}
              <th className="px-3 py-2 font-medium">最佳 Run</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((ev: any, idx: number) => (
              <tr key={ev.event_id ?? idx} className="border-t border-edge/70 hover:bg-edge/30">
                <td className="px-3 py-2 text-[10.5px] tabular-nums text-faint">{start + idx + 1}</td>
                <td className="px-3 py-2 font-mono text-[11px]">{ev.event_id}</td>
                <td className="px-3 py-2">
                  <span
                    className={cls(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                      ev.oracle === "up"
                        ? "bg-jade/10 text-jade"
                        : ev.oracle === "down"
                        ? "bg-rise/10 text-rise"
                        : "bg-edge text-mute",
                    )}
                  >
                    {ev.oracle ?? "—"}
                  </span>
                </td>
                {runIds.map((rid, _ri) => {
                  const r = ev.per_run?.[rid];
                  if (!r) return <td key={rid} className="px-3 py-2 text-faint">—</td>;
                  const correct = r.correct;
                  const pred = r.prediction;
                  return (
                    <td key={rid} className="px-3 py-2">
                      <div
                        className={cls(
                          "rounded px-2 py-1 text-[10.5px]",
                          correct === true
                            ? "bg-jade/10 text-jade"
                            : correct === false
                            ? "bg-rise/10 text-rise"
                            : "bg-edge/40 text-mute",
                        )}
                      >
                        <span className="font-medium">{pred ?? "?"}</span>
                        {typeof r.confidence === "number" && (
                          <span className="ml-1 text-[9.5px] opacity-70">
                            @{(r.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                    </td>
                  );
                })}
                <td className="px-3 py-2">
                  {Array.isArray(ev.best_runs) && ev.best_runs.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {ev.best_runs.map((rid: string) => {
                        const idx_ = runIds.indexOf(rid);
                        return (
                          <span
                            key={rid}
                            className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-1.5 py-0.5 text-[10px] text-brand"
                          >
                            <span
                              className="inline-block h-1.5 w-1.5 rounded-full"
                              style={{ background: idx_ >= 0 ? runColor(idx_) : "var(--faint)" }}
                            />
                            {result.per_run[rid]?.display_name ?? rid}
                          </span>
                        );
                      })}
                    </div>
                  ) : (
                    <span className="text-[10.5px] text-faint">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-[11.5px] text-mute">
        <div>
          共 {total} 条共同事件，显示 {start + 1}–{Math.min(total, start + PAGE)}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded-md border border-edgeDark/70 px-2 py-0.5 text-mute hover:text-ink disabled:opacity-40"
          >
            上一页
          </button>
          <span className="tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="rounded-md border border-edgeDark/70 px-2 py-0.5 text-mute hover:text-ink disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  );
}

/* ===================================== Pareto 成本/效果 面板 ===================================== */

type XAxisKey = "cost_tokens" | "cost_usd" | "step_ms";
type YAxisKey = "effect" | "composite_score";

const X_LABELS: Record<XAxisKey, string> = {
  cost_tokens: "总成本 tokens (in+out)",
  cost_usd: "估算成本 USD",
  step_ms: "总耗时 ms",
};
const Y_LABELS: Record<YAxisKey, string> = {
  effect: "效果 (主指标 acc)",
  composite_score: "综合得分 composite_score",
};
const X_FORMAT: Record<XAxisKey, (v: number) => string> = {
  cost_tokens: (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`),
  cost_usd: (v) => `$${v.toFixed(3)}`,
  step_ms: (v) =>
    v >= 1000 * 60
      ? `${(v / 60000).toFixed(1)} min`
      : v >= 1000
        ? `${(v / 1000).toFixed(1)}s`
        : `${v} ms`,
};

function ParetoPanel({ result }: { result: ArenaComputeResult }) {
  const [xKey, setXKey] = useState<XAxisKey>("cost_tokens");
  const [yKey, setYKey] = useState<YAxisKey>("effect");
  const [hover, setHover] = useState<string | null>(null);

  const data = result.pareto_chart;
  if (!data || !Array.isArray(data.points) || data.points.length === 0) {
    return (
      <div className="rounded-lg border border-edgeDark/70 bg-card p-10 text-center text-sm text-mute">
        暂无 成本/效果 数据。请先对模型完成回测，Arena 结果会自动从 bt_predictions.tokens 聚合成本后计算。
        <br />
        或点击「重新计算」触发后端补算。
      </div>
    );
  }

  const getX = (p: (typeof data.points)[number]) => p[xKey];
  const getY = (p: (typeof data.points)[number]) => {
    if (yKey === "composite_score") {
      const v = p.composite_score;
      return typeof v === "number" ? v : 0;
    }
    return p.effect;
  };

  // SVG 坐标系
  const W = 900;
  const H = 520;
  const PAD = { l: 72, r: 28, t: 24, b: 60 };
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;

  const xs = data.points.map(getX);
  const ys = data.points.map(getY);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;
  // 留出一点边距，避免点压到轴
  const xLo = xMin - xRange * 0.08;
  const xHi = xMax + xRange * 0.12;
  const yLo = Math.max(0, yMin - yRange * 0.15);
  const yHi = yMax + yRange * 0.15;
  const xSpan = xHi - xLo || 1;
  const ySpan = yHi - yLo || 1;

  const sx = (v: number) => PAD.l + ((v - xLo) / xSpan) * iw;
  const sy = (v: number) => PAD.t + ih - ((v - yLo) / ySpan) * ih;

  // 网格/轴刻度（每方向 5 格）
  const TICK_N = 5;
  const yTicks = Array.from({ length: TICK_N + 1 }, (_, i) => yLo + (ySpan * i) / TICK_N);
  const xTicks = Array.from({ length: TICK_N + 1 }, (_, i) => xLo + (xSpan * i) / TICK_N);

  // 帕累托前沿折线点（基于当前 x/y 重新判断非支配，防止用户切换轴后还是旧 frontier_line）
  const curPts = data.points.map((p) => ({
    p,
    x: getX(p),
    y: getY(p),
  }));
  const dominates = (a: (typeof curPts)[number], b: (typeof curPts)[number]) => {
    // X 越小越好，Y 越大越好
    const xok = a.x <= b.x;
    const yok = a.y >= b.y;
    const strict = a.x < b.x || a.y > b.y;
    return xok && yok && strict;
  };
  const onFront = new Set<string>();
  curPts.forEach((c, i) => {
    const dominated = curPts.some((d, j) => j !== i && dominates(d, c));
    if (!dominated) onFront.add(c.p.run_id);
  });
  const frontSorted = [...curPts]
    .filter((c) => onFront.has(c.p.run_id))
    .sort((a, b) => a.x - b.x);

  // 颜色分配（沿用 run_id hash）
  const colors = useMemo(() => {
    const palette = [
      "#3b82f6",
      "#f97316",
      "#10b981",
      "#8b5cf6",
      "#ef4444",
      "#0ea5e9",
      "#e11d48",
      "#a855f7",
    ];
    const map: Record<string, string> = {};
    const ids = Object.keys(result.per_run);
    ids.forEach((id, i) => {
      let h = 0;
      for (let k = 0; k < id.length; k++) h = (h * 31 + id.charCodeAt(k)) >>> 0;
      map[id] = palette[(i + h) % palette.length];
    });
    return map;
  }, [result.per_run]);

  return (
    <div className="space-y-4">
      {/* 坐标切换 + 图例 */}
      <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-edgeDark/70 bg-card p-4">
        <div className="flex flex-wrap items-center gap-5">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-mute">X 轴（成本，越小越好）</div>
            <div className="inline-flex overflow-hidden rounded-md border border-edgeDark/70 bg-paper">
              {(["cost_tokens", "cost_usd", "step_ms"] as XAxisKey[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setXKey(k)}
                  className={cls(
                    "px-3 py-1.5 text-[12px] font-medium transition",
                    xKey === k
                      ? "bg-brand text-white"
                      : "text-ink/80 hover:bg-edge/40 hover:text-ink"
                  )}
                >
                  {X_LABELS[k]}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-mute">Y 轴（效果，越大越好）</div>
            <div className="inline-flex overflow-hidden rounded-md border border-edgeDark/70 bg-paper">
              {(["effect", "composite_score"] as YAxisKey[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setYKey(k)}
                  className={cls(
                    "px-3 py-1.5 text-[12px] font-medium transition",
                    yKey === k
                      ? "bg-brand text-white"
                      : "text-ink/80 hover:bg-edge/40 hover:text-ink"
                  )}
                >
                  {Y_LABELS[k]}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="text-[11px] leading-relaxed text-mute">
          <div>
            <span className="mr-1 inline-block h-2 w-3 rounded-sm bg-brand/30 align-middle" />
            虚线折线 = <b className="text-ink">帕累托前沿（非支配边界）</b>
          </div>
          <div>前沿线上的点：在相同成本下效果最高 / 相同效果下成本最低。</div>
          <div>右下方向 = 性价比更高（更省、更好）。</div>
        </div>
      </div>

      {/* SVG 图 */}
      <div className="overflow-x-auto rounded-lg border border-edgeDark/70 bg-card p-4">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[720px]">
          {/* 背景 */}
          <rect x={PAD.l} y={PAD.t} width={iw} height={ih} fill="#0b1020" rx={6} />

          {/* 网格 + Y 刻度 */}
          {yTicks.map((t, i) => {
            const y = sy(t);
            return (
              <g key={`yt-${i}`}>
                <line
                  x1={PAD.l}
                  x2={PAD.l + iw}
                  y1={y}
                  y2={y}
                  stroke="#1f2937"
                  strokeDasharray={i === TICK_N ? "" : "3 3"}
                />
                <text
                  x={PAD.l - 8}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={11}
                  fill="#94a3b8"
                >
                  {yKey === "composite_score" || yKey === "effect"
                    ? t.toFixed(3)
                    : ""}
                </text>
              </g>
            );
          })}

          {/* X 刻度 */}
          {xTicks.map((t, i) => {
            const x = sx(t);
            return (
              <g key={`xt-${i}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={PAD.t}
                  y2={PAD.t + ih}
                  stroke="#1f2937"
                  strokeDasharray={i === 0 ? "" : "3 3"}
                />
                <text
                  x={x}
                  y={PAD.t + ih + 16}
                  textAnchor="middle"
                  fontSize={11}
                  fill="#94a3b8"
                >
                  {X_FORMAT[xKey](t)}
                </text>
              </g>
            );
          })}

          {/* 帕累托前沿连线 */}
          {frontSorted.length >= 2 && (
            <polyline
              points={frontSorted
                .map((f) => `${sx(f.x)},${sy(f.y)}`)
                .join(" ")}
              fill="none"
              stroke={colors[frontSorted[0].p.run_id] || "#3b82f6"}
              strokeOpacity={0.55}
              strokeDasharray="5 4"
              strokeWidth={2}
            />
          )}
          {/* 前沿延伸（起点向下画到 x 轴，终点向上画到顶部 —— 只在当前 frontier 逻辑下示意 "L 型外包线"） */}
          {frontSorted.length >= 1 && (
            <>
              {/* 左边界：从最小成本点向左下延伸 */}
              <line
                x1={sx(frontSorted[0].x)}
                x2={sx(frontSorted[0].x)}
                y1={sy(frontSorted[0].y)}
                y2={PAD.t + ih}
                stroke={colors[frontSorted[0].p.run_id] || "#3b82f6"}
                strokeOpacity={0.18}
                strokeDasharray="2 3"
              />
              <line
                x1={sx(frontSorted[0].x)}
                x2={PAD.l}
                y1={PAD.t + ih}
                y2={PAD.t + ih}
                stroke={colors[frontSorted[0].p.run_id] || "#3b82f6"}
                strokeOpacity={0.18}
                strokeDasharray="2 3"
              />
              {/* 右边界：从最大效果点向右上延伸 */}
              <line
                x1={sx(frontSorted[frontSorted.length - 1].x)}
                x2={sx(frontSorted[frontSorted.length - 1].x)}
                y1={sy(frontSorted[frontSorted.length - 1].y)}
                y2={PAD.t}
                stroke={colors[frontSorted[frontSorted.length - 1].p.run_id] || "#3b82f6"}
                strokeOpacity={0.18}
                strokeDasharray="2 3"
              />
              <line
                x1={sx(frontSorted[frontSorted.length - 1].x)}
                x2={PAD.l + iw}
                y1={PAD.t}
                y2={PAD.t}
                stroke={colors[frontSorted[frontSorted.length - 1].p.run_id] || "#3b82f6"}
                strokeOpacity={0.18}
                strokeDasharray="2 3"
              />
            </>
          )}

          {/* 轴标签 */}
          <text
            x={PAD.l + iw / 2}
            y={H - 16}
            textAnchor="middle"
            fontSize={12}
            fontWeight={600}
            fill="#cbd5e1"
          >
            {X_LABELS[xKey]} ← 越小越省 →
          </text>
          <text
            x={18}
            y={PAD.t + ih / 2}
            textAnchor="middle"
            fontSize={12}
            fontWeight={600}
            fill="#cbd5e1"
            transform={`rotate(-90, 18, ${PAD.t + ih / 2})`}
          >
            ↑ {Y_LABELS[yKey]} 越大越好 →
          </text>

          {/* 散点 */}
          {curPts.map(({ p, x, y }) => {
            const onF = onFront.has(p.run_id);
            const isHover = hover === p.run_id;
            const cx = sx(x);
            const cy = sy(y);
            return (
              <g
                key={p.run_id}
                onMouseEnter={() => setHover(p.run_id)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer" }}
              >
                {/* halo */}
                {isHover && (
                  <circle cx={cx} cy={cy} r={20} fill={colors[p.run_id]} fillOpacity={0.15} />
                )}
                {onF && (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={12}
                    fill="none"
                    stroke={colors[p.run_id]}
                    strokeOpacity={0.55}
                    strokeWidth={1.5}
                    strokeDasharray="2 2"
                  />
                )}
                <circle
                  cx={cx}
                  cy={cy}
                  r={onF ? 8.5 : 6.5}
                  fill={colors[p.run_id]}
                  stroke="#0b1020"
                  strokeWidth={2}
                />
                {/* 标签：前沿 or hover 才显示，否则只在右侧额外 legend 显示 */}
                {(onF || isHover) && (
                  <g>
                    <rect
                      x={cx + 10}
                      y={cy - 14}
                      width={Math.max(110, 9 * p.label.length)}
                      height={20}
                      rx={4}
                      fill="#0b1020"
                      stroke={colors[p.run_id]}
                      strokeOpacity={0.5}
                      opacity={0.95}
                    />
                    <text
                      x={cx + 16}
                      y={cy - 1}
                      fontSize={11}
                      fill="#e2e8f0"
                      fontWeight={500}
                    >
                      {p.label}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* 表：详细点信息 */}
      <div className="overflow-x-auto rounded-lg border border-edgeDark/70 bg-card">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-edgeDark/70 bg-edge/30 text-[11px] uppercase text-mute">
              <th className="px-3 py-2 text-left">模型 / Runner</th>
              <th className="px-3 py-2 text-right">效果 (acc)</th>
              <th className="px-3 py-2 text-right">综合得分</th>
              <th className="px-3 py-2 text-right">Tokens (in)</th>
              <th className="px-3 py-2 text-right">Tokens (out)</th>
              <th className="px-3 py-2 text-right">总成本 tokens</th>
              <th className="px-3 py-2 text-right">估算 USD</th>
              <th className="px-3 py-2 text-right">耗时</th>
              <th className="px-3 py-2 text-center">帕累托前沿</th>
            </tr>
          </thead>
          <tbody>
            {[...data.points]
              .sort((a, b) => (onFront.has(a.run_id) === onFront.has(b.run_id) ? 0 : onFront.has(a.run_id) ? -1 : 1))
              .map((p) => {
                const onF = onFront.has(p.run_id);
                const pr = result.per_run[p.run_id];
                return (
                  <tr
                    key={p.run_id}
                    onMouseEnter={() => setHover(p.run_id)}
                    onMouseLeave={() => setHover(null)}
                    className={cls(
                      "border-b border-edgeDark/40 transition",
                      hover === p.run_id ? "bg-edge/30" : "hover:bg-edge/20"
                    )}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{ background: colors[p.run_id] }}
                        />
                        <div>
                          <div className="font-medium text-ink">{p.label}</div>
                          <div className="text-[10px] text-mute">{pr?.runner} · {p.prompt_variant}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{(p.effect ?? 0).toFixed(3)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{typeof p.composite_score === "number" ? p.composite_score.toFixed(3) : "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{(pr?.tokens_in ?? 0).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{(pr?.tokens_out ?? 0).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-semibold">{p.cost_tokens.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-amber-300">${(p.cost_usd ?? 0).toFixed(4)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{X_FORMAT.step_ms(p.step_ms ?? 0)}</td>
                    <td className="px-3 py-2 text-center">
                      {onF ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
                          ● 帕累托最优
                        </span>
                      ) : (
                        <span className="text-[11px] text-mute">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ===================================== 主组件：Arena 详情 ===================================== */

type ArenaTab = "overview" | "radar" | "significance" | "h2h" | "pareto";

export default function ArenaDetail() {
  const currentArenaId = useStore((s) => s.currentArenaId);
  const backFromArenaDetail = useStore((s) => s.backFromArenaDetail);
  const goBTList = useStore((s) => () => s.setView("backtest-list"));
  const patchArena = useStore((s) => s.patchArena);

  const [arena, setArena] = useState<ArenaItem | null>(null);
  const [result, setResult] = useState<ArenaComputeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [computing, setComputing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<ArenaTab>("overview");
  const [hideTies, setHideTies] = useState(false); // 预留：未来可切换 h2h 是否隐藏平局

  const load = async (id: string) => {
    setLoading(true);
    setErr(null);
    try {
      const a = await api.arenaGet(id);
      setArena(a);
      if (a.status === "done" && a.result) {
        setResult(a.result);
      } else {
        setResult(null);
      }
    } catch (e) {
      setErr((e as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (currentArenaId) void load(currentArenaId);
  }, [currentArenaId]);

  const compute = async () => {
    if (!currentArenaId) return;
    setComputing(true);
    setErr(null);
    patchArena(currentArenaId, { status: "computing" });
    try {
      const r = await api.arenaCompute(currentArenaId);
      setResult(r);
      setArena((a) => (a ? { ...a, status: "done", finished_at: new Date().toISOString() } : a));
      patchArena(currentArenaId, { status: "done" });
    } catch (e) {
      setErr((e as Error).message || "计算失败");
      setArena((a) => (a ? { ...a, status: "failed" } : a));
      patchArena(currentArenaId, { status: "failed" });
    } finally {
      setComputing(false);
    }
  };

  const runIds = result ? Object.keys(result.per_run) : [];

  const tabs: Array<{ id: ArenaTab; label: string; icon: React.ReactNode }> = [
    { id: "overview", label: "概览 & 排名", icon: <Medal size={12} /> },
    { id: "radar", label: "雷达图", icon: <Target size={12} /> },
    { id: "significance", label: "显著性检验", icon: <Zap size={12} /> },
    { id: "h2h", label: "头对头 (事件级)", icon: <Swords size={12} /> },
    { id: "pareto", label: "成本/效果 (帕累托)", icon: <ScatterChart size={12} /> },
  ];

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-paper">
      {/* 顶栏 */}
      <header className="flex items-center justify-between gap-4 border-b border-edgeDark/70 px-5 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            onClick={backFromArenaDetail}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-mute transition hover:bg-edge hover:text-ink"
          >
            <ArrowLeft size={13} />
            Arena 列表
          </button>
          <span className="text-[11px] text-faint">/</span>
          <button
            onClick={goBTList}
            className="rounded-md px-2 py-1 text-[11.5px] text-mute hover:bg-edge hover:text-ink"
          >
            回测 Run
          </button>
          <ChevronRight size={11} className="text-faint" />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="grid h-6 w-6 place-items-center rounded-md bg-jade/10 text-jade">
                <Swords size={12} />
              </span>
              <span className="truncate text-[14px] font-semibold">{arena?.name ?? "Arena 详情"}</span>
              {result && (
                <span className="rounded-full bg-brand/10 px-1.5 py-0.5 text-[10px] font-medium text-brand">
                  {runIds.length} runs · {result.selected_metric_ids.length} 指标
                </span>
              )}
            </div>
            {arena?.description && (
              <div className="ml-8 mt-0.5 truncate text-[11px] text-mute">{arena.description}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {arena && (
            <div className="inline-flex items-center gap-1.5 rounded-full bg-edge/50 px-2 py-1 text-[10.5px] text-mute">
              <Database size={10.5} /> {arena.dataset_name ?? arena.dataset_id ?? "跨数据集"}
            </div>
          )}
          <button
            onClick={() => currentArenaId && void load(currentArenaId)}
            disabled={loading}
            title="刷新"
            className="rounded-md border border-edgeDark/70 bg-card p-1.5 text-mute transition hover:text-ink disabled:opacity-50"
          >
            <RefreshCw size={14} className={cls(loading && "animate-spin")} />
          </button>
          <button
            onClick={compute}
            disabled={computing}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-[12px] font-semibold text-white shadow-card transition hover:bg-brand/90 disabled:opacity-50"
          >
            {computing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={13} />
            )}
            {computing ? "正在计算…" : "重新计算"}
          </button>
        </div>
      </header>

      {/* Tab 栏 */}
      <div className="flex items-center justify-between gap-3 border-b border-edgeDark/70 bg-edge/20 px-5 py-2">
        <div className="flex flex-wrap items-center gap-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cls(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11.5px] font-medium transition",
                tab === t.id
                  ? "bg-card text-brand shadow-card"
                  : "text-mute hover:bg-card/60 hover:text-ink",
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setHideTies((x) => !x)}
            className={cls(
              "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10.5px]",
              hideTies
                ? "border-brand/40 bg-brand/10 text-brand"
                : "border-edgeDark/70 text-mute hover:text-ink",
            )}
            title="头对头面板是否隐藏平局事件（暂未过滤，仅为未来预留）"
          >
            {hideTies ? <EyeOff size={11} /> : <Eye size={11} />}
            隐藏平局
          </button>
        </div>
      </div>

      {/* 内容区 */}
      <main className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {loading && !result && (
          <div className="grid h-60 place-items-center text-[12px] text-faint">
            <Loader2 size={18} className="animate-spin" /> 正在加载 Arena 结果…
          </div>
        )}
        {err && !result && (
          <div className="rounded-md border border-rise/40 bg-rise/5 px-4 py-3 text-[12px] text-rise">{err}</div>
        )}
        {!loading && !result && !err && (
          <div className="mx-auto mt-16 max-w-lg rounded-xl border border-dashed border-edgeDark/70 p-8 text-center">
            <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand/10 text-brand">
              <Target size={22} />
            </div>
            <div className="mb-1 text-[14px] font-semibold">该 Arena 尚未计算比对结果</div>
            <div className="mb-4 text-[12px] leading-relaxed text-mute">
              点击「计算」按钮，聚合所选 Run 的指标并生成：
              <br />
              排名表 · 雷达图 · 显著性检验 · 头对头事件对决。
            </div>
            <button
              onClick={compute}
              disabled={computing}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-card hover:bg-brand/90 disabled:opacity-50"
            >
              {computing ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              {computing ? "正在计算…" : "立即计算"}
            </button>
          </div>
        )}

        {result && (
          <div className="mx-auto w-full max-w-[1200px]">
            {tab === "overview" && <OverviewPanel result={result} />}
            {tab === "radar" && (
              <RadarChart
                axes={result.radar_chart.axes}
                series={result.radar_chart.series}
                metricDefs={result.metric_defs}
              />
            )}
            {tab === "significance" && <SignificancePanel result={result} />}
            {tab === "h2h" && <HeadToHeadPanel result={result} />}
            {tab === "pareto" && <ParetoPanel result={result} />}
          </div>
        )}

        {/* 底部：参与 Run 卡片列表 */}
        {result && (
          <section className="mx-auto mt-8 w-full max-w-[1200px]">
            <div className="mb-2.5 text-[12px] font-semibold">参与的回测 Run</div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {runIds.map((rid, i) => {
                const info = result.per_run[rid];
                const color = runColor(i);
                return (
                  <div
                    key={rid}
                    className="rounded-lg border border-edgeDark/70 bg-card p-3"
                  >
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
                        <div className="min-w-0">
                          <div className="truncate text-[12.5px] font-medium">{info.display_name}</div>
                          <div className="mt-0.5 text-[10px] text-faint">{rid}</div>
                        </div>
                      </div>
                      <span className="rounded-full bg-edge/60 px-1.5 py-0.5 text-[9.5px] text-mute tabular-nums">
                        {info.done_events} / {info.total_events}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10.5px] text-mute">
                      <span className="truncate">runner</span>
                      <span className="truncate text-right text-ink">{info.runner}</span>
                      <span className="truncate">prompt</span>
                      <span className="truncate text-right text-ink">{info.prompt_variant}</span>
                      <span className="truncate">model</span>
                      <span className="truncate text-right font-mono text-ink">{info.model_version}</span>
                      <span className="truncate">status</span>
                      <span className="text-right text-ink">{info.status}</span>
                    </div>
                    {/* 该 Run 的核心指标 highlight */}
                    <div className="mt-2.5 border-t border-edge/70 pt-2">
                      <div className="flex flex-wrap gap-1.5">
                        {result.selected_metric_ids.slice(0, 5).map((mid) => {
                          const m: BTMetricItem | undefined = (info.metrics as any)?.[mid];
                          const def = result.metric_defs[mid];
                          return (
                            <div
                              key={mid}
                              className="rounded-md border border-edge/70 bg-edge/30 px-2 py-1"
                              title={def?.description}
                            >
                              <div className="text-[9px] uppercase tracking-wide text-faint">
                                {def?.display_name ?? mid}
                              </div>
                              <div className="text-[11.5px] font-semibold tabular-nums text-ink">
                                {fmtMetric(m?.value, 3)}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
