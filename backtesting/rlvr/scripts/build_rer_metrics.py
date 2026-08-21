"""build_rer_metrics.py — Pronoia-RLVR §1.2 RER 指标生成器。

输入 labels.jsonl（由 labeller.py 生成，含 ret_tXX/car_tXX），输出增强版 labels：
  · 显式 RER 字段：rer_t3 / rer_t7 / rer_t15 / rer_t30 / rer_t60
    （= ret_tXX，即标的自身累计收益，与 CAR 构成正交维度）
  · horizons_complete：5 个 horizon 全部 ret/car 有效（非 None 且 abs<10）才为 True
  · rer_car_agree_tXX：RER 与 CAR 同号；若两者都为 0 也算一致；任一无效→False
  · rer_car_agree_5h：5 个 horizon 全部 agree 才算 True
  · long_short_agree_t3_t60：rer_t3 与 rer_t60 同号（长短 horizon 反转惩罚用）
  · long_short_agree_short：{t1,t3,t7} 三元多数与 {t15,t30,t60} 三元多数同号

用法：
    python3 backtesting/rlvr/scripts/build_rer_metrics.py \
        --labels-in  backtesting/labels_cn_us_1000_v1.jsonl \
        --labels-out backtesting/labels_cn_us_1000_v1.jsonl   # 原地覆写允许
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter
from pathlib import Path


# Pronoia-RLVR 评估使用的 5 个主 horizon
PRIMARY_HORIZONS = ["t3", "t7", "t15", "t30", "t60"]
# 短/长 horizon 分组（用于 long_short_agree）
SHORT_HORIZONS = ["t1", "t3", "t7"]
LONG_HORIZONS  = ["t15", "t30", "t60"]


def _valid(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and abs(x) < 10.0


def _sign(x) -> int:
    if x > 0: return 1
    if x < 0: return -1
    return 0


def augment_label(lb: dict) -> dict:
    """给单条 label 写入 RER 字段。返回同一条 dict（原地修改）。"""
    # ---- 1) RER = ret_tXX（显式复制，便于下游直接引用字段名）----
    for h in PRIMARY_HORIZONS:
        lb[f"rer_{h}"] = lb.get(f"ret_{h}")

    # ---- 2) horizons_complete：5 主 horizon 全部 ret/car 有效 ----
    ok_all = True
    for h in PRIMARY_HORIZONS:
        r = lb.get(f"ret_{h}"); c = lb.get(f"car_{h}")
        if not (_valid(r) and _valid(c)):
            ok_all = False
            break
    lb["horizons_complete"] = ok_all

    # ---- 3) rer_car_agree_tXX（单 horizon）& 5h 汇总 ----
    agree_5h = True
    for h in PRIMARY_HORIZONS:
        r = lb.get(f"ret_{h}"); c = lb.get(f"car_{h}")
        if _valid(r) and _valid(c):
            agree = (_sign(r) == _sign(c))
        else:
            agree = False
        lb[f"rer_car_agree_{h}"] = agree
        if not agree:
            agree_5h = False
    lb["rer_car_agree_5h"] = agree_5h

    # ---- 4) long_short_agree：长短 horizon 反转检测 ----
    # t3 vs t60 直接比较
    r3 = lb.get("ret_t3"); r60 = lb.get("ret_t60")
    if _valid(r3) and _valid(r60):
        lb["long_short_agree_t3_t60"] = (_sign(r3) == _sign(r60))
    else:
        lb["long_short_agree_t3_t60"] = False

    # 短三元多数 vs 长三元多数
    short_signs = [_sign(lb.get(f"ret_{h}")) for h in SHORT_HORIZONS if _valid(lb.get(f"ret_{h}"))]
    long_signs  = [_sign(lb.get(f"ret_{h}")) for h in LONG_HORIZONS  if _valid(lb.get(f"ret_{h}"))]
    def _major_sign(signs):
        if not signs: return 0
        pos = sum(1 for s in signs if s > 0)
        neg = sum(1 for s in signs if s < 0)
        if pos > neg: return 1
        if neg > pos: return -1
        return 0
    ms = _major_sign(short_signs); ml = _major_sign(long_signs)
    if ms == 0 or ml == 0:
        lb["long_short_agree_short"] = False
    else:
        lb["long_short_agree_short"] = (ms == ml)

    return lb


def process(labels_in: Path, labels_out: Path) -> dict:
    rows = []
    with open(labels_in, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    print(f"[INFO] 读取 labels: {len(rows)} 条  ← {labels_in}")

    # 统计
    cnt_complete = 0
    agree_cnt = Counter()  # key=horizon, value=agree 条数
    agree_total_valid = Counter()
    ls_agree_360 = 0; ls_agree_short = 0

    for i, lb in enumerate(rows):
        augment_label(lb)
        if lb["horizons_complete"]:
            cnt_complete += 1
        for h in PRIMARY_HORIZONS:
            r = lb.get(f"ret_{h}"); c = lb.get(f"car_{h}")
            if _valid(r) and _valid(c):
                agree_total_valid[h] += 1
                if lb[f"rer_car_agree_{h}"]:
                    agree_cnt[h] += 1
        if lb["long_short_agree_t3_t60"]: ls_agree_360 += 1
        if lb["long_short_agree_short"]: ls_agree_short += 1
        if (i + 1) % 200 == 0 or (i + 1) == len(rows):
            print(f"[PROG] {i+1}/{len(rows)}  horizons_complete={cnt_complete}")

    # 写回（原地覆写允许：先读全内存 → tmp → replace）
    tmp = labels_out.with_suffix(labels_out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for lb in rows:
            f.write(json.dumps(lb, ensure_ascii=False) + "\n")
    os.replace(tmp, labels_out)

    # 汇总统计报告
    report = {
        "total": len(rows),
        "horizons_complete": cnt_complete,
        "horizons_complete_ratio": cnt_complete / max(1, len(rows)),
        "rer_car_agree_ratio": {
            h: (agree_cnt[h] / max(1, agree_total_valid[h]))
            for h in PRIMARY_HORIZONS
        },
        "rer_car_agree_n": {h: agree_total_valid[h] for h in PRIMARY_HORIZONS},
        "long_short_agree_t3_t60_ratio": ls_agree_360 / max(1, len(rows)),
        "long_short_agree_short_ratio": ls_agree_short / max(1, len(rows)),
    }
    print(f"\n[RER REPORT] 写出 → {labels_out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-in",  required=True)
    ap.add_argument("--labels-out", required=True)
    args = ap.parse_args()
    process(Path(args.labels_in), Path(args.labels_out))


if __name__ == "__main__":
    main()
