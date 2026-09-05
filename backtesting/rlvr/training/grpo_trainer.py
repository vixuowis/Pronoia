"""grpo_trainer.py — Pronoia-RLVR §3.5 GRPO MoE 训练封装（trl 兼容）。

训练两步走：
  STEP 1 · RFT 单专家监督微调：对每位专家 LoRA 单独跑 2 epochs SFT
           （用 expert_rft_dataset_mask 过滤其场景样本）
  STEP 2 · GRPO MoE：加载 K 个 RFT 初始化后的 LoRA，合并到同一模型，
           用无参数 Router 动态加权，跑 3 epochs GRPO（group size=4）。

依赖（需要 pip 安装，训练环境才有）：
    pip install transformers datasets peft trl accelerate

本文件设计为「伪代码 + 真实可运行骨架」：
  · 如果检测到依赖齐全 → 真实运行；
  · 否则 → 进入 dry-run 模式，只做数据流水线 & reward 计算 smoke test，
           并打印需要的 shell 命令。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))
_SCRIPTS = _THIS.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from expert_definitions import (                                  # noqa: E402
    EXPERT_IDS, EXPERT_SPECS, DEFAULT_HPARAMS, RLVRHyperparams,
    expert_rft_dataset_mask,
)
from prompt_template import (                                     # noqa: E402
    build_messages_for_sft, build_prompt_completion_for_grpo,
)
from reward_fn import compute_reward                              # noqa: E402


# ====================== 依赖检测 ======================
def _check_deps(dep_names: list[str]) -> bool:
    for d in dep_names:
        try:
            __import__(d)
        except Exception:
            return False
    return True


HAS_TRAIN_DEPS = _check_deps(["transformers", "datasets", "peft", "trl", "accelerate"])


# ====================== 数据加载辅助 ======================
def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: continue
    return rows


def load_pair(events_path: Path, labels_path: Path) -> tuple[list[dict], list[dict]]:
    evs = _read_jsonl(events_path)
    lbs = _read_jsonl(labels_path)
    lb_map = {str(lb.get("event_id") or ""): lb for lb in lbs}
    # 配对：只有两条都有才留
    matched = []
    for e in evs:
        eid = str(e.get("event_id") or "")
        lb = lb_map.get(eid)
        if lb is None: continue
        matched.append((e, lb))
    return [m[0] for m in matched], [m[1] for m in matched]


# ====================== STEP 1 · RFT ======================
def run_step1_rft(expert_id: str, events: list[dict], labels: list[dict],
                   out_dir: Path, hp: RLVRHyperparams, dry_run: bool) -> Path:
    """对单个专家跑 RFT（SFT）。返回 LoRA 输出目录。"""
    print(f"\n{'='*60}")
    print(f"[STEP1 RFT] expert = {expert_id}")
    print(f"{'='*60}")
    spec = EXPERT_SPECS[expert_id]

    # 数据过滤：按场景挑该专家的训练样本
    paired = [(e, lb) for e, lb in zip(events, labels)
              if expert_rft_dataset_mask(expert_id, e)]
    print(f"[RFT] 过滤后样本数：{len(paired)} / {len(events)} 总")
    if len(paired) < 32:
        print(f"[WARN] 样本不足 32，RFT 可能不稳定；继续（dry_run 模式不影响）")

    # 构造 messages 格式数据集
    ds_messages = []
    for e, lb in paired:
        ds_messages.append({
            "event_id": e.get("event_id"),
            "messages": build_messages_for_sft(e, lb),
        })
    print(f"[RFT] messages 数据集构造完成：{len(ds_messages)} 条")

    expert_out = out_dir / f"step1_rft_{expert_id}"

    if dry_run or not HAS_TRAIN_DEPS:
        # dry-run：存前 3 条 messages 到 JSON 供检查，然后返回
        expert_out.mkdir(parents=True, exist_ok=True)
        with open(expert_out / "dryrun_messages_sample.json", "w", encoding="utf-8") as f:
            json.dump(ds_messages[:3], f, ensure_ascii=False, indent=2)
        print(f"[DRYRUN] 保存 messages sample → {expert_out / 'dryrun_messages_sample.json'}")
        print(f"[DRYRUN] 真实训练命令：")
        print(f"""
  accelerate launch --multi_gpu --num_processes=1 <<PYEOF
  from transformers import AutoModelForCausalLM, AutoTokenizer
  from datasets import Dataset
  from peft import LoraConfig, get_peft_model
  from trl import SFTTrainer, SFTConfig

  model_name = "{hp.base_model}"
  model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto", torch_dtype="bfloat16")
  tok = AutoTokenizer.from_pretrained(model_name); tok.pad_token = tok.eos_token

  lcfg = LoraConfig(
      r={spec.rank}, lora_alpha={spec.lora_alpha}, lora_dropout={spec.lora_dropout},
      target_modules={spec.target_modules},
      bias="none", task_type="CAUSAL_LM",
  )
  model = get_peft_model(model, lcfg)
  ds = Dataset.from_list({json.dumps(ds_messages[:2], ensure_ascii=False)[:80]}...)  # 省略，真实代码 load {expert_out}/msgs.jsonl

  cfg = SFTConfig(
      output_dir="{expert_out}",
      num_train_epochs={hp.num_train_epochs_rft},
      per_device_train_batch_size={hp.train_batch_size},
      gradient_accumulation_steps={hp.gradient_accumulation_steps},
      learning_rate={hp.learning_rate}, weight_decay={hp.weight_decay},
      max_grad_norm={hp.max_grad_norm}, logging_steps=10, save_strategy="epoch",
      max_seq_length={hp.max_seq_len},
  )
  trainer = SFTTrainer(model=model, tokenizer=tok, args=cfg, train_dataset=ds)
  trainer.train()
  trainer.save_model("{expert_out}")
PYEOF
""")
        return expert_out

    # ====== 真实训练路径（依赖齐全）======
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from trl import SFTTrainer, SFTConfig

    expert_out.mkdir(parents=True, exist_ok=True)
    # 把完整 messages 写入 jsonl 给 Dataset.from_json 用
    msgs_p = expert_out / "messages_train.jsonl"
    with open(msgs_p, "w", encoding="utf-8") as f:
        for m in ds_messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    ds = Dataset.from_json(str(msgs_p))

    model = AutoModelForCausalLM.from_pretrained(
        hp.base_model, device_map="auto",
        torch_dtype="bfloat16", attn_implementation="flash_attention_2",
    )
    tok = AutoTokenizer.from_pretrained(hp.base_model)
    tok.pad_token = tok.eos_token

    lcfg = LoraConfig(
        r=spec.rank, lora_alpha=spec.lora_alpha, lora_dropout=spec.lora_dropout,
        target_modules=spec.target_modules,
        bias="none", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lcfg)

    cfg = SFTConfig(
        output_dir=str(expert_out),
        num_train_epochs=hp.num_train_epochs_rft,
        per_device_train_batch_size=hp.train_batch_size,
        gradient_accumulation_steps=hp.gradient_accumulation_steps,
        learning_rate=hp.learning_rate, weight_decay=hp.weight_decay,
        max_grad_norm=hp.max_grad_norm, logging_steps=10, save_strategy="epoch",
        max_seq_length=hp.max_seq_len,
    )
    trainer = SFTTrainer(model=model, args=cfg, tokenizer=tok, train_dataset=ds)
    trainer.train()
    trainer.model.save_pretrained(str(expert_out))
    tok.save_pretrained(str(expert_out))
    return expert_out


# ====================== STEP 2 · GRPO ======================
def run_step2_grpo_moe(events: list[dict], labels: list[dict],
                        step1_lora_dirs: dict[str, Path],
                        out_dir: Path, hp: RLVRHyperparams, dry_run: bool) -> Path:
    """GRPO MoE：K 专家 LoRA 并行 + 无参数 Router 加权融合。"""
    print(f"\n{'='*60}")
    print(f"[STEP2 GRPO MoE] experts = {EXPERT_IDS}")
    print(f"{'='*60}")
    print(f"[GRPO] 训练样本数：{len(events)}，group_size={hp.num_rollouts_per_event}")
    grpo_out = out_dir / "step2_grpo_moe"

    # 先做 reward_fn 的 smoke test：随机取 3 条样本，completion 用 RFT reference 跑 reward
    print("[GRPO] reward_fn smoke test（3 条，completion = RFT reference）...")
    from prompt_template import build_input_block, build_rft_reference
    samples = []
    for i in range(min(3, len(events))):
        e = events[i]; lb = labels[i]
        block = build_input_block(e, lb, include_ground_truth=True)
        comp = build_rft_reference(block, strict=True)
        r = compute_reward(comp, e, lb, hp)
        samples.append({
            "event_id": e.get("event_id"),
            "reward_scaled": r["reward"],
            "reward_raw":   r["reward_raw"],
            "R_components":  r["R_components"],
            "diagnostics":   r["diagnostics"],
        })
    print("[GRPO] reward smoke test 结果：")
    print(json.dumps(samples, ensure_ascii=False, indent=2))

    if dry_run or not HAS_TRAIN_DEPS:
        grpo_out.mkdir(parents=True, exist_ok=True)
        with open(grpo_out / "dryrun_reward_smoke.json", "w", encoding="utf-8") as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
        print(f"[DRYRUN] reward 样本 → {grpo_out / 'dryrun_reward_smoke.json'}")
        print("[DRYRUN] 真实 GRPO MoE 训练伪代码：")
        print("""
  1) 加载共享基座 + K 个 RFT LoRA，创建 MoE 包装模块（forward 时加权 sum）；
  2) 构造 GRPO 数据集：prompt=messages（不含 assistant），group_size=4；
  3) 自定义 reward_func(completion_list, prompt_list, **kwargs)：
       对每条 completion 调用 compute_reward，列表的第 j 条 rollout 返回对应 scalar；
  4) trl.GRPOTrainer.train() 跑 3 epochs；
  5) 存 K 个 LoRA 权重 + Router 融合说明 JSON。
""")
        return grpo_out

    # ====== 真实 GRPO 路径 ======
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from datasets import Dataset
    from trl import GRPOTrainer, GRPOConfig
    from peft import PeftModel

    grpo_out.mkdir(parents=True, exist_ok=True)
    # 数据集：每个 event 重复 group_size 次（GRPOTrainer 内部会按连续 group_size 条分 group）
    rows = []
    for e in events:
        pc = build_prompt_completion_for_grpo(e)
        for _ in range(hp.num_rollouts_per_event):
            rows.append({
                "event_id": e.get("event_id"),
                "prompt": pc["messages"],   # list[dict]（openai messages）
                "_scene_primary_h": pc["_scene_primary_h"],
                "_router_prior": pc["_router_prior"],
                "_event_json": json.dumps(e, ensure_ascii=False),
            })
    ds_path = grpo_out / "grpo_ds.jsonl"
    with open(ds_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ds = Dataset.from_json(str(ds_path))

    # 加载基座 + 第 0 个专家 LoRA 作为初始（其他专家需要自定义 MoE 模块）
    model = AutoModelForCausalLM.from_pretrained(
        hp.base_model, device_map="auto",
        torch_dtype="bfloat16", attn_implementation="flash_attention_2",
    )
    tok = AutoTokenizer.from_pretrained(hp.base_model)
    tok.pad_token = tok.eos_token
    first_lora = list(step1_lora_dirs.values())[0]
    model = PeftModel.from_pretrained(model, str(first_lora), adapter_name=EXPERT_IDS[0])
    for eid, p in list(step1_lora_dirs.items())[1:]:
        model.load_adapter(str(p), adapter_name=eid)

    # labels lookup（给 reward_fn 用）
    lb_map = {str(lb.get("event_id") or ""): lb for lb in labels}

    def reward_fn(completions: list[str], prompts: list[str | list], **kwargs):
        """GRPOTrainer reward sig：接受 batch completions，返回 list[float]。
        kwargs 里会带 dataset row fields（event_id 等）。"""
        eids = kwargs.get("event_id") or [None] * len(completions)
        event_jsons = kwargs.get("_event_json") or [None] * len(completions)
        priors = kwargs.get("_router_prior") or [None] * len(completions)
        rewards = []
        for comp, eid, ej, rw in zip(completions, eids, event_jsons, priors):
            try:
                e = json.loads(ej) if isinstance(ej, str) else {}
            except Exception:
                e = {}
            lb = lb_map.get(str(eid or ""), {})
            if rw and isinstance(rw, (dict, str)):
                if isinstance(rw, str):
                    try: rw = json.loads(rw)
                    except Exception: rw = {}
                if "router_weights" not in e and isinstance(rw, dict):
                    e["_router_weights"] = rw
            r = compute_reward(comp, e, lb, hp)
            rewards.append(float(r["reward"]))
        return rewards

    cfg = GRPOConfig(
        output_dir=str(grpo_out),
        num_train_epochs=hp.num_train_epochs_grpo,
        per_device_train_batch_size=hp.train_batch_size,
        gradient_accumulation_steps=hp.gradient_accumulation_steps,
        learning_rate=hp.learning_rate, weight_decay=hp.weight_decay,
        max_grad_norm=hp.max_grad_norm, logging_steps=5, save_strategy="epoch",
        max_completion_length=hp.max_new_tokens,
        max_prompt_length=hp.max_seq_len - hp.max_new_tokens,
        num_generations=hp.num_rollouts_per_event,
        temperature=hp.temperature, top_p=hp.top_p,
        beta=0.04,   # GRPO KL 系数（default）
    )
    trainer = GRPOTrainer(
        model=model, tokenizer=tok, args=cfg,
        train_dataset=ds, reward_funcs=reward_fn,
    )
    trainer.train()
    trainer.model.save_pretrained(str(grpo_out))
    tok.save_pretrained(str(grpo_out))
    return grpo_out


# ====================== CLI ======================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["step1", "step2", "pipeline"], default="pipeline",
                    help="step1=RFT 单专家或全部，step2=GRPO MoE，pipeline=顺序跑两步")
    ap.add_argument("--expert", default="ALL",
                    help="step1 指定单个专家 ID（默认 ALL=K=6 个依次跑）")
    ap.add_argument("--events", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out-dir", required=True, help="训练产物根目录")
    ap.add_argument("--dry-run", action="store_true",
                    help="即使依赖齐全，也只 dry-run（不真正训）")
    args = ap.parse_args()

    evs, lbs = load_pair(Path(args.events), Path(args.labels))
    print(f"[LOAD] events × labels 配对成功：{len(evs)} 条")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hp = DEFAULT_HPARAMS

    mode_dry = args.dry_run or (not HAS_TRAIN_DEPS)
    if mode_dry:
        print("[INFO] 进入 DRY-RUN 模式：" + ("用户指定" if args.dry_run else "依赖未安装（transformers/datasets/peft/trl）"))

    if args.mode in ("step1", "pipeline"):
        expert_list = EXPERT_IDS if args.expert == "ALL" else [args.expert]
        step1_dirs = {}
        for eid in expert_list:
            step1_dirs[eid] = run_step1_rft(eid, evs, lbs, out_dir, hp, mode_dry)
        if args.mode == "pipeline":
            run_step2_grpo_moe(evs, lbs, step1_dirs, out_dir, hp, mode_dry)
    elif args.mode == "step2":
        # 假设 step1 产物在 out_dir 下
        step1_dirs = {eid: out_dir / f"step1_rft_{eid}" for eid in EXPERT_IDS}
        run_step2_grpo_moe(evs, lbs, step1_dirs, out_dir, hp, mode_dry)

    print(f"\n[ALL DONE] 输出在 → {out_dir}")


if __name__ == "__main__":
    main()
