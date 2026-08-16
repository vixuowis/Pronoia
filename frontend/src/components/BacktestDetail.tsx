import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleDashed,
  FileText,
  Filter,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Square,
  XCircle,
  Minus,
  Timer,
  TrendingUp,
  TrendingDown,
  X,
  Maximize2,
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
  BTDirection,
  BTEventCatalogItem,
  BTEventStatus,
  BTTrajectoryCkpt,
} from "../types";
import { cls, clsx, relTime } from "../utils";

/* ===================================== 小工具 ===================================== */

function StatusBadge({ status }: { status: BTStatus | string }) {
  const cfg: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
    pending: { label: "待启动", className: "bg-edge text-mute", icon: <CircleDashed size={11} /> },
    running: { label: "运行中", className: "bg-brand-soft text-brand", icon: <Loader2 size={11} className="animate-spin" /> },
    done: { label: "已完成", className: "bg-jade-soft text-jade", icon: <CheckCircle2 size={11} /> },
    failed: { label: "失败", className: "bg-rise/10 text-rise", icon: <XCircle size={11} /> },
    cancelled: { label: "已取消", className: "bg-violet-soft text-violet", icon: <Square size={11} /> },
  };
  const c = cfg[status] ?? cfg.pending;
  return (
    <span className={cls("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium", c.className)}>
      {c.icon}{c.label}
    </span>
  );
}

function DirBadge({ d }: { d: BTDirection | string | null | undefined }) {
  if (!d) return <span className="text-faint">—</span>;
  const cfg: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    up:    { label: "看涨", cls: "bg-fall/10 text-fall", icon: <TrendingUp size={10.5} /> },
    down:  { label: "看跌", cls: "bg-rise/10 text-rise", icon: <TrendingDown size={10.5} /> },
    neutral: { label: "中性", cls: "bg-edge text-mute", icon: <Minus size={10.5} /> },
  };
  const c = cfg[d] ?? { label: d, cls: "bg-edge text-mute", icon: null };
  return (
    <span className={cls("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] font-medium", c.cls)}>
      {c.icon}{c.label}
    </span>
  );
}

/**
 * 判断 source_url 是否为 FEVER 生成的占位链接（点出去一定 404）。
 * 此类链接点击时应当拦截 → 打开「完整事件说明」Modal，而非跳外部 404。
 *
 * 识别逻辑（优先自上而下，最后用强特征兜底）：
 * 1) URL 里包含已知的 dataset_id 连字符形式 "<dsid>-NNN"（每个 FEVER 合成事件的 event_id = "<dsid>-NNN"，写 source_url 时都会带它）。
 * 2) 兼容旧数据：域名 + 参数特征（巨潮/SEC/港交所/中国政府网里的 fever_ 占位符）。
 */
function isFeverSyntheticSourceUrl(url: string): boolean {
  if (!url) return false;
  const FEVER_DATASET_IDS = [
    "cn_earnings_q2",
    "cn_insiders",
    "cn_policy",
    "us_earnings_q2",
    "hk_ratings",
  ];
  // 1) 最强特征：URL 里有 "<dsid>-NNN"（NNN 为 3 位数字，是 event_id 的格式）
  const eventIdLike = new RegExp(`(?:${FEVER_DATASET_IDS.join("|")})-\\d{2,4}`);
  if (eventIdLike.test(url)) return true;

  try {
    const u = new URL(url);
    const host = u.hostname;
    const search = u.search || "";
    const path = u.pathname || "";
    // 2) 兼容兜底：各类域名单独正则
    if (host.endsWith("cninfo.com.cn") && /announcementId=ann\d+h\d?_/.test(search)) return true;
    if (host.endsWith("cninfo.com.cn") && /announcementId=ann_insider_/.test(search)) return true;
    if (host.endsWith("sec.gov") && /-fever-/.test(path + search)) return true;
    if (host.endsWith("hkexnews.hk") && /fever_/.test(path + search)) return true;
    if (
      (host.endsWith("gov.cn") || host.endsWith("caixin.com") || host.endsWith("mofcom.gov.cn") || host.endsWith("pbc.gov.cn") || host.endsWith("csrc.gov.cn")) &&
      /(docid|fid|refid|id)=fever_/.test(search)
    ) {
      return true;
    }
    if (/(fever_|_fever_)/.test(url) && !host.includes("127.0.0.1") && !host.includes("localhost")) return true;
    return false;
  } catch {
    return false;
  }
}

function fmtPct(v: number | null | undefined, digits = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/* ===================================== 主组件 ===================================== */

export default function BacktestDetail() {
  const runId = useStore((s) => s.currentBTRunId);
  const backFromBTDetail = useStore((s) => s.backFromBTDetail);
  const patchBTRun = useStore((s) => s.patchBTRun);

  const [run, setRun] = useState<BTRun | null>(null);
  const [metrics, setMetrics] = useState<BTMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  // 每次用户显式操作（Start/Pause/Resume/Cancel）成功后 +1，
  // 用于让 SSE useEffect 仅在必要时重跑；避免「run.status 任何变化（包括 SSE hello 帧推送的 status 同步）」都 cleanup→abort 导致 DevTools 报 ERR_ABORTED。
  const [sseEpoch, setSseEpoch] = useState(0);

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
  const [predDetailTab, setPredDetailTab] =
    useState<"log" | "rationale" | "packet" | "prompt" | "logic" | "market">("log");

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
    // 只在「进入页面时 + run 已加载 + 用户显式操作 sseEpoch」时评估是否要开订阅，
    // 不随 run.status 任何变化重跑（否则会出现：SSE hello 帧推送 status=running → effect 重跑 → ctl.abort() → DevTools 报 net::ERR_ABORTED）。
    // 同一 runId 的整个生命周期，只要应该开流就只开一条；服务器 run_done/failed/cancelled 事件到达后会自然断流。
    const shouldStream = run.status === "running" || run.status === "pending";
    if (!shouldStream) return;

    const ctl = new AbortController();
    let cancelled = false;
    let streamStarted = false;
    let streamDone = false;

    // 用 50ms 延迟规避 React 18 StrictMode 双 mount 首帧立刻 abort 的问题：
    // StrictMode mount → cleanup → mount 整个序列在 1~2 个微任务内同步发生；
    // 如果我们 defer 50ms，第一次 mount 的 timer 会在 cleanup 里被 cancel，
    // 首 mount 永远不会发出真正的 fetch → 就没有 net::ERR_ABORTED（连 DevTools 层也不会打印）。
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
            patchBTRun(run.id, { done_events: ev.done_events, status: (ev.status as BTStatus) });
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
          patchBTRun(run.id, { status: "running" });
        } else if (ev.type === "run_done" || ev.type === "run_failed" || ev.type === "run_cancelled") {
          const st: BTStatus = ev.type === "run_done" ? "done" : ev.type === "run_failed" ? "failed" : "cancelled";
          setRun((r) => r ? { ...r, status: st, finished_at: new Date().toISOString(),
            error_msg: ev.error ?? ev.message ?? r.error_msg } : r);
          patchBTRun(run.id, { status: st });
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
  }, [runId, !!run, sseEpoch]);

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
      patchBTRun(runId, { status: r.status, done_events: r.done_events });
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function loadMetrics(_silent = false) {
    if (!runId) return;
    try {
      const m = await api.btGetMetrics(runId);
      setMetrics(m);
      // 同步把关键指标填回 run 卡片（列表页也能用）
      if (runId) {
        patchBTRun(runId, {
          acc_t3_strict: m.acc_t3_strict?.acc ?? null,
          acc_t3_strict_lo: m.acc_t3_strict?.wilson_lo_95 ?? null,
          acc_t3_non_neutral: m.acc_t3_non_neutral?.acc ?? null,
        });
      }
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
      // 不 bump sseEpoch：pending→running 共用同一条 SSE 长连接即可，
      // 后端会在现有 stream 上推送 run_started / prediction 事件；
      // 断开重连反而会触发 DevTools net::ERR_ABORTED 噪音。
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
      // 不 bump sseEpoch：后端 orchestrator 收到 cancel 信号后，
      // 会在同一条 SSE 上推送 run_cancelled 事件并自然关闭流；
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
      // 不 bump sseEpoch：暂停期间 SSE 仍可保持连接，
      // 后端要么继续保持心跳，要么在真正关闭时自然断开；
      // 主动 abort 会产生 DevTools ERR_ABORTED 噪音。
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
      setSseEpoch((e) => e + 1);
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

/* ===================================== 进度条卡片 ===================================== */

function ProgressCard({ run, progress }: { run: BTRun | null; progress: number }) {
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

function MetricsGrid({ m }: { m: BTMetrics }) {
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

function SSEEventRow({ ev }: { ev: BTSSEEvent }) {
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

function EventStatusBadge({ status }: { status: BTEventStatus }) {
  const cfg: Record<BTEventStatus, { label: string; cls: string; icon: React.ReactNode }> = {
    pending: {
      label: "待执行",
      cls: "bg-edge text-mute",
      icon: <CircleDashed size={10.5} />,
    },
    processing: {
      label: "执行中",
      cls: "bg-amber-soft/70 text-amber",
      icon: <Loader2 size={10.5} className="animate-spin" />,
    },
    done: {
      label: "已完成",
      cls: "bg-jade-soft/70 text-jade",
      icon: <CheckCircle2 size={10.5} />,
    },
  };
  const c = cfg[status] ?? cfg.pending;
  return (
    <span className={cls("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium", c.cls)}>
      {c.icon}
      {c.label}
    </span>
  );
}

function CatalogRow({
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
  // pending/processing 行可以点击（展开看事件标题 + 事件 time + 等预测中的提示）
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

/* ===================================== 单 case 详情展开面板 ===================================== */

type DetailTab = "log" | "rationale" | "packet" | "prompt" | "logic" | "market";

function CaseDetailPanel({
  loading,
  detail,
  activeTab,
  onTabChange,
  itemStatus,
  catalogItem,
}: {
  loading: boolean;
  detail: BTPredictionDetail | null;
  activeTab: DetailTab;
  onTabChange: (t: DetailTab) => void;
  itemStatus: BTEventStatus;
  catalogItem: BTEventCatalogItem;
}) {
  const traj: BTTrajectoryCkpt | null = detail?.trajectory ?? null;
  const stats = traj?.llm_trajectory_stats ?? null;
  // 合并事件说明：优先级 detail.event_meta（后端补全，含 event_text）> catalogItem（列表页已有字段）
  const em: Record<string, unknown> = { ...catalogItem };
  const dem = detail?.event_meta;
  if (dem && typeof dem === "object") {
    for (const [k, v] of Object.entries(dem)) {
      if (v != null && v !== "" && v !== undefined) em[k] = v;
    }
  }
  const titleStr =
    (em.title as string | undefined) ??
    (em.event_title as string | undefined) ??
    (em.headline as string | undefined) ??
    null;
  const eventTextStr = (em.event_text as string | undefined) ?? null;
  const sourceUrlStr = (em.source_url as string | undefined) ?? null;
  const symbolStr = (em.symbol as string | undefined) ?? catalogItem.symbol ?? null;
  const marketStr = (em.market as string | undefined) ?? catalogItem.market ?? null;
  const typeStr = (em.event_type_l2 as string | undefined) ?? catalogItem.event_type_l2 ?? null;
  const timeStr = (em.event_time as string | undefined) ?? catalogItem.event_time ?? null;

  // ---------------- 完整事件说明 Modal（解决：占位 source_url 点出去 404 的问题） ----------------
  const [fullEventOpen, setFullEventOpen] = useState(false);
  const synthetic = sourceUrlStr ? isFeverSyntheticSourceUrl(sourceUrlStr) : false;
  useEffect(() => {
    if (!fullEventOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullEventOpen(false); };
    window.addEventListener("keydown", onKey);
    // 禁 body 滚动（避免页面超长时，打开 modal 背后还能滚）
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [fullEventOpen]);

  const openFullEvent = (e?: React.MouseEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    setFullEventOpen(true);
  };
  // 尝试解析 as_of_packet JSON（字符串存储）
  let packetJson: Record<string, unknown> | null = null;
  if (traj?.as_of_packet) {
    try { packetJson = JSON.parse(traj.as_of_packet) as Record<string, unknown>; } catch { packetJson = null; }
  }
  const tabs: Array<{ id: DetailTab; label: string; disabled?: boolean }> = [
    { id: "log",       label: "完整 Team Log", disabled: itemStatus !== "done" },
    { id: "rationale", label: "决策·结论与理由" },
    { id: "logic",     label: "逻辑链·Agent 协作", disabled: !traj?.team_final_state },
    { id: "market",    label: "标的视图·行情 & 预测" },
    { id: "packet",    label: "As-of Packet", disabled: !traj?.as_of_packet },
    { id: "prompt",    label: "给 Team 的 Prompt", disabled: !traj?.question_to_team },
  ];
  const pred = detail?.prediction;
  return (
    <div className="px-5 py-4">
      {/* ================================================= 事件信息 · Event Info 区块（始终展示） */}
      <div className="mb-4 rounded-lg border border-edge bg-paper p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
            <FileText size={13} className="text-brand" /> 事件说明 · Event Info
          </h4>
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            {marketStr && (
              <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono text-[10.5px] text-mute">{marketStr}</span>
            )}
            {symbolStr && (
              <span className="rounded bg-brand-soft/40 px-1.5 py-0.5 font-mono text-[10.5px] text-brand">{symbolStr}</span>
            )}
            {typeStr && (
              <span className="rounded bg-violet-soft/40 px-1.5 py-0.5 text-[10.5px] text-violet">{typeStr}</span>
            )}
            {timeStr && (
              <span className="inline-flex items-center gap-1 text-mute">
                <Timer size={11} /> as-of {timeStr.slice(0, 19).replace("T", " ")}
              </span>
            )}
          </div>
        </div>
        {titleStr ? (
          <div className="text-[13.5px] font-semibold leading-relaxed text-ink">{titleStr}</div>
        ) : (
          <div className="text-[12px] text-faint">（未命名事件）event_id {catalogItem.event_id}</div>
        )}
        {eventTextStr ? (
          <div className="whitespace-pre-wrap break-words rounded-md border border-edge/60 bg-card/60 p-3 text-[12.5px] leading-relaxed text-ink/90 max-h-[240px] overflow-y-auto">
            {eventTextStr}
          </div>
        ) : itemStatus !== "done" ? (
          <div className="text-[11.5px] text-faint">
            事件正文加载中…（team_full 执行完成后会从 as_of_packet 中提取完整公告正文，或见 As-of Packet Tab 的原始 JSON）
          </div>
        ) : (
          <div className="text-[11.5px] text-faint">
            此 runner 未保存 event_text；可切换到「As-of Packet」Tab（若启用）查看原始输入。
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          {sourceUrlStr ? (
            <a
              href={sourceUrlStr}
              target={synthetic ? undefined : "_blank"}
              rel="noopener noreferrer"
              onClick={synthetic ? openFullEvent : undefined}
              className={cls(
                "inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11.5px] hover:bg-edge/40",
                synthetic ? "border-violet/30 bg-violet-soft/20 text-violet" : "border-edge bg-card text-brand"
              )}
              title={synthetic ? `（FEVER 合成数据，点击查看完整原文）${sourceUrlStr}` : sourceUrlStr}
            >
              <ChevronRight size={11} />
              原文链接
              <span className="font-mono truncate max-w-[220px] text-mute">
                {sourceUrlStr.replace(/^https?:\/\//, "")}
              </span>
              {synthetic && (
                <span className="ml-0.5 rounded bg-violet/15 px-1 text-[9.5px] text-violet">FEVER 合成</span>
              )}
            </a>
          ) : null}
          <button
            type="button"
            onClick={openFullEvent}
            className="inline-flex items-center gap-1 rounded-md border border-edge bg-card px-2.5 py-1 text-[11.5px] text-ink/80 hover:bg-edge/40 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!eventTextStr && !titleStr}
            title="展开查看完整事件说明（不限高）"
          >
            <Maximize2 size={11} /> 查看完整事件
          </button>
          <span className="font-mono text-[10.5px] text-faint">
            eid {catalogItem.event_id}
          </span>
        </div>
      </div>

      {/* -------- 完整事件 Modal：点击「原文链接（合成）」或「查看完整事件」打开 -------- */}
      {fullEventOpen && (
        <div
          className="fixed inset-0 z-[200] flex items-start justify-center overflow-y-auto bg-ink/55 backdrop-blur-sm px-4 py-10"
          onClick={() => setFullEventOpen(false)}
        >
          <div
            className="relative w-full max-w-3xl rounded-xl border border-edge bg-paper shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-edge/70 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <h3 className="flex items-center gap-1.5 text-[13.5px] font-semibold text-ink">
                  <FileText size={13} className="text-brand" /> 完整事件说明
                </h3>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                  {marketStr && (
                    <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono text-[10.5px] text-mute">{marketStr}</span>
                  )}
                  {symbolStr && (
                    <span className="rounded bg-brand-soft/40 px-1.5 py-0.5 font-mono text-[10.5px] text-brand">{symbolStr}</span>
                  )}
                  {typeStr && (
                    <span className="rounded bg-violet-soft/40 px-1.5 py-0.5 text-[10.5px] text-violet">{typeStr}</span>
                  )}
                  {timeStr && (
                    <span className="inline-flex items-center gap-1 text-mute">
                      <Timer size={10.5} /> as-of {timeStr.slice(0, 19).replace("T", " ")}
                    </span>
                  )}
                  <span className="ml-1 font-mono text-[10px] text-faint">eid {catalogItem.event_id}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setFullEventOpen(false)}
                className="rounded-md p-1.5 text-mute hover:bg-edge/50 hover:text-ink"
                title="关闭 (Esc)"
              >
                <X size={15} />
              </button>
            </div>

            <div className="space-y-3 px-5 py-4">
              {titleStr ? (
                <div className="text-[15px] font-semibold leading-relaxed text-ink">{titleStr}</div>
              ) : (
                <div className="text-[12px] text-faint">（未命名事件）event_id {catalogItem.event_id}</div>
              )}

              {eventTextStr ? (
                <div className="whitespace-pre-wrap break-words rounded-lg border border-edge/70 bg-card/70 p-4 text-[13px] leading-7 text-ink/95">
                  {eventTextStr}
                </div>
              ) : (
                <div className="rounded-lg border border-edge/60 bg-edge/20 p-4 text-[12px] text-mute">
                  暂无事件正文。等该事件执行完毕（status = done）后，as_of_packet 中会保存完整公告正文，届时再打开查看即可。
                </div>
              )}

              {sourceUrlStr && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-edge/60 bg-edge/20 px-3 py-2 text-[11.5px]">
                  <span className="text-mute">来源 URL：</span>
                  {synthetic ? (
                    <>
                      <span className="rounded bg-violet/15 px-1 text-[10px] text-violet">FEVER 合成事件</span>
                      <span className="font-mono break-all text-faint">{sourceUrlStr}</span>
                      <span className="text-mute">（原文即上方事件正文，此 URL 仅作追溯引用）</span>
                    </>
                  ) : (
                    <a
                      href={sourceUrlStr}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono break-all text-brand hover:underline"
                    >
                      {sourceUrlStr}
                    </a>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-edge/70 px-5 py-3 text-[11.5px]">
              <div className="text-mute">提示：按 <kbd className="rounded bg-edge/70 px-1 font-mono text-[10px] text-ink/80">Esc</kbd> 或点击遮罩可关闭</div>
              <button
                type="button"
                onClick={() => setFullEventOpen(false)}
                className="rounded-md border border-edge bg-card px-3 py-1.5 text-[11.5px] text-ink hover:bg-edge/40"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 顶部执行摘要 / 状态说明 */}
      {itemStatus !== "done" && (
        <div className={cls(
          "mb-3 flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 text-[11.5px]",
          itemStatus === "processing"
            ? "border-amber/30 bg-amber/5 text-amber"
            : "border-edge bg-edge/30 text-mute",
        )}>
          {itemStatus === "processing" ? (
            <>
              <Loader2 size={12} className="animate-spin shrink-0" />
              <span>Team 多 Agent 正在对该事件进行决策（通常 30~90s），可切换其他 Tab 查看已有的事件元信息；完成后这里会自动刷新为执行结果。</span>
            </>
          ) : (
            <>
              <CircleDashed size={12} className="shrink-0" />
              <span>该事件尚未被调度执行。等待执行队列空闲后会自动开始，完成后会自动进入「已完成」状态。</span>
            </>
          )}
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-3 text-[11.5px]">
        <span className="inline-flex items-center gap-1 text-mute">
          <Timer size={12} className="text-brand" />
          耗时：{traj?.wall_seconds != null ? `${traj.wall_seconds.toFixed(1)}s` : itemStatus === "processing" ? "进行中..." : "—"}
        </span>
        {stats?.n_tokens_total != null && (
          <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono">tokens {stats.n_tokens_total}</span>
        )}
        {stats?.n_tool_calls != null && (
          <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono">tool_calls {stats.n_tool_calls}</span>
        )}
        {stats?.n_sse_events_stored != null && (
          <span className="rounded bg-edge/60 px-1.5 py-0.5 font-mono">steps {stats.n_sse_events_stored}</span>
        )}
        {traj?.model_version && (
          <span className="rounded bg-violet-soft/40 px-1.5 py-0.5 font-mono text-[10.5px] text-violet">
            model {traj.model_version}
          </span>
        )}
        {traj?.system_prompt_variant && (
          <span className="rounded bg-brand-soft/40 px-1.5 py-0.5 font-mono text-[10.5px] text-brand">
            variant {traj.system_prompt_variant}
          </span>
        )}
        {loading && (
          <span className="inline-flex items-center gap-1 text-brand">
            <Loader2 size={12} className="animate-spin" /> 加载 trajectory...
          </span>
        )}
        {!loading && !traj && itemStatus === "done" && (
          <span className="text-faint">此 runner 未产生 trajectory（baseline / team_prompt 只有结论理由）</span>
        )}
      </div>

      {/* Tab 切换 */}
      <div className="mb-2 flex flex-wrap items-center gap-1 border-b border-edge">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => !t.disabled && onTabChange(t.id)}
            disabled={t.disabled}
            className={cls(
              "-mb-px rounded-t px-3 py-1.5 text-[11.5px] transition",
              activeTab === t.id
                ? "border border-b-0 border-edge bg-card text-ink"
                : t.disabled
                ? "text-faint cursor-not-allowed opacity-60"
                : "text-mute hover:bg-edge/40 hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="max-h-[62vh] overflow-auto rounded-lg border border-edge bg-paper p-4">
        {activeTab === "log" && (
          <PreTextBlock
            empty={!traj?.team_final_state?.content_full}
            emptyHint={detail?.prediction.rationale ?? "（runner 未生成 Team Log，查看「决策·结论与理由」。）"}
            text={traj?.team_final_state?.content_full ?? ""}
          />
        )}
        {activeTab === "rationale" && (
          <div className="space-y-3 text-[12.5px] leading-relaxed text-ink">
            <div>
              <div className="mb-1 text-[10.5px] uppercase tracking-wider text-faint">Final Prediction</div>
              <div className="flex flex-wrap items-center gap-2">
                <DirBadge d={traj?.structured_extract?.direction ?? pred?.pred_direction} />
                <span className="font-mono">
                  confidence {((traj?.structured_extract?.confidence ?? pred?.confidence ?? 0) * 100).toFixed(0)}%
                </span>
                {traj?.structured_extract?.conf_gate_applied ? (
                  <span className="rounded bg-brand-soft/50 px-1.5 py-0.5 text-[10.5px] text-brand">conf 闸 已生效</span>
                ) : null}
                {pred?.abstain ? (
                  <span className="rounded bg-violet-soft px-1.5 py-0.5 text-[10.5px] text-violet">abstain（5xx/超时 fallback neutral）</span>
                ) : null}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[10.5px] uppercase tracking-wider text-faint">Rationale（DB prediction）</div>
              <div className="whitespace-pre-wrap break-words rounded-md bg-edge/30 p-3 text-[12.5px] text-ink">
                {pred?.rationale ?? itemStatus === "processing" ? "等待执行完成..." : "（无）"}
              </div>
            </div>
            {traj?.structured_extract?.rationale &&
              traj.structured_extract.rationale !== pred?.rationale ? (
              <div>
                <div className="mb-1 text-[10.5px] uppercase tracking-wider text-faint">Structured Extract Rationale</div>
                <div className="whitespace-pre-wrap break-words rounded-md bg-edge/30 p-3 text-[12.5px] text-ink">
                  {traj.structured_extract.rationale}
                </div>
              </div>
            ) : null}
          </div>
        )}
        {activeTab === "logic" && (
          <LogicChainPanel traj={traj} />
        )}
        {activeTab === "market" && (
          <MarketViewPanel
            traj={traj}
            packet={packetJson}
            pred={pred ?? null}
            itemStatus={itemStatus}
          />
        )}
        {activeTab === "packet" && (
          <PreTextBlock
            empty={!traj?.as_of_packet}
            emptyHint="（runner 未保存 as_of_packet）"
            text={traj?.as_of_packet ?? ""}
            code
          />
        )}
        {activeTab === "prompt" && (
          <PreTextBlock
            empty={!traj?.question_to_team}
            emptyHint="（runner 未保存 question_to_team）"
            text={traj?.question_to_team ?? ""}
          />
        )}
      </div>
    </div>
  );
}

/* ---- 逻辑链 Panel：把 tool_trace 按 phase 分组 + hypotheses 展示 ---- */

function LogicChainPanel({ traj }: { traj: BTTrajectoryCkpt | null }) {
  const [openPhase, setOpenPhase] = useState<string | null>("plan");
  if (!traj?.team_final_state) {
    return (
      <div className="text-[12px] text-mute">
        没有 Team 协作记录（baseline/team_prompt 只产出单 agent rationale，没有 tool_trace）。
      </div>
    );
  }
  const tfs = traj.team_final_state;
  // tool_trace：每条形如 { type: "tool_call"|"tool_result"|"agent_step"|"note", phase, agent_id, name, content?, note?, at_ms?, duration_ms? }
  const toolTrace = (tfs.tool_trace ?? []) as Array<Record<string, unknown>>;
  const hypotheses = (tfs.hypotheses ?? []) as Array<Record<string, unknown>>;
  const phaseOrder = ["plan", "fan_out", "synthesize", "verify", "extract"];
  const phaseLabel: Record<string, string> = {
    plan: "① Plan（主理人拆解任务）",
    fan_out: "② Fan-out（各专家 Agent 并行调研）",
    synthesize: "③ Synthesize（合成初版结论）",
    verify: "④ Verify（复核 & 二次检索）",
    extract: "⑤ Extract（结构化成 direction/confidence/rationale）",
  };
  // 按 phase 分组；没 phase 的统一归到 "其他"
  const byPhase: Record<string, Array<Record<string, unknown>>> = {};
  for (const t of toolTrace) {
    const ph = String(t.phase ?? t.stage ?? "其他");
    if (!byPhase[ph]) byPhase[ph] = [];
    byPhase[ph].push(t);
  }
  const orderedPhases = phaseOrder.filter((p) => (byPhase[p]?.length ?? 0) > 0);
  const others = Object.keys(byPhase).filter((p) => !phaseOrder.includes(p));
  const phases = [...orderedPhases, ...others];

  if (!phases.length && !hypotheses.length) {
    return (
      <PreTextBlock
        empty
        emptyHint="（tool_trace / hypotheses 为空；说明该 trajectory 只保留了 content_full，结构化逻辑链暂不可用，去「完整 Team Log」看全文。）"
        text=""
      />
    );
  }

  return (
    <div className="space-y-4 text-[12.5px]">
      {/* 顶部 Hypotheses 摘要 */}
      {hypotheses.length > 0 && (
        <div className="rounded-md border border-edge bg-edge/10 p-3">
          <div className="mb-2 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wider text-faint">
            📝 Fan-out Hypotheses（各 Agent 形成的候选观点）
            <span className="font-mono text-[10px]">共 {hypotheses.length} 条</span>
          </div>
          <ul className="space-y-1.5 pl-1">
            {hypotheses.map((h: Record<string, unknown>, i: number) => {
              const label = String((h as any).agent_id ?? (h as any).from ?? (h as any).label ?? `H${i + 1}`);
              const body = String((h as any).text ?? (h as any).content ?? (h as any).summary ?? JSON.stringify(h));
              return (
                <li key={i} className="flex gap-2 items-start">
                  <span className="mt-0.5 shrink-0 rounded bg-brand-soft/50 px-1.5 py-0.5 text-[9.5px] text-brand font-medium">{label}</span>
                  <span className="whitespace-pre-wrap break-words text-ink/90">{body}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Phase 折叠面板 */}
      <div>
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-faint">
          🔗 Step-by-step 决策链（tool_trace）
        </div>
        <div className="space-y-2">
          {phases.map((p) => {
            const rows = byPhase[p] ?? [];
            const open = openPhase === p;
            return (
              <div key={p} className="rounded-md border border-edge overflow-hidden">
                <button
                  onClick={() => setOpenPhase((cur) => (cur === p ? null : p))}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left bg-edge/20 hover:bg-edge/40 transition"
                >
                  <span className="text-[11.5px] font-semibold text-ink">
                    {phaseLabel[p] ?? p}
                    <span className="ml-2 font-mono text-[10px] font-normal text-faint">{rows.length} 条</span>
                  </span>
                  {open ? <ChevronUp size={13} className="text-mute" /> : <ChevronDown size={13} className="text-mute" />}
                </button>
                {open && (
                  <ol className="divide-y divide-edge/60">
                    {rows.map((t, idx) => {
                      const tp = String(t.type ?? t.kind ?? "step");
                      const agent = String(t.agent_id ?? t.agent ?? "");
                      const name = String(t.name ?? t.tool ?? t.title ?? "");
                      const note = String(t.note ?? t.summary ?? t.phase_note ?? "");
                      const content =
                        t.content != null && String(t.content).length > 0
                          ? String(t.content)
                          : t.result != null
                          ? String(t.result)
                          : t.args != null && typeof t.args === "object"
                          ? JSON.stringify(t.args, null, 2)
                          : "";
                      return (
                        <li key={idx} className="px-3 py-2 text-[11.5px]">
                          <div className="flex flex-wrap items-center gap-1.5 text-[10.5px] uppercase tracking-wider text-faint">
                            <span className="rounded bg-edge/60 px-1.5 py-0.5 tracking-normal text-ink/80">{tp}</span>
                            {agent && <span className="font-mono">· agent={agent}</span>}
                            {name && <span className="font-mono">· {name}</span>}
                            {note && <span className="ml-1 tracking-normal text-mute">{note}</span>}
                          </div>
                          {content && (
                            <div className="mt-1.5 rounded bg-edge/20 p-2 text-[11.5px] leading-relaxed whitespace-pre-wrap break-words">
                              {content.length > 4000 ? content.slice(0, 4000) + `\n\n…(truncated, 原文长 ${content.length} chars)` : content}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ---- 标的视图 Panel：as_of 行情（从 as_of_packet / event_meta 取）+ 预测方向/置信度/强度可视化 ---- */

function MarketViewPanel({
  traj,
  packet,
  pred,
  itemStatus,
}: {
  traj: BTTrajectoryCkpt | null;
  packet: Record<string, unknown> | null;
  pred: BTPredictionItem | null;
  itemStatus: BTEventStatus;
}) {
  // 从 packet 或 event_meta 抽取常见字段（字段名按 team_full run_team_full_one_event 的 as-of-packet 来）
  const any = packet ?? traj?.event_meta ?? {};
  const g = <K extends string>(ks: K[]): unknown => {
    for (const k of ks) if (k in any) return (any as Record<string, unknown>)[k];
    return undefined;
  };
  const symbol = (g(["symbol"]) as string | undefined) ?? pred?.symbol ?? "—";
  const market = (g(["market"]) as string | undefined) ?? pred?.market ?? "—";
  const eventTime = (g(["event_time", "as_of", "eventTime"]) as string | undefined) ?? "";
  const sourceUrl = (g(["source_url", "sourceUrl", "url"]) as string | undefined) ?? "";
  // 先验 / drift 类
  const t0Ar = g(["t0_ar", "t0AR", "t0_excess_return"]);
  const t0Car = g(["t0_car", "t0CAR", "t0_car_vs_benchmark"]);
  const pre5 = g(["pre5_ar", "pre5drift", "pre_5d_ar", "drift_pre_5"]);
  const pre20 = g(["pre20_ar", "pre20drift", "pre_20d_ar", "drift_pre_20"]);
  const benchmark = (g(["benchmark", "benchmark_symbol", "bench"]) as string | undefined) ?? "";
  const sectorEtf = (g(["sector_etf", "sectorEtf"]) as string | undefined) ?? "";
  const title = (g(["title", "event_title", "headline"]) as string | undefined) ?? "";
  const eventType = (g(["event_type_l2", "eventType"]) as string | undefined) ?? pred?.event_type_l2 ?? "";

  // 预测
  const predDir = traj?.structured_extract?.direction ?? pred?.pred_direction ?? "";
  const predConf = traj?.structured_extract?.confidence ?? pred?.confidence ?? null;
  const confGate = !!traj?.structured_extract?.conf_gate_applied;

  // 强度等级：confidence × dir
  let strengthLabel = itemStatus === "processing" ? "决策中" : itemStatus === "pending" ? "待执行" : "中性";
  let strengthColor = "bg-edge text-mute";
  if (predDir === "up" && predConf != null) {
    if (predConf >= 0.8) { strengthLabel = "强多 ↑↑"; strengthColor = "bg-fall/15 text-fall"; }
    else if (predConf >= 0.6) { strengthLabel = "偏多 ↑"; strengthColor = "bg-fall/10 text-fall"; }
    else { strengthLabel = "轻多 ↗"; strengthColor = "bg-fall/5 text-fall"; }
  } else if (predDir === "down" && predConf != null) {
    if (predConf >= 0.8) { strengthLabel = "强空 ↓↓"; strengthColor = "bg-rise/15 text-rise"; }
    else if (predConf >= 0.6) { strengthLabel = "偏空 ↓"; strengthColor = "bg-rise/10 text-rise"; }
    else { strengthLabel = "轻空 ↘"; strengthColor = "bg-rise/5 text-rise"; }
  } else if (predDir === "neutral") {
    strengthLabel = "中性 ⇄";
    strengthColor = "bg-edge text-mute";
  }

  const StatRow = ({ label, v, pct = false, hint }: { label: string; v: unknown; pct?: boolean; hint?: string }) => {
    const raw = v as number | string | undefined;
    let display: string;
    let cls = "";
    if (typeof raw === "number") {
      if (pct) display = (raw >= 0 ? "+" : "") + (raw * 100).toFixed(2) + "%";
      else display = raw.toString();
      if (pct) cls = raw >= 0 ? "text-fall" : raw < 0 ? "text-rise" : "";
    } else if (raw == null) {
      display = "—";
    } else {
      display = String(raw);
    }
    return (
      <div>
        <div className="text-[10.5px] uppercase tracking-wider text-faint" title={hint}>{label}</div>
        <div className={clsx("mt-0.5 font-mono text-[13px] tabular-nums text-ink", cls)}>{display}</div>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      {/* 预测：大方向 badge + 置信度条 + 强度 */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-[auto_1fr] items-start">
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-edge bg-edge/10 px-5 py-4 text-center">
          <div className="text-[10.5px] uppercase tracking-wider text-faint">方向预测 · T+3</div>
          {predDir || itemStatus !== "done" ? (
            <DirBadge d={predDir || (itemStatus === "processing" ? "决策中" : "TBD")} />
          ) : (
            <span className="text-faint text-[12px]">（无）</span>
          )}
          <span className={cls("mt-1 rounded px-2 py-0.5 text-[11px] font-semibold", strengthColor)}>{strengthLabel}</span>
        </div>
        <div className="space-y-3">
          <div>
            <div className="flex items-baseline justify-between">
              <span className="text-[10.5px] uppercase tracking-wider text-faint">置信度 Confidence</span>
              <span className="font-mono text-[11px] text-ink">
                {predConf != null ? (predConf * 100).toFixed(0) + "%" : itemStatus === "processing" ? "计算中" : "—"}
              </span>
            </div>
            <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-edge/80">
              {predConf != null && (
                <div
                  className={cls(
                    "h-full rounded-full transition-all",
                    predDir === "up" ? "bg-fall" : predDir === "down" ? "bg-rise" : "bg-faint",
                  )}
                  style={{ width: `${Math.max(4, (predConf ?? 0) * 100)}%` }}
                />
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[10.5px]">
            {confGate && <span className="rounded bg-brand-soft/60 px-2 py-0.5 text-brand">✓ Confidence Gate 已生效（低于 70% 强降 neutral）</span>}
            {pred?.abstain && <span className="rounded bg-violet-soft px-2 py-0.5 text-violet">⚠ 执行失败 fallback neutral abstain</span>}
            {pred?.oracle_label_t3 && (
              <span className="rounded bg-edge/70 px-2 py-0.5 text-mute">
                Oracle T+3：{(pred.oracle_label_t3 as string).toUpperCase()}
                {pred.oracle_car_t3 != null
                  ? ` · CAR = ${(pred.oracle_car_t3 * 100).toFixed(2)}%`
                  : ""}
              </span>
            )}
          </div>
        </div>
      </section>

      {/* 事件元信息 */}
      <section className="rounded-md border border-edge p-3 space-y-2 text-[12px]">
        <div className="text-[10.5px] uppercase tracking-wider text-faint">事件元信息 · As-of 视角（无未来函数）</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
          <StatRow label="标的 Symbol" v={symbol} />
          <StatRow label="市场 Market" v={market} />
          <StatRow label="事件类型" v={eventType} />
          <StatRow label="事件时间" v={eventTime ? eventTime.slice(0, 19).replace("T", " ") : undefined} />
        </div>
        {title && <div className="text-[12px] text-ink/90 whitespace-pre-wrap break-words">{title}</div>}
        {sourceUrl && (
          <a
            href={sourceUrl.startsWith("http") ? sourceUrl : undefined}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] text-brand truncate hover:underline"
            title={sourceUrl}
          >
            🔗 {sourceUrl}
          </a>
        )}
      </section>

      {/* 先验行情（as-of packet 已有的 drift 字段；K 线数据接口待下一阶段接 yfinance/akshare） */}
      <section className="rounded-md border border-edge p-3 space-y-3">
        <div className="flex items-baseline justify-between">
          <div className="text-[10.5px] uppercase tracking-wider text-faint">行情先验（As-of 计算，避免未来函数）</div>
          <div className="text-[10px] text-faint">
            注：真实 K 线 OHLCV 图表将在后续接入统一行情源（yfinance/akshare）后补；这里展示的是 as-of 当日已有的漂移/基准/板块对比。
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-4">
          <StatRow label="T0 超额 AR (vs 基准)" v={t0Ar} pct hint="事件日开盘~当前时间点的超额收益" />
          <StatRow label="T0 累计 CAR" v={t0Car} pct />
          <StatRow label="Pre T-5 漂移" v={pre5} pct hint="事件前 5 日的超额收益累积" />
          <StatRow label="Pre T-20 漂移" v={pre20} pct hint="事件前 20 日的超额收益累积（预期泄露信号）" />
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          {benchmark && <span className="rounded bg-edge/50 px-2 py-0.5 text-mute">benchmark: {benchmark}</span>}
          {sectorEtf && <span className="rounded bg-edge/50 px-2 py-0.5 text-mute">sector ETF: {sectorEtf}</span>}
        </div>
      </section>
    </div>
  );
}

function PreTextBlock({
  text,
  empty,
  emptyHint,
  code,
}: {
  text: string;
  empty: boolean;
  emptyHint: string;
  code?: boolean;
}) {
  if (empty) return <div className="whitespace-pre-wrap text-[12px] text-faint">{emptyHint}</div>;
  return (
    <pre
      className={cls(
        "whitespace-pre-wrap break-words text-[12px] leading-relaxed",
        code ? "font-mono text-ink" : "font-serif text-ink",
      )}
    >
      {text}
    </pre>
  );
}

/* ===================================== 小筛选控件 ===================================== */

function FilterSelect({
  placeholder,
  value,
  options,
  onChange,
}: {
  placeholder: string;
  value: string;
  options: Array<string | { v: string; l: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cls(
          "h-7 appearance-none rounded-md border border-edge bg-card px-2 pr-6 text-[11.5px] outline-none transition focus:border-brand",
          value ? "text-ink" : "text-mute",
        )}
      >
        <option value="">{placeholder}（全部）</option>
        {options.map((o) => {
          const v = typeof o === "string" ? o : o.v;
          const l = typeof o === "string" ? o : o.l;
          return (
            <option key={v} value={v}>{l}</option>
          );
        })}
      </select>
      <ChevronRight
        size={12}
        className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 rotate-90 text-faint"
      />
    </div>
  );
}
