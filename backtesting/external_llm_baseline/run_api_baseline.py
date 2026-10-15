#!/usr/bin/env python3
"""run_api_baseline.py — 外部 LLM 基线（P0 #1）：同一 OOS 集、同一 PAV prompt、
同一结算口径下，评测 ARK API 上的 5 个外部模型。

与论文主实验（Qwen3-8B base 0.573 / v6.2-vanilla 0.632）完全可比：
  · 输入  = build_messages_for_papv(event, research_cache)  ← 同一函数
  · 结算  = evaluate_completions(completions, labels)        ← 同一函数
  · 采样  = temperature 0.6（对齐论文 t=0.6 口径）

用法：
  python3 run_api_baseline.py --model glm-5.3 --n 20          # pilot
  python3 run_api_baseline.py --model glm-5.3                 # 全量 1,034
  python3 run_api_baseline.py --model all                     # 依次跑全部
断点续跑：已完成 event_id 会跳过（completions 文件即检查点）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import concurrent.futures as cf
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent
_TRAIN = _HERE.parent / "rlvr" / "training"
sys.path.insert(0, str(_TRAIN))
sys.path.insert(0, str(_TRAIN / "remote_scripts"))

from prompt_template_papv import build_messages_for_papv       # noqa: E402
from eval_papv_remote import evaluate_completions              # noqa: E402

ARK_BASE = os.environ.get("ARK_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3")
ARK_KEY = os.environ.get("ARK_API_KEY", "")
if not ARK_KEY:
    raise SystemExit("set ARK_API_KEY in the environment (key is not committed)")

MODELS = ["glm-5.3", "glm-5.3-flash", "deepseek-v4-pro", "deepseek-v4-flash", "kimi-k3"]
DATA = _HERE / "data_v61_test"
OUT = _HERE / "outputs"


def load_rows() -> list[dict]:
    events, labels, cache = {}, {}, {}
    for fn, store in (("events_enriched.jsonl", events),
                     ("labels.jsonl", labels),
                     ("research_cache.jsonl", cache)):
        with open(DATA / fn, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                store[d["event_id"]] = d
    rows = []
    for eid, ev in events.items():
        if eid not in labels:
            continue
        rows.append({
            "event_id": eid,
            "event": ev,
            "label": labels[eid],
            "research": cache.get(eid),
        })
    return rows


def call_ark(model: str, messages: list[dict], temperature: float,
              max_retries: int = 4) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
    }
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {ARK_KEY}"}
    for i in range(max_retries):
        try:
            r = requests.post(f"{ARK_BASE}/chat/completions",
                              json=payload, headers=headers, timeout=180)
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"]
                content = (msg.get("content") or "").strip()
                if content:
                    return content
                # content 空（极端情况：全部预算耗在 reasoning）→ 重试
                payload["max_tokens"] = min(payload["max_tokens"] * 2, 16384)
            elif r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 * (i + 1))
            else:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException:
            if i == max_retries - 1:
                raise
            time.sleep(5 * (i + 1))
    raise RuntimeError("exhausted retries")


def run_model(model: str, rows: list[dict], n: int | None,
              temperature: float, workers: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{model.replace('/', '_')}_completions.jsonl"
    done: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line)["event_id"])
                    except Exception:
                        pass
    todo = [r for r in rows if r["event_id"] not in done][:n]
    print(f"[{model}] total={len(rows)} done={len(done)} todo={len(todo)}")

    lock_write = []

    def work(r: dict) -> dict | None:
        msgs = build_messages_for_papv(r["event"], r["research"])
        try:
            content = call_ark(model, msgs, temperature)
            return {"event_id": r["event_id"], "model": model, "content": content}
        except Exception as exc:
            return {"event_id": r["event_id"], "model": model,
                    "error": str(exc)[:200]}

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(work, todo), 1):
            if res is None:
                continue
            lock_write.append(res)
            if i % 20 == 0 or i == len(todo):
                with open(out_path, "a", encoding="utf-8") as f:
                    for w in lock_write:
                        f.write(json.dumps(w, ensure_ascii=False) + "\n")
                    f.flush()
                lock_write = []
                el = time.time() - t0
                eta = el / i * (len(todo) - i) / 60
                print(f"  [{model}] {i}/{len(todo)} ({el/i:.1f}s/req, ETA {eta:.0f}m)")

    # ---- 结算（与论文同一口径）----
    comp_by_eid: dict[str, str] = {}
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("content"):
                comp_by_eid[d["event_id"]] = d["content"]
    eval_rows = [r for r in rows if r["event_id"] in comp_by_eid]
    completions = [comp_by_eid[r["event_id"]] for r in eval_rows]
    label_jsons = [json.dumps(r["label"], ensure_ascii=False) for r in eval_rows]
    if completions:
        metrics = evaluate_completions(completions, label_jsons)
        metrics["model"] = model
        metrics["n_eval"] = len(completions)
        mpath = OUT / f"{model.replace('/', '_')}_metrics.json"
        mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        print(f"[{model}] ACC={metrics.get('acc')} n={len(completions)} → {mpath.name}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True,
                    help=f"one of {MODELS} or 'all'")
    ap.add_argument("--n", type=int, default=None, help="limit events (pilot)")
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows = load_rows()
    print(f"loaded {len(rows)} OOS rows")

    models = MODELS if args.model == "all" else [args.model]
    for m in models:
        run_model(m, rows, args.n, args.temperature, args.workers)


if __name__ == "__main__":
    main()
