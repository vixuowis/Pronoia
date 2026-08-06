import { CandlestickChart, LineChart, Newspaper, ScrollText, Table2, ArrowUpRight, Network, GitBranch } from "lucide-react";
import type { ArtifactKind } from "../types";
import { KIND_CN } from "../names";
import { cls } from "../utils";
import { useStore } from "../store";

export function KindIcon({ kind, size = 16 }: { kind: ArtifactKind; size?: number }) {
  const clsName = "shrink-0";
  switch (kind) {
    case "kline":
      return <CandlestickChart size={size} className={clsName} />;
    case "line":
      return <LineChart size={size} className={clsName} />;
    case "table":
      return <Table2 size={size} className={clsName} />;
    case "evidence":
      return <Newspaper size={size} className={clsName} />;
    case "report":
      return <ScrollText size={size} className={clsName} />;
    case "graph":
      return <Network size={size} className={clsName} />;
    case "simulation":
      return <GitBranch size={size} className={clsName} />;
    default:
      return <Table2 size={size} className={clsName} />;
  }
}

/** 对话内联产出物卡片：点击在右栏定位打开 */
export default function ArtifactCard({
  artifactId,
  kind,
  title,
}: {
  artifactId: string;
  kind: ArtifactKind;
  title: string;
}) {
  const artifact = useStore((s) => s.artifacts.find((a) => a.id === artifactId));
  const selected = useStore((s) => s.selectedArtifactId === artifactId);
  const selectArtifact = useStore((s) => s.selectArtifact);

  const k = artifact?.kind ?? kind;
  const t = artifact?.title ?? title;

  return (
    <button
      onClick={() => selectArtifact(artifactId)}
      className={cls(
        "flex w-full items-center gap-3 rounded-card border bg-card px-3.5 py-3 text-left shadow-card transition-all duration-200 hover:-translate-y-px hover:shadow-pop",
        selected ? "border-jade/60 ring-1 ring-jade/30" : "border-edge hover:border-edgeDark",
      )}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-jade-soft text-jade">
        <KindIcon kind={k} size={17} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium text-ink">{t}</span>
        <span className="mt-0.5 block text-[11.5px] text-faint">{KIND_CN[k] ?? k} · 点击在右栏查看</span>
      </span>
      <ArrowUpRight
        size={15}
        className={cls("shrink-0 transition-colors", selected ? "text-jade" : "text-faint")}
      />
    </button>
  );
}
