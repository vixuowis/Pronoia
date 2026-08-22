"""eval_papv_remote.py — PAPV 训练效果评估（远程 GPU，训练完成后运行）。

评估对象：held-out 事件（训练用 rows[:2600]，评估用 rows[2600:2600+N]）
对比两侧：
  A) base：Qwen3-8B 基座
  B) adapter：base + PAPV LoRA（GRPO 训练产物）

核心指标（PAPV 提案）：
  1. 断言判断准确率（settleable 口径）
  2. 置信度校准：ECE（10 bin）+ Brier + 分 bin 校准表
  3. 分 horizon 命中率（t1/t3/t5/t7/t15/t30/t60）
  4. 分指标族命中率（car/ret/bm/pvalue/avg）
  5. 退化检查：TRUE 判断占比、可结算率、平均断言数

用法（远程机器，训练完成后）：
  /root/miniconda3/bin/python eval_papv_remote.py \
      --data-dir /root/pronoia/data_v3 --adapter /root/pronoia/papv_full/papv_mixed \
      --skip 2600 --n-eval 400 --out /root/pronoia/eval_papv_results.json
  （--adapter 省略则只评 base）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS.parent))

from papv_claims import (                                  # noqa: E402
    METRIC_PANEL, parse_claims, settle_claim_truth, metric_family,
)

BASE_MODEL = "/root/Qwen3-8B"
HORIZONS = ("1", "3", "5", "7", "15", "30", "60")


# ---------------- 数据 ----------------
def load_eval_rows(data_dir: Path, skip: int, n_eval: int, tok):
    """训练脚本同源的过滤逻辑，取 rows[skip:skip+n_eval] 做 held-out。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "papv_train_remote", _THIS / "papv_train_remote.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 只 import，不执行 main
    rows = mod.load_dataset_rows(data_dir, "mixed", 0, tok=tok)  # 全量（含 prompt 渲染）
    held = rows[skip:skip + n_eval]
    print(f"[DATA] total={len(rows)} skip={skip} → held-out eval={len(held)}")
    if not held:
        raise SystemExit("empty eval split")
    return held


# ---------------- 生成 ----------------
def generate_batch(model, tok, prompts: list[str], max_new_tokens=1280,
                   temperature=0.6, top_p=0.95) -> list[str]:
    enc = tok(prompts, return_tensors="pt", padding=True,
              add_special_tokens=False).to(model.device)
    do_sample = temperature > 0
    out = model.generate(
        **enc, max_new_tokens=max_new_tokens,
        do_sample=do_sample,
        temperature=temperature if do_sample else None,
        top_p=top_p if do_sample else None,
        pad_token_id=tok.pad_token_id or tok.eos_token_id,
    )
    texts = []
    for i in range(len(prompts)):
        gen = out[i][enc["input_ids"].shape[1]:]
        texts.append(tok.decode(gen, skip_special_tokens=True))
    return texts


def run_generate(model, tok, prompts: list[str], bs: int, tag: str,
                 temperature: float) -> list[str]:
    model.eval()
    outs: list[str] = []
    t0 = time.time()
    for bi, batch in enumerate(prompts[i:i + bs] for i in range(0, len(prompts), bs)):
        outs.extend(generate_batch(model, tok, batch, temperature=temperature))
        if bi % 5 == 0 or bi == len(prompts) // bs - 1:
            el = time.time() - t0
            done = (bi + 1) * bs
            print(f"[GEN:{tag}] {min(done,len(prompts))}/{len(prompts)} "
                  f"({el:.0f}s, {el/max(done,1):.2f}s/prompt)", flush=True)
    return outs


# ---------------- 指标 ----------------
def horizon_of(metric: str) -> str | None:
    m = re.search(r"_t(\d+)", metric)
    return m.group(1) if m else None


def evaluate_completions(completions: list[str], label_jsons: list[str]) -> dict:
    """结算全部 completion → 汇总指标。"""
    n_claims_all, settleable_all, correct_all = 0, 0, 0
    true_judge_n, true_judge_correct = 0, 0          # 模型判 TRUE 的断言
    false_judge_n, false_judge_correct = 0, 0        # 模型判 FALSE 的断言
    conf_correct: list[tuple[float, bool]] = []      # (对自身判断的置信度, 判断是否正确)
    by_h = defaultdict(lambda: [0, 0])               # horizon -> [correct, settleable]
    by_f = defaultdict(lambda: [0, 0])               # family  -> [correct, settleable]
    n_valid_fmt = 0
    samples = []

    for text, lj in zip(completions, label_jsons):
        try:
            label = json.loads(lj)
        except Exception:
            label = {}
        claims = parse_claims(text)
        n_claims_all += len(claims)
        if 3 <= len(claims) <= 6:
            n_valid_fmt += 1
        for c in claims:
            truth = settle_claim_truth(c, label)
            if truth is None:
                continue
            settleable_all += 1
            ok = truth == c["judge"]
            correct_all += int(ok)
            conf = c["conf"] if c["conf"] is not None else 0.5
            conf_correct.append((conf, ok))
            if c["judge"]:
                true_judge_n += 1
                true_judge_correct += int(ok)
            else:
                false_judge_n += 1
                false_judge_correct += int(ok)
            h = horizon_of(c["metric"])
            if h:
                by_h[h][1] += 1
                by_h[h][0] += int(ok)
            f = metric_family(c["metric"])
            by_f[f][1] += 1
            by_f[f][0] += int(ok)
        if len(samples) < 5:
            samples.append(text[:1200])

    # 校准：10 bin ECE + Brier（p = 对自身判断的置信度；目标 = 判断正确）
    bins = [0.0] * 10
    bin_correct = [0] * 10
    brier = 0.0
    for conf, ok in conf_correct:
        b = min(9, int(conf * 10))
        bins[b] += 1
        bin_correct[b] += int(ok)
        brier += (conf - (1.0 if ok else 0.0)) ** 2
    n = len(conf_correct)
    ece = sum(bins[b] / n * abs(bin_correct[b] / bins[b] - (b + 0.5) / 10)
              for b in range(10) if bins[b] > 0) if n else None
    cal_table = {
        f"{b/10:.1f}-{(b+1)/10:.1f}": {
            "n": bins[b],
            "acc": round(bin_correct[b] / bins[b], 4) if bins[b] else None,
            "conf_mid": (b + 0.5) / 10,
        } for b in range(10)
    }

    acc = correct_all / settleable_all if settleable_all else None
    return {
        "n_events": len(completions),
        "avg_claims": round(n_claims_all / len(completions), 3),
        "fmt_valid_ratio": round(n_valid_fmt / len(completions), 4),
        "settleable_ratio": round(settleable_all / n_claims_all, 4) if n_claims_all else None,
        "n_settleable": settleable_all,
        "accuracy": round(acc, 4) if acc is not None else None,
        "true_judge_ratio": round(true_judge_n / settleable_all, 4) if settleable_all else None,
        "acc_when_TRUE": round(true_judge_correct / true_judge_n, 4) if true_judge_n else None,
        "acc_when_FALSE": round(false_judge_correct / false_judge_n, 4) if false_judge_n else None,
        "ece_10bin": round(ece, 4) if ece is not None else None,
        "brier": round(brier / n, 4) if n else None,
        "calibration_bins": cal_table,
        "acc_by_horizon": {
            f"t{h}": {"n": by_h[h][1],
                      "acc": round(by_h[h][0] / by_h[h][1], 4) if by_h[h][1] else None}
            for h in HORIZONS if by_h[h][1] > 0
        },
        "acc_by_family": {
            f: {"n": v[1], "acc": round(v[0] / v[1], 4)}
            for f, v in sorted(by_f.items()) if v[1] > 0
        },
        "sample_completions": samples,
    }


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--adapter", default="", help="LoRA adapter 目录；空 = 只评 base")
    ap.add_argument("--skip", type=int, default=2600)
    ap.add_argument("--n-eval", type=int, default=400)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--out", default="/root/pronoia/eval_papv_results.json")
    ap.add_argument("--save-completions", default="",
                    help="可选：保存全部 completion 到 jsonl（对比分析用）")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    rows = load_eval_rows(Path(args.data_dir), args.skip, args.n_eval, tok)
    prompts = [r["prompt"] for r in rows]
    label_jsons = [r["_label_json"] for r in rows]

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, device_map="cuda:0")
    model.config.use_cache = True

    results = {"config": vars(args), "timestamp": time.strftime("%F %T")}

    # A) base
    print("\n===== A) base =====", flush=True)
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
        print("\n===== B) base + PAPV LoRA =====", flush=True)
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

    # Δ 摘要
    if "lora" in results:
        results["delta"] = {
            k: (round(results["lora"][k] - results["base"][k], 4)
                if isinstance(results["base"].get(k), (int, float))
                and isinstance(results["lora"].get(k), (int, float)) else None)
            for k in ("accuracy", "ece_10bin", "brier", "settleable_ratio",
                      "true_judge_ratio", "avg_claims")
        }
        print("\n===== Δ (lora - base) =====")
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
