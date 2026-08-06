import { useEffect, useRef, useState } from "react";
import { AlertCircle, GitBranch, Loader2 } from "lucide-react";
import { api } from "../api";
import type { Artifact, SimulationJob } from "../types";
import { useStore } from "../store";

const STAGE_CN: Record<string, string> = {
  queued: "等待执行",
  compiling_spec: "整理证据与参与方",
  validating: "校验输入",
  building_graph: "构建模拟世界",
  simulating: "多方行动推演",
  compiling_scenarios: "汇总情景分支",
  completed: "推演完成",
  failed: "推演失败",
  cancel_requested: "正在安全停止",
  cancelled: "已取消",
};

export default function SimulationLaunch({ artifact }: { artifact: Artifact }) {
  const caseId = useStore((s) => s.currentCaseId);
  const loadCase = useStore((s) => s.loadCase);
  const selectArtifact = useStore((s) => s.selectArtifact);
  const [job, setJob] = useState<SimulationJob | null>(null);
  const [error, setError] = useState("");
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
      const resumable = jobs.find(
        (item) => item.graph_artifact_id === artifact.id && ["queued", "running", "cancelling"].includes(item.status),
      );
      if (resumable) setJob(resumable);
    }).catch(() => { /* gateway may be offline while browsing old artifacts */ });
    return () => { active = false; };
  }, [artifact.id, caseId]);
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
        max_actors: 6,
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
          <p className="text-[13px] font-semibold text-ink">多智能体事件推演</p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-mute">将证据图中的事实编译为参与方、约束与行动空间，异步生成未来情景。当前快速模式输出情景，不输出校准概率。</p>
          {busy ? (
            <div className="mt-3">
              <div className="mb-1.5 flex items-center justify-between text-[11px] text-mute">
                <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" />{STAGE_CN[job.stage] ?? job.stage}</span>
                <span>{Math.round(job.progress * 100)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-edge"><div className="h-full rounded-full bg-jade transition-all" style={{ width: `${Math.max(3, job.progress * 100)}%` }} /></div>
              <button disabled={job.status === "cancelling"} onClick={() => void cancel()} className="mt-2 text-[11px] font-medium text-mute underline-offset-2 hover:text-ink hover:underline disabled:cursor-not-allowed disabled:text-faint">{job.status === "cancelling" ? "正在停止…" : "取消推演"}</button>
            </div>
          ) : (
            <button onClick={() => void start()} className="mt-3 rounded-lg bg-jade px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-[#0c665f]">
              开始快速推演
            </button>
          )}
          {(error || job?.error) && <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-[#A33A32]"><AlertCircle size={12} className="mt-0.5 shrink-0" />{error || job?.error}</p>}
        </div>
      </div>
    </div>
  );
}
