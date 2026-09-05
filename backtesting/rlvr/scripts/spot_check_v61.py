"""spot_check_v61.py — 抽检 checkpoint-800：test 分区 3 样本生成 + 结算明细。

显存注意：训练占 31GB，本脚本用 4bit 量化加载（~6GB）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training")
sys.path.insert(0, "/root/Pronoia/backtesting/rlvr/training/remote_scripts")

from papv_claims import parse_claims, settle_all  # noqa: E402
from prompt_template_papv import build_messages_for_papv          # noqa: E402

from unsloth import FastLanguageModel  # noqa: E402

CKPT = "/root/Pronoia/pronoia_run/papv_v61/papv_mixed/checkpoint-800"
TEST = Path("/root/Pronoia/pronoia_run/data_v61_test")


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def pick_samples():
    evs = read_jsonl(TEST / "events_enriched.jsonl")
    lbs = {str(l["event_id"]): l for l in read_jsonl(TEST / "labels.jsonl")}
    # 1) US 宏观  2) CN 个股  3) 难负（程序性正面事件）
    macro = ("增长/就业数据意外", "通胀数据意外", "政策利率调整")
    us = next(e for e in evs if e.get("market") == "US" and e.get("event_type_l2") in macro)
    cn = next(e for e in evs if e.get("market") == "CN" and e.get("event_type_l2") not in macro)
    import re
    hard_re = re.compile(r"中标|扭亏|预增|定增获通过|不向下修正|收购进展")
    hard = next(e for e in evs if hard_re.search(str(e.get("title", "")) or ""))
    return [(us, lbs[str(us["event_id"])]),
            (cn, lbs[str(cn["event_id"])]),
            (hard, lbs[str(hard["event_id"])])]


def main():
    model, tok = FastLanguageModel.from_pretrained(
        model_name=CKPT,           # adapter 目录（含 base 指向）
        max_seq_length=3072,
        load_in_4bit=True,
        fast_inference=False,      # 无独立显存起 vLLM，用 HF 路径抽检
    )
    FastLanguageModel.for_inference(model)

    for ev, lb in pick_samples():
        print("=" * 80, flush=True)
        print(f"[EVENT] {ev.get('market')} | {ev.get('event_type')} | {str(ev.get('title',''))[:60]}", flush=True)
        print(f"[TIME] {ev.get('event_time', ev.get('datetime',''))}", flush=True)

        msgs = build_messages_for_papv(ev, research=None)
        inputs = tok.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=True,
            return_tensors="pt", return_dict=True, enable_thinking=False,
        )
        out = model.fast_generate(**inputs.to("cuda"), max_new_tokens=768, temperature=1.0)
        if hasattr(out[0], "outputs"):          # vLLM 路径返回对象
            text = out[0].outputs[0].text
        else:                                   # HF 路径返回 token 张量
            import torch
            if isinstance(out, torch.Tensor):
                seq = out[0]
            else:
                seq = out.sequences[0] if hasattr(out, "sequences") else out[0]
            n_in = inputs["input_ids"].shape[1]
            text = tok.decode(seq[n_in:], skip_special_tokens=True)
        print(f"[COMPLETION] ({len(text)} chars):\n{text}", flush=True)

        claims = parse_claims(text)
        print(f"\n[PARSED] {len(claims)} 条断言", flush=True)
        st = settle_all(claims, lb)
        from papv_claims import settle_claim_truth
        for c in claims:
            truth = settle_claim_truth(c, lb)
            print(f"  - {c.get('metric')} judge={c.get('judge')} conf={c.get('conf')}"
                  f" | truth={truth} {'✓' if truth == c.get('judge') else '✗'}", flush=True)
        print(f"[SETTLE] 可结算 {st['settleable']}/{st['n_claims']}，"
              f"命中 {st['correct']}，acc={st['accuracy']}", flush=True)


if __name__ == "__main__":
    main()
