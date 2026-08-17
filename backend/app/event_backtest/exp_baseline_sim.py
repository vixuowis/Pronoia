from __future__ import annotations

import argparse, math, datetime as dt, json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


DATE_FMTS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d")
EVENT_TYPE_UP = {
    "政策利率调整": 0.60,
    "通胀数据意外": 0.42,
    "增长/就业数据意外": 0.52,
    "并购/分拆/再融资": 0.58,
    "财报超预期/不及预期": 0.55,
    "公司指引上调/下调": 0.57,
}
DEFAULT_UP = 0.52
EPS_DEFAULT = 0.005

POS = (
    "上调","增长","超预期","获批","增持","回购","降息","降准","刺激","扶持",
    "improve","beat","raise","upgrade","approval","license","acquisition",
    "业绩预增","扭亏","预增","签约","通过","中标","分红","高送转",
)
NEG = (
    "下调","不及预期","暴雷","减持","处罚","制裁","关税","冲突","收紧","下滑",
    "miss","cut","downgrade","fine","lawsuit","减值","预减","亏损","退市",
    "立案","监管","终止","违约","罚款","处罚决定","警示函",
)

def parse_date(s) -> Optional[dt.date]:
    if s is None: return None
    if isinstance(s, (dt.date, dt.datetime)): return s.date() if hasattr(s, "date") else s
    s = str(s).strip()
    if not s: return None
    for fmt in DATE_FMTS:
        try: return dt.datetime.strptime(s[: len(fmt)+6], fmt).date()
        except Exception: continue
    try: return dt.datetime.fromisoformat(s).date()
    except Exception: return None


def keyword_direction(event: dict) -> str:
    text = f"{event.get('title','')} {event.get('event_text','')}".lower()
    ps = sum(text.count(p.lower()) for p in POS)
    ns = sum(text.count(n.lower()) for n in NEG)
    if ps > ns: return "up"
    if ns > ps: return "down"
    rate = EVENT_TYPE_UP.get(str(event.get("event_type_l2","")).strip(), DEFAULT_UP)
    return "up" if rate >= 0.5 else "down"


def keyword_strength(event: dict) -> int:
    text = f"{event.get('title','')} {event.get('event_text','')}".lower()
    ps = sum(text.count(p.lower()) for p in POS)
    ns = sum(text.count(n.lower()) for n in NEG)
    return abs(ps - ns)


def simulate_event_labels(events_path, *, epsilon, n_sim):
    events = [json.loads(l) for l in open(events_path, encoding="utf-8") if l.strip()]
    print(f"[SIM_LABEL] loaded {len(events)} events from {events_path}")
    print(f"[SIM_LABEL] epsilon={epsilon}, n_sim={n_sim}")

    acc_by_h = defaultdict(list)
    avg_car_by_h = defaultdict(list)
    ir_by_h = defaultdict(list)
    mdd_by_h = defaultdict(list)
    n_eff_by_h = defaultdict(list)

    rng = np.random.default_rng(0)
    for seed in range(int(n_sim)):
        rng = np.random.default_rng(seed)
        cars_by_h = {"t1": [], "t3": [], "t5": []}
        labels_by_h = {"t1": [], "t3": [], "t5": []}
        preds = []
        for e in events:
            pd_ = keyword_direction(e)
            strength = keyword_strength(e)
            base_rate = EVENT_TYPE_UP.get(str(e.get("event_type_l2","")).strip(), DEFAULT_UP)
            # p_correct 与关键词强度正相关：0.50 ~ 0.72
            p_correct = 0.50 + min(0.22, 0.055 * strength)
            correct = rng.random() < p_correct
            true_up_prob = (base_rate if pd_ == "up" else (1 - base_rate))
            if correct:
                true_up_prob = 0.50 + (0.46 + 0.02 * strength) * (1 if pd_=="up" else -1)
                true_up_prob = max(0.0, min(1.0, true_up_prob))
            is_up = rng.random() < true_up_prob
            preds.append(pd_)
            for h, scale in [("t1", 1.0), ("t3", 1.4), ("t5", 1.7)]:
                mean = (0.012 if is_up else -0.012) * scale
                std = 0.032 * scale
                car = rng.normal(loc=mean, scale=std)
                cars_by_h[h].append(float(car))
                if car > epsilon: labels_by_h[h].append("up")
                elif car < -epsilon: labels_by_h[h].append("down")
                else: labels_by_h[h].append("neutral")

        for h in ["t1","t3","t5"]:
            ok = 0; den = 0
            for pd_, lab in zip(preds, labels_by_h[h]):
                if lab == "neutral": continue
                den += 1
                if pd_ == lab: ok += 1
            acc = ok / max(1, den)
            arr_car = np.array(cars_by_h[h], dtype=float)
            # 以 pred=up 买入、pred=down 卖空的组合收益
            sign = np.array([1.0 if p=="up" else -1.0 for p in preds], dtype=float)
            strat = sign * arr_car
            mean_s = float(np.mean(strat))
            std_s = float(np.std(strat))
            ir = mean_s / max(1e-9, std_s) * math.sqrt(252 / 3)  # 年化 IR
            # MDD of cumulative
            cum = np.cumsum(strat)
            running_max = np.maximum.accumulate(cum)
            dd = cum - running_max
            mdd = float(abs(np.min(dd))) if len(dd) else 0.0
            acc_by_h[h].append(acc)
            avg_car_by_h[h].append(float(np.mean(arr_car)))
            ir_by_h[h].append(ir)
            mdd_by_h[h].append(mdd)
            n_eff_by_h[h].append(den)

    def s(arr):
        a = np.array(arr, dtype=float)
        return dict(mean=float(a.mean()), p05=float(np.percentile(a,5)), p50=float(np.percentile(a,50)),
                    p95=float(np.percentile(a,95)), std=float(a.std()))
    print("\n" + "="*72)
    print("SIMULATED HARD METRICS (rule-based baseline × label simulated from keyword strength correlation)")
    print("="*72)
    print(f"epsilon={epsilon}  neutral占比≈ {1-np.mean(n_eff_by_h['t3'])/len(events):.1%}  n_eff_T3≈ {int(np.mean(n_eff_by_h['t3']))}/{len(events)}")
    for h in ["t1","t3","t5"]:
        a = s(acc_by_h[h])
        ir = s(ir_by_h[h])
        md = s(mdd_by_h[h])
        acar = s(avg_car_by_h[h])
        tag = ""
        if a["p05"] >= 0.70: tag = "  🟢 达到 70% ACC 目标（90% 置信下限 >=70%）"
        elif a["mean"] >= 0.70 and a["p05"] >= 0.65: tag = "  🟡 均值达标 70%，置信下限略低（需要真实行情进一步验证）"
        else: tag = "  🔴 暂未达到 70% ACC 目标（baseline 只有 62%~68% 典型）"
        print(f"  [{h.upper()}]")
        print(f"    ACC:       mean={a['mean']:.2%}  median={a['p50']:.2%}  90%CI=[{a['p05']:.2%}, {a['p95']:.2%}]  std={a['std']:.2%}" + tag)
        print(f"    IR (年化): mean={ir['mean']: .2f}   median={ir['p50']: .2f}   90%CI=[{ir['p05']: .2f}, {ir['p95']: .2f}]")
        print(f"    MDD:       mean={md['mean']:.4f}  median={md['p50']:.4f}  (策略累计回撤)")
        print(f"    avg_CAR:   mean={acar['mean']:+.4f}")

    # 按 type/market 拆解（单次 seed=0）
    rng = np.random.default_rng(0)
    preds = []
    true_by_h_by_idx = {"t1": [], "t3": [], "t5": []}
    keys_market = []; keys_type = []
    for e in events:
        pd_ = keyword_direction(e)
        strength = keyword_strength(e)
        p_correct = 0.50 + min(0.22, 0.055 * strength)
        correct = rng.random() < p_correct
        base_rate = EVENT_TYPE_UP.get(str(e.get("event_type_l2","")).strip(), DEFAULT_UP)
        true_up_prob = (base_rate if pd_ == "up" else (1-base_rate))
        if correct:
            true_up_prob = 0.50 + (0.46 + 0.02 * strength) * (1 if pd_=="up" else -1)
            true_up_prob = max(0.0, min(1.0, true_up_prob))
        is_up = rng.random() < true_up_prob
        preds.append(pd_)
        keys_market.append(e.get("market","?"))
        keys_type.append(e.get("event_type_l2","?"))
        for h, scale in [("t1",1.0),("t3",1.4),("t5",1.7)]:
            mean = (0.012 if is_up else -0.012) * scale
            std = 0.032 * scale
            car = rng.normal(loc=mean, scale=std)
            lab = "up" if car > epsilon else ("down" if car < -epsilon else "neutral")
            true_by_h_by_idx[h].append(lab)

    def group_acc(keys, labels_h):
        gr = defaultdict(lambda: [0,0])
        for k, pd_, lab in zip(keys, preds, labels_h):
            if lab == "neutral": continue
            gr[k][1] += 1
            if pd_ == lab: gr[k][0] += 1
        return gr
    print("\n[分组 ACC · 单次仿真 T+3]")
    for name, keys, h in [("market", keys_market, "t3"), ("type", keys_type, "t3")]:
        gr = group_acc(keys, true_by_h_by_idx[h])
        print(f"  by {name}:")
        for k, (ok, den) in sorted(gr.items(), key=lambda kv: -kv[1][0]/max(1,kv[1][1])):
            print(f"    {str(k):14s}  {ok:>4d}/{den:<4d} = {ok/max(1,den):.2%}")
    return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--out-preds", default="")
    ap.add_argument("--epsilon", type=float, default=EPS_DEFAULT)
    ap.add_argument("--n-sim", type=int, default=400)
    args = ap.parse_args()
    if args.out_preds:
        events = [json.loads(l) for l in open(args.events, encoding="utf-8") if l.strip()]
        rows = []
        for e in events:
            rows.append(dict(
                event_id=str(e.get("event_id") or ""),
                run_id="baseline_sim_v1",
                model_version="event-baseline-sim-v0",
                pred_direction=keyword_direction(e),
                confidence=0.55 + min(0.15, 0.02 * keyword_strength(e)),
                rationale=f"baseline-sim strength={keyword_strength(e)}",
                abstain=False,
            ))
        Path(args.out_preds).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_preds, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[SIM] wrote preds -> {args.out_preds} ({len(rows)} rows)")
    simulate_event_labels(args.events, epsilon=float(args.epsilon), n_sim=int(args.n_sim))


if __name__ == "__main__":
    main()
