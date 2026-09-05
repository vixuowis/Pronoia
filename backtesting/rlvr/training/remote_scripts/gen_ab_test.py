"""gen_ab_test.py — 远程诊断：定位 GRPO rollout 乱码根因。

A) base eval        : 基座模型 + eval 模式（期望：正常）
B) lora train+drop  : LoRA(dropout=0.05) + train 模式（假设：乱码）
C) lora eval        : LoRA(dropout=0.05) + eval 模式（期望：正常）
D) lora train nodrop: LoRA(dropout=0.0)  + train 模式（期望：正常 → 修复方案）
"""
import sys
sys.path.insert(0, "/root/pronoia")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model
from grpo_train_remote import load_dataset_rows, render_prompt_str
from pathlib import Path

BASE = "/root/Qwen3-8B"
tok = AutoTokenizer.from_pretrained(BASE)
rows = load_dataset_rows(Path("/root/pronoia/data"), "mixed", 1, tok=tok)
prompt = rows[0]["prompt"]
ids = tok(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")

model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map="cuda:0"
)
model.config.use_cache = True


def gen(tag: str):
    torch.manual_seed(42)
    out = model.generate(
        **ids, max_new_tokens=200, do_sample=True, temperature=1.0, top_p=1.0,
        pad_token_id=tok.pad_token_id or tok.eos_token_id,
    )
    text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    print(f"\n===== {tag} =====")
    print(text[:400].replace("\n", " | "))


# A) base eval
model.eval()
gen("A-base-eval")

# B) LoRA + dropout 0.05 + train
lora_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                      target_modules="all-linear", bias="none", task_type="CAUSAL_LM")
model = get_peft_model(model, lora_cfg)
model.train()
gen("B-lora-train-drop005")

# C) LoRA + eval
model.eval()
gen("C-lora-eval")

# D) LoRA dropout=0 + train（修复方案验证）
model = model.unload()
model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map="cuda:0"
)
model.config.use_cache = True
lora_cfg0 = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0,
                       target_modules="all-linear", bias="none", task_type="CAUSAL_LM")
model = get_peft_model(model, lora_cfg0)
model.train()
gen("D-lora-train-drop000")
print("\nDONE_AB_TEST")
