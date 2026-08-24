"""oos_case_study.py — OOS case study：base vs LoRA 同一事件的断言 + 真实结算。

复用 oos_eval 的采样顺序（rows[:n_eval]，剔除训练集），读取已保存的两套
completions（base 前 n，lora 后 n），对每个事件结算其断言，输出：
  · 双方均对的样本
  · base 错但 LoRA 对（= 训练带来的提升）
  · base 对但 LoRA 错（= 训练导致的回退）
每类取 top-N 按事件展示事件元信息 + 断言 + label 数据。

用法（远程）：
  /root/miniconda3/bin/python oos_case_study.py \
      --train-dir /root/pronoia/data_v4 --oos-dir /root/pronoia/data_v3 \
      --completions /root/pronoia/oos_eval_v4_completions.jsonl \
      --n-eval 200 --out /root/pronoia/oos_case_study.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from collections import defaultdict

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

from oos_eval_papv_remote import load_train_eids               # noqa: E402
from oos_eval_papv_remote import load_oos_rows                 # noqa: E402
from papv_claims import parse_claims, settle_claim_truth       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-dir", required=True)
    ap.add_argument("--oos-dir", required=True)
    ap.add_argument("--completions", required=True)
    ap.add_argument("--n-eval", type=int, default=200)
    ap.add_argument("--out", default="/root/pronoia/oos_case_study.json")
    ap.add_argument("--top", type=int, default=4)
    args = ap.parse_args()

    import torch
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("/root/Qwen3-8B")

    train_eids = load_train_eids(Path(args.train_dir))
    rows = load_oos_rows(Path(args.oos_dir), tok, train_eids)
    held = rows[:args.n_eval]

    # completions: base 前 n，lora 后 n
    comps = []
    with open(args.completions, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                comps.append(json.loads(line))
    base_comps = [c["completion"] for c in comps if c["side"] == "base"]
    lora_comps = [c["completion"] for c in comps if c["side"] == "lora"]
    n = min(len(held), len(base_comps), len(lora_comps))
    print(f"[CASE] held={len(held)} base={len(base_comps)} lora={len(lora_comps)} align={n}")

    def settle(text, label):
        claims = parse_claims(text)
        out = []
        for c in claims:
            truth = settle_claim_truth(c, label)
            out.append({
                "metric": c["metric"], "op": c["op"], "thr": c["thr"],
                "judge": c["judge"], "conf": c["conf"],
                "truth": truth, "correct": None if truth is None else (truth == c["judge"]),
            })
        return out

    cats = defaultdict(list)  # category -> [case]
    for i in range(n):
        ev = json.loads(held[i].get("_event_json") or "{}")
        label = json.loads(held[i].get("_label_json") or "{}")
        b = settle(base_comps[i], label)
        l = settle(lora_comps[i], label)
        b_ok = [x["correct"] for x in b if x["correct"] is not None]
        l_ok = [x["correct"] for x in l if x["correct"] is not None]
        b_acc = (sum(b_ok) / len(b_ok)) if b_ok else None
        l_acc = (sum(l_ok) / len(l_ok)) if l_ok else None
        # 事件 label 关键数值（便于人工核验）
        lbl_dump = {k: (round(v, 4) if isinstance(v, (int, float)) else v)
                    for k, v in label.items()}
        case = {
            "event_id": str(ev.get("event_id") or ""),
            "symbol": str(ev.get("symbol") or "?"),
            "market": str(ev.get("market") or "?"),
            "event_date": str(ev.get("event_time") or ev.get("event_date") or "?")[:10],
            "event_type": str(ev.get("event_type_l2") or ev.get("event_type") or ""),
            "title": str(ev.get("title") or "")[:100],
            "body": str(ev.get("event_text") or ev.get("body") or "")[:200],
            "label_vals": {k: v for k, v in lbl_dump.items() if k in
                ("car_t3","car_t7","car_t15","car_t30","car_t60",
                 "ret_t3","ret_t7","ret_t15","ret_t30","ret_t60")},
            "base_acc": b_acc, "lora_acc": l_acc,
            "base_claims": b, "lora_claims": l,
        }
        if b_acc is None and l_acc is None:
            continue
        if b_acc is not None and l_acc is not None:
            if l_acc > b_acc:
                cats["improve"].append(case)
            elif l_acc < b_acc:
                cats["regress"].append(case)
            else:
                cats["tie"].append(case)
        elif l_acc is not None:
            cats["lora_first_settle"].append(case)

    for k in ("improve", "regress", "tie"):
        cats[k].sort(key=lambda x: (x["lora_acc"] if k == "improve" else
                                    -x["lora_acc"] if k == "regress" else 0),
                     reverse=(k != "regress"))
    summary = {k: len(v) for k, v in cats.items()}
    out = {"summary": summary,
           "n_events": n,
           "improve": cats["improve"][:args.top],
           "regress": cats["regress"][:args.top],
           "tie": cats["tie"][:args.top]}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"[CASE] summary={summary}")
    print(f"[SAVED] {args.out}")


if __name__ == "__main__":
    main()