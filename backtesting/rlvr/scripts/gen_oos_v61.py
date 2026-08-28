"""gen_oos_v61.py — v6.1 time-OOS completions 生成（纯 vLLM，LoRA 显式加载）。

对 data_v61_test 全部分区样本生成 PAPV completions：
  --side base     : Qwen3-8B 裸模型
  --side adapter  : + papv_v61 final LoRA（vLLM LoRARequest 显式加载）
输出 completions.jsonl（每行 {event_id, completion, side}），供 eval_papv_suite.py 结算。

注意：之前 unsloth fast_inference 路径未把 LoRA 权重注入 vLLM 引擎（base/adapter
结果几乎一致），故改为纯 vLLM + enable_lora + LoRARequest，确保 adapter 生效。
"""
import argparse
import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training/remote_scripts")

from papv_train_remote import load_dataset_rows  # noqa: E402

BASE_MODEL = "/root/Qwen3-8B"
ADAPTER = "/root/Pronoia/pronoia_run/papv_v61/papv_mixed"
TEST_DIR = "/root/Pronoia/pronoia_run/data_v61_test"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=("base", "adapter"), required=True)
    ap.add_argument("--n", type=int, default=0, help="0 = 全量")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    rows = load_dataset_rows(Path(TEST_DIR), "mixed", args.n, tok=tok)
    print(f"[GEN] rows={len(rows)}", flush=True)

    engine_kwargs = dict(
        model=BASE_MODEL, max_model_len=3072,
        gpu_memory_utilization=0.85, dtype="bfloat16",
    )
    lora_req = None
    if args.side == "adapter":
        engine_kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1)
        lora_req = LoRARequest("papv", 1, ADAPTER)
        print(f"[GEN] LoRA loaded from {ADAPTER}", flush=True)

    print(f"[GEN] init vLLM (side={args.side})", flush=True)
    llm = LLM(**engine_kwargs)
    sp = SamplingParams(max_tokens=768, temperature=args.temperature)

    out_path = args.out or f"/root/Pronoia/pronoia_run/oos_v61_{args.side}_completions.jsonl"
    t0 = time.time()
    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(0, len(rows), args.batch):
            chunk = rows[i:i + args.batch]
            prompts = [r["prompt"] for r in chunk]
            outs = llm.generate(prompts, sp, lora_request=lora_req)
            for r, o in zip(chunk, outs):
                eid = json.loads(r["_event_json"]).get("event_id", "")
                f.write(json.dumps({
                    "event_id": eid,
                    "completion": o.outputs[0].text,
                    "side": args.side,
                }, ensure_ascii=False) + "\n")
            done = min(i + args.batch, len(rows))
            el = time.time() - t0
            print(f"[GEN] {done}/{len(rows)} ({el:.0f}s, {el/done:.2f}s/条)",
                  flush=True)
    print(f"[DONE] → {out_path}", flush=True)


if __name__ == "__main__":
    main()
