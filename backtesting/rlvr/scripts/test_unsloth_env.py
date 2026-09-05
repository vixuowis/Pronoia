"""unsloth 环境冒烟测试：加载 Qwen3-8B + 进程内 vLLM + LoRA。"""
import os
os.environ["UNSLOTH_VLLM_STANDBY"] = "1"

from unsloth import FastLanguageModel  # noqa: E402

model, tok = FastLanguageModel.from_pretrained(
    model_name="/root/Qwen3-8B",
    max_seq_length=3072,
    load_in_4bit=False,
    fast_inference=True,
    max_lora_rank=16,
    gpu_memory_utilization=0.9,
)
print("[SMOKE] model + vLLM loaded OK", flush=True)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=32,
    lora_dropout=0.05,
    use_gradient_checkpointing="unsloth",
    random_state=42,
)
print("[SMOKE] LoRA attached OK", flush=True)

# chat template 渲染验证（与训练路径一致）
msgs = [{"role": "user", "content": "hello"}]
s = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                            enable_thinking=False)
print(f"[SMOKE] chat template OK, len={len(s)}", flush=True)

# 快速生成验证
FastLanguageModel.for_inference(model)
out = model.fast_generate(s, max_new_tokens=32, temperature=1.0)
print(f"[SMOKE] generate OK: {out[0].outputs[0].text[:120]!r}", flush=True)
print("[SMOKE] ALL PASS", flush=True)
