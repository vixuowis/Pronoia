"""scene_match.py — Pronoia-RLVR §2.1 Market × EventType × Horizon 三维定向匹配表。

核心逻辑：
  · 每个 (Market, EventTypeL2) 对 → 分配一个**主 horizon**（primary_horizon），
    训练/评估用定向 label（car_t{primary} / label_t{primary} / rer_t{primary}），
    避免用 label_avg_all 稀释信号。
  · 次级 horizon（secondary_horizons）用于双窗一致率、长短反转检测。
  · scene_priority：场景信号强度分桶（用于 Router 的场景先验 + 训练样本权重）。

用法：
    from scene_match import SCENE_MATCH, primary_horizon_for, scene_weights_for
"""
from __future__ import annotations

from typing import Optional


# ======================== 定向匹配主表 ========================
# Market × EventTypeL2 → 主 horizon + 次 horizon 列表 + scene_priority
# primary_horizon 选型依据（design §2.1）：
#   - 政策/宏观数据（利率调整、通胀、就业增长）→ 短期吸收快 → t3
#   - 财报/指引 → 短期有动量 + 中期确认 → t7
#   - 并购/分拆/再融资 → 落地周期长 → t15
SCENE_MATCH: dict[tuple[str, str], dict] = {
    # ---------- CN ----------
    ("CN", "并购/分拆/再融资"): {
        "primary_horizon": "t15",
        "secondary_horizons": ["t7", "t30"],
        "scene_priority": "HIGH",   # 事件确定性强，CAR 可分离度高
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("CN", "财报超预期/不及预期"): {
        "primary_horizon": "t7",
        "secondary_horizons": ["t3", "t15"],
        "scene_priority": "HIGH",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("CN", "公司指引上调/下调"): {
        "primary_horizon": "t7",
        "secondary_horizons": ["t3", "t15"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("CN", "政策利率调整"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "HIGH",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("CN", "增长/就业数据意外"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("CN", "通胀数据意外"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    # ---------- US ----------
    ("US", "并购/分拆/再融资"): {
        "primary_horizon": "t15",
        "secondary_horizons": ["t7", "t30"],
        "scene_priority": "HIGH",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("US", "财报超预期/不及预期"): {
        "primary_horizon": "t7",
        "secondary_horizons": ["t3", "t15"],
        "scene_priority": "HIGH",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("US", "公司指引上调/下调"): {
        "primary_horizon": "t7",
        "secondary_horizons": ["t3", "t15"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("US", "政策利率调整"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "HIGH",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("US", "增长/就业数据意外"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
    ("US", "通胀数据意外"): {
        "primary_horizon": "t3",
        "secondary_horizons": ["t1", "t7"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    },
}

PRIORITY_WEIGHT = {"HIGH": 1.2, "MEDIUM": 1.0, "LOW": 0.8}

# ============ 专家编号映射 ============
# K=6 专家：CN_overnight (t1/t3 场景) / CN_short (t7) / CN_mid (t15+) /
#           US_overnight / US_short / Volume_agnostic（量价背离专家）
EXPERT_IDS = [
    "cn_overnight",     # 0: CN 宏观数据类场景（t3 primary）→ 隔夜/短期反应
    "cn_short",         # 1: CN 财报/指引类场景（t7 primary）→ 短期
    "cn_mid",           # 2: CN 并购类场景（t15 primary）→ 中期
    "us_overnight",     # 3: US 宏观数据类场景（t3 primary）
    "us_short",         # 4: US 财报/指引+并购类场景（t7/t15 primary，US 样本少→合并）
    "volume_agnostic",  # 5: 量价专家（跨市场，vol_regime=HIGH 时权重高）
]


def primary_horizon_for(market: str, event_type_l2: str) -> str:
    """返回主 horizon；未知组合兜底 t7。"""
    key = (str(market or "").upper(), str(event_type_l2 or ""))
    if key in SCENE_MATCH:
        return SCENE_MATCH[key]["primary_horizon"]
    # 兜底：7 日是通用中短期窗口
    return "t7"


def scene_meta_for(market: str, event_type_l2: str) -> dict:
    key = (str(market or "").upper(), str(event_type_l2 or ""))
    if key in SCENE_MATCH:
        return dict(SCENE_MATCH[key])
    return {
        "primary_horizon": "t7",
        "secondary_horizons": ["t3", "t15"],
        "scene_priority": "MEDIUM",
        "horizons_all": ["t1", "t3", "t7", "t15", "t30", "t60"],
    }


def expert_targets_for(market: str, event_type_l2: str,
                        vol_regime: Optional[str] = None) -> list[str]:
    """根据场景返回应激活的专家（按权重排序，供 Router 初始化先验）。"""
    mkt = str(market or "").upper()
    meta = scene_meta_for(mkt, event_type_l2)
    h = meta["primary_horizon"]

    experts: list[str] = []
    if mkt == "CN":
        if h in ("t1", "t3"): experts.append("cn_overnight")
        if h == "t7":          experts.append("cn_short")
        if h in ("t15", "t30", "t60"): experts.append("cn_mid")
        # 兜底补一个
        if not experts: experts.append("cn_short")
    elif mkt == "US":
        if h in ("t1", "t3"): experts.append("us_overnight")
        experts.append("us_short")   # US 样本少：t7+ 全走 us_short
        if not experts: experts.append("us_short")
    else:
        experts.append("volume_agnostic")

    # 量价 regime 非 NORMAL 时加入量价专家
    if vol_regime and vol_regime != "NORMAL":
        experts.append("volume_agnostic")
    return experts


def scene_priority_weight(market: str, event_type_l2: str) -> float:
    meta = scene_meta_for(market, event_type_l2)
    return PRIORITY_WEIGHT.get(meta["scene_priority"], 1.0)


# 列表形式（供 training data pipeline 配额循环使用）
ALL_SCENE_KEYS = list(SCENE_MATCH.keys())
