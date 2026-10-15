#!/usr/bin/env python3
"""plot_reward_divergence.py — Reward hacking 实证图（WWW 论文 P1#6）。

从 GRPO 训练日志提取 reward 序列，绘制 v6.1-b vs v6.2-vanilla 训练奖励曲线，
叠加各自 OOS 终点：直观呈现「训练奖励更高 ≠ OOS 更好」的背离。

输出：outputs/reward_divergence.png + reward_series.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
LOGS = _HERE / "train_logs"
OUT = _HERE / "outputs"


def series(path: Path) -> list[float]:
    txt = path.read_text(errors="ignore")
    return [float(m) for m in re.findall(r"'reward': '([0-9.eE+-]+)'", txt)]


def smooth(xs: list[float], k: int = 50) -> list[float]:
    return [sum(xs[i:i + k]) / len(xs[i:i + k]) for i in range(0, len(xs), k)]


def main():
    v62 = series(LOGS / "v62_vanilla_train.log")
    # v61 完整序列 = unsloth 主日志前 800 步 + resume 日志 441 步
    v61 = series(LOGS / "v61_train_unsloth.log")[:800] + series(LOGS / "v61_train_resume.log")
    print(f"v6.1-b steps={len(v61)} mean={sum(v61)/len(v61):.3f} "
          f"last200={sum(v61[-200:])/200:.3f}")
    print(f"v6.2   steps={len(v62)} mean={sum(v62)/len(v62):.3f} "
          f"last200={sum(v62[-200:])/200:.3f}")

    OUT.mkdir(exist_ok=True)
    (OUT / "reward_series.json").write_text(json.dumps({
        "v61b_reward_mean": round(sum(v61) / len(v61), 4),
        "v62_reward_mean": round(sum(v62) / len(v62), 4),
        "v61b_last200": round(sum(v61[-200:]) / 200, 4),
        "v62_last200": round(sum(v62[-200:]) / 200, 4),
        "oos_base": 0.5729, "oos_v61b": 0.6093, "oos_v62": 0.6322,
    }, indent=2))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib 不可用，仅输出 JSON")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 3.2),
                                   gridspec_kw={"width_ratios": [3, 2]})

    # ---- 左图：训练 reward 曲线 ----
    for s, name, c in ((v61, "v6.1-b (corrections)", "#d62728"),
                       (v62, "v6.2 (vanilla)", "#1f77b4")):
        sm = smooth(s, 50)
        ax1.plot([i * 50 for i in range(len(sm))], sm, label=name, color=c, lw=1.6)
    ax1.set_xlabel("GRPO training step")
    ax1.set_ylabel("Training reward (50-step mean)")
    ax1.set_title("(a) Training reward")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.25)

    # ---- 右图：训练 reward vs OOS 终点 ----
    models = ["Base", "v6.1-b", "v6.2"]
    tr_reward = [None, sum(v61) / len(v61), sum(v62) / len(v62)]
    oos = [0.5729, 0.6093, 0.6322]
    x = range(3)
    ax2b = ax2.twinx()
    b1 = ax2.bar([i - 0.18 for i in x[1:]], tr_reward[1:], width=0.36,
                 color="#ff9896", label="Training reward")
    b2 = ax2b.bar([i + 0.18 for i in x], oos, width=0.36,
                  color="#1f77b4", label="OOS claim ACC")
    ax2.set_ylabel("Training reward", color="#d62728")
    ax2b.set_ylabel("OOS claim accuracy", color="#1f77b4")
    ax2.set_xticks(list(x), models)
    ax2.set_title("(b) Reward vs OOS (divergence)")
    for r, v in zip(b1, tr_reward[1:]):
        ax2.text(r.get_x() + r.get_width() / 2, v + 0.01, f"{v:.2f}",
                 ha="center", fontsize=8)
    for r, v in zip(b2, oos):
        ax2b.text(r.get_x() + r.get_width() / 2, v + 0.01, f"{v:.3f}",
                  ha="center", fontsize=8)
    ax2.grid(alpha=0.25, axis="y")

    fig.tight_layout()
    fig.savefig(OUT / "reward_divergence.png", dpi=200)
    print(f"saved → {OUT / 'reward_divergence.png'}")


if __name__ == "__main__":
    main()
