"""parse_v5_log.py — 解析 papv_v5_run1.log，输出训练指标序列 CSV + PNG 曲线图。

输入：training 日志（每步一行含 dict）
输出：
  · v5_train_metrics.csv      逐步序列
  · v5_reward_loss_curves.png 多面板图
"""
import ast
import csv
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = Path(__file__).parent / "papv_v5_run1.log"

# 每行形如「  5/627 [...]{'loss': ..., 'reward': ...}」取最后一个 dict 字面量
rows = []
for line in LOG.read_text(encoding="utf-8").splitlines():
    m = re.search(r"\{'loss'.*\}$", line.strip())
    if not m:
        continue
    try:
        d = ast.literal_eval(m.group(0))
    except Exception:
        continue
    prog = re.search(r"(\d+)/(\d+)", line)
    step = int(prog.group(1)) if prog else len(rows) + 1
    rows.append({
        "step": step,
        "loss": d.get("loss"),
        "grad_norm": d.get("grad_norm"),
        "lr": d.get("learning_rate"),
        "reward": d.get("reward"),
        "reward_std": d.get("reward_std"),
        "kl": d.get("kl"),
        "mean_len": d.get("completions/mean_length"),
        "clipped": d.get("completions/clipped_ratio"),
    })

if not rows:
    raise SystemExit("no metric rows parsed")

# 存 CSV
csv_path = Path(__file__).parent / "v5_train_metrics.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

steps = [r["step"] for r in rows]
npmean = (lambda xs: sum(xs) / len(xs))
reward = [r["reward"] for r in rows]
kl = [r["kl"] for r in rows]
g = [r["grad_norm"] for r in rows]

# 平滑 EMA
def ema(x, a=0.7):
    out, e = [], 0.0
    for v in x:
        e = a * e + (1 - a) * v
        out.append(e)
    return out

fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))

# 1. Reward
ax = axes[0, 0]
ax.plot(steps, reward, ".", color="#c0392b", ms=5, alpha=0.45, label="reward(per step)")
ax.plot(steps, ema(reward), color="#c0392b", lw=2, label="EMA(0.7)")
ax.axhline(sum(reward) / len(reward), color="gray", ls="--", lw=1,
           label=f"mean {npmean(reward):.3f}")
ax.set_title("PAPV Reward (claim-settlement score)")
ax.set_xlabel("step"); ax.set_ylabel("reward")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# 2. KL
ax = axes[0, 1]
ax.plot(steps, kl, ".", color="#2980b9", ms=5, alpha=0.5, label="KL(per step)")
ax.plot(steps, ema(kl), color="#2980b9", lw=2, label="EMA")
ax.set_title("KL divergence (policy vs reference)")
ax.set_xlabel("step"); ax.set_ylabel("KL")
ax.set_ylim(bottom=0)
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# 3. Gradient Norm（原 GRPO Loss 为 TRL 占位 0，改用有语义的 grad_norm）
ax = axes[1, 0]
ax.plot(steps, g, ".", color="#8e44ad", ms=5, alpha=0.45, label="grad_norm(per step)")
ax.plot(steps, ema(g), color="#8e44ad", lw=2, label="EMA(0.7)")
ax.axhline(sum(g) / len(g), color="gray", ls="--", lw=1,
           label=f"mean {npmean(g):.3f}")
ax.set_title("Gradient Norm (policy update signal)")
ax.set_xlabel("step"); ax.set_ylabel("grad_norm")
ax.set_ylim(bottom=0)
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# 4. Learning Rate + completion length
ax = axes[1, 1]
ax.plot(steps, [r["lr"] for r in rows], color="#d35400", lw=1.5, label="lr")
ax.set_title("Learning Rate")
ax.set_xlabel("step"); ax.set_ylabel("learning_rate")
ax2 = ax.twinx()
ax2.plot(steps, [r["mean_len"] or 0 for r in rows], ".", color="#27ae60", ms=4,
         alpha=0.4, label="completions/mean_length")
ax2.set_ylabel("tokens")
ax.legend(fontsize=8, loc="upper left"); ax2.legend(fontsize=8, loc="upper right")
ax.grid(alpha=0.3)

fig.tight_layout()
out_png = Path(__file__).parent / "v5_reward_loss_curves.png"
fig.savefig(out_png, dpi=120)
print(f"SAVED {out_png} (rows={len(rows)})")
print(f"steps {steps[0]}..{steps[-1]}; reward last={reward[-1]:.3f}; "
      f"kl last={kl[-1]:.5f}; grad last={g[-1]:.3f}")