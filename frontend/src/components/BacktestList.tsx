import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Database,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api";
import { useStore } from "../store";
import type { BTDataset, BTEventsCount, BTRun, BTStatus, BTRunner } from "../types";
import { cls, relTime, uid } from "../utils";

/* ===================================== 辅助：状态徽章 ===================================== */

function StatusBadge({ status }: { status: BTStatus | string }) {
  const cfg: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
    pending: {
      label: "待启动",
      className: "bg-edge text-mute",
      icon: <CircleDashed size={11} />,
    },
    running: {
      label: "运行中",
      className: "bg-brand-soft text-brand",
      icon: <Loader2 size={11} className="animate-spin" />,
    },
    paused: {
      label: "已暂停",
      className: "bg-amber-soft text-amber",
      icon: <Pause size={11} />,
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
    cancelled: {
      label: "已取消",
      className: "bg-violet-soft text-violet",
      icon: <Square size={11} />,
    },
  };
  const c = cfg[status] ?? cfg.pending;
  return (
    <span className={cls("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium", c.className)}>
      {c.icon}
      {c.label}
    </span>
  );
}

/* ===================================== 新建回测 Modal ===================================== */

interface CreateFormState {
  name: string;
  runner: BTRunner;
  dataset_id: string;
  events_path: string;
  labels_path: string;
  prompt_variant: string;
  model_version: string;
  concurrency: number;
}

function CreateModal({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: CreateFormState) => Promise<void>;
}) {
  function defaultForm(datasets: BTDataset[] = []) {
    const now = new Date();
    const pad = (n: number) => n.toString().padStart(2, "0");
    const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
    return {
      name: `回测 run · ${stamp}`,
      runner: "team_full" as BTRunner,
      // 优先选第一个可用数据集；若还未加载列表则为空，useEffect 拿到 datasets 后会修正
      dataset_id: datasets[0]?.id ?? "",
      events_path: "",
      labels_path: "",
      prompt_variant: "v0",
      model_version: "deepseek-v4-flash",
      concurrency: 4,
    };
  }

  const [form, setForm] = useState<CreateFormState>(defaultForm());
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  /* -------- 数据集列表（Data list 下拉） -------- */
  const [datasets, setDatasets] = useState<BTDataset[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [datasetsErr, setDatasetsErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDatasetsLoading(true);
    setDatasetsErr(null);
    let alive = true;
    api.btListDatasets()
      .then((list) => {
        if (!alive) return;
        setDatasets(list ?? []);
        // 如果当前 form.dataset_id 空，而列表有值，自动填第一个
        setForm((cur) => {
          if ((!cur.dataset_id || !(list ?? []).find((d) => d.id === cur.dataset_id)) && (list ?? []).length > 0) {
            return { ...cur, dataset_id: list[0].id };
          }
          return cur;
        });
      })
      .catch((e) => alive && setDatasetsErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setDatasetsLoading(false));
    return () => {
      alive = false;
    };
  }, [open]);

  const selectedDataset: BTDataset | undefined = useMemo(
    () => datasets.find((d) => d.id === form.dataset_id),
    [datasets, form.dataset_id],
  );

  useEffect(() => {
    if (!open) return;
    // modal 重新打开时重置 form（数据集已知时用 defaultForm(datasets) 自动选第一个）
    setForm(defaultForm(datasets));
    setErrorMsg(null);
  }, [open, datasets]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const canSubmit =
    form.name.trim().length > 0 && form.dataset_id.trim().length > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      await onCreate({
        ...form,
        name: form.name.trim(),
        // 以 dataset_id 为主，后端会自动从 bt_datasets 行取 path/labels_path；
        // events_path/labels_path 保留空字符串，后端在 dataset_id 存在时会忽略空值
        events_path: "",
        labels_path: "",
        model_version: form.model_version.trim() || "deepseek-v4-flash",
      });
      onClose();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-ink/30 backdrop-blur-sm p-4 animate-fadeUp">
      <div className="w-full max-w-lg rounded-card bg-card shadow-pop border border-edge">
        {/* 头 */}
        <div className="flex items-center justify-between border-b border-edge px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="text-jade"><Plus size={16} /></span>
            <h3 className="font-serif text-[16px] font-semibold text-ink">新建回测</h3>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-mute transition hover:bg-edge/60 hover:text-ink">
            <X size={16} />
          </button>
        </div>
        {/* 表单 */}
        <div className="max-h-[70vh] space-y-3.5 overflow-y-auto px-5 py-4 text-[13px]">
          <Field label="回测名称" required>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="input"
              placeholder="例如：team_full · balanced_1000 v7 baseline"
            />
          </Field>
          <Field label="Runner" required hint="baseline=启发式基线；team_prompt=单 Agent；team_full=多专家协作">
            <select
              value={form.runner}
              onChange={(e) => setForm({ ...form, runner: e.target.value as BTRunner })}
              className="input"
            >
              <option value="team_full">team_full（多专家，推荐）</option>
              <option value="team_prompt">team_prompt（单 Agent）</option>
              <option value="baseline">baseline（启发式基线）</option>
            </select>
          </Field>
          <Field
            label="Data list（数据集）"
            required
            hint="从已注册数据集选择，自带事件文件路径与 Oracle labels；无需手动填写路径"
          >
            <>
              <select
                value={form.dataset_id}
                onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}
                className="input"
                disabled={datasetsLoading || datasets.length === 0}
              >
                {datasetsLoading ? (
                  <option value="">正在加载数据集列表…</option>
                ) : datasetsErr ? (
                  <option value="">数据集列表加载失败</option>
                ) : datasets.length === 0 ? (
                  <option value="">（暂无可用数据集）</option>
                ) : (
                  datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} · {d.total_events || 0}ev · {Object.keys(d.by_market || {}).join("/") || "—"}
                    </option>
                  ))
                )}
              </select>

              {/* 选中数据集摘要 */}
              {selectedDataset && (
                <div className="mt-2 rounded-lg border border-edge/70 bg-paper p-2.5 space-y-1.5 text-[11.5px]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 text-ink font-medium">
                      <Database size={11} className="text-brand" /> {selectedDataset.name}
                    </span>
                    <span className="font-mono text-[10.5px] text-faint">id {selectedDataset.id}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="rounded bg-edge/70 px-1.5 py-0.5 text-mute">
                      事件数 <b className="text-ink">{selectedDataset.total_events || 0}</b>
                    </span>
                    {Object.entries(selectedDataset.by_market || {}).map(([k, v]) => (
                      <span key={k} className="rounded bg-brand-soft/50 px-1.5 py-0.5 text-brand">
                        {k}: {v as number}
                      </span>
                    ))}
                    {Object.entries(selectedDataset.by_type || {}).map(([k, v]) => (
                      <span key={k} className="rounded bg-violet-soft/40 px-1.5 py-0.5 text-violet">
                        {k}: {v as number}
                      </span>
                    ))}
                    {selectedDataset.labels_path ? (
                      <span className="inline-flex items-center gap-1 rounded bg-jade-soft/60 px-1.5 py-0.5 text-jade">
                        <CheckCircle2 size={10} /> 已含 Oracle labels
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-edge/70 px-1.5 py-0.5 text-mute">
                        无 Oracle labels（仅记录预测，不计算 ACC）
                      </span>
                    )}
                  </div>
                  {selectedDataset.date_range?.min && selectedDataset.date_range?.max && (
                    <div className="text-faint flex flex-wrap items-center gap-2">
                      <span>时间范围：</span>
                      <span className="font-mono">{String(selectedDataset.date_range.min).slice(0, 16).replace("T", " ")}</span>
                      <span>→</span>
                      <span className="font-mono">{String(selectedDataset.date_range.max).slice(0, 16).replace("T", " ")}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-1.5 flex items-center gap-2 text-[11px]">
                {datasetsLoading ? (
                  <span className="text-mute flex items-center gap-1">
                    <Loader2 size={11} className="animate-spin" /> 读取中…
                  </span>
                ) : datasetsErr ? (
                  <span className="text-rise">✗ 数据集列表加载失败：{datasetsErr}</span>
                ) : datasets.length === 0 ? (
                  <span className="text-rise">✗ bt_datasets 为空；请先在后端注册数据集</span>
                ) : selectedDataset ? (
                  <span className="text-jade flex items-center gap-1">
                    <CheckCircle2 size={12} /> 已就绪
                  </span>
                ) : null}
              </div>
            </>
          </Field>
          <div className="space-y-3.5">
            <Field label="模型版本">
              <input
                value={form.model_version}
                onChange={(e) => setForm({ ...form, model_version: e.target.value })}
                className="input"
                placeholder="deepseek-v4-flash"
              />
            </Field>
            <Field label="并发数" hint="同时处理的事件数，范围 1~10；越大越快但 LLM/Rate Limit 压力越高">
              <input
                type="number"
                min={1}
                max={10}
                step={1}
                value={form.concurrency}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isNaN(v)) return;
                  const clamped = Math.min(10, Math.max(1, Math.round(v)));
                  setForm({ ...form, concurrency: clamped });
                }}
                className="input"
              />
            </Field>
          </div>
          {errorMsg && (
            <div className="rounded-lg border border-rise/30 bg-rise/5 px-3 py-2 text-[12px] text-rise">
              ⚠️ {errorMsg}
            </div>
          )}
        </div>
        {/* 底 */}
        <div className="flex items-center justify-end gap-2 border-t border-edge px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-edge bg-card px-3.5 py-1.5 text-[12.5px] text-mute transition hover:bg-edge/40 hover:text-ink"
          >
            取消
          </button>
          <button
            onClick={() => void submit()}
            disabled={!canSubmit}
            className={cls(
              "flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-[12.5px] font-medium transition shadow-card",
              canSubmit
                ? "bg-brand text-card hover:bg-brand-hover hover:shadow-pop"
                : "bg-edge text-faint cursor-not-allowed",
            )}
          >
            {submitting && <Loader2 size={13} className="animate-spin" />}
            创建回测
          </button>
        </div>
      </div>
      <style>{`
        .input {
          width: 100%;
          border-radius: 8px;
          border: 1px solid #E8E5E0;
          background: #FFFFFF;
          padding: 7px 10px;
          font-size: 13px;
          color: #1C1B1A;
          outline: none;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .input::placeholder { color: #9B968C; }
        .input:focus { border-color: #B45309; box-shadow: 0 0 0 3px rgba(180,83,9,0.12); }
      `}</style>
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1 flex items-baseline gap-1">
        <span className="text-[12px] font-medium text-ink">
          {label}
          {required && <span className="ml-0.5 text-rise">*</span>}
        </span>
        {hint && <span className="text-[10.5px] text-faint">{hint}</span>}
      </div>
      {children}
    </label>
  );
}

/* ===================================== 主组件：BacktestList ===================================== */

export default function BacktestList() {
  const btRuns = useStore((s) => s.btRuns);
  const btRunsLoading = useStore((s) => s.btRunsLoading);
  const loadBTRuns = useStore((s) => s.loadBTRuns);
  const patchBTRun = useStore((s) => s.patchBTRun);
  const openBTDetail = useStore((s) => s.openBTDetail);

  const [modalOpen, setModalOpen] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);

  useEffect(() => {
    void loadBTRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = useMemo(() => btRuns, [btRuns]);

  const onCreate = async (data: CreateFormState) => {
    const r = await api.btCreateRun({ ...data });
    // 刷新列表
    await loadBTRuns(true);
    // 直接进入详情页，等待用户点击 start
    openBTDetail(r.id);
  };

  const doStart = async (id: string) => {
    setActingId(id);
    setActionErr(null);
    try {
      patchBTRun(id, { status: "running", started_at: new Date().toISOString() });
      const r = await api.btStartRun(id);
      if (!r.ok) throw new Error(r.message || "start failed");
      // 进入详情页订阅 SSE
      openBTDetail(id);
    } catch (e) {
      setActionErr(`${id.slice(0, 8)}… 启动失败：${e instanceof Error ? e.message : String(e)}`);
      // 乐观回滚
      void loadBTRuns(true);
    } finally {
      setActingId(null);
    }
  };

  const doCancel = async (id: string) => {
    setActingId(id);
    setActionErr(null);
    try {
      const r = await api.btCancelRun(id);
      if (!r.ok) throw new Error(r.message || "cancel failed");
      patchBTRun(id, { status: "cancelled" });
    } catch (e) {
      setActionErr(`${id.slice(0, 8)}… 取消失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActingId(null);
    }
  };

  const doPause = async (id: string) => {
    setActingId(id);
    setActionErr(null);
    try {
      patchBTRun(id, { status: "paused" });
      const r = await api.btPauseRun(id);
      if (!r.ok) throw new Error(r.message || "pause failed");
    } catch (e) {
      setActionErr(`${id.slice(0, 8)}… 暂停失败：${e instanceof Error ? e.message : String(e)}`);
      void loadBTRuns(true);
    } finally {
      setActingId(null);
    }
  };

  const doResume = async (id: string) => {
    setActingId(id);
    setActionErr(null);
    try {
      patchBTRun(id, { status: "running" });
      const r = await api.btResumeRun(id);
      if (!r.ok) throw new Error(r.message || "resume failed");
    } catch (e) {
      setActionErr(`${id.slice(0, 8)}… 继续失败：${e instanceof Error ? e.message : String(e)}`);
      void loadBTRuns(true);
    } finally {
      setActingId(null);
    }
  };

  const doDelete = async (id: string) => {
    setActingId(id);
    setActionErr(null);
    try {
      const r = await api.btDeleteRun(id);
      if (!r.ok) throw new Error(r.message || "delete failed");
      await loadBTRuns(true);
    } catch (e) {
      setActionErr(`${id.slice(0, 8)}… 删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActingId(null);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
      {/* ===================================== Header ===================================== */}
      <header className="flex shrink-0 items-center justify-between border-b border-edge bg-paper px-6 py-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-[20px] font-bold tracking-wide text-ink">回测中心</h2>
            <span className="rounded bg-jade-soft px-1.5 py-px text-[10px] font-semibold text-jade">P0</span>
          </div>
          <p className="mt-0.5 font-serif text-[11.5px] italic text-mute">
            Backtest &amp; Benchmark Suite — 批量验证、追踪指标、沉淀可进化知识
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void loadBTRuns(true)}
            disabled={btRunsLoading}
            className="flex items-center gap-1 rounded-lg border border-edge bg-card px-3 py-1.5 text-[12px] text-mute transition hover:bg-edge/40 hover:text-ink disabled:opacity-50"
            title="刷新列表"
          >
            <RefreshCw size={13} className={cls(btRunsLoading && "animate-spin")} />
            刷新
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-brand px-3.5 py-1.5 text-[12.5px] font-medium text-card shadow-card transition hover:bg-brand-hover hover:shadow-pop"
          >
            <Plus size={14} />
            新建回测
          </button>
        </div>
      </header>

      {actionErr && (
        <div className="mx-6 mt-3 rounded-lg border border-rise/30 bg-rise/5 px-3 py-2 text-[12px] text-rise">
          ⚠️ {actionErr}
        </div>
      )}

      {/* ===================================== Table ===================================== */}
      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        {btRunsLoading && rows.length === 0 ? (
          <EmptyHint
            title="加载中..."
            desc="正在从数据库拉取回测历史..."
            icon={<Loader2 size={24} className="animate-spin text-brand" />}
          />
        ) : rows.length === 0 ? (
          <EmptyHint
            title="还没有回测记录"
            desc="点击右上角「新建回测」，创建第一组批量验证。"
            actionLabel="新建回测"
            onAction={() => setModalOpen(true)}
          />
        ) : (
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="sticky top-0 z-10 border-b border-edge bg-paper/95 backdrop-blur text-left text-[11px] uppercase tracking-wider text-faint">
                <th className="py-2.5 pr-4 font-medium">名称</th>
                <th className="py-2.5 pr-4 font-medium">Runner</th>
                <th className="py-2.5 pr-4 font-medium">状态</th>
                <th className="py-2.5 pr-4 font-medium">进度</th>
                <th className="py-2.5 pr-4 font-medium">T+3 ACC (Strict)</th>
                <th className="py-2.5 pr-4 font-medium">T+3 ACC (Non-Neutral)</th>
                <th className="py-2.5 pr-4 font-medium">更新时间</th>
                <th className="py-2.5 pr-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <RunRow
                  key={r.id}
                  run={r}
                  actingId={actingId}
                  onStart={() => doStart(r.id)}
                  onPause={() => doPause(r.id)}
                  onResume={() => doResume(r.id)}
                  onCancel={() => doCancel(r.id)}
                  onDelete={() => doDelete(r.id)}
                  onOpen={() => openBTDetail(r.id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <CreateModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={onCreate}
      />
    </div>
  );
}

/* ===================================== RunRow ===================================== */

function RunRow({
  run,
  actingId,
  onStart,
  onPause,
  onResume,
  onCancel,
  onDelete,
  onOpen,
}: {
  run: BTRun;
  actingId: string | null;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const progress = run.total_events > 0 ? Math.round((run.done_events / run.total_events) * 100) : 0;
  const busy = actingId === run.id;

  return (
    <tr className="group border-b border-edge/70 transition hover:bg-card/60">
      <td className="py-3 pr-4">
        <button
          onClick={onOpen}
          className="text-left"
          title={run.id}
        >
          <div className="flex items-center gap-1.5">
            <span className="block truncate max-w-[280px] text-[13px] font-medium text-ink hover:text-brand">
              {run.name || "未命名回测"}
            </span>
            <ArrowRight size={12} className="shrink-0 text-faint opacity-0 transition group-hover:opacity-100" />
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] text-faint">
            id {run.id.slice(0, 10)}… · runner={run.runner}{run.prompt_variant ? ` · prompt=${run.prompt_variant}` : ""}
            {run.model_version ? ` · ${run.model_version}` : ""}
          </div>
        </button>
      </td>
      <td className="py-3 pr-4">
        <RunnerTag runner={run.runner} />
      </td>
      <td className="py-3 pr-4">
        <StatusBadge status={run.status} />
      </td>
      <td className="py-3 pr-4">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-edge/80">
            <div
              className={cls(
                "h-full rounded-full transition-all",
                run.status === "failed" ? "bg-rise"
                : run.status === "done" ? "bg-jade"
                : run.status === "running" ? "bg-brand" : "bg-faint",
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="font-mono text-[11px] text-mute tabular-nums">
            {run.done_events}/{run.total_events}
          </span>
        </div>
      </td>
      <td className="py-3 pr-4">
        <AccCell acc={run.acc_t3_strict} lo={run.acc_t3_strict_lo} />
      </td>
      <td className="py-3 pr-4">
        <AccCell acc={run.acc_t3_non_neutral} />
      </td>
      <td className="py-3 pr-4 text-[11.5px] text-mute">
        <div>{relTime(run.updated_at)}</div>
        <div className="font-mono text-[10px] text-faint">{run.updated_at?.slice(5, 16).replace("T", " ")}</div>
      </td>
      <td className="py-3 pr-2">
        <div className="flex items-center justify-end gap-1 opacity-80 transition group-hover:opacity-100">
          {(run.status === "pending" || run.status === "failed" || run.status === "cancelled") && (
            <button
              onClick={onStart}
              disabled={busy}
              className="flex items-center gap-1 rounded-md border border-jade/40 bg-jade-soft px-2 py-1 text-[11.5px] text-jade transition hover:bg-jade hover:text-card disabled:opacity-50"
              title="启动回测"
            >
              {busy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
              启动
            </button>
          )}
          {run.status === "running" && (
            <>
              <button
                onClick={onPause}
                disabled={busy}
                className="flex items-center gap-1 rounded-md border border-amber/40 bg-amber-soft px-2 py-1 text-[11.5px] text-amber transition hover:bg-amber hover:text-card disabled:opacity-50"
                title="暂停（下一条事件起生效）"
              >
                {busy ? <Loader2 size={11} className="animate-spin" /> : <Pause size={11} />}
                暂停
              </button>
              <button
                onClick={onCancel}
                disabled={busy}
                className="flex items-center gap-1 rounded-md border border-rise/30 bg-rise/5 px-2 py-1 text-[11.5px] text-rise transition hover:bg-rise hover:text-card disabled:opacity-50"
                title="取消回测"
              >
                {busy ? <Loader2 size={11} className="animate-spin" /> : <Square size={11} />}
                取消
              </button>
            </>
          )}
          {run.status === "paused" && (
            <>
              <button
                onClick={onResume}
                disabled={busy}
                className="flex items-center gap-1 rounded-md border border-jade/40 bg-jade-soft px-2 py-1 text-[11.5px] text-jade transition hover:bg-jade hover:text-card disabled:opacity-50"
                title="继续"
              >
                {busy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                继续
              </button>
              <button
                onClick={onCancel}
                disabled={busy}
                className="flex items-center gap-1 rounded-md border border-rise/30 bg-rise/5 px-2 py-1 text-[11.5px] text-rise transition hover:bg-rise hover:text-card disabled:opacity-50"
                title="取消（丢弃暂停状态，置为已取消）"
              >
                {busy ? <Loader2 size={11} className="animate-spin" /> : <Square size={11} />}
                取消
              </button>
            </>
          )}
          <button
            onClick={onOpen}
            className="rounded-md border border-edge bg-card px-2 py-1 text-[11.5px] text-mute transition hover:bg-edge/40 hover:text-ink"
            title="查看详情"
          >
            详情
          </button>
          <button
            onClick={onDelete}
            disabled={busy}
            className="rounded-md p-1 text-faint transition hover:bg-edge/60 hover:text-rise disabled:opacity-50"
            title="删除"
          >
            <Trash2 size={12.5} />
          </button>
        </div>
      </td>
    </tr>
  );
}

function RunnerTag({ runner }: { runner: string }) {
  const cfg: Record<string, string> = {
    team_full: "bg-violet-soft text-violet",
    team_prompt: "bg-brand-soft text-brand",
    baseline: "bg-edge text-mute",
  };
  return (
    <span className={cls("rounded-md px-1.5 py-0.5 font-mono text-[10.5px] font-medium", cfg[runner] ?? "bg-edge text-mute")}>
      {runner}
    </span>
  );
}

function AccCell({ acc, lo }: { acc?: number | null; lo?: number | null }) {
  if (acc == null || Number.isNaN(acc)) {
    return <span className="font-mono text-[11px] text-faint">—</span>;
  }
  const pct = acc * 100;
  const color = pct >= 70 ? "text-jade" : pct >= 55 ? "text-ink" : "text-rise";
  return (
    <div>
      <div className={cls("font-mono text-[12px] font-semibold tabular-nums", color)}>
        {pct.toFixed(1)}%
      </div>
      {lo != null && !Number.isNaN(lo) && (
        <div className="font-mono text-[10px] text-faint tabular-nums">
          Wilson 95% lo ≥ {(lo * 100).toFixed(1)}%
        </div>
      )}
    </div>
  );
}

function EmptyHint({
  title,
  desc,
  icon,
  actionLabel,
  onAction,
}: {
  title: string;
  desc: string;
  icon?: React.ReactNode;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center px-6">
      {icon ?? <CircleDashed size={32} className="text-faint/60" />}
      <h3 className="mt-4 font-serif text-[17px] font-semibold text-ink">{title}</h3>
      <p className="mt-1 max-w-md text-[12.5px] text-mute">{desc}</p>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="mt-5 flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-[12.5px] font-medium text-card shadow-card transition hover:bg-brand-hover hover:shadow-pop"
        >
          <Plus size={14} />
          {actionLabel}
        </button>
      )}
      <style>{`.input{}`}</style>
      <span key={uid()}></span>
    </div>
  );
}
