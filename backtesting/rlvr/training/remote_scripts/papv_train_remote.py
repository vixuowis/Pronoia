"""papv_train_remote.py — Pronoia-PAPV GRPO 训练（远程 48GB GPU）。

范式：预测-断言-事后验证（PAPV）
  · 输入：事件 + 前置研究上下文 + 可断言指标面板（任意指标进输入，只给定义不给数值）
  · 输出：模型自主提出 3~6 条可验证断言（CLAIM）+ TRUE/FALSE 判断 + 置信度 + 逻辑链
  · Reward：labels.jsonl 客观结算 → 断言判断准确性（核心）+ 置信度校准 + 可验证性/多样性

与旧范式（grpo_train_remote.py）的差异：
  · 不再输出 direction+confidence，不再用 CAR/RET 方向做后向校验；
  · 任意指标都可断言（car/ret/bm_ret/pvalue/avg 系列 × t1~t60），模型自主选择；
  · 核心度量 = 断言提得准不准（accuracy + calibration）。

复用：
  · _patch_rollout_generation：trl 0.17 梯度检查点 × KV cache 乱码修复（已验证）
  · MoE：expert_rft_dataset_mask 场景过滤 + router_prior 进 prompt（架构不变）
  · 数据：events_enriched.jsonl / labels.jsonl / research_cache.jsonl（已上传远程）

用法（远程机器）：
  /root/miniconda3/bin/python papv_train_remote.py \
      --data-dir /root/pronoia/data_v2 --expert mixed \
      --max-samples 0 --epochs 1 --out-dir /root/pronoia/papv_full
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS.parent))          # training/（papv_claims 等模块所在）

from papv_claims import METRIC_PANEL                        # noqa: E402
from reward_fn_papv import compute_papv_reward              # noqa: E402
from prompt_template_papv import build_messages_for_papv    # noqa: E402
from expert_definitions import (                            # noqa: E402
    EXPERT_IDS, DEFAULT_HPARAMS, expert_rft_dataset_mask,
)

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
    """预渲染 prompt 字符串（Qwen3 关闭 thinking，插入空 think 块）。"""
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
        # 至少 2 个指标可结算（保证 PAPV 结算有信号）
        n_settle = sum(1 for m in METRIC_PANEL if isinstance(lb.get(m), (int, float)))
        if n_settle < 2:
            continue
        if expert != "mixed" and not expert_rft_dataset_mask(expert, e):
            continue
        rc = rcs.get(eid)
        msgs = build_messages_for_papv(e, research=rc)
        prompt_val = render_prompt_str(tok, msgs) if tok is not None else msgs
        rows.append({
            "prompt": prompt_val,
            "_event_json": json.dumps(e, ensure_ascii=False),
            "_label_json": json.dumps(lb, ensure_ascii=False),
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
    if isinstance(comp, list):
        parts = [m.get("content", "") if isinstance(m, dict) else str(m) for m in comp]
        return "\n".join(p for p in parts if p)
    return str(comp)


def make_papv_reward_fn():
    def reward_fn(completions, prompts=None, completion_ids=None, **kwargs):
        label_jsons = kwargs.get("_label_json") or []
        event_jsons = kwargs.get("_event_json") or []
        rewards = []
        for i, comp in enumerate(completions):
            try:
                lb = json.loads(label_jsons[i]) if i < len(label_jsons) else {}
            except Exception:
                lb = {}
            try:
                ev = json.loads(event_jsons[i]) if i < len(event_jsons) else {}
            except Exception:
                ev = {}
            text = _completion_to_text(comp)
            try:
                r = compute_papv_reward(text, ev, lb)
                rewards.append(float(r["reward"]))
            except Exception:
                rewards.append(-0.2)
        return rewards

    reward_fn.__name__ = "papv_claim_settlement_reward"
    return reward_fn


# ---------------- rollout 乱码修复（已验证，勿动） ----------------
def _patch_rollout_generation(gradient_checkpointing_kwargs=None):
    """trl 0.17 GRPO rollout 乱码修复：梯度检查点 × KV cache 冲突。

    GenerationConfig 未设 use_cache（默认 True），而梯度检查点下
    Qwen3DecoderLayer 丢弃 KV cache 写入 → 增量解码状态损坏 → rollout 乱码。
    修复：rollout 期间临时关闭梯度检查点 + eval + 启用 cache；结束后恢复。
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


# ---------------- 训练 ----------------
def run_expert(expert: str, rows: list[dict], args) -> Path:
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    out_dir = Path(args.out_dir) / f"papv_{expert}"
    out_dir.mkdir(parents=True, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ds_rows = []
    for r in rows:
        if isinstance(r["prompt"], list):
            r = {**r, "prompt": render_prompt_str(tok, r["prompt"])}
        ds_rows.append(r)
    ds = Dataset.from_list(ds_rows)
    print(f"[DATA] prompt 预渲染完成，样例（尾 250 字符）：\n...{ds_rows[0]['prompt'][-250:]}")

    hp = DEFAULT_HPARAMS
    gen_bs = args.per_device_batch_size * args.grad_accum
    assert gen_bs % args.num_generations == 0, (
        f"generation_batch_size({gen_bs}) 必须能被 num_generations({args.num_generations}) 整除")

    cfg = GRPOConfig(
        output_dir=str(out_dir),
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
        num_generations=args.num_generations,
        max_prompt_length=args.max_prompt_length,
        max_completion_length=args.max_completion_length,
        temperature=1.0,
        top_p=1.0,
        beta=0.04,
        loss_type="grpo",
        scale_rewards=True,
        mask_truncated_completions=True,
        log_completions=getattr(args, "log_completions", False),
        num_completions_to_print=3,
        report_to="none",
        seed=args.seed,
        **(
            dict(use_vllm=True, vllm_gpu_memory_utilization=args.vllm_mem_util)
            if args.use_vllm else {}
        ),
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
        reward_funcs=make_papv_reward_fn(),
        peft_config=lora_cfg,
        processing_class=tok,
    )
    _patch_rollout_generation(cfg.gradient_checkpointing_kwargs)
    trainer.train()
    trainer.save_model(str(out_dir))
    tok.save_pretrained(str(out_dir))
    print(f"[DONE] expert={expert} PAPV LoRA → {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--expert", default="mixed",
                    help=f"mixed=不过滤；all=6 专家顺序跑；或单个：{'/'.join(EXPERT_IDS)}")
    ap.add_argument("--max-samples", type=int, default=0, help="0=全量")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--num-generations", type=int, default=4, help="GRPO group size G")
    ap.add_argument("--per-device-batch-size", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--lora-rank", type=int, default=16)
    ap.add_argument("--log-completions", action="store_true")
    ap.add_argument("--save-steps", type=int, default=200, help="每 N 步存 checkpoint（0=按 epoch）")
    ap.add_argument("--max-prompt-length", type=int, default=2304)
    ap.add_argument("--max-completion-length", type=int, default=1280)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--use-vllm", action="store_true", help="vLLM colocate rollout（提速 2-4x）")
    ap.add_argument("--vllm-mem-util", type=float, default=0.25, help="vLLM colocate 显存占比")
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
