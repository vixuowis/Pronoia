"""build_rlvr_train_dataset.py — Pronoia-RLVR §4.1 训练数据集构建：12 层分层 1:5 放大 5000 条。

策略：
  1) 分析评估集 events_cn_us_1000_v1.jsonl 的 Market × EventTypeL2 分层分布；
  2) 按 1:5 比例为每一层分配配额（1000→5000）；
  3) 从既有 events 数据源（backtesting/*.jsonl + generate_datasets 历史生成路径）
     拉取 2024-01 ~ 2026-06 时间窗内的样本，按层配额填充；
  4) 严格去重（同 (symbol, event_date, event_type_l2) 记为重复，保留 1 条）；
  5) 与评估集交集严格为 0（按 event_id 排除）。

输出：
    backtesting/rlvr/data/rlvr_train_v1_5000/
        ├── events.jsonl         # 5000 条训练事件
        ├── labels.jsonl         # 空壳（后续由 labeller CLI 填）
        ├── quota_report.json    # 12 层配额完成度报告

用法（第一步，events 生成）：
    python3 backtesting/rlvr/scripts/build_rlvr_train_dataset.py \
        --eval-events backtesting/events_cn_us_1000_v1.jsonl \
        --out-dir     backtesting/rlvr/data/rlvr_train_v1_5000 \
        --target-size 5000

后续步骤（需要 labeller 和 RER 增强）：
    · 调用 labeller.py --events events.jsonl --out labels.jsonl
    · 调用 build_rer_metrics.py --labels-in labels.jsonl --labels-out labels.jsonl
    · 调用 build_volume_features.py --events events.jsonl --out events.jsonl
    · 调用 quant_selfcheck.py 做 5 项定量自检
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

# scene_match 本地相对导入
import sys
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from scene_match import SCENE_MATCH, ALL_SCENE_KEYS  # noqa: E402


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists(): return []
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: continue
    return rows


def _dedup_key(e: dict) -> tuple:
    """(symbol, YYYY-MM-DD, event_type_l2) — 同日同类型公告视为重复。"""
    sym = str(e.get("symbol") or "").strip()
    et = str(e.get("event_time") or e.get("event_date") or "")[:10]
    el2 = str(e.get("event_type_l2") or "").strip()
    return (sym, et, el2)


def _is_in_time_window(e: dict, start_ym: str, end_ym: str) -> bool:
    ym = (str(e.get("event_time") or e.get("event_date") or "")[:7])
    return bool(ym) and start_ym <= ym <= end_ym


def analyze_eval_distribution(eval_events: list[dict]) -> dict:
    """返回 { (market, et_l2): count }，无 key 的层补 0。"""
    dist = Counter()
    for e in eval_events:
        key = (str(e.get("market") or "").upper(), str(e.get("event_type_l2") or ""))
        dist[key] += 1
    out = {}
    for k in ALL_SCENE_KEYS:
        out[k] = dist.get(k, 0)
    return out


def gather_source_candidates(source_globs: Iterable[Path],
                              exclude_event_ids: set[str],
                              start_ym: str, end_ym: str) -> dict[tuple, list[dict]]:
    """从所有 source jsonl 中拉候选样本，按 (market, et_l2) 分桶。
    严格过滤：时间窗内 + 不在评估集 + 基础字段齐全。"""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    seen_dups: set[tuple] = set()  # 全局去重 key

    for src in source_globs:
        rows = _read_jsonl(src)
        for e in rows:
            eid = str(e.get("event_id") or "")
            if eid and eid in exclude_event_ids:
                continue
            if not _is_in_time_window(e, start_ym, end_ym):
                continue
            mkt = str(e.get("market") or "").upper()
            el2 = str(e.get("event_type_l2") or "")
            if (mkt, el2) not in SCENE_MATCH:
                continue
            sym = str(e.get("symbol") or "").strip()
            if not sym:
                continue
            dk = _dedup_key(e)
            if dk in seen_dups:
                continue
            seen_dups.add(dk)
            buckets[(mkt, el2)].append(e)
    return buckets


def select_by_quota(buckets: dict[tuple, list[dict]],
                     quota: dict[tuple, int],
                     target_total: int) -> tuple[list[dict], dict]:
    """按层配额抽样本。配额不够就跨层借（同 Market 内借），并记录完成度。"""
    selected: list[dict] = []
    quota_remain = dict(quota)
    report: dict[str, dict] = {}

    # ---- 第一轮：严格按层配额抽 ----
    for key, q in quota.items():
        pool = list(buckets.get(key, []))
        take = min(q, len(pool))
        # 按事件日期倒序（新样本优先，训练分布更贴近评估集尾部）
        pool.sort(key=lambda e: str(e.get("event_time") or e.get("event_date") or ""), reverse=True)
        picked = pool[:take]
        selected.extend(picked)
        quota_remain[key] = q - take
        report[f"{key[0]}|{key[1]}"] = {
            "quota": q, "picked": take,
            "pool_available": len(pool),
            "borrowed": 0,
        }

    # ---- 第二轮：跨层借（同 Market 内优先借其他 EventType 的余量）----
    total_need = sum(quota_remain.values())
    borrowed_total = 0
    if total_need > 0:
        # 构建余量池：每层没被抽走的按 Market 归集
        remain_by_market: dict[str, list[dict]] = defaultdict(list)
        for key, pool in buckets.items():
            mkt = key[0]
            already = quota[key] - quota_remain[key]  # 第一轮已抽走
            leftover = pool[already:] if len(pool) > already else []
            remain_by_market[mkt].extend(leftover)

        for key, need in quota_remain.items():
            if need <= 0: continue
            mkt = key[0]
            pool = remain_by_market.get(mkt, [])
            # 借的时候也要全局去重（dedup key 不在已选中）
            selected_dedup = {_dedup_key(e) for e in selected}
            candidates = [e for e in pool if _dedup_key(e) not in selected_dedup]
            take = min(need, len(candidates))
            selected.extend(candidates[:take])
            borrowed_total += take
            report[f"{key[0]}|{key[1]}"] = report[f"{key[0]}|{key[1]}"] or {}
            report[f"{key[0]}|{key[1]}"] = {
                **report[f"{key[0]}|{key[1]}"],
                "borrowed": take,
                "picked": report[f"{key[0]}|{key[1]}"] ["picked"] + take,
            }
            quota_remain[key] = need - take
            remain_by_market[mkt] = candidates[take:]

    # ---- 第三轮：仍不足 → 跨 Market 借（所有剩余池全局借）----
    remain_global = 0
    for need in quota_remain.values():
        remain_global += need
    if remain_global > 0:
        global_pool: list[dict] = []
        for pool in buckets.values():
            global_pool.extend(pool)
        selected_dedup = {_dedup_key(e) for e in selected}
        candidates = [e for e in global_pool if _dedup_key(e) not in selected_dedup]
        # 全局按日期倒序借
        candidates.sort(key=lambda e: str(e.get("event_time") or e.get("event_date") or ""), reverse=True)
        take = min(remain_global, len(candidates))
        selected.extend(candidates[:take])
        borrowed_total += take
        # 报告里补一条全局借
        report["_GLOBAL_BORROW"] = {"picked": take, "note": "跨 Market 兜底借用"}

    final_n = len(selected)
    # 如最终多于 target_total（因四舍五入），按 event_time 排序后砍掉尾部较旧的
    if final_n > target_total:
        selected.sort(key=lambda e: str(e.get("event_time") or e.get("event_date") or ""), reverse=True)
        selected = selected[:target_total]
    report["_SUMMARY"] = {
        "target": target_total,
        "final_selected": len(selected),
        "total_borrowed": borrowed_total,
    }
    return selected, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-events", required=True,
                    help="评估集 events.jsonl 路径（用于分析分布 + 去重排除）")
    ap.add_argument("--out-dir", required=True,
                    help="训练集输出目录（events.jsonl / labels.jsonl（空壳） / quota_report.json）")
    ap.add_argument("--target-size", type=int, default=5000, help="训练集目标条数（默认 5000）")
    ap.add_argument("--scale", type=int, default=5,
                    help="评估集 → 训练集 分层放大倍数（默认 5 倍 = 1000 → 5000）")
    ap.add_argument("--start-ym", default="2024-01", help="训练样本时间窗起（YYYY-MM，含）")
    ap.add_argument("--end-ym",   default="2026-06", help="训练样本时间窗止（YYYY-MM，含）")
    ap.add_argument("--source-glob", default=None,
                    help="可选：额外源 events.jsonl glob（如 /data/dumps/*.jsonl）；多个用 : 分隔")
    args = ap.parse_args()

    eval_events = _read_jsonl(Path(args.eval_events))
    eval_ids = {str(e.get("event_id") or "") for e in eval_events if e.get("event_id")}
    print(f"[INFO] 评估集 {len(eval_events)} 条，{len(eval_ids)} 个 event_id 排除")

    # ---- 配额计算 ----
    eval_dist = analyze_eval_distribution(eval_events)
    quota: dict[tuple, int] = {}
    for k, v in eval_dist.items():
        quota[k] = v * args.scale
    sum_quota = sum(quota.values())
    print(f"[INFO] 12 层配额合计 {sum_quota}（scale={args.scale}），目标 {args.target_size}")
    if sum_quota != args.target_size:
        # 四舍五入修正：把差额补到最大的层（CN 并购/财报）
        diff = args.target_size - sum_quota
        # 找最大的层
        max_key = max(quota.items(), key=lambda x: x[1])[0]
        quota[max_key] += diff
        print(f"[INFO] 配额修正：差额 {diff:+d} 条 → 加到 {max_key}，新合计 {sum(quota.values())}")

    # ---- 源搜索：workspace/backtesting/*.jsonl + scripts/ 下历史产物 + --source-glob ----
    workspace = Path(__file__).resolve().parent.parent.parent.parent  # /workspace
    source_paths: list[Path] = []
    for pat in [
        "backtesting/*.jsonl",
        "backend/tests/golden/*.jsonl",
        "scripts/*.jsonl",
    ]:
        source_paths.extend(sorted(workspace.glob(pat)))
    if args.source_glob:
        for pat in args.source_glob.split(":"):
            pat = pat.strip()
            if pat:
                # 支持 glob 和目录
                p = Path(pat)
                if p.is_dir():
                    source_paths.extend(sorted(p.glob("**/*.jsonl")))
                elif "*" in pat or "?" in pat:
                    source_paths.extend(sorted(Path(p.parent).glob(p.name)))
                elif p.exists():
                    source_paths.append(p)
    # 去重路径
    source_paths = list(dict.fromkeys(p.resolve() for p in source_paths if p.exists()))
    print(f"[INFO] 源 events 文件 {len(source_paths)} 个：")
    for p in source_paths[:8]:
        print(f"        · {p}")
    if len(source_paths) > 8:
        print(f"        · ... 省略 {len(source_paths)-8} 个")

    # ---- 拉候选池 ----
    buckets = gather_source_candidates(source_paths, eval_ids,
                                        args.start_ym, args.end_ym)
    print(f"[INFO] 候选池（12 层内）样本：",
          {f"{k[0]}|{k[1]}": len(v) for k, v in sorted(buckets.items(), key=lambda x: -len(x[1]))})

    # ---- 抽样本 ----
    selected, report = select_by_quota(buckets, quota, args.target_size)

    # ---- 写出 ----
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ev_path = out_dir / "events.jsonl"
    with open(ev_path, "w", encoding="utf-8") as f:
        for e in selected:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # labels 空壳：写 event_id 索引，等 labeller 补字段
    lb_path = out_dir / "labels.jsonl"
    with open(lb_path, "w", encoding="utf-8") as f:
        for e in selected:
            f.write(json.dumps({
                "event_id": e.get("event_id"),
                "market":   e.get("market"),
                "symbol":   e.get("symbol"),
                "event_time": e.get("event_time") or e.get("event_date"),
                "event_type_l2": e.get("event_type_l2"),
                "_needs_label": True,
            }, ensure_ascii=False) + "\n")

    rep_path = out_dir / "quota_report.json"
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump({
            "quota_input": {f"{k[0]}|{k[1]}": v for k, v in quota.items()},
            "selection_report": report,
            "eval_distribution": {f"{k[0]}|{k[1]}": v for k, v in eval_dist.items()},
            "meta": {
                "target_size": args.target_size,
                "scale": args.scale,
                "start_ym": args.start_ym,
                "end_ym": args.end_ym,
                "source_files_count": len(source_paths),
                "source_files": [str(p) for p in source_paths],
            },
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] 写出 {len(selected)} 条 → {ev_path}")
    print(f"       labels 空壳  → {lb_path}")
    print(f"       配额报告    → {rep_path}")
    print(json.dumps(report.get("_SUMMARY", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
