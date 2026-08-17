from __future__ import annotations

from pathlib import Path


def _fmt_wilson(d: dict | None) -> str:
    if not d: return "N/A"
    return (
        f"n={d.get('n')} k={d.get('k')} acc={float(d.get('acc') or 0):.2%}  "
        f"Wilson95% [{float(d.get('wilson_lo_95') or 0):.2%}, {float(d.get('wilson_hi_95') or 1):.2%}]"
    )


def render_markdown(metrics: dict) -> str:
    strict_t3 = metrics.get("acc_t3_strict") or {}
    non_neu = metrics.get("acc_t3_non_neutral") or {}
    overall = (
        f"- n_total (pred∩labels): {metrics.get('n_total')}\n"
        f"- n_abstain_pred (runner failed/confidence hard闸): {metrics.get('n_abstain_pred')}\n"
        f"- n_abstain_oracle (label_t3 空，car_t3 缺失): {metrics.get('n_abstain_oracle')}\n"
        f"- epsilon (中性边界 bps): {float(metrics.get('epsilon') or 0)*10000:.0f}\n"
        "\n"
        "### ACC 主口径 · 严格（含 neutral 分母 + 剔除双方 abstain）\n"
        f"- T+1: {_fmt_wilson(metrics.get('acc_t1_strict'))}\n"
        f"- T+3: {_fmt_wilson(strict_t3)}\n"
        f"- T+5: {_fmt_wilson(metrics.get('acc_t5_strict'))}\n"
        "\n"
        "### ACC 次口径 · T+3 非中性样本（剔除 neutral + 剔除 abstain）\n"
        f"- T+3 non-neutral: {_fmt_wilson(non_neu)}\n"
        "\n"
        "### Oracle CAR 均值（有效 label 样本）\n"
        f"- avg_car_t1: {float(metrics.get('avg_car_t1') or 0):.4f}\n"
        f"- avg_car_t3: {float(metrics.get('avg_car_t3') or 0):.4f}\n"
        f"- avg_car_t5: {float(metrics.get('avg_car_t5') or 0):.4f}\n"
        # 向后兼容老字段名（直接打印数值）
        f"\n<details><summary>Legacy fields（backward-compat）</summary>\n"
        f"\n"
        f"- acc_t1 = {metrics.get('acc_t1'):.4f}\n"
        f"- acc_t3 = {metrics.get('acc_t3'):.4f}\n"
        f"- acc_t5 = {metrics.get('acc_t5'):.4f}\n"
        f"</details>\n"
    )

    def section(title: str, rows: dict) -> str:
        keys = sorted(rows.keys())
        lines = [
            f"## {title}", "",
            "| key | n | n_valid_t3 | acc_t1 | acc_t3 | acc_t5 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for k in keys:
            r = rows[k] or {}
            lines.append(
                f"| {k} | {int(r.get('n') or 0)} | {int(r.get('n_valid_t3') or 0)} "
                f"| {float(r.get('acc_t1') or 0.0):.4f} "
                f"| {float(r.get('acc_t3') or 0.0):.4f} "
                f"| {float(r.get('acc_t5') or 0.0):.4f} |"
            )
        lines.append("")
        return "\n".join(lines)

    by_market = section("By Market", metrics.get("acc_by_market") or {})
    by_type = section("By Type", metrics.get("acc_by_type") or {})

    return "\n".join(
        [
            "# Event Backtest Report",
            "",
            "## Overall",
            "",
            overall,
            by_market,
            by_type,
        ]
    ).rstrip() + "\n"


def write_markdown(path: str | Path, metrics: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown(metrics), encoding="utf-8")

