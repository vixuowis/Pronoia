"""expert_definitions.py — Pronoia-RLVR §3.4 K=6 专家 LoRA 定义 + 无参数 Router。

K=6 专家（与 scene_match.py EXPERT_IDS 对齐）：
  [0] cn_overnight     — CN 宏观数据场景（政策利率、通胀、就业增长），primary t3
  [1] cn_short         — CN 财报/指引场景，primary t7
  [2] cn_mid           — CN 并购/分拆/再融资，primary t15
  [3] us_overnight     — US 宏观数据场景（利率决议/NFP/CPI），primary t3
  [4] us_short         — US 财报/指引/并购（US 样本少，合并为一个）
  [5] volume_agnostic  — 跨市场量价专家（vol_regime HIGH/LOW 时激活，防止假突破/出货）

无参数 Router（三信号融合，避免训练额外 gate network）：
  s1 场景先验 p(e|scene)     = 由 expert_targets_for(scene) 给 1/0 掩码 + softmax(0.5)
  s2 量价增量 vol_delta      = |log(vol_t0_ratio)| × 对应 volume_agnostic 权重放大
  s3 Dirichlet 平滑 α=0.1    = 防止 degenerate（单专家独霸 → MoE 崩塌）

最终加权 = normalize( (s1 + s2) + α )
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import sys
from pathlib import Path
_THIS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from scene_match import EXPERT_IDS, expert_targets_for  # noqa: E402


@dataclass
class ExpertLoRASpec:
    expert_id: str
    rank: int = 16                  # r=16 通用
    lora_alpha: int = 32            # alpha = 2r （standard）
    lora_dropout: float = 0.05
    # target modules: Qwen3-8B Attn + MLP（LoRA 接入标准配置）
    target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",   # Attn
        "gate_proj", "up_proj", "down_proj",      # MLP (SwiGLU)
    ])
    # 该专家期望覆盖的 (market, event_type_l2) 场景（用于 RFT 阶段数据筛选）
    scene_keys: list[tuple[str, str]] = field(default_factory=list)


EXPERT_SPECS: dict[str, ExpertLoRASpec] = {
    "cn_overnight": ExpertLoRASpec(
        expert_id="cn_overnight",
        scene_keys=[
            ("CN", "政策利率调整"),
            ("CN", "通胀数据意外"),
            ("CN", "增长/就业数据意外"),
        ],
    ),
    "cn_short": ExpertLoRASpec(
        expert_id="cn_short",
        scene_keys=[
            ("CN", "财报超预期/不及预期"),
            ("CN", "公司指引上调/下调"),
        ],
    ),
    "cn_mid": ExpertLoRASpec(
        expert_id="cn_mid",
        scene_keys=[("CN", "并购/分拆/再融资")],
    ),
    "us_overnight": ExpertLoRASpec(
        expert_id="us_overnight",
        scene_keys=[
            ("US", "政策利率调整"),
            ("US", "通胀数据意外"),
            ("US", "增长/就业数据意外"),
        ],
    ),
    "us_short": ExpertLoRASpec(
        expert_id="us_short",
        scene_keys=[
            ("US", "财报超预期/不及预期"),
            ("US", "公司指引上调/下调"),
            ("US", "并购/分拆/再融资"),
        ],
    ),
    "volume_agnostic": ExpertLoRASpec(
        expert_id="volume_agnostic",
        scene_keys=[],   # 量价专家跨市场，RFT 阶段用 vol_regime != NORMAL 样本
    ),
}


# ==================== 无参数 Router ====================
DIRICHLET_ALPHA = 0.1
VOL_AGNOSTIC_GAIN = 2.0   # 量价非 NORMAL 时 volume_agnostic 的放大倍数
SCENE_LOGIT_HIT   = 1.0   # 场景匹配专家的基础 logit
SCENE_LOGIT_MISS  = -3.0  # 场景不匹配专家的惩罚 logit


def router_weights(market: str, event_type_l2: str,
                   vol_regime: Optional[str] = None,
                   vol_t0_ratio: Optional[float] = None,
                   alpha: float = DIRICHLET_ALPHA) -> dict[str, float]:
    """返回 K 个专家的归一化权重 dict[expert_id]=w（和为 1）。

    三信号：
      s1 = 场景掩码 softmax-logits
      s2 = vol_t0_ratio 偏离 1 越大 → volume_agnostic logit 越大
      s3 = Dirichlet α 加性平滑（每个专家权重加 α 再归一）
    """
    # ---- s1 ----
    active_experts = set(expert_targets_for(market, event_type_l2, vol_regime))
    logits = {}
    for eid in EXPERT_IDS:
        logits[eid] = SCENE_LOGIT_HIT if eid in active_experts else SCENE_LOGIT_MISS

    # ---- s2 ----
    if vol_regime and vol_regime != "NORMAL":
        # 量价异常 → 放大 volume_agnostic
        delta = 0.0
        if isinstance(vol_t0_ratio, (int, float)) and vol_t0_ratio > 0:
            delta = abs(math.log(max(vol_t0_ratio, 1e-6)))
        boost = VOL_AGNOSTIC_GAIN + delta
        logits["volume_agnostic"] = logits.get("volume_agnostic", 0.0) + boost

    # 转为概率（softmax）
    mx = max(logits.values())
    exps = {k: math.exp(v - mx) for k, v in logits.items()}
    Z = sum(exps.values())
    p = {k: (v / Z if Z > 0 else 1.0 / len(EXPERT_IDS)) for k, v in exps.items()}

    # ---- s3 Dirichlet smoothing ----
    p_smooth = {k: (v + alpha) for k, v in p.items()}
    Z2 = sum(p_smooth.values())
    return {k: v / Z2 for k, v in p_smooth.items()}


def expert_rft_dataset_mask(expert_id: str, e: dict) -> bool:
    """RFT 阶段：某专家只在其适配场景的样本上做监督微调。
    e = 单条 event（含 market, event_type_l2, vol_regime 字段）。"""
    spec = EXPERT_SPECS.get(expert_id)
    if spec is None:
        return False
    if expert_id == "volume_agnostic":
        # 量价专家：vol_regime != NORMAL 的全市场样本（HIGH / LOW 都学）
        return str(e.get("vol_regime") or "") != "NORMAL"
    key = (str(e.get("market") or "").upper(), str(e.get("event_type_l2") or ""))
    return key in spec.scene_keys


# ============ 训练超参默认值（§3.5）============
@dataclass
class RLVRHyperparams:
    base_model: str = "Qwen/Qwen3-8B-Instruct"
    # LoRA 通用（K 个专家共享相同 r=16）
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    # GRPO
    num_rollouts_per_event: int = 4        # 每组 4 条 rollout（group relative）
    learning_rate: float = 1e-6
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    num_train_epochs_rft: int = 2          # RFT 阶段 2 epochs 即可
    num_train_epochs_grpo: int = 3         # GRPO MoE 阶段 3 epochs
    train_batch_size: int = 8
    gradient_accumulation_steps: int = 4
    max_seq_len: int = 4096
    max_new_tokens: int = 1500             # 推理时 7 段 CoT 输出长度
    temperature: float = 0.7               # rollout 采样温度
    top_p: float = 0.9
    # Reward 权重（七元组）
    reward_weights: dict = field(default_factory=lambda: {
        "R0":   0.04,    # 窗口合规
        "R05":  0.04,    # 量价段合规
        "R1":   0.50,    # 方向正确（主项）
        "R2":   0.27,    # 置信度校准 × κ_vol
        "R3":   0.13,    # CAR 幅度 + 双窗 + 量价安全阀 + RET↔CAR 一致 + 长短一致
        "R4":   0.04,    # 推理链一致性
        "R5":   0.02,    # 专家熵正则（MoE 健康度）
    })
    # R3 子项系数
    R3_eta_rer:  float = 0.30   # RET↔CAR 不一致惩罚系数（变量名保留 R3_eta_rer 兼容配置）
    R3_eta_long: float = 0.25   # 长短 horizon 反转惩罚系数


DEFAULT_HPARAMS = RLVRHyperparams()
