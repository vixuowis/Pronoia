"""split_rlvr_5fold.py — Pronoia-RLVR §4.3 训练集 4 维分层 5-Fold 切分。

4 维 stratification keys（从 events + labels 综合得到）：
  K1: market              — CN / US
  K2: event_type_l2       — 六大事件类型
  K3: primary_horizon     — t3 / t7 / t15（由 scene_match 决定）
  K4: label_direction_bin — up/down/neutral（primary horizon label，来自 labels）

原则：
  · 不允许同一 symbol 在相邻 fold 中同时出现（防 data leakage：同公司时间接近）；
  · 同 (K1,K2,K3,K4) 桶样本按 1:1:1:1:1 尽量均分到 5 个 fold；
  · 写出 5 份 events_fold_{0..4}.jsonl + labels_fold_{0..4}.jsonl。

用法：
    python3 backtesting/rlvr/scripts/split_rlvr_5fold.py \
        --events backtesting/rlvr/data/rlvr_train_v1_5000/events.jsonl \
        --labels backtesting/rlvr/data/rlvr_train_v1_5000/labels.jsonl \
        --out-dir backtesting/rlvr/data/rlvr_train_v1_5000/folds
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import sys
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from scene_match import primary_horizon_for  # noqa: E402


NUM_FOLDS = 5


def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: continue
    return rows


def _direction_bin(lb: dict, primary_h: str) -> str:
    """从 label 拿 primary horizon 的方向（up/down/neutral）；拿不到用 car_avg_all 兜底。"""
    key = f"label_{primary_h}"
    v = lb.get(key)
    if v in ("up", "down", "neutral"):
        return v
    key2 = "label_avg_all"
    v2 = lb.get(key2)
    if v2 in ("up", "down", "neutral"):
        return v2
    # 再兜底：car_primary 符号
    car = lb.get(f"car_{primary_h}")
    if isinstance(car, (int, float)):
        if car > 0.01: return "up"
        if car < -0.01: return "down"
    return "neutral"


def build_stratified_folds(events: list[dict], labels_map: dict[str, dict]) -> list[list[int]]:
    """返回 NUM_FOLDS 个 list，每个 list 是 events 的 indices（in-place 顺序一致）。"""
    # 1) 按 4 维分桶
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, e in enumerate(events):
        mkt = str(e.get("market") or "").upper()
        el2 = str(e.get("event_type_l2") or "")
        ph  = primary_horizon_for(mkt, el2)
        eid = str(e.get("event_id") or "")
        lb  = labels_map.get(eid, {})
        direction = _direction_bin(lb, ph)
        k = (mkt, el2, ph, direction)
        buckets[k].append(i)

    # 2) 每个桶内按 symbol 排序后，轮询分配到 fold（= 尽量把同 symbol 放同一 fold）
    folds: list[list[int]] = [[] for _ in range(NUM_FOLDS)]
    fold_sizes = [0] * NUM_FOLDS

    for key, idxs in sorted(buckets.items()):
        # 按 symbol 聚类 + 事件时间排序
        idxs_sorted = sorted(
            idxs,
            key=lambda i: (
                str(events[i].get("symbol") or ""),
                str(events[i].get("event_time") or events[i].get("event_date") or ""),
            ),
        )
        # 记录每个 symbol 的目标 fold（尽量锁定，避免同 symbol 跨 fold）
        symbol_fold: dict[str, int] = {}
        # 先统计该桶里每个 symbol 的样本数，大的优先分配
        sym_idxs: dict[str, list[int]] = defaultdict(list)
        for i in idxs_sorted:
            sym = str(events[i].get("symbol") or "")
            sym_idxs[sym].append(i)
        sym_order = sorted(sym_idxs.keys(), key=lambda s: -len(sym_idxs[s]))

        for sym in sym_order:
            sis = sym_idxs[sym]
            # 选当前最小的 fold
            target_fold = min(range(NUM_FOLDS), key=lambda f: fold_sizes[f])
            symbol_fold[sym] = target_fold
            for i in sis:
                folds[target_fold].append(i)
                fold_sizes[target_fold] += 1

    print(f"[INFO] Fold 大小：{fold_sizes} （期望 ~{len(events) // NUM_FOLDS}）")
    return folds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    events = _read_jsonl(Path(args.events))
    labels = _read_jsonl(Path(args.labels))
    labels_map = {str(lb.get("event_id") or ""): lb for lb in labels}
    print(f"[INFO] events={len(events)}  labels={len(labels)}  matched={sum(1 for e in events if e.get('event_id') in labels_map)}")

    folds = build_stratified_folds(events, labels_map)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 写 fold 文件
    for fi in range(NUM_FOLDS):
        ev_fold = [events[i] for i in folds[fi]]
        lb_fold = [labels_map.get(str(e.get("event_id") or ""), {}) for e in ev_fold]
        ev_path = out_dir / f"events_fold_{fi}.jsonl"
        lb_path = out_dir / f"labels_fold_{fi}.jsonl"
        with open(ev_path, "w", encoding="utf-8") as f:
            for e in ev_fold:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(lb_path, "w", encoding="utf-8") as f:
            for lb in lb_fold:
                f.write(json.dumps(lb, ensure_ascii=False) + "\n")
        print(f"  [FOLD {fi}] events={len(ev_fold)}  → {ev_path.name}")

    # 写一份切分索引 JSON（便于训练脚本读取）
    idx_path = out_dir / "split_index.json"
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump({
            "num_folds": NUM_FOLDS,
            "fold_event_ids": {
                str(fi): [str(events[i].get("event_id") or "") for i in folds[fi]]
                for fi in range(NUM_FOLDS)
            },
            "fold_sizes": {str(fi): len(folds[fi]) for fi in range(NUM_FOLDS)},
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] 切分索引 → {idx_path}")


if __name__ == "__main__":
    main()
