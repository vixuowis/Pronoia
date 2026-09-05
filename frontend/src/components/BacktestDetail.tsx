import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Filter,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Square,
  XCircle,
} from "lucide-react";
import { api, streamBacktest, StreamAbortedError } from "../api";
import { useStore } from "../store";
import type {
  BTRun,
  BTMetrics,
  BTPredictionItem,
  BTPredictionDetail,
  BTStatus,
  BTSSEEvent,
  BTEventCatalogItem,
  BTEventStatus,
} from "../types";
import { CaseDetailPanel, type DetailTab } from "./BacktestDetailPanels";
import { FilterSelect, StatusBadge } from "./BacktestDetailShared";
import { CatalogRow, MetricsGrid, ProgressCard, SSEEventRow } from "./BacktestDetailWidgets";

/* ===================================== 主组件 ===================================== */

export default function BacktestDetail() {
  const runId = useStore((s) => s.currentBTRunId);
  const backFromBTDetail = useStore((s) => s.backFromBTDetail);

  const [run, setRun] = useState<BTRun | null>(null);
  const [metrics, setMetrics] = useState<BTMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  // 分页预测列表 → 改为事件目录（events JSONL 全量 N 条，pending/processing/done 都展示）
  const [catalog, setCatalog] = useState<{ total: number; items: BTEventCatalogItem[] }>({ total: 0, items: [] });
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogLoadedOnce, setCatalogLoadedOnce] = useState(false);
  const [fOnlyIncorrect, setFOnlyIncorrect] = useState(false);
  const [fMarket, setFMarket] = useState<string>("");
  const [fEventType, setFEventType] = useState<string>("");
  const [fStatus, setFStatus] = useState<BTEventStatus | "">(
    "",
  );

  // SSE 最近事件（时间线）
  const [sseEvents, setSseEvents] = useState<BTSSEEvent[]>([]);
  const sseAbortRef = useRef<AbortController | null>(null);
  const [sseConnected, setSseConnected] = useState(false);

  // 单 case 展开详情（点击表格行切换；detail 网络请求在展开后懒加载）
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [predDetail, setPredDetail] = useState<BTPredictionDetail | null>(null);
  const [predDetailLoading, setPredDetailLoading] = useState(false);
  const [predDetailTab, setPredDetailTab] = useState<DetailTab>("log");

  // expandedEventId 变化 → 懒加载详情；切页/取消展开时清零
  useEffect(() => {
    if (!runId || !expandedEventId) {
      setPredDetail(null);
      setPredDetailLoading(false);
      return;
    }
    const matched = catalog.items.find((x) => x.event_id === expandedEventId);
    // 先把列表里已有的 prediction 填进去（若 pending/processing 则没有 prediction，也要构造一个 detail 的 prediction 壳，保证 UI 不空）
    const skeletonEventMeta: Record<string, unknown> = {};
    if (matched) {
      for (const k of ["title", "event_time", "source_url", "symbol", "market", "event_type_l2", "event_text"]) {
        const v = (matched as unknown as Record<string, unknown>)[k];
        if (v != null && v !== "") skeletonEventMeta[k] = v;
      }
    }
    if (matched) {
      if (matched.prediction) {
        setPredDetail({ prediction: matched.prediction, trajectory: null, event_meta: Object.keys(skeletonEventMeta).length ? skeletonEventMeta : undefined });
      } else {
        setPredDetail({
          prediction: {
            id: "",
            run_id: runId,
            event_id: matched.event_id,
            symbol: matched.symbol ?? null,
            market: matched.market ?? null,
            event_type_l2: matched.event_type_l2 ?? null,
            pred_direction: "",
            abstain: false,
            created_at: new Date().toISOString(),
          },
          trajectory: null,
          event_meta: Object.keys(skeletonEventMeta).length ? skeletonEventMeta : undefined,
        });
      }
    }
    let cancelled = false;
    // 只有 status=done 的 prediction 才发网络请求拉 trajectory；pending/processing 直接显示 loading 文案
    if (matched?.status !== "done" || !matched.prediction) {
      setPredDetailLoading(false);
      return;
    }
    setPredDetailLoading(true);
    void (async () => {
      try {
        const d = await api.btGetPredictionDetail(runId, matched?.event_id ?? "");
        if (cancelled) return;
        setPredDetail(d);
      } catch (e) {
        if (cancelled) return;
        console.debug("[bt pred detail] load fail", e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setPredDetailLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedEventId, runId, catalog.items]);

  // -------------------- 初始加载 --------------------
  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    Promise.allSettled([loadRun(), loadMetrics(), loadCatalog()])
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // -------------------- SSE 订阅 --------------------
  useEffect(() => {
    if (!runId || !run) return;
    // 一个 runId 只维护一条 SSE 连接（进入详情页且 run 加载完成后开启）。
    // 终态（done/failed/cancelled）不订阅；pending/running/paused 均保持连接，
    // 以便实时收到 prediction / run_status_changed / run_done 等事件。
    // 依赖用「run 是否已加载」(!run) 而非 run.status，避免 status 每次变化都重开连接。
    const terminal = ["done", "failed", "cancelled"].includes(run.status);
    if (terminal) return;

    const ctl = new AbortController();
    let cancelled = false;
    let streamStarted = false;
    let streamDone = false;

    // 用 50ms 延迟规避 React 18 StrictMode 双 mount 首帧立刻 abort 的问题。
    const id = window.setTimeout(() => {
      if (cancelled || ctl.signal.aborted) return;
      streamStarted = true;
      sseAbortRef.current = ctl;
      setSseConnected(true);

      const onEvent = (ev: BTSSEEvent) => {
        if (cancelled) return;
        if (ev.type === "heartbeat") return;
        // 收集事件（最新在前，保留最近 50 条）
        setSseEvents((xs) => [ev, ...xs].slice(0, 50));

        if (ev.type === "hello") {
          if (typeof ev.done_events === "number") {
            setRun((r) => r ? { ...r, done_events: ev.done_events!, status: (ev.status as BTStatus) ?? r.status } : r);
          }
        } else if (ev.type === "prediction") {
          setRun((r) => r ? { ...r, done_events: (r.done_events ?? 0) + 1 } : r);
          // 局部 merge：catalog 里 event_id 匹配 → 直接 status=done + prediction（减少轮询压力 + UI 立即刷新）
          if (ev.event_id && ev.prediction) {
            setCatalog((c) => ({
              ...c,
              items: c.items.map((it) =>
                it.event_id === ev.event_id
                  ? {
                      ...it,
                      status: "done",
                      prediction: ev.prediction as BTPredictionItem,
                    }
                  : it,
              ),
            }));
          }
          // 间隔性同步 run status；catalog 靠 2s 轮询兜底 + 上面 prediction merge 实时
          void loadRun(true);
        } else if (ev.type === "metrics_snapshot") {
          setRun((r) => r ? {
            ...r,
            done_events: ev.done_count ?? r.done_events,
            acc_t3_strict: ev.acc_t3_strict ?? r.acc_t3_strict,
            acc_t3_strict_lo: ev.acc_t3_strict_lo ?? r.acc_t3_strict_lo,
            acc_t3_non_neutral: ev.acc_t3_non_neutral ?? r.acc_t3_non_neutral,
          } : r);
          // 顺便刷新完整 metrics（偶尔）
          if ((ev.done_count ?? 0) % 10 === 0) void loadMetrics(true);
        } else if (ev.type === "run_started") {
          setRun((r) => r ? { ...r, status: "running", started_at: new Date().toISOString() } : r);
        } else if (ev.type === "run_status_changed") {
          // pause/resume 由后端事件驱动状态同步，不再依赖乐观更新
          if (ev.to) setRun((r) => r ? { ...r, status: ev.to as BTStatus } : r);
        } else if (ev.type === "run_done" || ev.type === "run_failed" || ev.type === "run_cancelled") {
          const st: BTStatus = ev.type === "run_done" ? "done" : ev.type === "run_failed" ? "failed" : "cancelled";
          setRun((r) => r ? { ...r, status: st, finished_at: new Date().toISOString(),
            error_msg: ev.error ?? ev.message ?? r.error_msg } : r);
          // 结束后拉一次完整数据
          void Promise.allSettled([loadRun(true), loadMetrics(true), loadCatalog(true)]);
        }
      };

      streamBacktest(runId, { onEvent, signal: ctl.signal })
        .catch((e) => {
          if (streamDone) return;
          if (e instanceof StreamAbortedError) return;
          const isAbort = (e instanceof DOMException && e.name === "AbortError") ||
            (typeof (e as Error)?.message === "string" &&
              /abort|cancelled|user aborted/i.test((e as Error).message));
          if (isAbort) return;
          console.debug("[bt sse] disconnected", e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          streamDone = true;
          if (streamStarted) setSseConnected(false);
        });
    }, 50);

    return () => {
      cancelled = true;
      window.clearTimeout(id);
      ctl.abort();
      sseAbortRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, !!run]);

  // -------------------- 事件目录 2s 轮询兜底（processing 状态靠文件判定，轮询才能捕捉到变化） --------------------
  useEffect(() => {
    if (!runId || !run) return;
    const active = run.status === "pending" || run.status === "running";
    if (!active) return;
    const interval = window.setInterval(() => {
      void loadCatalog(true);
    }, 2000);
    void loadCatalog(true);
    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, run?.status]);

  // -------------------- 加载函数 --------------------
  async function loadRun(silent = false) {
    if (!runId) return;
    if (!silent) setLoading(true);
    try {
      const r = await api.btGetRun(runId);
      setRun(r);
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function loadMetrics(_silent = false) {
    if (!runId) return;
    try {
      const m = await api.btGetMetrics(runId);
      // 兼容：后端现在返回 BTMetricsV2（可插拔 metrics 字典 + 向后兼容的 acc_t3_* 字段），
      // 详情页的旧面板只消费 acc_t3_strict / acc_t3_non_neutral 这两个 BTPredAccStat 字段，
      // BTMetricsV2 已保留它们，因此这里宽放 setMetrics 存即可。后续再迁移详情页到新指标体系面板。
      setMetrics(m as unknown as BTMetrics);
    } catch {
      /* 没 labels 时 compute_metrics 可能失败 → 置空 */
      setMetrics(null);
    }
  }

  async function loadCatalog(silent = false) {
    if (!runId) return;
    if (!silent) setCatalogLoading(true);
    setCatalogError(null);
    try {
      const r = await api.btListEventCatalog(runId, {
        market: fMarket || undefined,
        event_type_l2: fEventType || undefined,
        only_incorrect: fOnlyIncorrect,
        status: fStatus || undefined,
      });
      setCatalog({ total: r.total, items: r.items });
      setCatalogLoadedOnce(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setCatalogError(msg);
      console.debug("[bt catalog] load fail", msg);
    } finally {
      if (!silent) setCatalogLoading(false);
    }
  }

  // 事件目录首屏必拉一次（任何 status：done/failed/cancelled/running 都应当能看到 N 条事件）
  useEffect(() => {
    if (!runId) return;
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // 当筛选条件变化时，立即重拉 catalog（不再需要分页，直接一次性）
  useEffect(() => {
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fOnlyIncorrect, fMarket, fEventType, fStatus]);

  // -------------------- 操作 --------------------
  async function doStart() {
    if (!runId) return;
    setActing(true);
    setActionErr(null);
    try {
      setRun((r) => r ? { ...r, status: "running" } : r);
      const r = await api.btStartRun(runId);
      if (!r.ok) throw new Error(r.message || "start failed");
    } catch (e) {
      setActionErr(`启动失败：${e instanceof Error ? e.message : String(e)}`);
      void loadRun(true);
    } finally {
      setActing(false);
    }
  }

  async function doCancel() {
    if (!runId) return;
    setActing(true);
    setActionErr(null);
    try {
      const r = await api.btCancelRun(runId);
      if (!r.ok) throw new Error(r.message || "cancel failed");
      setRun((r) => r ? { ...r, status: "cancelled" } : r);
      // 后端 orchestrator 收到 cancel 信号后，会在同一条 SSE 上推送 run_cancelled 并自然关闭流；
      // 客户端主动 abort 只会产生 DevTools ERR_ABORTED 噪音。
    } catch (e) {
      setActionErr(`取消失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActing(false);
    }
  }

  async function doPause() {
    if (!runId) return;
    setActing(true);
    setActionErr(null);
    try {
      setRun((r) => r ? { ...r, status: "paused" } : r);
      const r = await api.btPauseRun(runId);
      if (!r.ok) throw new Error(r.message || "pause failed");
    } catch (e) {
      setActionErr(`暂停失败：${e instanceof Error ? e.message : String(e)}`);
      void loadRun(true);
    } finally {
      setActing(false);
    }
  }

  async function doResume() {
    if (!runId) return;
    setActing(true);
    setActionErr(null);
    try {
      setRun((r) => r ? { ...r, status: "running" } : r);
      const r = await api.btResumeRun(runId);
      if (!r.ok) throw new Error(r.message || "resume failed");
    } catch (e) {
      setActionErr(`继续失败：${e instanceof Error ? e.message : String(e)}`);
      void loadRun(true);
    } finally {
      setActing(false);
    }
  }

  const progress = useMemo(() => {
    if (!run) return 0;
    if (!run.total_events) return 0;
    return Math.min(100, Math.round((run.done_events / run.total_events) * 100));
  }, [run]);

  // -------------------- 渲染 --------------------
  if (!runId) {
    return (
      <div className="flex flex-1 items-center justify-center text-mute text-[13px]">
        <button onClick={backFromBTDetail} className="text-brand hover:underline">← 返回回测列表</button>
        <span className="mx-2">·</span>
        未指定回测 run_id
      </div>
    );
  }

  if (loading && !run) {
    return (
      <div className="flex flex-1 items-center justify-center text-mute text-[13px]">
        <Loader2 size={16} className="mr-2 animate-spin" />
        加载回测详情...
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
      {/* ===================================== Header ===================================== */}
      <header className="flex shrink-0 items-center justify-between border-b border-edge bg-paper px-6 py-3.5">
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={backFromBTDetail}
            className="shrink-0 rounded-lg p-1.5 text-mute transition hover:bg-edge/60 hover:text-ink"
            title="返回回测列表"
          >
            <ArrowLeft size={16} />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate font-serif text-[17px] font-semibold text-ink">{run?.name ?? "加载中..."}</h2>
              {run && <StatusBadge status={run.status} />}
              {sseConnected && (
                <span className="inline-flex items-center gap-1 rounded-full bg-jade-soft/70 px-2 py-0.5 text-[10px] text-jade">
                  <span className="h-1.5 w-1.5 animate-blink rounded-full bg-jade"></span>
                  SSE 实时
                </span>
              )}
            </div>
            {run && (
              <div className="mt-0.5 font-mono text-[10.5px] text-faint">
                id {run.id.slice(0, 14)}… · runner={run.runner} · concurrency={run.concurrency}
                {run.prompt_variant ? ` · prompt=${run.prompt_variant}` : ""}
                {run.model_version ? ` · model=${run.model_version}` : ""}
              </div>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => {
              void Promise.allSettled([loadRun(true), loadMetrics(true), loadCatalog(true)]);
            }}
            className="flex items-center gap-1 rounded-lg border border-edge bg-card px-3 py-1.5 text-[12px] text-mute transition hover:bg-edge/40 hover:text-ink"
          >
            <RefreshCw size={12.5} /> 刷新
          </button>
          {run?.status === "pending" && (
            <button
              onClick={() => void doStart()}
              disabled={acting}
              className="flex items-center gap-1.5 rounded-lg bg-jade px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:bg-jade-hover hover:shadow-pop disabled:opacity-50"
            >
              {acting ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              启动回测
            </button>
          )}
          {run?.status === "running" && (
            <>
              <button
                onClick={() => void doPause()}
                disabled={acting}
                className="flex items-center gap-1.5 rounded-lg bg-amber px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:opacity-90 hover:shadow-pop disabled:opacity-50"
              >
                {acting ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}
                暂停
              </button>
              <button
                onClick={() => void doCancel()}
                disabled={acting}
                className="flex items-center gap-1.5 rounded-lg bg-rise px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:opacity-90 hover:shadow-pop disabled:opacity-50"
              >
                {acting ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                取消
              </button>
            </>
          )}
          {run?.status === "paused" && (
            <>
              <button
                onClick={() => void doResume()}
                disabled={acting}
                className="flex items-center gap-1.5 rounded-lg bg-jade px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:bg-jade-hover hover:shadow-pop disabled:opacity-50"
              >
                {acting ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                继续
              </button>
              <button
                onClick={() => void doCancel()}
                disabled={acting}
                className="flex items-center gap-1.5 rounded-lg bg-rise px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:opacity-90 hover:shadow-pop disabled:opacity-50"
              >
                {acting ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                取消
              </button>
            </>
          )}
        </div>
      </header>

      {actionErr && (
        <div className="mx-6 mt-3 rounded-lg border border-rise/30 bg-rise/5 px-3 py-2 text-[12px] text-rise">
          ⚠️ {actionErr}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4 space-y-5">
        {/* ===================================== 进度 + 指标卡片 ===================================== */}
        <section className="space-y-4">
          {/* 进度条 */}
          <ProgressCard run={run} progress={progress} />

          {/* 指标网格 */}
          {metrics ? (
            <MetricsGrid m={metrics} />
          ) : (
            <div className="rounded-card border border-edge bg-card shadow-card px-5 py-4 text-[12px] text-mute">
              暂无指标数据。若需计算 ACC，请在创建 run 时提供 <span className="font-mono">labels_path</span>，或等待预测事件产生后点击刷新。
            </div>
          )}
        </section>

        {/* ===================================== 实时流 / 事件流 时间线 ===================================== */}
        {run?.status === "running" && (
          <section className="rounded-card border border-edge bg-card shadow-card">
            <div className="flex items-center justify-between border-b border-edge px-4 py-2.5">
              <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
                <Loader2 size={13} className="animate-spin text-brand" />
                实时事件流
              </h3>
              <span className="font-mono text-[11px] text-faint">{sseEvents.length} 条事件</span>
            </div>
            <div className="max-h-[220px] overflow-y-auto px-4 py-2">
              {sseEvents.length === 0 ? (
                <div className="py-4 text-center text-[12px] text-faint">等待事件到达...</div>
              ) : (
                <ul className="space-y-1.5">
                  {sseEvents.map((ev, i) => (
                    <SSEEventRow key={i} ev={ev} />
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}

        {/* ===================================== 预测事件列表 ===================================== */}
        <section className="rounded-card border border-edge bg-card shadow-card">
          {/* 表格头 + 筛选 */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-edge px-4 py-3">
            <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
              <Filter size={13} className="text-mute" />
              事件目录
              <span className="font-mono text-[11px] font-normal text-faint">
                {catalog.total ? `共 ${catalog.total} 条事件` : ""}
              </span>
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex items-center gap-1 text-[11.5px] text-mute">
                <input
                  type="checkbox"
                  checked={fOnlyIncorrect}
                  onChange={(e) => setFOnlyIncorrect(e.target.checked)}
                  className="h-3.5 w-3.5 accent-brand"
                />
                仅显示错误
              </label>
              <FilterSelect
                placeholder="状态"
                value={fStatus}
                options={[
                  { v: "pending", l: "待执行" },
                  { v: "processing", l: "执行中" },
                  { v: "done", l: "已完成" },
                ]}
                onChange={(v) => setFStatus(v as BTEventStatus | "")}
              />
              <FilterSelect
                placeholder="市场"
                value={fMarket}
                options={["CN", "US", "HK", "MACRO"]}
                onChange={setFMarket}
              />
              <FilterSelect
                placeholder="事件类型"
                value={fEventType}
                options={["财报", "并购", "股东增减持", "宏观", "评级调整", "行业政策"]}
                onChange={setFEventType}
              />
            </div>
          </div>

          {/* 表格 */}
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="border-b border-edge bg-edge/20 text-left text-[11px] uppercase tracking-wider text-faint">
                  <th className="w-[38px] px-2 py-2 font-medium"></th>
                  <th className="px-2 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">状态</th>
                  <th className="px-4 py-2 font-medium">标的</th>
                  <th className="px-4 py-2 font-medium">市场</th>
                  <th className="px-4 py-2 font-medium">类型</th>
                  <th className="px-4 py-2 font-medium">预测方向</th>
                  <th className="px-4 py-2 font-medium">置信度</th>
                  <th className="px-4 py-2 font-medium">Oracle T+3 标签</th>
                  <th className="px-4 py-2 font-medium">Oracle CAR T+3</th>
                  <th className="px-4 py-2 font-medium">T+3 对错</th>
                  <th className="px-4 py-2 font-medium">完成时间</th>
                </tr>
              </thead>
              <tbody>
                {catalogLoading && catalog.items.length === 0 ? (
                  <tr><td colSpan={12} className="px-4 py-10 text-center text-mute">
                    <Loader2 size={16} className="mx-auto mb-2 animate-spin text-brand" />
                    加载事件目录...
                  </td></tr>
                ) : catalogError ? (
                  <tr><td colSpan={12} className="px-4 py-10 text-center">
                    <div className="inline-flex flex-col items-center gap-2 text-[12px] text-rose">
                      <XCircle size={16} />
                      <div>事件目录加载失败：<span className="font-mono">{catalogError}</span></div>
                      <button
                        onClick={() => void loadCatalog()}
                        className="mt-1 rounded-md border border-edge bg-card px-3 py-1 text-[11px] text-mute transition hover:bg-edge/40 hover:text-ink"
                      >
                        重新加载
                      </button>
                    </div>
                  </td></tr>
                ) : catalog.items.length === 0 ? (
                  <tr><td colSpan={12} className="px-4 py-10 text-center text-mute text-[12px]">
                    {!catalogLoadedOnce ? "事件目录加载中…" :
                      (fOnlyIncorrect || fMarket || fEventType || fStatus ? "暂无匹配的数据。尝试调整筛选条件。" : "暂无数据：本 run 的 events 文件未定义事件，或 events_path 配置缺失。")}
                  </td></tr>
                ) : (
                  catalog.items.flatMap((it, idx) => {
                    const rowNum = idx + 1;
                    const isOpen = expandedEventId === it.event_id;
                    return [
                      <CatalogRow
                        key={"row-" + it.event_id}
                        item={it}
                        rowIdx={rowNum}
                        isOpen={isOpen}
                        onToggle={() => setExpandedEventId((cur) => (cur === it.event_id ? null : it.event_id))}
                      />,
                      isOpen ? (
                        <tr key={"exp-" + it.event_id}>
                          <td colSpan={12} className="border-b border-edge/60 bg-edge/10">
                            <CaseDetailPanel
                              loading={predDetailLoading}
                              detail={predDetail}
                              activeTab={predDetailTab}
                              onTabChange={setPredDetailTab}
                              itemStatus={it.status}
                              catalogItem={it}
                              runId={runId}
                            />
                          </td>
                        </tr>
                      ) : null,
                    ];
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        {run?.error_msg && run.status === "failed" && (
          <section className="rounded-card border border-rise/40 bg-rise/5 p-4 text-[12.5px] text-rise">
            <div className="mb-1 font-semibold">错误信息</div>
            <div className="font-mono whitespace-pre-wrap break-all">{run.error_msg}</div>
          </section>
        )}

        {/* 底部留白 */}
        <div className="h-6" />
      </div>
    </div>
  );
}