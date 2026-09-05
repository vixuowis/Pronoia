#!/usr/bin/env python3
"""Generate Feishu doc content from today's prediction data."""
import json
from collections import Counter, defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = _PROJECT_ROOT / "data_snapshots" / "today"

def load(p):
    return [json.loads(l) for l in open(DATA / p) if l.strip()]

events = load("events_today.jsonl")
team = load("research_cache_team.jsonl")
merged = load("research_cache_merged.jsonl")
research_claims = load("claims_today.jsonl")
baseline_claims = load("claims_today_baseline.jsonl")

team_by_eid = {r["event_id"]: r for r in team}
research_by_eid = {r["event_id"]: r for r in research_claims}
baseline_by_eid = {r["event_id"]: r for r in baseline_claims}
merged_by_eid = {r["event_id"]: r for r in merged}

WINDOW_ORDER = ["T-0", "T-1", "T-3", "T-7", "T-14", "T-30", "T-60"]

def fmt_claim(c):
    """Format a single claim as readable string."""
    m = c.get("metric", "?")
    op = c.get("op", "?")
    thr = c.get("thr", "?")
    judge = "TRUE" if c.get("judge") else "FALSE"
    conf = c.get("conf", "?")
    if isinstance(thr, float):
        thr_str = f"{thr:.4f}" if abs(thr) < 1 else f"{thr:.2f}"
    else:
        thr_str = str(thr)
    return f"{m} {op} {thr_str} → {judge} (conf {conf})"

def claims_summary(claims_row):
    """Return (n_claims, list of formatted claim strings, horizon_dist, family_dist)."""
    claims = claims_row.get("claims", []) if claims_row else []
    if isinstance(claims, str):
        return 0, [], {}, {}
    n = len(claims)
    strs = [fmt_claim(c) for c in claims]
    h_dist = Counter(str(c.get("horizon", "?")) for c in claims)
    f_dist = Counter(str(c.get("family", "?")) for c in claims)
    return n, strs, dict(h_dist), dict(f_dist)

# ===== Distribution stats =====
win_dist = Counter(e["_window"] for e in events)
type_dist = Counter(e["event_type_l2"] for e in events)
team_dir_dist = Counter(r["direction"] for r in team if r.get("ok"))
team_conf = [r["confidence"] for r in team if r.get("ok") and r.get("confidence") is not None]

research_n = sum(len(r.get("claims", []) or []) for r in research_claims)
baseline_n = sum(len(r.get("claims", []) or []) for r in baseline_claims)

# horizon/family distribution for research claims
all_r_claims = [c for r in research_claims for c in (r.get("claims") or [])]
all_b_claims = [c for r in baseline_claims for c in (r.get("claims") or [])]
r_h_dist = Counter(str(c.get("horizon", "?")) for c in all_r_claims)
b_h_dist = Counter(str(c.get("horizon", "?")) for c in all_b_claims)
r_f_dist = Counter(str(c.get("family", "?")) for c in all_r_claims)
b_f_dist = Counter(str(c.get("family", "?")) for c in all_b_claims)

# ===== Build markdown =====
lines = []
lines.append("# Pronoia 前向预测报告 · 2026-09-04")
lines.append("")
lines.append("> 事件收集日：2026-09-04 ｜ 验证日：2026-09-05 收盘后 ｜ 模型：papv_v61 LoRA (Qwen3-8B)")
lines.append("> Team 三专家：market_analyst + fundamentals_analyst + deep_researcher ｜ 量价特征：vol_t0_ratio / vol_pre5_ratio / price_vol_diverge / range_t0_normalized")
lines.append("")

# ---- Overview ----
lines.append("## 一、总览")
lines.append("")
lines.append(f"- 事件总数：**{len(events)}** 条（A 股 akshare 高质量公告，qscore≥4）")
lines.append(f"- Team 推理成功：**{sum(1 for r in team if r.get('ok'))}/{len(team)}**")
lines.append(f"- 量价特征覆盖：**{sum(1 for r in merged if (r.get('vol_features') or {}).get('vol_t0_ratio') is not None)}/{len(merged)}**")
lines.append(f"- 基准上下文覆盖：**{sum(1 for r in merged if (r.get('benchmark_ctx') or {}).get('benchmark_stats', {}).get('ok'))}/{len(merged)}**")
lines.append(f"- Baseline 断言（无 research）：**{baseline_n}** 条（{baseline_n/len(baseline_claims):.1f}/event）")
lines.append(f"- Research 断言（带 Team + 量价）：**{research_n}** 条（{research_n/len(research_claims):.1f}/event）")
lines.append("")

# ---- Distribution tables ----
lines.append("## 二、数据分布")
lines.append("")
lines.append("### 2.1 事件窗口分布（T-X = X 日前发生）")
lines.append("")
lines.append("| 窗口 | 事件数 | 占比 |")
lines.append("|---|---|---|")
for w in WINDOW_ORDER:
    n = win_dist.get(w, 0)
    lines.append(f"| {w} | {n} | {n/len(events)*100:.0f}% |")
lines.append("")

lines.append("### 2.2 事件类型分布")
lines.append("")
lines.append("| 类型 | 事件数 | 占比 |")
lines.append("|---|---|---|")
for t, n in type_dist.most_common():
    lines.append(f"| {t} | {n} | {n/len(events)*100:.0f}% |")
lines.append("")

lines.append("### 2.3 Team 方向预测分布")
lines.append("")
lines.append("| 方向 | 数量 | 占比 |")
lines.append("|---|---|---|")
for d in ["up", "down", "neutral"]:
    n = team_dir_dist.get(d, 0)
    lines.append(f"| {d} | {n} | {n/len(team)*100:.0f}% |")
if team_conf:
    lines.append(f"\nTeam 置信度：均值 {sum(team_conf)/len(team_conf):.2f}，最低 {min(team_conf):.2f}，最高 {max(team_conf):.2f}")
lines.append("")

lines.append("### 2.4 断言 horizon 分布（两版模型对比）")
lines.append("")
all_h = sorted(set(r_h_dist) | set(b_h_dist), key=lambda x: (x == "?", x))
lines.append("| Horizon | Baseline | Research |")
lines.append("|---|---|---|")
for h in all_h:
    lines.append(f"| t{h} | {b_h_dist.get(h, 0)} | {r_h_dist.get(h, 0)} |")
lines.append("")

lines.append("### 2.5 断言指标族分布（两版模型对比）")
lines.append("")
all_f = sorted(set(r_f_dist) | set(b_f_dist))
lines.append("| 指标族 | Baseline | Research |")
lines.append("|---|---|---|")
for f in all_f:
    lines.append(f"| {f} | {b_f_dist.get(f, 0)} | {r_f_dist.get(f, 0)} |")
lines.append("")

# ---- Per-event details ----
lines.append("## 三、逐事件详情")
lines.append("")
lines.append("> 每条事件包含：事件信息 → Team 决策链（方向/置信度/推理依据）→ Baseline 断言 → Research 断言")
lines.append("")

# Group events by window for readability
events_by_win = defaultdict(list)
for e in events:
    events_by_win[e["_window"]].append(e)

for w in WINDOW_ORDER:
    wev = events_by_win.get(w, [])
    if not wev:
        continue
    lines.append(f"### {w} 窗口（{len(wev)} 条）")
    lines.append("")
    for idx, e in enumerate(wev, 1):
        eid = e["event_id"]
        sym = e["symbol"]
        mkt = e["market"]
        edate = e["event_date"]
        etype = e["event_type_l2"]
        title = e["title"]
        qscore = e["_qscore"]
        name = e.get("_name", "")

        lines.append(f"#### {idx}. [{mkt}] {sym} {name} — {title[:50]}")
        lines.append("")
        lines.append(f"- **事件日**：{edate} ｜ **类型**：{etype} ｜ **质量分**：q={qscore}")
        lines.append(f"- **event_id**：`{eid}`")
        lines.append("")

        # Team decision chain
        t = team_by_eid.get(eid, {})
        if t.get("ok"):
            lines.append(f"**🧠 Team 决策链**：方向 `{t.get('direction')}` ｜ 置信度 `{t.get('confidence')}`")
            rat = (t.get("rationale") or "").strip()
            if rat:
                # Truncate to 400 chars to keep doc readable
                rat_disp = rat[:500] + ("…" if len(rat) > 500 else "")
                lines.append(f"")
                lines.append(f"> {rat_disp}")
            lines.append("")
        else:
            lines.append(f"**🧠 Team 决策链**：失败 — {t.get('error', 'unknown')}")
            lines.append("")

        # vol_features
        m = merged_by_eid.get(eid, {})
        vf = m.get("vol_features") or {}
        if vf.get("vol_t0_ratio") is not None:
            lines.append(f"- **量价特征**：vol_t0_ratio={vf['vol_t0_ratio']:.3f} ｜ vol_pre5_ratio={vf['vol_pre5_ratio']:.3f} ｜ price_vol_diverge={vf['price_vol_diverge']:.2f} ｜ range_t0_normalized={vf['range_t0_normalized']:.2f}")
            lines.append("")

        # Baseline claims
        b = baseline_by_eid.get(eid)
        bn, bstrs, bh, bf = claims_summary(b)
        lines.append(f"**📋 Baseline 断言（{bn} 条）**：")
        for s in bstrs:
            lines.append(f"  - {s}")
        lines.append("")

        # Research claims
        r = research_by_eid.get(eid)
        rn, rstrs, rh, rf = claims_summary(r)
        lines.append(f"**🔬 Research 断言（{rn} 条，带 Team+量价上下文）**：")
        for s in rstrs:
            lines.append(f"  - {s}")
        lines.append("")
        lines.append("---")
        lines.append("")

lines.append("## 四、验证说明")
lines.append("")
lines.append("明日（2026-09-05）收盘后执行验证：")
lines.append("")
lines.append("```bash")
lines.append("cd /root/Pronoia && /root/miniconda3/bin/python pipelines/today/verify_today_predictions.py")
lines.append("```")
lines.append("")
lines.append("脚本将：")
lines.append("1. 下载 56 只股票 + 沪深300基准最新 K 线")
lines.append("2. 计算 car_t1/t3/t7/t15/t30/t60 + ret + bm_ret + pvalue")
lines.append("3. 结算所有断言，输出准确率（按窗口/horizon/类型/指标族拆分）")
lines.append("4. 产出 settlement_today.jsonl + summary_verification.json")

content = "\n".join(lines)
out = _PROJECT_ROOT / "data_snapshots" / "today" / "feishu_doc.md"
with open(out, "w", encoding="utf-8") as f:
    f.write(content)
print(f"doc content generated: {len(content)} chars, {len(lines)} lines")
print(f"-> {out}")
