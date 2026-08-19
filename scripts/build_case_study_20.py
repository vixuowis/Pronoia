"""构建 20 条 case study 小批量数据集（10 正例+10 负例，覆盖各场景）。

输入：1000 条回测的 trajectory ckpt + events + labels
输出：
  data/events_case_study_20.jsonl  —— 20 条事件
  data/labels_case_study_20.jsonl  —— 对应 Oracle 标签
  data/case_study_20_meta.json     —— 每条的旧预测结果（用于对比）
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CKPT_DIR = DATA / "_trajectory_ckpt_tf1000_c4_20260816"
EVENTS_PATH = DATA / "events_phase1_backtestable_balanced_v9_1000.jsonl"
LABELS_PATH = DATA / "labels_phase1_balanced_v9_1000.jsonl"

OUT_EVENTS = DATA / "events_case_study_20.jsonl"
OUT_LABELS = DATA / "labels_case_study_20.jsonl"
OUT_META = DATA / "case_study_20_meta.json"


def load_jsonl(p: Path) -> list[dict]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    events_list = load_jsonl(EVENTS_PATH)
    labels_list = load_jsonl(LABELS_PATH)
    events = {e["event_id"]: e for e in events_list}
    labels = {l["event_id"]: l for l in labels_list}

    # 从 trajectory ckpt 提取旧 prediction（G=0.50 gate）
    # 旧 ckpt schema: direction/confidence 在 structured_extract 里
    old_preds: dict[str, dict] = {}
    for ckpt_file in sorted(CKPT_DIR.glob("*.json")):
        try:
            ck = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        eid = ck.get("event_id") or ckpt_file.stem
        # 先尝试 structured_extract（1000 条旧管线格式）
        sex = ck.get("structured_extract") or {}
        pred = ck.get("prediction") or {}
        direction = sex.get("direction") or pred.get("pred_direction") or pred.get("direction")
        confidence = float(sex.get("confidence", 0) or pred.get("confidence", 0) or 0)
        if not direction:
            continue
        # G=0.50 gate
        if confidence < 0.50:
            direction = "neutral"
        ttypes = {t.get("type") for t in (ck.get("team_final_state", {}).get("tool_trace") or [])}
        old_preds[eid] = {
            "direction": direction,
            "confidence": confidence,
            "has_signal_routing": "signal_routing" in ttypes,
        }

    print(f"events={len(events)}, labels={len(labels)}, old_preds={len(old_preds)}")

    # 建联合表
    joined = []
    for eid, e in events.items():
        if eid not in labels or eid not in old_preds:
            continue
        lbl = labels[eid]
        op = old_preds[eid]
        correct = op["direction"] == lbl["label_t3"]
        car_abs = abs(lbl.get("car_t3", 0))
        joined.append({
            "event_id": eid,
            "market": e.get("market", "?"),
            "event_type_l2": e.get("event_type_l2", "?"),
            "label": lbl["label_t3"],
            "car_t3": lbl.get("car_t3", 0),
            "car_abs": car_abs,
            "old_direction": op["direction"],
            "old_confidence": op["confidence"],
            "old_correct": correct,
            "title": e.get("title", ""),
            "has_old_signal_routing": op["has_signal_routing"],
        })
    print(f"joined valid={len(joined)}")

    # 分层抽样策略：
    #   按 (market, event_type_l2) 分组，每组内取 correct=True × 1 + correct=False × 1
    #   优先选 |CAR| ≥ 50bps（非噪声），再兼顾 car 大小
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for j in joined:
        key = (j["market"], j["event_type_l2"])
        groups[key].append(j)

    selected: list[dict] = []
    random.seed(42)

    for key, items in sorted(groups.items()):
        # 剔除纯噪声样本（|CAR|<20bps 几乎无法判断）
        items = [x for x in items if x["car_abs"] >= 0.002]
        if not items:
            continue

        positives = [x for x in items if x["old_correct"]]
        negatives = [x for x in items if not x["old_correct"]]

        # 优先选 MED 幅度（1-3%），其次 LARGE，其次 SMALL
        def bucket_score(j: dict) -> tuple:
            a = j["car_abs"]
            if 0.01 <= a < 0.03:
                return (0, -a)  # MED 优先，幅度越大越好
            elif a >= 0.03:
                return (1, -a)  # LARGE 其次
            else:
                return (2, -a)  # SMALL

        positives.sort(key=bucket_score)
        negatives.sort(key=bucket_score)

        # 每组至少 1 正 1 负（不够就补）
        picked = []
        if positives:
            picked.append(positives[0])
        if negatives:
            picked.append(negatives[0])

        for p in picked:
            if p["event_id"] not in {x["event_id"] for x in selected}:
                selected.append(p)

    print(f"分层抽样初步得到 {len(selected)} 条")

    # 如果不够 20，用剩余高价值样本补足（优先负例，其次 MED 幅度）
    if len(selected) < 20:
        used = {x["event_id"] for x in selected}
        remaining = [x for x in joined if x["event_id"] not in used and x["car_abs"] >= 0.002]
        # 排序：先负例 → 再 MED → 再 LARGE → 大 car 优先
        def priority(j: dict) -> tuple:
            a = j["car_abs"]
            med = 1 if (0.01 <= a < 0.03) else 0
            large = 1 if a >= 0.03 else 0
            return (0 if not j["old_correct"] else 1,  # 负例优先
                    -med, -large, -a)
        remaining.sort(key=priority)
        for j in remaining:
            if len(selected) >= 20:
                break
            selected.append(j)

    print(f"补足后共 {len(selected)} 条")

    # 统计分布
    from collections import Counter
    dist_correct = Counter(x["old_correct"] for x in selected)
    dist_mkt = Counter((x["market"], x["event_type_l2"]) for x in selected)
    dist_label = Counter(x["label"] for x in selected)
    print(f"\n====== 抽样分布 ======")
    print(f"正/负（旧管线正确/错误）：{dist_correct}")
    print(f"标签分布：{dist_label}")
    for k, v in sorted(dist_mkt.items()):
        print(f"  {k}: {v}")

    # 写出
    selected_ids = [x["event_id"] for x in selected]
    with open(OUT_EVENTS, "w", encoding="utf-8") as f:
        for eid in selected_ids:
            f.write(json.dumps(events[eid], ensure_ascii=False) + "\n")
    with open(OUT_LABELS, "w", encoding="utf-8") as f:
        for eid in selected_ids:
            f.write(json.dumps(labels[eid], ensure_ascii=False) + "\n")

    meta = {x["event_id"]: {k: v for k, v in x.items() if k != "event_id"} for x in selected}
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已写出：")
    print(f"  events → {OUT_EVENTS}")
    print(f"  labels → {OUT_LABELS}")
    print(f"  meta   → {OUT_META}")

    # 打印选中列表供人眼检查
    print("\n====== 20 条事件清单 ======")
    for i, x in enumerate(selected, 1):
        sign = "✓" if x["old_correct"] else "✗"
        short_title = x["title"][:40]
        print(f"{i:2d}.{sign} {x['market']}/{x['event_type_l2'][:8]:8s} "
              f"lbl={x['label']:7s} CAR={x['car_t3']:+.4f} "
              f"old={x['old_direction']:7s}@{x['old_confidence']:.2f} "
              f"| {short_title}…")


if __name__ == "__main__":
    main()
