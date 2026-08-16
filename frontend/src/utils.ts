/** className 拼接小工具（作为默认导出 clsx 别名）。 */
export function cls(...xs: (string | false | null | undefined)[]): string {
  return xs.filter(Boolean).join(" ");
}
export { cls as clsx };

export function uid(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** 相对时间：刚刚 / n分钟前 / n小时前 / 昨天 / YYYY-MM-DD */
export function relTime(iso?: string): string {
  if (!iso) return "";
  const t = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(t.getTime())) return "";
  const diff = Date.now() - t.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  if (d === 1) return "昨天";
  if (d < 7) return `${d} 天前`;
  const mm = String(t.getMonth() + 1).padStart(2, "0");
  const dd = String(t.getDate()).padStart(2, "0");
  return `${t.getFullYear()}-${mm}-${dd}`;
}

/** 参数摘要：把 args 压成一行短文本 */
export function argsSummary(args?: Record<string, unknown>): string {
  if (!args) return "";
  const parts = Object.entries(args)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${String(v)}`);
  const s = parts.join(" · ");
  return s.length > 72 ? s.slice(0, 72) + "…" : s;
}

/** 大数字缩写展示 */
export function fmtNum(n: unknown): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return String(n ?? "");
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + "亿";
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + "万";
  return String(n);
}
