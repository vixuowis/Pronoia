"""test_reward_b7_t3.py — B7 弱指标打折 + T3 覆盖加分的单测（本地运行）。"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent / "training"))

import reward_fn_papv as rf  # noqa: E402

# 构造 completion：4 条断言，覆盖 car/ret/pvalue/benchmark 四族、4 个 horizon
COMP = """【0. 断言规划】
围绕事件做超额与显著性断言。
【1. 断言列表】
CLAIM-1: car_t3 > 0 @t3 | 判断: TRUE | 置信度: 0.70 | 依据: 同类事件基率正向
CLAIM-2: ret_t7 > 0 @t7 | 判断: TRUE | 置信度: 0.65 | 依据: 前置漂移为正
CLAIM-3: car_t3_pvalue < 0.05 @t3 | 判断: TRUE | 置信度: 0.75 | 依据: T0 反应大
CLAIM-4: bm_ret_t7 > 0 @t7 | 判断: FALSE | 置信度: 0.60 | 依据: 基准弱势
【2. 逻辑链】
car_t3 与显著性互证；ret_t7 依赖漂移延续；基准弱势使 ret 弱于 car。
【3. 反方与风险】
T0 或已透支；基准若反弹则 car 跑输。"""

LABEL = {
    "car_t3": 0.03, "ret_t7": 0.02, "car_t3_pvalue": 0.03,
    "bm_ret_t7": -0.01, "car_t1": 0.02, "ret_t1": 0.01,
}
EVENT = {"event_type": "财报", "title": "某公司季报", "market": "CN", "body": ""}

# 弱指标表：ret_t7 在列（acc=0.52 < 0.55），其余强
PRIOR = {"_meta": {}, "metrics": {
    "car_t3": {"acc": 0.70, "n": 100},
    "ret_t7": {"acc": 0.52, "n": 517},
    "car_t3_pvalue": {"acc": 0.835, "n": 700},
    "bm_ret_t7": {"acc": 0.70, "n": 50},
}}


def test_no_prior_backward_compat():
    """表缺失时行为不变（向后兼容）。"""
    with patch.dict(os.environ, {"PAPV_METRIC_PRIOR": ""}):
        rf._METRIC_PRIOR = {}
        out = rf.compute_papv_reward(COMP, EVENT, LABEL)
        d = out["detail"]
        assert "b7_weak_frac" not in d, "无表不应有 b7 诊断"
        assert "t3_bonus" in d
        print(f"[compat] reward={out['reward']:.3f} t3={d.get('t3_bonus')}")


def test_b7_discount_applied():
    """弱指标 ret_t7 占可结算 1/4 → R2 ×(1-0.3*0.25)=0.925。"""
    p = Path("/tmp/_prior_test.json")
    p.write_text(json.dumps(PRIOR), encoding="utf-8")
    with patch.dict(os.environ, {"PAPV_METRIC_PRIOR": str(p)}):
        rf._METRIC_PRIOR = {}  # 重置缓存
        out = rf.compute_papv_reward(COMP, EVENT, LABEL)
        d = out["detail"]
        assert d.get("b7_weak_frac") == 0.25, d
        assert abs(d.get("b7_r2_mult", 0) - 0.925) < 1e-6, d
        print(f"[b7] reward={out['reward']:.3f} frac={d['b7_weak_frac']} mult={d['b7_r2_mult']}")


def test_b7_full_weak():
    """全部弱指标 → mult=0.7 下限。"""
    prior = {"_meta": {}, "metrics": {
        "car_t3": {"acc": 0.50, "n": 100}, "ret_t7": {"acc": 0.52, "n": 517},
        "car_t3_pvalue": {"acc": 0.51, "n": 700}, "bm_ret_t7": {"acc": 0.53, "n": 50},
    }}
    p = Path("/tmp/_prior_test.json")
    p.write_text(json.dumps(prior), encoding="utf-8")
    with patch.dict(os.environ, {"PAPV_METRIC_PRIOR": str(p)}):
        rf._METRIC_PRIOR = {}
        out = rf.compute_papv_reward(COMP, EVENT, LABEL)
        d = out["detail"]
        assert abs(d["b7_r2_mult"] - 0.7) < 1e-6, d
        print(f"[b7-full-weak] mult={d['b7_r2_mult']} reward={out['reward']:.3f}")


def test_t3_bonus_levels():
    """四族四 horizon → 满档加分。"""
    rf._METRIC_PRIOR = {}
    bonus, diag = rf._t3_coverage_bonus(rf.parse_claims(COMP) if hasattr(rf, "parse_claims") else [])
    print(f"[t3-direct] bonus={bonus:.3f} diag={diag}")
    assert bonus > 0


def test_t3_single_family_no_bonus():
    """单族堆叠 → 零加分。"""
    comp1 = COMP.replace("CLAIM-2: ret_t7 > 0 @t7 | 判断: TRUE | 置信度: 0.65 | 依据: 前置漂移为正\n", "") \
                .replace("CLAIM-4: bm_ret_t7 > 0 @t7 | 判断: FALSE | 置信度: 0.60 | 依据: 基准弱势\n", "") \
                .replace("CLAIM-3: car_t3_pvalue < 0.05 @t3 | 判断: TRUE | 置信度: 0.75 | 依据: T0 反应大\n",
                         "CLAIM-3: car_t15 > 0 @t15 | 判断: TRUE | 置信度: 0.75 | 依据: T0 反应大\n")
    from papv_claims import parse_claims
    claims = parse_claims(comp1)
    fams = {rf.metric_family(c["metric"]) for c in claims}
    assert len(fams) == 1, fams  # 全 car 族
    bonus, diag = rf._t3_coverage_bonus(claims)
    # 单族：new_fam=1 → 族分 0；horizon t3/t7/t15=3 → horizon 分 0.06
    assert bonus <= 0.06 + 1e-9, (bonus, diag)
    print(f"[t3-single-fam] bonus={bonus:.3f} diag={diag}")


if __name__ == "__main__":
    test_no_prior_backward_compat()
    test_b7_discount_applied()
    test_b7_full_weak()
    test_t3_bonus_levels()
    test_t3_single_family_no_bonus()
    print("\nALL TESTS PASSED")
