"""train_detail_extract.py — 提取 v62/v61 trainer_state 训练细节 + 校准/断言级分析."""
import json

RUN = "/root/Pronoia/pronoia_run"

for tag, path in (
    ("v62-vanilla", f"{RUN}/papv_v62_vanilla/papv_mixed/checkpoint-1241/trainer_state.json"),
    ("v61-b", f"{RUN}/papv_v61/papv_mixed/checkpoint-1241/trainer_state.json"),
):
    try:
        ts = json.load(open(path))
    except Exception as ex:
        print(f"[{tag}] load fail: {ex}")
        continue
    print("=" * 60)
    print(f"[{tag}] {path.split('pronoia_run/')[1]}")
    print("  global_step:", ts["global_step"], " epoch:", ts.get("epoch"))
    print("  train_runtime: %.2f h" % (ts.get("train_runtime", 0) / 3600))
    print("  train_samples_per_sec:", round(ts.get("train_samples_per_second", 0), 3))
    print("  total flos: %.3e" % ts.get("total_flos", 0))
    lr = [h.get("learning_rate") for h in ts["log_history"] if "learning_rate" in h]
    if lr:
        print(f"  lr: first={lr[0]:.2e} mid={lr[len(lr)//2]:.2e} last={lr[-1]:.2e}")
    rew = [(h.get("step"), h.get("reward")) for h in ts["log_history"] if "reward" in h]
    if rew:
        rs = [r for _, r in rew]
        print(f"  reward: n={len(rs)} first={rs[0]:.3f} last={rs[-1]:.3f} "
              f"max={max(rs):.3f} min={min(rs):.3f}")
        print(f"  reward@step samples:", [(s, round(r, 3)) for s, r in rew[::max(1, len(rew)//10)]])
    # 其他键采样
    keys = set()
    for h in ts["log_history"]:
        keys.update(h.keys())
    print("  log_history keys:", sorted(keys))
    # completion length / kl / clip ratio
    for k in ("completions/mean_length", "kl", "reward_std", "completions/clipped_ratio", "epoch"):
        vals = [h[k] for h in ts["log_history"] if k in h]
        if vals:
            print(f"  {k}: first={vals[0]:.4f} mid={vals[len(vals)//2]:.4f} last={vals[-1]:.4f}")
