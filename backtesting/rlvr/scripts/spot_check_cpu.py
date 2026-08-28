"""spot_check_cpu.py — CPU 抽检 checkpoint-800：不占 GPU，训练期间安全。

用 transformers+peft 在 CPU 上加载 Qwen3-8B + LoRA adapter（bf16，~15GB RAM），
抽 test 分区 2 个样本（US 宏观 + CN 难负）生成并结算，与 GPU 抽检结果对照。
"""
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training/remote_scripts")

from papv_claims import parse_claims, settle_all, settle_claim_truth  # noqa: E402
from prompt_template_papv import build_messages_for_papv             # noqa: E402

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402
from peft import PeftModel  # noqa: E402

BASE = "/root/Qwen3-8B"
CKPT = "/root/Pronoia/pronoia_run/papv_v61/papv_mixed/checkpoint-800"
TEST = Path("/root/Pronoia/pronoia_run/data_v61_test")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def pick_samples():
    evs = read_jsonl(TEST / "events_enriched.jsonl")
    lbs = {str(l["event_id"]): l for l in read_jsonl(TEST / "labels.jsonl")}
    macro = ("增长/就业数据意外", "通胀数据意外", "政策利率调整")
    us = next(e for e in evs if e.get("market") == "US" and e.get("event_type_l2") in macro)
    import re
    hard_re = re.compile(r"中标|扭亏|预增|定增获通过|不向下修正|收购进展")
    hard = next(e for e in evs if hard_re.search(str(e.get("title", "")) or ""))
    return [(us, lbs[str(us["event_id"])]),
            (hard, lbs[str(hard["event_id"])])]


def main():
    torch.set_num_threads(64)
    print("[CPU] loading tokenizer...", flush=True)
    tok = AutoTokenizer.from_pretrained(BASE)
    print("[CPU] loading base model (bf16, cpu)...", flush=True)
    t0 = time.time()
    base = AutoModelForCausalLM.from_pretrained(
        BASE, torch_dtype=torch.bfloat16, device_map={"": "cpu"},
    )
    print(f"[CPU] base loaded in {time.time()-t0:.0f}s", flush=True)
    model = PeftModel.from_pretrained(base, CKPT)
    model.eval()
    print("[CPU] LoRA adapter attached", flush=True)

    for ev, lb in pick_samples():
        print("=" * 80, flush=True)
        print(f"[EVENT] {ev.get('market')} | {ev.get('event_type_l2')} | {str(ev.get('title',''))[:60]}", flush=True)
        msgs = build_messages_for_papv(ev, research=None)
        inputs = tok.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=True,
            return_tensors="pt", return_dict=True, enable_thinking=False,
        )
        t0 = time.time()
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=768, temperature=1.0,
                top_p=1.0, do_sample=True,
            )
        n_in = inputs["input_ids"].shape[1]
        text = tok.decode(out[0][n_in:], skip_special_tokens=True)
        print(f"[GEN] {time.time()-t0:.0f}s, {len(text)} chars", flush=True)
        print(f"[COMPLETION]\n{text}", flush=True)

        claims = parse_claims(text)
        print(f"\n[PARSED] {len(claims)} 条断言", flush=True)
        st = settle_all(claims, lb)
        for c in claims:
            truth = settle_claim_truth(c, lb)
            mark = "OK" if truth == c.get("judge") else "MISS"
            print(f"  - {c.get('metric')} judge={c.get('judge')} conf={c.get('conf')}"
                  f" | truth={truth} [{mark}]", flush=True)
        print(f"[SETTLE] 可结算 {st['settleable']}/{st['n_claims']}，"
              f"命中 {st['correct']}，acc={st['accuracy']}", flush=True)

    print("[CPU] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
