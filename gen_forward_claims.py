#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_forward_claims.py — Pronoia-PAPV 前向断言生成（Step 2）。

读取 events_forward.jsonl，用训练好的 papv_v61 LoRA adapter 生成 T 日断言
（PAPV claims）。prompt 仅含事件 + 指标面板（无 research_cache），最干净的前向测试。

输出 claims_forward.jsonl：每行 {event_id, side, completion, claims, n_claims}
  · claims = parse_claims(completion) 解析出的结构化断言
"""
from __future__ import annotations
import sys, json, time, argparse
from pathlib import Path

sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training/remote_scripts")

from papv_claims import parse_claims, settle_all, METRIC_PANEL  # noqa: E402
from prompt_template_papv import build_messages_for_papv       # noqa: E402

BASE_MODEL = "/root/Qwen3-8B"
ADAPTER = "/root/Pronoia/pronoia_run/papv_v61/papv_mixed"
EVENTS_FILE = "/root/Pronoia/pronoia_run/forward_test/events_forward.jsonl"
OUT_FILE = "/root/Pronoia/pronoia_run/forward_test/claims_forward.jsonl"


def render_prompt(tok, messages):
    """Qwen3 chat template, thinking off, add generation prompt."""
    return tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=False,
    )


def load_events(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=("base", "adapter"), default="adapter",
                    help="base=裸模型对照；adapter=+papv_v61 LoRA（默认）")
    ap.add_argument("--events", default=EVENTS_FILE)
    ap.add_argument("--out", default=OUT_FILE)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=768)
    ap.add_argument("--max-model-len", type=int, default=3072)
    ap.add_argument("--n", type=int, default=0, help="0=全量")
    args = ap.parse_args()

    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    # ---- 构建 prompts（research=None，纯前向） ----
    events = load_events(args.events)
    if args.n > 0:
        events = events[:args.n]
    print(f"[GEN] events={len(events)} side={args.side}", flush=True)

    rows = []
    for e in events:
        msgs = build_messages_for_papv(e, research=None)
        prompt = render_prompt(tok, msgs)
        rows.append({"event": e, "prompt": prompt})

    # 样例预览
    print(f"[GEN] prompt 样例（尾 300 字符）：\n...{rows[0]['prompt'][-300:]}", flush=True)

    # ---- vLLM ----
    engine_kwargs = dict(
        model=BASE_MODEL, max_model_len=args.max_model_len,
        gpu_memory_utilization=0.85, dtype="bfloat16",
        enforce_eager=True,  # 跳过 CUDA graph 编译（避免 ninja PATH 问题）
    )
    lora_req = None
    if args.side == "adapter":
        engine_kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1)
        lora_req = LoRARequest("papv", 1, args.adapter)
        print(f"[GEN] LoRA loaded from {args.adapter}", flush=True)

    print(f"[GEN] init vLLM (side={args.side})", flush=True)
    llm = LLM(**engine_kwargs)
    sp = SamplingParams(max_tokens=args.max_tokens, temperature=args.temperature)

    # ---- 批量生成 ----
    t0 = time.time()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(0, len(rows), args.batch):
            chunk = rows[i:i + args.batch]
            prompts = [r["prompt"] for r in chunk]
            outs = llm.generate(prompts, sp, lora_request=lora_req)
            for r, o in zip(chunk, outs):
                e = r["event"]
                eid = e.get("event_id", "")
                comp = o.outputs[0].text
                claims = parse_claims(comp)
                f.write(json.dumps({
                    "event_id": eid,
                    "symbol": e.get("symbol"),
                    "market": e.get("market"),
                    "event_date": e.get("event_date"),
                    "event_type_l2": e.get("event_type_l2"),
                    "_window": e.get("_window"),
                    "side": args.side,
                    "completion": comp,
                    "claims": claims,
                    "n_claims": len(claims),
                }, ensure_ascii=False) + "\n")
            done = min(i + args.batch, len(rows))
            el = time.time() - t0
            print(f"[GEN] {done}/{len(rows)} ({el:.0f}s, {el/done:.2f}s/条)  "
                  f"claims均={sum(len(parse_claims(o.outputs[0].text)) for o in outs)/len(outs):.1f}",
                  flush=True)

    print(f"[DONE] → {out_path}", flush=True)

    # ---- 汇总 ----
    n_total_claims = 0
    n_rows = 0
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            n_total_claims += r["n_claims"]
            n_rows += 1
    print(f"[SUM] rows={n_rows} claims={n_total_claims} "
          f"均={n_total_claims/n_rows:.1f} claims/event", flush=True)


if __name__ == "__main__":
    main()
