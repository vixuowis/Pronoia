import { useEffect, useRef, useState } from "react";
import { AlertCircle, GitBranch, Loader2 } from "lucide-react";
import { api } from "../api";
import type { Artifact, SimulationJob } from "../types";
import { useStore } from "../store";

const STAGE_CN: Record<string, string> = {
  queued: "等待执行",
  compiling_spec: "整理证据与参与方",
  validating: "校验输入",
  preparing_direct: "从证据图编译模拟世界",
  building_graph: "构建模拟世界",
  retrying_ontology: "本体生成暂时失败，正在重试",
  resuming: "从已保存进度继续",
  simulating: "多方行动推演",
  compiling_scenarios: "汇总情景分支",
  completed: "推演完成",
  partial: "部分完成",
  failed: "推演失败",
  cancel_requested: "正在安全停止",
  cancelled: "已取消",
};

function friendlySimulationError(message?: string | null) {
  if (!message) return "";
  if (message.includes("Ontology generation failed")) {
    return "MiroFish 在整理参与方关系时暂时失败。证据图和团队报告已保留，可以重新启动单次推演。";
  }
  if (message.includes("safety budget is exhausted")) {
    return "MiroFish 本次服务的模型安全预算已经用完。证据图已保留；重启 MiroFish 后可重新启动单次推演。";
  }
  if (message.includes("ZEP read quota") || message.toLowerCase().includes("rate limit")) {
    return "ZEP 的读取额度暂时用完，但已经提交的图谱批次仍被保留。额度窗口恢复后，可从原进度继续，不需要重新生成。";
  }
  return message;
}

export default function SimulationLaunch({ artifact }: { artifact: Artifact }) {
  const caseId = useStore((s) => s.currentCaseId);
  const loadCase = useStore((s) => s.loadCase);
  const selectArtifact = useStore((s) => s.selectArtifact);
  const [job, setJob] = useState<SimulationJob | null>(null);
  const [error, setError] = useState("");
  const [actorCap, setActorCap] = useState<"auto" | "4" | "6" | "8" | "10">("auto");
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.simulationPreview>> | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!caseId) return;
    let active = true;
    void api.simulations(caseId).then((jobs) => {
      if (!active) return;
      const latest = jobs.find((item) => item.graph_artifact_id === artifact.id);
      setJob(latest ?? null);
    }).catch(() => { /* gateway may be offline while browsing old artifacts */ });
    return () => { active = false; };
  }, [artifact.id, caseId]);
  useEffect(() => {
    if (!caseId) return;
    let active = true;
    setPreview(null);
    const body = {
      source_graph_artifact_id: artifact.id,
      question: artifact.payload?.question,
      horizon_days: 30,
      mode: "quick" as const,
      ...(actorCap === "auto" ? {} : { max_actors: Number(actorCap) }),
    };
    void api.simulationPreview(caseId, body).then((result) => {
      if (active) setPreview(result);
    }).catch(() => { /* 正式启动时仍会显示可操作的错误 */ });
    return () => { active = false; };
  }, [actorCap, artifact.id, artifact.payload?.question, caseId]);
  useEffect(() => {
    if (!job || !["queued", "running", "cancelling"].includes(job.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.simulation(job.id);
        if (!alive.current) return;
        setJob(next);
        if (next.artifact_id && caseId) {
          await loadCase(caseId);
          if (alive.current) selectArtifact(next.artifact_id);
        }
      } catch (reason) {
        if (alive.current) setError(reason instanceof Error ? reason.message : String(reason));
      }
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [job, caseId, loadCase, selectArtifact]);

  const start = async () => {
    if (!caseId) return;
    setError("");
    try {
      const next = await api.startSimulation(caseId, {
        source_graph_artifact_id: artifact.id,
        question: artifact.payload?.question,
        horizon_days: 30,
        mode: "quick",
        ...(actorCap === "auto" ? {} : { max_actors: Number(actorCap) }),
      });
      setJob(next);
      if (next.artifact_id) {
        await loadCase(caseId);
        selectArtifact(next.artifact_id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const startOrResume = async () => {
    if (job?.status !== "failed") {
      await start();
      return;
    }
    setError("");
    try {
      setJob(await api.resumeSimulation(job.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const cancel = async () => {
    if (!job) return;
    setError("");
    try {
      setJob(await api.cancelSimulation(job.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const busy = job && ["queued", "running", "cancelling"].includes(job.status);
  return (
    <div className="mb-3 rounded-card border border-jade/25 bg-jade-soft/50 p-3.5">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-jade text-white"><GitBranch size={15} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-ink">事件预测员 · 多智能体事件推演</p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-mute">以深度研究者导出的证据图为输入，由事件预测员协调后台多方行动推演。当前单次模式通常需要 5～10 分钟，输出可审查情景，不输出校准概率。</p>
          {!busy && (
            <div className="mt-3 rounded-lg border border-jade/20 bg-white/60 p-2.5">
              <div className="flex items-center justify-between gap-3">
                <label htmlFor={`actor-cap-${artifact.id}`} className="text-[11px] font-medium text-ink">参与方预算</label>
                <select
                  id={`actor-cap-${artifact.id}`}
                  value={actorCap}
                  onChange={(event) => setActorCap(event.target.value as typeof actorCap)}
                  className="rounded-md border border-edge bg-card px-2 py-1 text-[11px] text-ink outline-none focus:border-jade"
                >
                  <option value="auto">自动推荐</option>
                  <option value="4">最多 4 个</option>
                  <option value="6">最多 6 个</option>
                  <option value="8">最多 8 个</option>
                  <option value="10">最多 10 个</option>
                </select>
              </div>
              {preview && (
                <div className="mt-2 text-[10.5px] leading-relaxed text-mute">
                  <p className="mb-1 font-medium text-ink">参与方预览（尚未产生推演结果）</p>
                  <p>
                    {actorCap === "auto" ? `本次自动推荐最多 ${preview.actor_selection.recommended_count} 个，实际选中 ${preview.actors.length} 个` : `本次最多 ${preview.actor_selection.applied_limit} 个，实际选中 ${preview.actors.length} 个`}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {preview.actors.map((actor) => (
                      <span key={actor.id} title={actor.selection_reason} className="rounded-full bg-jade-soft px-2 py-0.5 text-jade">{actor.label}</span>
                    ))}
                  </div>
                  <ul className="mt-1.5 space-y-0.5">
                    {preview.actors.map((actor) => <li key={actor.id}>• {actor.label}：{actor.selection_reason}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
          {busy ? (
            <div className="mt-3">
              <p className="mb-2 rounded-md bg-white/60 px-2 py-1.5 text-[10.5px] leading-relaxed text-mute">后台任务独立运行：聊天回答可能先结束，你可以继续浏览或离开当前产出物，完成后结果会写入侧边栏。</p>
              <div className="mb-1.5 flex items-center justify-between text-[11px] text-mute">
                <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" />{STAGE_CN[job.stage] ?? job.stage}</span>
                <span>{Math.round(job.progress * 100)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-edge"><div className="h-full rounded-full bg-jade transition-all" style={{ width: `${Math.max(3, job.progress * 100)}%` }} /></div>
              <button disabled={job.status === "cancelling"} onClick={() => void cancel()} className="mt-2 text-[11px] font-medium text-mute underline-offset-2 hover:text-ink hover:underline disabled:cursor-not-allowed disabled:text-faint">{job.status === "cancelling" ? "正在停止…" : "取消推演"}</button>
            </div>
          ) : (
            <>
              {job?.status === "failed" && (
                <p className="mt-3 rounded-md border border-[#D98B83]/40 bg-[#FFF4F2] px-2.5 py-2 text-[11px] leading-relaxed text-[#8C3530]">
                  上一次推演未进入多方行动阶段；证据图不受影响。如果已经保存了图谱批次，本次会从原进度继续。
                </p>
              )}
              <button onClick={() => void startOrResume()} className="mt-3 rounded-lg bg-jade px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-[#0c665f]">
                {job?.status === "failed" ? "从保存进度继续" : job?.status === "cancelled" ? "重新启动单次推演" : job?.status === "completed" || job?.status === "partial" ? "再次启动单次推演" : "交给事件预测员推演"}
              </button>
            </>
          )}
          {(error || job?.error) && <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-[#A33A32]"><AlertCircle size={12} className="mt-0.5 shrink-0" />{error || friendlySimulationError(job?.error)}</p>}
        </div>
      </div>
    </div>
  );
}
