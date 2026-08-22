"""repair_train_dataset.py — 修复训练集 Q2/Q5 自检失败项（Pronoia-RLVR v1）。

问题定位（selfcheck_train_v1.json）：
  · Q2 FAIL：574 条 horizons 不完整（485 缺 t60 / 55 缺 t30+t60 / 34 无行情），
    主因 2026-05~07 事件的前瞻窗口超过数据可用日期（今天 2026-08-21）。
  · Q5 FAIL：17 条内部重复（key = symbol+date+event_type_l2）。

修复策略（保持 12 层配额不变 → Q1 仍为 0）：
  1. 找出坏行：内部重复（保留首条）+ horizons 不完整；
  2. 每条坏行生成同层（Market × EventTypeL2）替换：新 symbol + 新日期 ∈ [2024-01-02, 2026-05-10]
     （日期封顶保证 t60 = 60 交易日前瞻窗口可得），避开现有 (sym,date,etl2) 键与评估集 (sym,date)；
  3. 仅对替换行调 labeller 拉真实 K 线 → 合并回 5000 条；
  4. 重跑 build_ret_metrics（幂等）→ 输出待复检。

用法：
  python3 repair_train_dataset.py --base backtesting/rlvr/data/rlvr_train_v1_5000 \
      --eval-events backtesting/events_cn_us_1000_v1.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bootstrap_train_events_from_eval import (  # noqa: E402
    CN_STOCK_POOL, US_STOCK_POOL, _replace_names, _add_event_variant_tag,
)

# t60 需要 60 交易日（≈ 84 自然日）前瞻数据；今天 2026-08-21 → 事件日封顶 2026-05-10
DATE_MAX = dt.date(2026, 5, 10)
DATE_MIN = dt.date(2024, 1, 2)
PRIMARY_HORIZONS = ["t3", "t7", "t15", "t30", "t60"]


def _proxy_patch() -> None:
    """沙箱出网必须走本地代理（akshare/requests 不自动读环境变量的场景）。"""
    proxies = {"http": "http://127.0.0.1:18080", "https": "http://127.0.0.1:18080"}
    os.environ.setdefault("HTTP_PROXY", proxies["http"])
    os.environ.setdefault("HTTPS_PROXY", proxies["https"])
    import requests
    orig_get, orig_post = requests.get, requests.post
    requests.get = functools.partial(orig_get, proxies=proxies, timeout=30)
    requests.post = functools.partial(orig_post, proxies=proxies, timeout=30)


def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def _bad_symbols(labels: list[dict], ev_map: dict[str, dict]) -> set[str]:
    """完全没有 CAR 数据的 symbol（行情源拉不到，替换时避开）。"""
    bad = set()
    for lb in labels:
        if all(lb.get(f"car_{h}") is None for h in PRIMARY_HORIZONS):
            e = ev_map.get(lb.get("event_id"))
            if e:
                bad.add(str(e.get("symbol")))
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="训练集目录（含 events.jsonl / labels.jsonl）")
    ap.add_argument("--eval-events", required=True, help="评估集 events.jsonl（排除池）")
    ap.add_argument("--seed", type=int, default=20260823)
    args = ap.parse_args()
    random.seed(args.seed)

    base = Path(args.base)
    ev_path = base / "events.jsonl"
    lb_path = base / "labels.jsonl"

    events = _read_jsonl(ev_path)
    labels = _read_jsonl(lb_path)
    lb_map = {lb["event_id"]: lb for lb in labels}
    ev_map = {e["event_id"]: e for e in events}
    print(f"[LOAD] events={len(events)} labels={len(labels)}")

    eval_events = _read_jsonl(Path(args.eval_events))
    eval_pairs = {
        (str(e.get("symbol")), str(e.get("event_time") or e.get("event_date"))[:10])
        for e in eval_events
    }

    # ---- 1) 定位坏行 ----
    # Q5 重复：保留每个 (sym, date, etl2) 首条
    seen: dict[tuple, str] = {}
    dup_ids: set[str] = set()
    for e in events:
        k = (str(e.get("symbol")), str(e.get("event_time") or e.get("event_date"))[:10],
             str(e.get("event_type_l2")))
        if k in seen:
            dup_ids.add(e["event_id"])
        else:
            seen[k] = e["event_id"]

    # Q2 不完整：horizons_complete 为假
    incomplete_ids = {
        lb["event_id"] for lb in labels
        if lb.get("event_id") in ev_map and not lb.get("horizons_complete")
    }
    # 无行情的 symbol（替换时避开）
    bad_syms = _bad_symbols(labels, ev_map) | {"BRK-B"}
    bad_ids = (dup_ids | incomplete_ids) & set(ev_map)
    print(f"[DIAG] dup={len(dup_ids)} incomplete={len(incomplete_ids)} "
          f"union_bad={len(bad_ids)} bad_symbols={sorted(bad_syms)}")

    # ---- 2) 生成同层替换 ----
    used_keys = set(seen.keys())
    replacements: list[dict] = []
    for eid in sorted(bad_ids):
        e = ev_map[eid]
        mkt = str(e.get("market")).upper()
        et_l2 = str(e.get("event_type_l2"))
        pool = [(s, n) for s, n in (CN_STOCK_POOL if mkt == "CN" else US_STOCK_POOL)
                if s not in bad_syms]
        old_sym = str(e.get("symbol"))
        old_title, old_text = str(e.get("title") or ""), str(e.get("event_text") or "")

        for _ in range(300):
            new_sym, new_name = random.choice(pool)
            new_date = DATE_MIN + dt.timedelta(
                days=random.randint(0, (DATE_MAX - DATE_MIN).days))
            k = (new_sym, new_date.isoformat(), et_l2)
            if k in used_keys:
                continue
            if (new_sym, new_date.isoformat()) in eval_pairs:
                continue
            used_keys.add(k)
            break
        else:
            print(f"[WARN] 无法为 {eid} 找到不冲突替换，保留原行")
            continue

        new_event = dict(e)  # 保留 sector_etf/benchmark/_from_seed_event 等字段
        new_event.update({
            "event_id": f"{eid}_r1",
            "symbol": new_sym,
            "event_time": new_date.isoformat(),
            "event_date": new_date.isoformat(),
            "title": _replace_names(old_title, old_sym, "", new_sym, new_name),
            "event_text": _add_event_variant_tag(
                _replace_names(old_text, old_sym, "", new_sym, new_name), et_l2, 77),
            "_variant_idx": 77,
        })
        replacements.append(new_event)

    print(f"[GEN] 生成替换 {len(replacements)} 条（同层 → 12 层配额不变）")
    if not replacements:
        print("[DONE] 无需修复")
        return

    # ---- 3) 仅对替换行拉真实 K 线 ----
    _proxy_patch()
    from app.event_backtest.labeller import (  # noqa: E402
        load_events, _compute_cars_for_events, write_labels,
    )
    tmp_events = base / "_repair_events.jsonl"
    tmp_labels = base / "_repair_labels.jsonl"
    _write_jsonl(tmp_events, replacements)
    ev_objs = load_events(str(tmp_events))  # dict → Event 对象
    cars = _compute_cars_for_events(ev_objs)
    new_rows = write_labels(ev_objs, cars, str(tmp_labels), epsilon=0.005)
    print(f"[LABEL] 替换行 labels={len(new_rows)}（cars={len(cars)}）")

    # ---- 4) 合并回 5000 ----
    keep_events = [e for e in events if e["event_id"] not in bad_ids]
    keep_labels = [lb for lb in labels if lb["event_id"] not in bad_ids]
    merged_events = keep_events + replacements
    merged_labels = keep_labels + _read_jsonl(tmp_labels)
    assert len(merged_events) == len(merged_labels), \
        f"events({len(merged_events)}) != labels({len(merged_labels)})"
    _write_jsonl(ev_path, merged_events)
    _write_jsonl(lb_path, merged_labels)
    tmp_events.unlink(missing_ok=True)
    tmp_labels.unlink(missing_ok=True)

    dist = Counter((e["market"], e["event_type_l2"]) for e in merged_events)
    print(f"[MERGED] {len(merged_events)} 条（保持 12 层：{dict(dist)}）")
    print("[NEXT] 请重跑：build_ret_metrics → quant_selfcheck（期望 Q1-Q5 全 GREEN）")


if __name__ == "__main__":
    main()
