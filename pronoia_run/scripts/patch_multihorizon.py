#!/usr/bin/env python3
"""patch_multihorizon.py — 多窗口判别改造（ret/car × T+3/7/15/30/60，共10个judge）。

1. models.py   TeamPrediction 增加 horizons 字段
2. engine.py   问题模板改多窗口；解析10个窗口行（每行「指标: 方向 置信度」）；
               主指标 = car_t3（向后兼容 direction/confidence）；每窗口独立conf闸
3. batch       cache 行写入 horizons；model_version → team-full-v4
"""
import sys


def patch(path: str, replacements: list[tuple[str, str]]) -> None:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(replacements):
        if old not in src:
            print(f"[FAIL] {path} 片段#{i} 未找到")
            sys.exit(1)
        if src.count(old) != 1:
            print(f"[FAIL] {path} 片段#{i} 非唯一({src.count(old)}处)")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"[OK] {path}: {len(replacements)} 处补丁")


MODELS = "/root/Pronoia/backend/app/event_backtest/models.py"
ENGINE = "/root/Pronoia/backend/app/event_backtest/engine.py"
BATCH = "/root/Pronoia/backtesting/rlvr/scripts/team_research_batch.py"

# ---------- models.py ----------
models_patches = [
    (
        "    rationale: Optional[str] = None\n"
        "    abstain: bool = False\n",
        "    rationale: Optional[str] = None\n"
        "    abstain: bool = False\n"
        "    # 多窗口判别：ret_t3..ret_t60 / car_t3..car_t60 → {direction, confidence, ...}\n"
        "    horizons: Optional[dict[str, Any]] = None\n",
    ),
    (
        "            abstain=bool(d.get(\"abstain\") is True),\n"
        "        )\n",
        "            abstain=bool(d.get(\"abstain\") is True),\n"
        "            horizons=(d.get(\"horizons\") or None),\n"
        "        )\n",
    ),
    (
        "            \"rationale\": self.rationale,\n"
        "            \"abstain\": self.abstain,\n"
        "        }\n",
        "            \"rationale\": self.rationale,\n"
        "            \"abstain\": self.abstain,\n"
        "            \"horizons\": self.horizons,\n"
        "        }\n",
    ),
]

# ---------- engine.py ----------
OLD_CONSTRAINT = """【核心约束 — 红线】
1. 方向 = benchmark-relative CAR（超额收益）方向，非绝对收益。个股涨但跑输基准 → down；个股跌但跑赢基准 → up。
2. 评估窗口 T+3（事件后3个交易日），CAR = 个股累计收益 − 基准累计收益。
3. 严格禁止未来函数：event_study_skill 在 as_of=True 下仅返回事件日及以前数据（T0涨跌、pre5/pre20漂移），
   绝不包含 T+1/T+3/T+5 未来收益或 CAR。你的判断是前瞻预判，禁止引用/推断任何 post-event CAR。
   如工具返回中出现 post-event CAR 数值，必须忽略——那是工具故障泄露。"""

NEW_CONSTRAINT = """【核心约束 — 红线】
1. 两类判别指标 × 各 5 个窗口，共 10 个独立判断（judge 数量 = 指标数量）：
   - ret（正常收益率）：个股绝对累计收益方向，窗口 T+3 / T+7 / T+15 / T+30 / T+60（事件后N个交易日）。
   - CAR（异常收益率）：个股累计收益 − 基准累计收益 的方向，同样 T+3 / T+7 / T+15 / T+30 / T+60。
   个股涨但跑输基准 → ret=up 而 CAR=down；两类指标可以不一致，必须分别独立判断。
2. 窗口衰减方法论：短窗（T+3/T+7）由事件冲击与 T0 动能延续主导；中窗（T+15/T+30）由基本面趋势
   与资金持续性主导；长窗（T+60）由基本面定价与均值回归主导。同一净分可映射出不同窗口方向
   （如净分+4 → car_t3=up 而 car_t60=neutral）；长窗 confidence 应整体低于短窗。
3. 严格禁止未来函数：event_study_skill 在 as_of=True 下仅返回事件日及以前数据（T0涨跌、pre5/pre20漂移），
   绝不包含 T+1/T+3/T+5 未来收益或 CAR。你的判断是前瞻预判，禁止引用/推断任何 post-event 收益。
   如工具返回中出现 post-event 数值，必须忽略——那是工具故障泄露。"""

OLD_ANSWER_FMT = """最后在你的最终回答里必须清晰给出（必须是4行格式，便于脚本解析）：
【最终方向】 up 或 down 或 neutral（三选一）
【置信度】 0.5~1.0 之间一个小数
【中文理由】 1~3 句中文，引用公告正文基本面证据 + 事件日/事前行情信号；严禁引用 T+N 事后 CAR
【依据原文片段】 直接 1:1 复制 as_of_packet 里支持你判断的 1~2 句原文"""

NEW_ANSWER_FMT = """最后在你的最终回答里必须清晰给出（固定格式，便于脚本解析）：
【多窗口判别】（必须10行，每行固定「指标: 方向 置信度」；方向 up/down/neutral 三选一；置信度 0.50~1.00）
ret_t3: 方向 置信度
ret_t7: 方向 置信度
ret_t15: 方向 置信度
ret_t30: 方向 置信度
ret_t60: 方向 置信度
car_t3: 方向 置信度
car_t7: 方向 置信度
car_t15: 方向 置信度
car_t30: 方向 置信度
car_t60: 方向 置信度
【最终方向】（主指标 = car_t3，须与上面 car_t3 行一致）up 或 down 或 neutral（三选一）
【置信度】（主指标 = car_t3 的置信度）0.5~1.0 之间一个小数
【中文理由】 1~3 句中文，引用公告正文基本面证据 + 事件日/事前行情信号；说明各窗口方向差异的依据；严禁引用 T+N 事后收益
【依据原文片段】 直接 1:1 复制 as_of_packet 里支持你判断的 1~2 句原文"""

HORIZON_PARSE = '''    # ===== 多窗口判别解析：ret/car × T+3/7/15/30/60，共 10 个 judge =====
    # 每行格式「指标: 方向 置信度」；主指标 = car_t3（向后兼容 direction/confidence）
    horizon_keys = ["ret_t3", "ret_t7", "ret_t15", "ret_t30", "ret_t60",
                    "car_t3", "car_t7", "car_t15", "car_t30", "car_t60"]
    horizons: dict = {}
    for hk in horizon_keys:
        mh = re.search(
            rf"{hk}\\s*[:：]\\s*\\**\\s*(up|down|neutral)\\s*[,，/ ]+\\s*\\**\\s*(0?\\.\\d+|1\\.0+|1)\\b",
            final_txt, flags=re.I)
        if mh:
            hd = mh.group(1).lower()
            try:
                hc = max(0.50, min(1.0, float(mh.group(2))))
            except ValueError:
                hc = 0.55
            hgate = False
            if hc < 0.60 and hd != "neutral":
                hd, hgate = "neutral", True
            horizons[hk] = {"direction": hd, "confidence": round(hc, 3),
                            "conf_gate_applied": hgate}
    # 缺失窗口用主判断兜底（schema 完整性；主判断语义 = car_t3）
    for hk in horizon_keys:
        if hk not in horizons:
            horizons[hk] = {"direction": direction, "confidence": round(float(confidence), 3),
                            "conf_gate_applied": applied_gate, "filled_from_primary": True}
    # 主指标缺失时的反向兜底：从 car_t3 行恢复 direction/confidence
    if direction in {"up", "down", "neutral"} and horizons.get("car_t3", {}).get("filled_from_primary"):
        pass  # 主判断已可用，无需处理

'''

engine_patches = [
    (OLD_CONSTRAINT, NEW_CONSTRAINT),
    (OLD_ANSWER_FMT, NEW_ANSWER_FMT),
    # 插入多窗口解析（在 I1 conf 闸之后、落盘之前）
    (
        "    # I1 方案A硬闸：confidence<0.60 强制 neutral（0.60 为方向判别最低可信阈值，低于此即不应做方向性判断）\n"
        "    applied_gate = False\n"
        "    if confidence < 0.60 and direction != \"neutral\":\n"
        "        direction = \"neutral\"\n"
        "        applied_gate = True\n",
        "    # I1 方案A硬闸：confidence<0.60 强制 neutral（0.60 为方向判别最低可信阈值，低于此即不应做方向性判断）\n"
        "    applied_gate = False\n"
        "    if confidence < 0.60 and direction != \"neutral\":\n"
        "        direction = \"neutral\"\n"
        "        applied_gate = True\n\n"
        + HORIZON_PARSE,
    ),
    # structured_extract 增加 horizons
    (
        "        \"structured_extract\": {\n"
        "            \"direction\": direction,\n"
        "            \"confidence\": confidence,\n"
        "            \"rationale\": rationale,\n"
        "            \"conf_gate_applied\": applied_gate,\n"
        "        },",
        "        \"structured_extract\": {\n"
        "            \"direction\": direction,\n"
        "            \"confidence\": confidence,\n"
        "            \"rationale\": rationale,\n"
        "            \"conf_gate_applied\": applied_gate,\n"
        "            \"horizons\": horizons,\n"
        "        },",
    ),
    # TeamPrediction 返回增加 horizons
    (
        "    return TeamPrediction(\n"
        "        event_id=eid,\n"
        "        run_id=str(run_id),\n"
        "        model_version=str(model_version),\n"
        "        pred_direction=direction,\n"
        "        confidence=float(confidence),\n"
        "        rationale=str(rationale) + gate_tag,\n"
        "    )",
        "    return TeamPrediction(\n"
        "        event_id=eid,\n"
        "        run_id=str(run_id),\n"
        "        model_version=str(model_version),\n"
        "        pred_direction=direction,\n"
        "        confidence=float(confidence),\n"
        "        rationale=str(rationale) + gate_tag,\n"
        "        horizons=horizons,\n"
        "    )",
    ),
]

# ---------- batch ----------
batch_patches = [
    (
        "                p = await engine_mod.run_team_full_one_event(\n"
        "                    ev, run_id=run_id, model_version=\"team-full-v3\",",
        "                p = await engine_mod.run_team_full_one_event(\n"
        "                    ev, run_id=run_id, model_version=\"team-full-v4\",",
    ),
    (
        "                    \"rationale\": (p.rationale or \"\")[:4000],\n"
        "                    \"abstain\": bool(p.abstain),",
        "                    \"rationale\": (p.rationale or \"\")[:4000],\n"
        "                    \"horizons\": p.horizons,\n"
        "                    \"abstain\": bool(p.abstain),",
    ),
]


def main() -> None:
    patch(MODELS, models_patches)
    patch(ENGINE, engine_patches)
    patch(BATCH, batch_patches)
    print("ALL PATCHED")


if __name__ == "__main__":
    main()
