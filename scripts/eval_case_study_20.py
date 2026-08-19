"""Case Study 20 条验证：新管线 vs 旧管线 ACC 对比 + 每条明细。"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_jsonl(p: Path) -> list[dict]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 置信区间。"""
    if n == 0:
        return (0.0, 0.0)
    p_hat = k / n
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    half = (z * math.sqrt(p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def gate_direction(direction: str, confidence: float, threshold: float) -> str:
    if confidence < threshold:
        return "neutral"
    return direction


def strict_acc(preds: dict[str, dict], labels: dict[str, dict],
               gate: float, valid_event_ids: set[str]) -> tuple[int, int]:
    k = n = 0
    for eid in valid_event_ids:
        if eid not in labels or eid not in preds:
            continue
        lbl = labels[eid]["label_t3"]
        p = gate_direction(preds[eid]["direction"], preds[eid]["confidence"], gate)
        # 非 neutral 才算有效
        if lbl == "neutral":
            continue  # 旧系统和报告都忽略 neutral label（设计约束要求）
        n += 1
        if p == lbl:
            k += 1
    return k, n


def main() -> None:
    # 加载数据
    labels_list = load_jsonl(DATA / "labels_case_study_20.jsonl")
    labels = {l["event_id"]: l for l in labels_list}

    # 旧预测（从 1000 条 trajectory ckpt 提取，G=0.50 gate）
    meta = json.loads((DATA / "case_study_20_meta.json").read_text(encoding="utf-8"))
    old_preds = {}
    for eid, m in meta.items():
        old_preds[eid] = {"direction": m["old_direction"], "confidence": m["old_confidence"]}

    # 新预测（20 条刚跑完）
    new_preds_list = load_jsonl(DATA / "preds_case_study_20_new_pipeline.jsonl")
    new_preds = {}
    for p in new_preds_list:
        eid = p.get("event_id")
        direction = p.get("pred_direction") or p.get("direction")
        confidence = float(p.get("confidence", 0) or 0)
        if eid and direction:
            new_preds[eid] = {"direction": direction, "confidence": confidence}

    # 检查 signal_routing 是否真的生效（验证 analyzer 被调用）
    ckpt_dir = DATA / "_trajectory_ckpt_case_study_20_v4"
    analyzer_called: dict[str, str | None] = {}
    for ckpt_file in sorted(ckpt_dir.glob("*.json")):
        eid = ckpt_file.stem
        try:
            ck = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except Exception:
            analyzer_called[eid] = None
            continue
        tt = ck.get("team_final_state", {}).get("tool_trace") or []
        routing_evs = [t for t in tt if t.get("type") == "signal_routing"]
        analyzer_called[eid] = routing_evs[-1].get("analyzer") if routing_evs else None

    valid_ids = set(labels.keys()) & set(old_preds.keys()) & set(new_preds.keys())
    print(f"有效事件数（三方都有数据）: {len(valid_ids)} / 20")

    events_list = load_jsonl(DATA / "events_case_study_20.jsonl")
    events = {e["event_id"]: e for e in events_list}

    # ===== 逐条明细 =====
    print("\n" + "=" * 130)
    print(f"{'#':>2} {'市场':>2} {'类型':<10} {'CarT3':>8} {'Label':>7} │ "
          f"{'旧Dir':>7} {'旧Conf':>6} {'旧G=0.50':>8} {'旧对':>3} │ "
          f"{'新Dir':>7} {'新Conf':>6} {'新G=0.50':>8} {'新对':>3} │ "
          f"{'Analyzer':<18} 标题")
    print("=" * 130)

    rows = []
    for idx, eid in enumerate(sorted(valid_ids, key=lambda x: (
        events.get(x, {}).get("market", ""),
        events.get(x, {}).get("event_type_l2", ""),
        -abs(labels[x]["car_t3"]),
    )), 1):
        e = events[eid]
        mkt = e.get("market", "?")
        et = e.get("event_type_l2", "?")
        car_t3 = labels[eid]["car_t3"]
        lbl = labels[eid]["label_t3"]

        op = old_preds[eid]
        np_ = new_preds[eid]
        og = gate_direction(op["direction"], op["confidence"], 0.50)
        ng = gate_direction(np_["direction"], np_["confidence"], 0.50)
        old_ok = "✓" if og == lbl and lbl != "neutral" else ("-" if lbl == "neutral" else "✗")
        new_ok = "✓" if ng == lbl and lbl != "neutral" else ("-" if lbl == "neutral" else "✗")

        analyzer = analyzer_called.get(eid) or "(no routing)"
        title = e.get("title", "")[:36]

        rows.append({
            "idx": idx, "eid": eid, "mkt": mkt, "et": et,
            "car_t3": car_t3, "lbl": lbl,
            "old_dir": op["direction"], "old_conf": op["confidence"], "old_gate": og, "old_ok": old_ok,
            "new_dir": np_["direction"], "new_conf": np_["confidence"], "new_gate": ng, "new_ok": new_ok,
            "analyzer": analyzer, "title": title,
        })

    for r in rows:
        print(f"{r['idx']:>2} {r['mkt']:>2} {r['et'][:10]:<10} {r['car_t3']:+8.4f} {r['lbl']:>7} │ "
              f"{r['old_dir']:>7} {r['old_conf']:6.3f} {r['old_gate']:>8} {r['old_ok']:>3} │ "
              f"{r['new_dir']:>7} {r['new_conf']:6.3f} {r['new_gate']:>8} {r['new_ok']:>3} │ "
              f"{r['analyzer']:<18} {r['title']}…")

    # ===== 聚合指标 =====
    # Strict ACC (G=0.50, 仅对非 neutral label 计分)
    for gate in [0.50, 0.52, 0.60]:
        ok, on = strict_acc(old_preds, labels, gate, valid_ids)
        nk, nn = strict_acc(new_preds, labels, gate, valid_ids)

        oacc = ok / on if on else 0
        nacc = nk / nn if nn else 0
        oci = wilson_ci(ok, on)
        nci = wilson_ci(nk, nn)

        print(f"\n===== Gate = {gate:.2f} (Strict ACC，对非 neutral label 计分) =====")
        print(f"  旧管线: ACC {ok}/{on} = {oacc*100:5.1f}%   Wilson 95% CI [{oci[0]*100:4.1f}%, {oci[1]*100:4.1f}%]")
        print(f"  新管线: ACC {nk}/{nn} = {nacc*100:5.1f}%   Wilson 95% CI [{nci[0]*100:4.1f}%, {nci[1]*100:4.1f}%]")
        if oacc > 0:
            delta = (nacc - oacc) * 100
            print(f"  变化: Δ = {delta:+.1f} pp  ({'+' if delta>=0 else ''}{(nacc/oacc-1)*100:.0f}%)")

    # 按 market×event_type 分层 G=0.50
    gate = 0.50
    from collections import defaultdict
    old_by_group = defaultdict(lambda: [0, 0])  # [correct, total]
    new_by_group = defaultdict(lambda: [0, 0])
    for eid in valid_ids:
        lbl = labels[eid]["label_t3"]
        if lbl == "neutral":
            continue
        key = (events[eid].get("market", "?"), events[eid].get("event_type_l2", "?"))
        og = gate_direction(old_preds[eid]["direction"], old_preds[eid]["confidence"], gate)
        ng = gate_direction(new_preds[eid]["direction"], new_preds[eid]["confidence"], gate)
        old_by_group[key][1] += 1
        new_by_group[key][1] += 1
        if og == lbl:
            old_by_group[key][0] += 1
        if ng == lbl:
            new_by_group[key][0] += 1

    print(f"\n===== 分层 ACC (Gate={gate:.2f}) =====")
    print(f"{'市场×类型':<28} {'旧ACC':>14} {'新ACC':>14} {'Δpp':>6}")
    for key in sorted(old_by_group.keys()):
        oc, ot = old_by_group[key]
        nc, nt = new_by_group[key]
        oa = oc / ot if ot else 0
        na = nc / nt if nt else 0
        label = f"{key[0]}/{key[1][:18]}"
        delta = (na - oa) * 100
        print(f"{label:<28} {oc:>2}/{ot:<2} = {oa*100:5.1f}%   {nc:>2}/{nt:<2} = {na*100:5.1f}%   {delta:+5.1f}")

    # Neutral 比例
    def neutral_ratio(preds, gate):
        n_all = 0; n_neu = 0
        for eid in valid_ids:
            if labels[eid]["label_t3"] == "neutral":
                continue
            n_all += 1
            if gate_direction(preds[eid]["direction"], preds[eid]["confidence"], gate) == "neutral":
                n_neu += 1
        return n_neu, n_all
    for gate in [0.50, 0.60]:
        on, ot = neutral_ratio(old_preds, gate)
        nn_, nt_ = neutral_ratio(new_preds, gate)
        print(f"\nNeutral 比例 (Gate={gate:.2f}, 不含 neutral label): "
              f"旧={on}/{ot}={on/ot*100:.0f}%  新={nn_}/{nt_}={nn_/nt_*100:.0f}%  (目标 15-20%)")

    # signal routing 覆盖率
    routed = sum(1 for eid in valid_ids if analyzer_called.get(eid))
    print(f"\n信号路由覆盖率：{routed}/{len(valid_ids)} = {routed/len(valid_ids)*100:.0f}%")
    analyzers_used = {v for v in analyzer_called.values() if v}
    print(f"  调用过的 Analyzer：{sorted(analyzers_used)}")


if __name__ == "__main__":
    main()
