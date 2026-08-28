"""extract_reward_series.py — 从训练日志提取 reward 序列（降采样）供绘图。"""
import json
import re

RUN = "/root/Pronoia/pronoia_run"


def series(paths):
    out = []
    for p in paths:
        try:
            txt = open(p, errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r"'reward': '([0-9.eE+-]+)'", txt):
            out.append(float(m.group(1)))
    return out


def ds(s, k=20):
    return [round(sum(s[i:i + k]) / len(s[i:i + k]), 4)
            for i in range(0, len(s), k)]


v62 = series([f"{RUN}/v62_vanilla_train.log"])
# v61 完整序列：unsloth 主日志前 800 步 + 恢复日志 441 步（801~1241）
v61a = series([f"{RUN}/v61_train_unsloth.log"])[:800]
v61b = series([f"{RUN}/v61_train_resume.log"])
v61 = v61a + v61b
print("V62_N:", len(v62), "V61_N:", len(v61))
print("V62:" + json.dumps(ds(v62)))
print("V61:" + json.dumps(ds(v61)))
