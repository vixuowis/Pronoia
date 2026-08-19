"""Case Study V2 评估：新管线 vs 旧管线 ACC 对比 + 每条明细。"""
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


def strict_acc(preds, labels, gate, valid_ids):
    k = n = 0
    nn_k = nn_n = 0
    for eid in valid_ids:
        if eid not in labels or eid not in preds:
            continue
        lbl = labels[eid]["label_t3"]
        if lbl == "neutral":
            continue
        p = gate_direction(preds[eid]["direction"], preds[eid]["confidence"], gate)
        n += 1
        if p == lbl:
            k += 1
        if p != "neutral":
            nn_n += 1
            if p == lbl:
                nn_k += 1
    return k, n, nn_k, nn_n


def main() -> None:
    labels_list = load_jsonl(DATA / "labels_case_study_v2.jsonl")
    labels = {l["event_id"]: l for l in labels_list}

    meta = json.loads((DATA / "case_study_v2_meta.json").read_text(encoding="utf-8"))
    old_preds = {}
    for eid, m in meta.items():
        old_preds[eid] = {"direction": m["old_direction"], "confidence": m["old_confidence"]}

    # 新预测
    new_preds_path = DATA / "preds_case_study_v2_new_pipeline.jsonl"
    new_preds = {}
    if new_preds_path.exists():
        for p in load_jsonl(new_preds_path):
            eid = p.get("event_id")
            direction = p.get("pred_direction") or p.get("direction")
            confidence = float(p.get("confidence", 0) or 0)
            if eid and direction:
                new_preds[eid] = {"direction": direction, "confidence": confidence}
    print(f"[加载] labels={len(labels)}, old={len(old_preds)}, new={len(new_preds)}")

    # signal routing 覆盖率
    ckpt_dir = DATA / "_trajectory_ckpt_case_study_v2"
    analyzer_called: dict[str, str | None] = {}
    routing_dirs: dict[str, str] = {}
    if ckpt_dir.exists():
        for cf in sorted(ckpt_dir.glob("*.json")):
            eid = cf.stem
            try:
                ck = json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                continue
            tt = ck.get("team_final_state", {}).get("tool_trace") or []
            routing_evs = [t for t in tt if t.get("type") == "signal_routing"]
            if routing_evs:
                analyzer_called[eid] = routing_evs[-1].get("analyzer")
                routing_dirs[eid] = routing_evs[-1].get("direction") or "?"
            else:
                analyzer_called[eid] = None

    valid_ids = set(labels.keys()) & set(old_preds.keys())
    if new_preds:
        valid_ids &= set(new_preds.keys())
    print(f"有效事件数: {len(valid_ids)}")

    events_list = load_jsonl(DATA / "events_case_study_v2.jsonl")
    events = {e["event_id"]: e for e in events_list}

    print("\n" + "=" * 140)
    print(f"{'#':>2} {'M':>2} {'类型':<10} {'CarT3%':>8} {'Lbl':>5} │ "
          f"{'旧Dir':>5} {'旧C':>5} {'旧G0.5':>5} {'对':>3} │ "
          f"{'新Dir':>5} {'新C':>5} {'新G0.5':>5} {'对':>3} │ "
          f"{'路由':>5} {'Analyzer':<20} 标题")
    print("=" * 140)

    rows = []
    for idx, eid in enumerate(sorted(valid_ids, key=lambda x: (
        events.get(x, {}).get("market", ""),
        events.get(x, {}).get("event_type_l2", ""),
        x))):
        ev = events.get(eid, {})
        lb = labels[eid]
        op = old_preds[eid]
        np_ = new_preds.get(eid, {"direction": "-", "confidence": 0})
        lbl = lb["label_t3"]
        car = lb.get("car_t3")
        op_g = gate_direction(op["direction"], op["confidence"], 0.50)
        np_g = gate_direction(np_["direction"], np_["confidence"], 0.50)
        ok_old = "✓" if op_g == lbl else ("·" if op_g == "neutral" else "✗")
        ok_new = "✓" if np_g == lbl else ("·" if np_g == "neutral" else "✗")
        title = (ev.get("title") or "")[:40]
        aly = analyzer_called.get(eid) or "-"
        rd = routing_dirs.get(eid, "-")
        rows.append({
            "eid": eid, "market": ev.get("market"), "et": ev.get("event_type_l2"),
            "lbl": lbl, "car": car,
            "op": op, "np": np_, "op_g": op_g, "np_g": np_g,
            "ok_old": ok_old, "ok_new": ok_new,
            "analyzer": aly, "rout_dir": rd,
        })
        car_s = f"{car*100:+.2f}" if isinstance(car, (int, float)) else str(car)
        print(f"{idx+1:2d} {ev.get('market','?'):>2} {(ev.get('event_type_l2') or ''):<10} "
              f"{car_s:>8} {lbl:>5} │ "
              f"{op['direction']:>5} {op['confidence']:0.2f} {op_g:>5} {ok_old:>3} │ "
              f"{np_['direction']:>5} {np_['confidence']:0.2f} {np_g:>5} {ok_new:>3} │ "
              f"{rd:>5} {aly:<20} {title}")

    # ===== Summary =====
    gate = 0.50
    print("\n" + "=" * 140)
    print(f"{'Gate':<6} {'系统':<12} {'严格ACC':>10} {'Wilson下界':>10} {'Wilson上界':>10} │ "
          f"{'非中性命中':>8} {'非中性总数':>10} {'非中性ACC':>10} │ Neutral")
    print("-" * 140)

    for name, preds in [("旧管线", old_preds), ("新管线", new_preds)]:
        if not preds:
            continue
        k, n, nn_k, nn_n = strict_acc(preds, labels, gate, valid_ids)
        lo, hi = wilson_ci(k, n)
        neu_count = sum(1 for e in valid_ids
                        if gate_direction(preds[e]["direction"], preds[e]["confidence"], gate) == "neutral"
                        and labels[e]["label_t3"] != "neutral")
        acc = k / n if n else 0
        nn_acc = nn_k / nn_n if nn_n else 0
        print(f"G={gate:<3.2f} {name:<12} {k}/{n}={acc*100:5.1f}%   [{lo*100:5.1f}%, {hi*100:5.1f}%] │ "
              f"{nn_k:>5}/{nn_n:<5}   {nn_acc*100:5.1f}%       │ {neu_count}")

    # 路由覆盖率
    routed = sum(1 for e in valid_ids if analyzer_called.get(e))
    print(f"\n[路由覆盖率] {routed}/{len(valid_ids)} = {routed/len(valid_ids)*100:.1f}%" if valid_ids else "")


if __name__ == "__main__":
    main()
