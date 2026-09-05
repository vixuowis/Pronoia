"""gen_batch_test.py — 隔离 GRPO rollout 乱码的真实根因。

与 GRPOTrainer 生成路径的差异因子：
  E) fp32 + use_cache=False + grad-ckpt + batch4 左填充 + train  （复刻 trainer 路径）
  F) bf16 + use_cache=False + grad-ckpt + batch4 + train          （隔离 dtype）
  G) bf16 + use_cache=True  + grad-ckpt + batch4 + train          （隔离 KV cache）
"""
import sys
sys.path.insert(0, "/root/pronoia")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model
from grpo_train_remote import load_dataset_rows
from pathlib import Path

BASE = "/root/Qwen3-8B"
tok = AutoTokenizer.from_pretrained(BASE)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
rows = load_dataset_rows(Path("/root/pronoia/data"), "mixed", 4, tok=tok)
prompts = [r["prompt"] for r in rows]
enc = tok(prompts, return_tensors="pt", padding=True, padding_side="left",
          add_special_tokens=False)
enc = {k: v.to("cuda") for k, v in enc.items()}


def load_model(dtype):
    m = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=dtype, device_map="cuda:0")
    lora_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                          target_modules="all-linear", bias="none", task_type="CAUSAL_LM")
    m = get_peft_model(m, lora_cfg)
    return m


def gen(tag, model, use_cache):
    model.config.use_cache = use_cache
    old = model.generation_config.use_cache if model.generation_config else None
    if model.generation_config:
        model.generation_config.use_cache = use_cache
    torch.manual_seed(42)
    try:
        out = model.generate(
            **enc, max_new_tokens=120, do_sample=True, temperature=1.0, top_p=1.0,
            pad_token_id=tok.pad_token_id,
        )
        for i in range(out.shape[0]):
            text = tok.decode(out[i][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            flag = "OK" if ("【0" in text or "【0." in text or "【" in text) else "GARBAGE?"
            print(f"[{tag} #{i}] {flag}: {text[:90].replace(chr(10), ' | ')}")
    except Exception as e:
        print(f"[{tag}] ERROR: {e}")
    finally:
        if model.generation_config and old is not None:
            model.generation_config.use_cache = old
    print()


# E) fp32 + no cache + grad ckpt + batch4 + train（复刻 trainer）
m = load_model(torch.float32)
m.gradient_checkpointing_enable()
m.train()
gen("E-fp32-nocache-gc-train-b4", m, False)
del m; torch.cuda.empty_cache()

# F) bf16 + no cache + grad ckpt + batch4 + train
m = load_model(torch.bfloat16)
m.gradient_checkpointing_enable()
m.train()
gen("F-bf16-nocache-gc-train-b4", m, False)
del m; torch.cuda.empty_cache()

# G) bf16 + cache + grad ckpt + batch4 + train
m = load_model(torch.bfloat16)
m.gradient_checkpointing_enable()
m.train()
gen("G-bf16-cache-gc-train-b4", m, True)
del m; torch.cuda.empty_cache()

print("DONE_BATCH_TEST")
