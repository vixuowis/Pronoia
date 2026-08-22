"""grpo_train_remote.py — Pronoia-RLVR STEP2 GRPO 训练（远程 48GB GPU 真实可跑版）。

架构落地（MoE = 输出融合）：
  · 每位专家一个 LoRA，在自己的场景子集上跑 GRPO（--expert <id>）；
  · 训练时 prompt 内置 router_prior_weights（无参数 Router 的先验权重）；
  · 推理时由 Router 对 K 个专家的输出加权融合（输出级 MoE，无需自定义 forward）。

数据（--data-dir 下）：
  events.jsonl          事件（含四维量价特征）
  labels.jsonl          真实 K 线标签（car_tXX / ret_tXX / label_tXX）
  research_cache.jsonl  前置研究上下文（Tier 1 Experts 离线预计算，GRPO 不再跑工具）

用法（远程机器）：
  /root/miniconda3/bin/python grpo_train_remote.py \
      --data-dir /root/autodl-tmp/rlvr/data/v2 \
      --expert mixed --max-samples 64 --epochs 1 \
      --out-dir /root/autodl-tmp/rlvr/grpo_smoke

依赖：torch 2.6 / trl 0.17 / peft 0.15 / transformers 4.55（远程已装）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
_SCRIPTS = _THIS.parent.parent / "scripts"
if _SCRIPTS.exists():
    sys.path.insert(0, str(_SCRIPTS))

from reward_fn import compute_reward                      # noqa: E402
from expert_definitions import (                          # noqa: E402
    EXPERT_IDS, DEFAULT_HPARAMS, expert_rft_dataset_mask,
)
from prompt_template import build_prompt_completion_for_grpo  # noqa: E402

BASE_MODEL = "/root/Qwen3-8B"


# ---------------- 数据 ----------------
def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return rows


def render_prompt_str(tok, messages: list[dict]) -> str:
    """预渲染 prompt 字符串（Qwen3 关闭 thinking）。

    关键：Qwen3 hybrid-thinking 模板默认让模型自生成 <think> 块（会吃光 completion 预算），
    enable_thinking=False 时模板显式插入空 <think>\\n\\n</think>，生成立即进入正文。
    trl 对「字符串 prompt」不再二次套 chat template，故预渲染即生效。
    """
    return tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )


def load_dataset_rows(data_dir: Path, expert: str, max_samples: int,
                      tok=None) -> list[dict]:
    ev_path = data_dir / "events_enriched.jsonl"
    if not ev_path.exists():
        ev_path = data_dir / "events.jsonl"
    evs = _read_jsonl(ev_path)
    lbs = {str(l.get("event_id") or ""): l for l in _read_jsonl(data_dir / "labels.jsonl")}
    rcs = {str(r.get("event_id") or ""): r for r in _read_jsonl(data_dir / "research_cache.jsonl")}
    print(f"[DATA] events={len(evs)} labels={len(lbs)} research_cache={len(rcs)}")

    rows = []
    for e in evs:
        eid = str(e.get("event_id") or "")
        lb = lbs.get(eid)
        if lb is None:
            continue
        # 有效标签：主 horizon 方向非空（reward R1 需要）
        if not any(lb.get(f"label_{h}") for h in ("t3", "t7", "t15", "t30", "t60")):
            continue
        if expert != "mixed" and not expert_rft_dataset_mask(expert, e):
            continue
        rc = rcs.get(eid)
        pc = build_prompt_completion_for_grpo(e, research=rc)
        prompt_val = pc["messages"]
        if tok is not None:
            prompt_val = render_prompt_str(tok, prompt_val)
        rows.append({
            "prompt": prompt_val,
            "_event_json": json.dumps(e, ensure_ascii=False),
            "_label_json": json.dumps(lb, ensure_ascii=False),
            "_router_prior": json.dumps(pc["_router_prior"], ensure_ascii=False),
            "_primary_h": pc["_scene_primary_h"],
        })
    print(f"[DATA] expert={expert} 过滤后样本：{len(rows)}")
    if max_samples > 0:
        rows = rows[:max_samples]
        print(f"[DATA] 截断到 max_samples={max_samples}")
    if not rows:
        raise SystemExit("no usable rows")
    return rows


# ---------------- Reward ----------------
def _completion_to_text(comp) -> str:
    """trl 传入的 completion：conversational 时为 [{"role":"assistant","content":...}]，否则 str。"""
    if isinstance(comp, list):
        parts = [m.get("content", "") if isinstance(m, dict) else str(m) for m in comp]
        return "\n".join(p for p in parts if p)
    return str(comp)


def make_reward_fn(hp):
    lb_cache: dict[str, dict] = {}

    def reward_fn(completions, prompts=None, completion_ids=None, **kwargs):
        eids = kwargs.get("_event_json") or []
        label_jsons = kwargs.get("_label_json") or []
        router_priors = kwargs.get("_router_prior") or []
        rewards = []
        for i, comp in enumerate(completions):
            try:
                e = json.loads(eids[i]) if i < len(eids) else {}
            except Exception:
                e = {}
            try:
                lb = json.loads(label_jsons[i]) if i < len(label_jsons) else {}
            except Exception:
                lb = {}
            try:
                rw = json.loads(router_priors[i]) if i < len(router_priors) else {}
            except Exception:
                rw = {}
            if rw and isinstance(rw, dict):
                e["_router_weights"] = rw
            text = _completion_to_text(comp)
            try:
                r = compute_reward(text, e, lb, hp)
                rewards.append(float(r["reward"]))
            except Exception:
                rewards.append(-1.0)
        return rewards

    reward_fn.__name__ = "pronoia_seven_component_reward"
    return reward_fn


# ---------------- 训练 ----------------
def _patch_rollout_generation(gradient_checkpointing_kwargs=None):
    """修复 trl 0.17 GRPO rollout 乱码（Qwen3 + 梯度检查点 + PEFT）。

    根因：GRPOTrainer 构造的 GenerationConfig 未设 use_cache（默认 True），
    而梯度检查点开启时 Qwen3DecoderLayer 丢弃 KV cache 写入（past_key_value=None），
    增量解码状态损坏 → rollout 输出乱码 token。
    修复：rollout 期间临时 关闭梯度检查点 + eval 模式 + 启用 KV cache；结束后恢复。
    （对照实验：cache+无检查点=干净；无cache+检查点=干净但 O(L²) 慢；cache+检查点=乱码）
    """
    import trl.trainer.grpo_trainer as gt
    orig = gt.unwrap_model_for_generation

    @contextmanager
    def patched(model, accelerator, gather_deepspeed3_params=True):
        with orig(model, accelerator, gather_deepspeed3_params=gather_deepspeed3_params) as unwrapped:
            unwrapped.gradient_checkpointing_disable()
            unwrapped.config.use_cache = True
            unwrapped.eval()
            try:
                yield unwrapped
            finally:
                unwrapped.train()
                unwrapped.config.use_cache = False
                unwrapped.gradient_checkpointing_enable(
                    gradient_checkpointing_kwargs=gradient_checkpointing_kwargs
                )

    gt.unwrap_model_for_generation = patched
    return orig


def run_expert(expert: str, rows: list[dict], args) -> Path:
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    out_dir = Path(args.out_dir) / f"grpo_{expert}"
    out_dir.mkdir(parents=True, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    # prompt 预渲染（含 Qwen3 空 think 块，关闭深度思考）
    ds_rows = []
    for r in rows:
        if isinstance(r["prompt"], list):
            r = {**r, "prompt": render_prompt_str(tok, r["prompt"])}
        ds_rows.append(r)
    ds = Dataset.from_list(ds_rows)
    print(f"[DATA] prompt 预渲染完成，样例（尾 200 字符）：\n...{ds_rows[0]['prompt'][-200:]}")

    hp = DEFAULT_HPARAMS
    gen_bs = args.per_device_batch_size * args.grad_accum   # 每步生成 completions 总数
    assert gen_bs % args.num_generations == 0, (
        f"generation_batch_size({gen_bs}) 必须能被 num_generations({args.num_generations}) 整除")

    cfg = GRPOConfig(
        output_dir=str(out_dir),
        # bf16 加载基座（默认 fp32 会占 32GB+ 且慢一倍）
        model_init_kwargs={"torch_dtype": "bfloat16"},
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        weight_decay=hp.weight_decay,
        max_grad_norm=hp.max_grad_norm,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="steps" if args.save_steps > 0 else "epoch",
        save_steps=args.save_steps if args.save_steps > 0 else 500,
        save_total_limit=2,
        bf16=True,
        gradient_checkpointing=True,
        # GRPO 核心
        num_generations=args.num_generations,          # group size G
        max_prompt_length=2048,
        max_completion_length=1024,
        temperature=1.0,
        top_p=1.0,
        beta=0.04,                                     # KL 系数
        loss_type="grpo",
        scale_rewards=True,
        mask_truncated_completions=True,               # 丢弃打满长度未终止的 completion
        log_completions=getattr(args, "log_completions", False),
        num_completions_to_print=3,
        # vLLM 加速 rollout（trl 0.17 仅支持外部 server 模式：先启动 `trl vllm-serve --model /root/Qwen3-8B`）
        **({"use_vllm": True,
            "vllm_gpu_memory_utilization": 0.35,
            "vllm_max_model_len": 4096} if args.use_vllm else {"use_vllm": False}),
        report_to="none",
        seed=args.seed,
    )

    lora_cfg = LoraConfig(
        r=args.lora_rank, lora_alpha=args.lora_rank * 2,
        lora_dropout=0.05, target_modules="all-linear",
        bias="none", task_type="CAUSAL_LM",
    )

    trainer = GRPOTrainer(
        model=BASE_MODEL,
        args=cfg,
        train_dataset=ds,
        reward_funcs=make_reward_fn(hp),
        peft_config=lora_cfg,
        processing_class=tok,
    )
    # rollout 乱码修复补丁（见 _patch_rollout_generation docstring）
    _patch_rollout_generation(cfg.gradient_checkpointing_kwargs)
    trainer.train()
    trainer.save_model(str(out_dir))
    tok.save_pretrained(str(out_dir))
    print(f"[DONE] expert={expert} LoRA → {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--expert", default="mixed",
                    help=f"mixed=不过滤（smoke）；all=6 专家顺序跑；或单个：{'/'.join(EXPERT_IDS)}")
    ap.add_argument("--max-samples", type=int, default=0, help="0=全量")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--num-generations", type=int, default=4, help="GRPO group size G")
    ap.add_argument("--per-device-batch-size", type=int, default=8, help="每卡 completions/step")
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--lora-rank", type=int, default=16)
    ap.add_argument("--use-vllm", action="store_true", help="vLLM colocate 加速 rollout")
    ap.add_argument("--log-completions", action="store_true", help="打印生成样本（调试）")
    ap.add_argument("--save-steps", type=int, default=0, help="每 N 步存 checkpoint（0=按 epoch）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    experts = EXPERT_IDS if args.expert == "all" else [args.expert]
    for ex in experts:
        if ex not in EXPERT_IDS and ex != "mixed":
            raise SystemExit(f"unknown expert: {ex}")
        rows = load_dataset_rows(data_dir, ex, args.max_samples)
        run_expert(ex, rows, args)


if __name__ == "__main__":
    main()
