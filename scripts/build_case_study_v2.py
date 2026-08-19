"""构建 case_study_v2 20 条新事件（与 case_study_v1 20 条不重叠）。

策略：
  1. 从 1000 条回测事件池里挑出未在 v1 使用过的 980 条
  2. 只挑有 Oracle 标签 + 有 trajectory ckpt（含旧管线ACC结果）的
  3. 按 (label_dir × market × event_type_l2) 分层抽样 20 条（10 正 + 10 负）
  4. 偏好以下我们已知需修复的场景：
     - CN Earnings 业绩说明会预告类（3条反向案例模式）
     - CN 公司指引/增减持 被误标类（公司指引上调/下调）
     - US M&A 收购方 Rule 425
输出：
  data/events_case_study_v2.jsonl
  data/labels_case_study_v2.jsonl
  data/case_study_v2_meta.json  （含旧管线 direction/confidence）
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CKPT_DIR = DATA / "_trajectory_ckpt_tf1000_c4_20260816"
EVENTS_PATH = DATA / "events_phase1_backtestable_balanced_v9_1000.jsonl"
LABELS_PATH = DATA / "labels_phase1_balanced_v9_1000.jsonl"
V1_META = DATA / "case_study_20_meta.json"

OUT_EVENTS = DATA / "events_case_study_v2.jsonl"
OUT_LABELS = DATA / "labels_case_study_v2.jsonl"
OUT_META = DATA / "case_study_v2_meta.json"


def load_jsonl(p: Path) -> list[dict]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    random.seed(20260819)

    events_list = load_jsonl(EVENTS_PATH)
    labels_list = load_jsonl(LABELS_PATH)
    events = {e["event_id"]: e for e in events_list}
    labels = {l["event_id"]: l for l in labels_list}

    # v1 已用的 20 个 id 排除
    v1_ids = set()
    if V1_META.exists():
        try:
            v1 = json.loads(V1_META.read_text(encoding="utf-8"))
            v1_ids = set(v1.keys())
        except Exception:
            pass
    print(f"[v1 排除] {len(v1_ids)} 条")

    # 旧预测结果（从 ckpt 提取）
    old_preds: dict[str, dict] = {}
    for ckpt_file in sorted(CKPT_DIR.glob("*.json")):
        try:
            ck = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        eid = ck.get("event_id") or ckpt_file.stem
        sex = ck.get("structured_extract") or {}
        pred = ck.get("prediction") or {}
        direction = pred.get("pred_direction") or sex.get("direction") or "neutral"
        confidence = pred.get("confidence") or sex.get("confidence") or 0.5
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        old_preds[eid] = {"direction": direction, "confidence": round(confidence, 3)}

    print(f"[候选池] events={len(events)}, labels={len(labels)}, old_preds={len(old_preds)}")

    # 过滤：有 label + 有 old_pred + 不在 v1
    valid: list[dict] = []
    for eid, ev in events.items():
        if eid in v1_ids:
            continue
        if eid not in labels or eid not in old_preds:
            continue
        lab = labels[eid]
        # Oracle label_t3：从 label 中直接取（标签管线已打好）
        label_dir = lab.get("label_t3")
        if label_dir not in ("up", "down"):
            continue  # Oracle 中性的不抽样（难评估）
        valid.append({
            "event_id": eid,
            "event": ev,
            "label": lab,
            "label_dir": label_dir,
            "old": old_preds[eid],
        })
    print(f"[有效] 非中性 Oracle + 有 ckpt = {len(valid)}")

    # 分层桶: (label_dir, market, event_type_l2)
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for v in valid:
        key = (v["label_dir"], v["event"].get("market"), v["event"].get("event_type_l2"))
        buckets[key].append(v)
    print(f"[桶数] {len(buckets)}")
    for k, lst in sorted(buckets.items(), key=lambda x: -len(x[1])):
        print(f"  {k}: {len(lst)}")

    # 采样目标：up=10, down=10，市场/类型尽量广
    target_up = 10
    target_down = 10

    picked: list[dict] = []

    def pick_from_bucket(label_dir, market, et, n):
        b = buckets.get((label_dir, market, et), [])
        random.shuffle(b)
        take = b[:n]
        for t in take:
            buckets[(label_dir, market, et)].remove(t)
        picked.extend(take)

    # up 类：覆盖 CN M&A, CN Earnings, CN 增减持, US M&A, US Earnings, CN 公司指引
    pick_from_bucket("up", "CN", "并购/分拆/再融资", 3)
    pick_from_bucket("up", "CN", "财报超预期/不及预期", 2)
    pick_from_bucket("up", "CN", "增减持", 1)
    pick_from_bucket("up", "CN", "公司指引上调/下调", 1)
    pick_from_bucket("up", "US", "并购/分拆/再融资", 2)
    pick_from_bucket("up", "US", "财报超预期/不及预期", 1)

    # down 类：尽量覆盖需修复场景
    pick_from_bucket("down", "CN", "并购/分拆/再融资", 2)
    pick_from_bucket("down", "CN", "财报超预期/不及预期", 3)  # 含业绩说明会预告场景
    pick_from_bucket("down", "CN", "增减持", 1)
    pick_from_bucket("down", "CN", "公司指引上调/下调", 1)
    pick_from_bucket("down", "US", "并购/分拆/再融资", 2)   # Rule 425
    pick_from_bucket("down", "US", "财报超预期/不及预期", 1)

    # 如果不够，用任何剩余 up/down 补齐
    ups = [p for p in picked if p["label_dir"] == "up"]
    downs = [p for p in picked if p["label_dir"] == "down"]

    # 补齐 up
    all_remaining_up = []
    for (ld, m, et), lst in buckets.items():
        if ld == "up":
            all_remaining_up.extend(lst)
    random.shuffle(all_remaining_up)
    while len([p for p in picked if p["label_dir"] == "up"]) < target_up and all_remaining_up:
        picked.append(all_remaining_up.pop(0))

    # 补齐 down
    all_remaining_dn = []
    for (ld, m, et), lst in buckets.items():
        if ld == "down":
            all_remaining_dn.extend(lst)
    random.shuffle(all_remaining_dn)
    while len([p for p in picked if p["label_dir"] == "down"]) < target_down and all_remaining_dn:
        picked.append(all_remaining_dn.pop(0))

    ups = [p for p in picked if p["label_dir"] == "up"]
    downs = [p for p in picked if p["label_dir"] == "down"]
    print(f"[抽样结果] up={len(ups)}, down={len(downs)}, total={len(picked)}")

    # 按 market × type 汇总
    scen = defaultdict(int)
    for p in picked:
        scen[(p["label_dir"], p["event"].get("market"), p["event"].get("event_type_l2"))] += 1
    for k, n in sorted(scen.items()):
        print(f"  {k}: {n}")

    # 写文件
    picked_sorted = sorted(picked, key=lambda x: x["event_id"])
    with open(OUT_EVENTS, "w", encoding="utf-8") as fe, \
         open(OUT_LABELS, "w", encoding="utf-8") as fl:
        meta = {}
        for p in picked_sorted:
            fe.write(json.dumps(p["event"], ensure_ascii=False) + "\n")
            fl.write(json.dumps(p["label"], ensure_ascii=False) + "\n")
            meta[p["event_id"]] = {
                "label_dir": p["label_dir"],
                "car_t3": p["label"].get("car_t3"),
                "market": p["event"].get("market"),
                "event_type_l2": p["event"].get("event_type_l2"),
                "old_direction": p["old"]["direction"],
                "old_confidence": p["old"]["confidence"],
                "title": p["event"].get("title"),
            }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n输出: {OUT_EVENTS} ({sum(1 for _ in open(OUT_EVENTS))} 行)")
    print(f"      {OUT_LABELS}")
    print(f"      {OUT_META}")


if __name__ == "__main__":
    main()
