import { AlertTriangle, CheckCircle2, GitBranch, Users } from "lucide-react";

function Stat({ label, value }: { label: string; value: number | string }) {
  return <div className="rounded-lg border border-edge bg-card px-3 py-2"><p className="text-[10.5px] text-faint">{label}</p><p className="mt-0.5 text-[15px] font-semibold text-ink">{value}</p></div>;
}

export default function SimulationView({ payload }: { payload: any }) {
  const execution = payload?.execution ?? {};
  const scenarios = Array.isArray(payload?.scenarios) ? payload.scenarios : [];
  const warnings = Array.isArray(payload?.warnings) ? payload.warnings : [];
  return (
    <div className="space-y-3">
      <div className="rounded-card border border-edge bg-card p-3.5 shadow-card">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-ink"><Users size={15} className="text-jade" />执行摘要</div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Stat label="配置参与方" value={execution.configured_actor_count ?? 0} />
          <Stat label="实际活跃参与方" value={execution.active_actor_counts?.[0] ?? 0} />
          <Stat label="有效决策" value={execution.valid_decision_count ?? 0} />
          <Stat label="情景分支" value={scenarios.length} />
        </div>
      </div>
      <div className="rounded-lg border border-[#E8D7A5] bg-[#FFF9E8] px-3 py-2.5 text-[11.5px] leading-relaxed text-[#775B19]">
        <span className="font-semibold">含义提示：</span>分支频率与置信度只描述模拟内部的一致性，不等于真实市场发生概率，也不构成投资建议。
      </div>
      {scenarios.map((scenario: any, index: number) => (
        <div key={scenario.id ?? index} className="rounded-card border border-edge bg-card p-4 shadow-card">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-jade-soft text-jade"><GitBranch size={12} /></span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2"><p className="text-[13px] font-semibold text-ink">{scenario.label || `情景 ${index + 1}`}</p><span className="shrink-0 text-[10.5px] text-faint">内部一致性 {Math.round(Number(scenario.confidence ?? 0) * 100)}%</span></div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-mute">{scenario.summary}</p>
            </div>
          </div>
          {scenario.triggers?.length > 0 && <Section title="触发条件" items={scenario.triggers} tone="jade" />}
          {scenario.consequences?.length > 0 && <Section title="可能后果" items={scenario.consequences} tone="ink" />}
          {scenario.invalidation_conditions?.length > 0 && <Section title="失效条件" items={scenario.invalidation_conditions} tone="warn" />}
        </div>
      ))}
      {warnings.map((warning: string, index: number) => <div key={index} className="flex items-start gap-2 rounded-lg border border-edge bg-[#F8F6F2] px-3 py-2.5 text-[11.5px] text-mute"><AlertTriangle size={13} className="mt-0.5 shrink-0 text-[#B7791F]" />{warning}</div>)}
      {scenarios.length === 0 && <div className="py-10 text-center text-[12px] text-faint"><CheckCircle2 size={20} className="mx-auto mb-2" />本次未生成可展示的情景分支</div>}
    </div>
  );
}

function Section({ title, items, tone }: { title: string; items: string[]; tone: "jade" | "ink" | "warn" }) {
  const color = tone === "jade" ? "text-jade" : tone === "warn" ? "text-[#A15C22]" : "text-ink";
  return <div className="mt-3 border-t border-edge pt-2.5"><p className={`mb-1 text-[10.5px] font-semibold ${color}`}>{title}</p><ul className="space-y-1 text-[11.5px] leading-relaxed text-mute">{items.map((item, i) => <li key={i} className="flex gap-1.5"><span className="text-faint">•</span><span>{item}</span></li>)}</ul></div>;
}
