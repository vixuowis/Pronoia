"""oos_eval_papv_remote.py — 训练样本外（OOS）PAPV 评估。

与 eval_papv_remote.py 的区别：
  训练按 data_dir/data_v4 的 1782 个 event_id 划分；本脚本用 data_v3 全量可结算
  样本，去掉「在 data_v4 训练集出现过的 event_id」，剩下即真正的样本外。
  对比两侧：A) base（Qwen3-8B） B) adapter（base + checkpoint-299 LoRA）

指标沿用 eval_papv_remote（断言准确率 / ECE / Brier / 分 horizon / 分指标族 / 退化检查）。

用法（远程机器）：
  /root/miniconda3/bin/python oos_eval_papv_remote.py \
      --train-dir /root/pronoia/data_v4 --oos-dir /root/pronoia/data_v3 \
      --adapter /root/pronoia/papv_v4_run1/papv_mixed/checkpoint-299 \
      --n-eval 200 --out /root/pronoia/oos_eval_v4_results.json \
      --save-completions /root/pronoia/oos_eval_v4_completions.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

from eval_papv_remote import (                    # noqa: E402
    evaluate_completions, generate_batch, run_generate,
)

BASE_MODEL = "/root/Qwen3-8B"


def load_train_eids(train_dir: Path) -> set[str]:
    """读取训练集（labels.jsonl）的全部 event_id。"""
    lb_path = train_dir / "labels.jsonl"
    if not lb_path.exists():
        raise SystemExit(f"no training labels: {lb_path}")
    eids: set[str] = set()
    with open(lb_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                eids.add(str(json.loads(line).get("event_id") or ""))
            except Exception:
                continue
    return eids


def load_oos_rows(oos_dir: Path, tok, train_eids: set[str]) -> list[dict]:
    """data_v3 全量行 → 剔除在训练集出现的 event_id → OOS 行。"""
    spec = importlib.util.spec_from_file_location(
        "papv_train_remote", _THIS / "papv_train_remote.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.load_dataset_rows(oos_dir, "mixed", 0, tok=tok)
    kept, dropped = [], 0
    for r in rows:
        try:
            ev = json.loads(r.get("_event_json") or "{}")
            eid = str(ev.get("event_id") or "")
        except Exception:
            eid = ""
        if eid in train_eids:
            dropped += 1
            continue
        kept.append(r)
    print(f"[OOS] total={len(rows)} dropped_train={dropped} oos={len(kept)}")
    if not kept:
        raise SystemExit("no out-of-sample rows")
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-dir", required=True, help="训练集 data_dir（含 labels.jsonl）")
    ap.add_argument("--oos-dir", required=True, help="样本外 data_dir（data_v3）")
    ap.add_argument("--adapter", default="", help="LoRA adapter；空 = 只评 base")
    ap.add_argument("--n-eval", type=int, default=200)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--out", default="/root/pronoia/oos_eval_results.json")
    ap.add_argument("--save-completions", default="")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    train_eids = load_train_eids(Path(args.train_dir))
    rows = load_oos_rows(Path(args.oos_dir), tok, train_eids)
    held = rows[:args.n_eval]
    print(f"[OOS] eval sample = {len(held)}")
    prompts = [r["prompt"] for r in held]
    label_jsons = [r["_label_json"] for r in held]

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, device_map="cuda:0")
    model.config.use_cache = True

    results = {"config": vars(args), "timestamp": time.strftime("%F %T"),
               "n_train": len(train_eids), "oos_total": len(rows)}

    # A) base
    print("\n===== A) base (OOS) =====", flush=True)
    t0 = time.time()
    base_out = run_generate(model, tok, prompts, args.batch_size, "base",
                            args.temperature)
    results["base"] = evaluate_completions(base_out, label_jsons)
    results["base"]["gen_sec"] = round(time.time() - t0, 1)
    print(json.dumps({k: v for k, v in results["base"].items()
                      if k not in ("calibration_bins", "sample_completions",
                                   "acc_by_horizon", "acc_by_family")},
                     ensure_ascii=False, indent=2))

    all_completions = [("base", p, o) for p, o in zip(prompts, base_out)]

    # B) adapter
    if args.adapter:
        print("\n===== B) base + checkpoint-299 LoRA (OOS) =====", flush=True)
        from peft import PeftModel
        del model
        torch.cuda.empty_cache()
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, torch_dtype=torch.bfloat16, device_map="cuda:0")
        model.config.use_cache = True
        model = PeftModel.from_pretrained(model, args.adapter)
        model.eval()
        t0 = time.time()
        lora_out = run_generate(model, tok, prompts, args.batch_size, "lora",
                                args.temperature)
        results["lora"] = evaluate_completions(lora_out, label_jsons)
        results["lora"]["gen_sec"] = round(time.time() - t0, 1)
        print(json.dumps({k: v for k, v in results["lora"].items()
                          if k not in ("calibration_bins", "sample_completions",
                                       "acc_by_horizon", "acc_by_family")},
                         ensure_ascii=False, indent=2))
        all_completions += [("lora", p, o) for p, o in zip(prompts, lora_out)]

    if "lora" in results:
        results["delta"] = {
            k: (round(results["lora"][k] - results["base"][k], 4)
                if isinstance(results["base"].get(k), (int, float))
                and isinstance(results["lora"].get(k), (int, float)) else None)
            for k in ("accuracy", "ece_10bin", "brier", "settleable_ratio",
                      "true_judge_ratio", "avg_claims")
        }
        print("\n===== Δ (lora - base) on OOS =====")
        print(json.dumps(results["delta"], ensure_ascii=False, indent=2))

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVED] {args.out}")

    if args.save_completions:
        with open(args.save_completions, "w", encoding="utf-8") as f:
            for side, p, o in all_completions:
                f.write(json.dumps({"side": side, "prompt_tail": p[-300:],
                                    "completion": o}, ensure_ascii=False) + "\n")
        print(f"[SAVED] {args.save_completions}")


if __name__ == "__main__":
    main()