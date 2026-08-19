import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Database,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Swords,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import type { BTRun } from "../types";
import { cls, relTime, uid } from "../utils";

/* ===================================== 辅助：状态徽章 ===================================== */

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
    ready: {
      label: "待计算",
      className: "bg-edge text-mute",
      icon: <CircleDashed size={11} />,
    },
    computing: {
      label: "计算中",
      className: "bg-brand-soft text-brand",
      icon: <Loader2 size={11} className="animate-spin" />,
    },
    done: {
      label: "已完成",
      className: "bg-jade-soft text-jade",
      icon: <CheckCircle2 size={11} />,
    },
    failed: {
      label: "失败",
      className: "bg-rise/10 text-rise",
      icon: <X size={11} />,
    },
  };
  const c = cfg[status] ?? cfg.ready;
  return (
    <span className={cls("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium", c.className)}>
      {c.icon}
      {c.label}
    </span>
  );
}

/* ===================================== 新建 Arena Modal ===================================== */

interface CreateFormState {
  name: string;
  description: string;
  dataset_id_filter: string;
  selected_run_ids: string[];
  selected_metric_ids: string[];
}

function CreateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const loadBTRuns = useStore((s) => s.loadBTRuns);
  const [loading, setLoading] = useState(false);
  const [runs, setRuns] = useState<BTRun[]>([]);
  const [form, setForm] = useState<CreateFormState>({
    name: "",
    description: "",
    dataset_id_filter: "",
    selected_run_ids: [],
    selected_metric_ids: [],
  });
  const [availableMetrics, setAvailableMetrics] = useState<
    Array<{ id: string; display_name: string; tier: string; higher_is_better: boolean }>
  >([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      setRuns(await loadBTRuns(false));
      try {
        const defs = await api.btMetricDefs();
        setAvailableMetrics(
          Object.entries(defs).map(([id, v]) => ({
            id,
            display_name: v.display_name,
            tier: v.tier,
            higher_is_better: v.higher_is_better ?? true,
          })),
        );
      } catch {
        setAvailableMetrics([]);
      }
    })();
    setForm({
      name: "",
      description: "",
      dataset_id_filter: "",
      selected_run_ids: [],
      selected_metric_ids: [],
    });
    setErr(null);
  }, [open, loadBTRuns]);

  const datasetOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of runs) {
      if (r.dataset_id) map.set(r.dataset_id, r.dataset_name ?? r.dataset_id);
    }
    return Array.from(map.entries());
  }, [runs]);

  // 候选 Run 只显示"测过的"：status === 'done' 且完成事件数 > 0，
  // 未测（pending）、进行中（running）、失败（failed）、空跑（done_events==0）全部过滤掉，
  // 保证 Arena 创建时选择都是有效可比对的 run。
  const filteredRuns = useMemo(() => {
    const isMeasured = (r: BTRun) => r.status === "done" && (r.done_events ?? 0) > 0;
    if (!form.dataset_id_filter) return runs.filter(isMeasured);
    return runs.filter((r) => r.dataset_id === form.dataset_id_filter && isMeasured(r));
  }, [runs, form.dataset_id_filter]);

  if (!open) return null;

  const toggleRun = (id: string) => {
    setForm((s) => {
      const has = s.selected_run_ids.includes(id);
      return {
        ...s,
        selected_run_ids: has ? s.selected_run_ids.filter((x) => x !== id) : [...s.selected_run_ids, id],
      };
    });
  };

  const toggleMetric = (id: string) => {
    setForm((s) => {
      const has = s.selected_metric_ids.includes(id);
      return {
        ...s,
        selected_metric_ids: has ? s.selected_metric_ids.filter((x) => x !== id) : [...s.selected_metric_ids, id],
      };
    });
  };

  const submit = async () => {
    setErr(null);
    if (!form.name.trim()) return setErr("请填写 Arena 名称");
    if (form.selected_run_ids.length < 2) return setErr("至少需要选择 2 个回测 Run 才能比对");
    setLoading(true);
    try {
      const { id } = await api.arenaCreate({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        run_ids: form.selected_run_ids,
        selected_metric_ids: form.selected_metric_ids.length > 0 ? form.selected_metric_ids : undefined,
      });
      onCreated(id);
    } catch (e) {
      setErr((e as Error).message || "创建失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-xl border border-edgeDark/80 bg-paper shadow-pop">
        <div className="flex items-center justify-between border-b border-edgeDark/70 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-jade/10 text-jade">
              <Swords size={15} />
            </span>
            <div>
              <div className="text-[14px] font-semibold">新建 Arena 横向比对</div>
              <div className="text-[11.5px] text-mute">从同一数据集的不同回测 Run 中挑选，支持按多指标横向比较</div>
            </div>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-mute transition hover:bg-edge hover:text-ink">
            <X size={15} />
          </button>
        </div>
        <div className="space-y-5 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <div className="mb-1 text-[11.5px] font-medium text-ink">Arena 名称</div>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如：Predictor vs Market-Analyst"
                className="w-full rounded-md border border-edgeDark/70 bg-card px-3 py-2 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/60"
              />
            </label>
            <label className="block">
              <div className="mb-1 text-[11.5px] font-medium text-ink">数据集过滤</div>
              <select
                value={form.dataset_id_filter}
                onChange={(e) => setForm({ ...form, dataset_id_filter: e.target.value, selected_run_ids: [] })}
                className="w-full rounded-md border border-edgeDark/70 bg-card px-3 py-2 text-[12.5px] outline-none focus:border-brand/60"
              >
                <option value="">全部已完成的 Run</option>
                {datasetOptions.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <div className="mb-1 text-[11.5px] font-medium text-ink">描述（可选）</div>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={2}
              placeholder="实验目的、调参说明……"
              className="w-full resize-none rounded-md border border-edgeDark/70 bg-card px-3 py-2 text-[12.5px] outline-none placeholder:text-faint focus:border-brand/60"
            />
          </label>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className="text-[11.5px] font-medium text-ink">
                参与比对的回测 Run
                <span className="ml-1 text-[10.5px] text-mute">（已选 {form.selected_run_ids.length}）</span>
              </div>
              <div className="text-[10.5px] text-faint">仅显示状态为「已完成」的 Run</div>
            </div>
            <div className="max-h-48 overflow-y-auto rounded-md border border-edgeDark/70 bg-card">
              {filteredRuns.length === 0 ? (
                <div className="px-3 py-6 text-center text-[12px] text-faint">
                  {form.dataset_id_filter
                    ? "该数据集暂无已完成的回测 Run"
                    : "暂无已完成的回测 Run，请先完成一个或多个回测"}
                </div>
              ) : (
                filteredRuns.map((r) => {
                  const checked = form.selected_run_ids.includes(r.id);
                  return (
                    <label
                      key={r.id}
                      className={cls(
                        "flex cursor-pointer items-center gap-3 border-b border-edge/70 px-3 py-2.5 last:border-b-0 transition",
                        checked ? "bg-jade/5" : "hover:bg-edge/40",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleRun(r.id)}
                        className="h-3.5 w-3.5 accent-jade"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[12.5px] font-medium">{r.name}</span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[10.5px] text-mute">
                          <span className="inline-flex items-center gap-1">
                            <Database size={10} /> {r.dataset_name ?? r.dataset_id ?? "无数据集"}
                          </span>
                          <span>·</span>
                          <span>{r.runner}</span>
                          <span>·</span>
                          <span>{r.prompt_variant}</span>
                          <span>·</span>
                          <span className="font-mono">{r.model_version}</span>
                          <span>·</span>
                          <span>
                            {r.done_events ?? 0} / {r.total_events ?? 0}
                          </span>
                        </div>
                      </div>
                    </label>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className="text-[11.5px] font-medium text-ink">
                比对指标
                <span className="ml-1 text-[10.5px] text-mute">（留空则使用全部 Core 指标）</span>
              </div>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() =>
                    setForm({
                      ...form,
                      selected_metric_ids: availableMetrics.filter((m) => m.tier === "core").map((m) => m.id),
                    })
                  }
                  className="rounded px-2 py-0.5 text-[10.5px] text-mute hover:bg-edge hover:text-ink"
                >
                  仅 Core
                </button>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, selected_metric_ids: availableMetrics.map((m) => m.id) })}
                  className="rounded px-2 py-0.5 text-[10.5px] text-mute hover:bg-edge hover:text-ink"
                >
                  全选
                </button>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, selected_metric_ids: [] })}
                  className="rounded px-2 py-0.5 text-[10.5px] text-mute hover:bg-edge hover:text-ink"
                >
                  清空
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 rounded-md border border-edgeDark/70 bg-card p-2">
              {availableMetrics.length === 0 ? (
                <div className="w-full py-3 text-center text-[12px] text-faint">正在加载可用指标…</div>
              ) : (
                availableMetrics.map((m) => {
                  const checked = form.selected_metric_ids.includes(m.id);
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => toggleMetric(m.id)}
                      className={cls(
                        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10.5px] transition",
                        checked
                          ? "border-jade/60 bg-jade/10 text-jade"
                          : "border-edgeDark/70 text-mute hover:border-edgeDark hover:text-ink",
                      )}
                    >
                      <span
                        className={cls(
                          "inline-block h-1.5 w-1.5 rounded-full",
                          m.tier === "core"
                            ? "bg-brand"
                            : m.tier === "extended"
                            ? "bg-amber"
                            : "bg-violet",
                        )}
                      />
                      {m.display_name}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {err && (
            <div className="rounded-md border border-rise/40 bg-rise/5 px-3 py-2 text-[12px] text-rise">{err}</div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-edgeDark/70 bg-edge/30 px-5 py-3">
          <button
            onClick={onClose}
            disabled={loading}
            className="rounded-md border border-edgeDark/70 px-3.5 py-1.5 text-[12px] font-medium text-mute hover:bg-card hover:text-ink disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={submit}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md bg-jade px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-card transition hover:bg-jade/90 disabled:opacity-50"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Swords size={13} />}
            创建并计算
          </button>
        </div>
      </div>
    </div>
  );
}

/* ===================================== 主组件：Arena 列表页 ===================================== */

export default function ArenaList() {
  const goChat = useStore((s) => () => s.setView("chat"));
  const goBTList = useStore((s) => () => s.setView("backtest-list"));
  const openArenaDetail = useStore((s) => s.openArenaDetail);
  const arenaItems = useStore((s) => s.arenaItems);
  const arenaLoading = useStore((s) => s.arenaLoading);
  const loadArenas = useStore((s) => s.loadArenas);
  const patchArena = useStore((s) => s.patchArena);

  const [subView, setSubView] = useState<"arena" | "backtest">("arena");
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  useEffect(() => {
    void loadArenas(true);
  }, [loadArenas]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = [...arenaItems].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    if (!q) return list;
    return list.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        (a.description ?? "").toLowerCase().includes(q) ||
        (a.dataset_name ?? "").toLowerCase().includes(q),
    );
  }, [arenaItems, query]);

  const doDelete = async (id: string) => {
    try {
      await api.arenaDelete(id);
      useStore.setState((s) => ({ arenaItems: s.arenaItems.filter((a) => a.id !== id) }));
    } finally {
      setConfirmDel(null);
    }
  };

  const computeAndGo = async (id: string) => {
    patchArena(id, { status: "computing" });
    try {
      await api.arenaCompute(id);
      await loadArenas(true);
      openArenaDetail(id);
    } catch (e) {
      patchArena(id, { status: "failed" });
      alert((e as Error).message || "计算失败");
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-paper">
      {/* 顶栏：面包屑 + 子视图切换 + 操作 */}
      <header className="flex items-center justify-between gap-4 border-b border-edgeDark/70 px-5 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            onClick={goChat}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-mute transition hover:bg-edge hover:text-ink"
            title="返回研究工作台"
          >
            <ArrowLeft size={13} />
            研究工作台
          </button>
          <span className="text-[11px] text-faint">/</span>
          <div className="flex items-center gap-1 rounded-lg bg-edge/50 p-0.5">
            <button
              onClick={() => {
                setSubView("backtest");
                goBTList();
              }}
              className={cls(
                "rounded-md px-2.5 py-1 text-[11.5px] font-medium transition",
                subView === "backtest" ? "bg-card text-brand shadow-card" : "text-mute hover:text-ink",
              )}
            >
              回测 Run
            </button>
            <button
              onClick={() => setSubView("arena")}
              className={cls(
                "rounded-md px-2.5 py-1 text-[11.5px] font-medium transition",
                subView === "arena" ? "bg-card text-jade shadow-card" : "text-mute hover:text-ink",
              )}
            >
              <span className="inline-flex items-center gap-1">
                <Swords size={12} /> Arena 横向比对
              </span>
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索 Arena 名称 / 数据集 / 描述…"
              className="w-64 rounded-md border border-edgeDark/70 bg-card py-1.5 pl-8 pr-3 text-[12px] outline-none placeholder:text-faint focus:border-brand/60"
            />
          </div>
          <button
            onClick={() => void loadArenas(true)}
            disabled={arenaLoading}
            title="刷新列表"
            className="rounded-md border border-edgeDark/70 bg-card p-1.5 text-mute transition hover:text-ink disabled:opacity-50"
          >
            <RefreshCw size={14} className={cls(arenaLoading && "animate-spin")} />
          </button>
          <button
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-jade px-3 py-1.5 text-[12px] font-semibold text-white shadow-card transition hover:bg-jade/90"
          >
            <Plus size={14} />
            新建 Arena
          </button>
        </div>
      </header>

      {/* 列表内容 */}
      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        {arenaLoading && arenaItems.length === 0 ? (
          <div className="grid h-40 place-items-center text-[12px] text-faint">
            <Loader2 size={18} className="animate-spin" /> 正在加载 Arena 列表…
          </div>
        ) : filtered.length === 0 ? (
          <div className="mx-auto mt-16 max-w-md rounded-xl border border-dashed border-edgeDark/70 p-8 text-center">
            <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-jade/10 text-jade">
              <Swords size={22} />
            </div>
            <div className="mb-1 text-[14px] font-semibold">还没有任何 Arena 比对</div>
            <div className="mb-4 text-[12px] leading-relaxed text-mute">
              Arena 会把多个回测 Run 放在同一把尺子下比较：
              <br />
              支持多指标排名、雷达图、显著性检验、事件头对头对决。
            </div>
            <button
              onClick={() => setCreateOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-jade px-3.5 py-1.5 text-[12px] font-semibold text-white shadow-card hover:bg-jade/90"
            >
              <Plus size={14} />
              创建第一个 Arena
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-edgeDark/70 bg-card">
            <table className="w-full text-left text-[12px]">
              <thead className="bg-edge/40 text-[10.5px] uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-3 py-2 font-medium">Arena</th>
                  <th className="px-3 py-2 font-medium">数据集</th>
                  <th className="px-3 py-2 font-medium">参与 Runs</th>
                  <th className="px-3 py-2 font-medium">指标</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">更新时间</th>
                  <th className="px-3 py-2 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => {
                  const runCount = Array.isArray(a.run_ids) ? a.run_ids.length : 0;
                  const metricCount = Array.isArray(a.selected_metric_ids) ? a.selected_metric_ids.length : 0;
                  return (
                    <tr
                      key={a.id}
                      className="border-t border-edge/70 transition hover:bg-edge/30"
                      onDoubleClick={() => openArenaDetail(a.id)}
                    >
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="grid h-6 w-6 place-items-center rounded-md bg-jade/10 text-jade">
                            <Swords size={12} />
                          </span>
                          <div className="min-w-0">
                            <div className="truncate font-medium text-ink">{a.name}</div>
                            {a.description && (
                              <div className="truncate text-[10.5px] text-faint">{a.description}</div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="inline-flex items-center gap-1 text-mute">
                          <Database size={11} />
                          <span className="truncate text-[11.5px]">
                            {a.dataset_name ?? a.dataset_id ?? "—"}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-1.5 py-0.5 text-[10.5px] font-medium text-brand">
                          {runCount} runs
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="rounded-full bg-violet/10 px-1.5 py-0.5 text-[10.5px] font-medium text-violet">
                          {metricCount > 0 ? `${metricCount} 指标` : "默认 Core"}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge status={a.status} />
                      </td>
                      <td className="px-3 py-2.5 text-[11px] text-mute tabular-nums">
                        {a.updated_at ? relTime(a.updated_at) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="inline-flex items-center gap-1">
                          {a.status !== "done" && (
                            <button
                              onClick={() => void computeAndGo(a.id)}
                              className="rounded-md border border-edgeDark/70 px-2 py-1 text-[10.5px] text-mute hover:border-jade/50 hover:text-jade"
                              title={a.status === "computing" ? "正在计算…" : "重新计算"}
                              disabled={a.status === "computing"}
                            >
                              计算
                            </button>
                          )}
                          <button
                            onClick={() => openArenaDetail(a.id)}
                            className="inline-flex items-center gap-1 rounded-md border border-edgeDark/70 px-2 py-1 text-[10.5px] text-mute hover:border-brand/50 hover:text-brand"
                          >
                            详情
                            <ArrowRight size={11} />
                          </button>
                          {confirmDel === a.id ? (
                            <div className="inline-flex items-center gap-1 rounded-md border border-rise/40 bg-rise/5 px-1.5 py-0.5">
                              <span className="text-[10px] text-rise">确认?</span>
                              <button
                                onClick={() => void doDelete(a.id)}
                                className="text-[10.5px] font-medium text-rise hover:underline"
                              >
                                删除
                              </button>
                              <button
                                onClick={() => setConfirmDel(null)}
                                className="text-[10.5px] text-mute hover:text-ink"
                              >
                                <X size={11} />
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => setConfirmDel(a.id)}
                              className="rounded-md border border-edgeDark/70 p-1 text-mute hover:border-rise/40 hover:text-rise"
                              title="删除"
                            >
                              <Trash2 size={11} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false);
          void loadArenas(true).then(() => {
            // 创建成功后直接进入详情页并触发计算
            void computeAndGo(id);
          });
        }}
      />
    </div>
  );
}

// 为避免 lint 报错保留 uid 引用（供将来扩展）
void uid;
