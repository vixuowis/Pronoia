import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Search, X, Users, Check } from "lucide-react";
import { cls } from "../utils";

interface AgentLite {
  id: string;
  name: string;
  description: string;
  avatar_color?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** 可被勾选的专家（不含 deep_researcher，硬规则不可去掉） */
  agents: AgentLite[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

/** 团队成员多选对话框：
 *  - 默认全选；用户可选择性去掉非 deep_researcher 专家
 *  - 顶部快速操作：全选 / 全不选
 *  - 搜索 + 复选框 + 状态条 */
export default function TeamMemberPicker({ open, onClose, agents, selectedIds, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [mounted, setMounted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!mounted || !open) return null;

  const filtered = agents.filter((a) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return a.name.toLowerCase().includes(q) ||
           a.id.toLowerCase().includes(q) ||
           a.description.toLowerCase().includes(q);
  });

  const toggle = (id: string) => {
    if (id === "deep_researcher") return; // 硬规则
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const selectAll = () => onChange(agents.filter((a) => a.id !== "deep_researcher").map((a) => a.id));
  const clearAll = () => onChange([]); // deep_researcher 仍在硬规则里

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/35 px-4 py-8 backdrop-blur-sm animate-fadeIn"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="选择团队成员"
        className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-edge bg-card shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-edge px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-jade-soft text-jade">
              <Users size={15} />
            </span>
            <div>
              <div className="text-[13.5px] font-semibold text-ink">选择团队成员</div>
              <div className="text-[11px] text-faint">
                勾选要调度的专家；「深度研究者」始终参与（硬规则）；「主理人」负责最终综合与复核调度
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-mute transition-colors hover:bg-page hover:text-ink"
            title="关闭 (Esc)"
          >
            <X size={14} />
          </button>
        </div>

        {/* 搜索 + 快速操作 */}
        <div className="flex items-center gap-2 border-b border-edge bg-page/40 px-5 py-3">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索专家（按名称 / id / 描述）"
              className="block w-full rounded-lg border border-edge bg-card py-2 pl-8 pr-3 text-[12.5px] text-ink placeholder:text-faint focus:border-jade/50 focus:outline-none focus:ring-2 focus:ring-jade/20"
            />
          </div>
          <button
            onClick={selectAll}
            className="rounded-md border border-edge bg-card px-2 py-1.5 text-[11.5px] font-medium text-mute transition-colors hover:border-edgeDark hover:text-ink"
          >
            全选
          </button>
          <button
            onClick={clearAll}
            className="rounded-md border border-edge bg-card px-2 py-1.5 text-[11.5px] font-medium text-mute transition-colors hover:border-edgeDark hover:text-ink"
          >
            全不选
          </button>
        </div>

        {/* 列表 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-card border border-dashed border-edge text-faint">
                <Search size={16} />
              </span>
              <p className="mt-3 text-[12.5px] text-mute">没有匹配的专家</p>
            </div>
          ) : (
            <ul className="space-y-1">
              {filtered.map((a) => {
                const checked = a.id === "deep_researcher" ? true : selectedIds.includes(a.id);
                const locked = a.id === "deep_researcher";
                return (
                  <li key={a.id}>
                    <button
                      onClick={() => toggle(a.id)}
                      className={cls(
                        "group flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                        checked ? "bg-jade-soft/40 ring-1 ring-jade/30" : "hover:bg-page",
                      )}
                    >
                      <span
                        className={cls(
                          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
                          checked
                            ? "border-jade bg-jade text-card"
                            : "border-edgeDark bg-card text-transparent group-hover:border-jade/60",
                        )}
                      >
                        {checked && <Check size={11} strokeWidth={3} />}
                      </span>
                      <span
                        className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-card"
                        style={{ background: a.avatar_color || "#6B6862" }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] font-semibold text-ink">{a.name}</span>
                          <span className="font-mono text-[10.5px] text-faint">@{a.id}</span>
                          {locked && (
                            <span className="inline-flex items-center gap-0.5 rounded-full bg-jade-soft px-1.5 py-px text-[10px] font-medium text-jade">
                              必选
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-mute">
                          {a.description}
                        </p>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-between border-t border-edge bg-page/40 px-5 py-2.5 text-[11px] text-faint">
          <span>已选 {selectedIds.length + 1} 位专家（含「深度研究者」必选）</span>
          <button
            onClick={onClose}
            className="rounded-md bg-jade px-3 py-1.5 text-[12px] font-medium text-card hover:bg-jade-hover"
          >
            完成
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
