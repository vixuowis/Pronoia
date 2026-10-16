#!/usr/bin/env python3
"""retry_missing.py — 定向补跑某模型缺失的 event_id（error / 空 content 行）。

glm-5.3 是推理模型：reasoning_content 吃满 8192 预算后 content 为空；
翻倍到 16384 后生成耗时 > 180s 触发 Read timed out。本脚本用 max_tokens=16384
+ timeout=900s 的专用调用，as_completed + 每条即时落盘，无队头阻塞。

用法：
  python3 -u retry_missing.py --model glm-5.3 --workers 6
断点续跑：每次先算「已有 content 的 event_id」，只补差集。
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
sys.path.insert(0, str(_HERE.parent / "rlvr" / "training"))
sys.path.insert(0, str(_HERE.parent / "rlvr" / "training" / "remote_scripts"))

from prompt_template_papv import build_messages_for_papv       # noqa: E402
from eval_papv_remote import evaluate_completions              # noqa: E402
import run_api_baseline as rab                                 # noqa: E402

ARK_BASE = os.environ.get("ARK_BASE", rab.ARK_BASE)
ARK_KEY = os.environ.get("ARK_API_KEY", rab.ARK_KEY)


def call_long(model: str, messages: list[dict], temperature: float) -> str | None:
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": 8192}
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {ARK_KEY}"}
    for i in range(3):
        try:
            r = requests.post(f"{ARK_BASE}/chat/completions",
                              json=payload, headers=headers, timeout=900)
            if r.status_code == 200:
                msg = r.json()["choices"][0]["message"]
                content = (msg.get("content") or "").strip()
                if content:
                    return content
                return None  # 推理过长未产出 content，留待下轮
            elif r.status_code in (429, 500, 502, 503, 504):
                time.sleep(10 * (i + 1))
            else:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(10 * (i + 1))
    raise RuntimeError("exhausted retries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rab.OUT.mkdir(parents=True, exist_ok=True)
    out_path = rab.OUT / f"{args.model.replace('/', '_')}_completions.jsonl"

    rows = rab.load_rows()
    valid: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("content"):
                        valid.add(d["event_id"])
                except Exception:
                    pass
    todo = [r for r in rows if r["event_id"] not in valid]
    print(f"[retry] model={args.model} rows={len(rows)} valid={len(valid)} "
          f"missing={len(todo)}", flush=True)
    if not todo:
        print("[retry] nothing to do", flush=True)
        return

    # glm-5.3 对部分事件会把全部 token 花在 reasoning_content 上而不输出 content。
    # 前置一条 system 消息约束推理长度，逼出结构化断言（不改变任务与输出契约）。
    SYS = {"role": "system",
           "content": "Output your final structured answer directly. "
                      "Keep internal reasoning under 500 tokens."}

    def work(r: dict) -> dict:
        msgs = [SYS] + build_messages_for_papv(r["event"], r["research"])
        try:
            content = call_long(args.model, msgs, args.temperature)
            if not content:
                return {"event_id": r["event_id"], "model": args.model,
                        "error": "empty_content_after_reasoning"}
            return {"event_id": r["event_id"], "model": args.model, "content": content}
        except Exception as exc:
            return {"event_id": r["event_id"], "model": args.model,
                    "error": str(exc)[:200]}

    t0 = time.time()
    ok = err = 0
    with open(out_path, "a", encoding="utf-8") as fout:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(work, r): r["event_id"] for r in todo}
            for done, fut in enumerate(cf.as_completed(futs), 1):
                res = fut.result()
                fout.write(json.dumps(res, ensure_ascii=False) + "\n")
                fout.flush()
                if res.get("content"):
                    ok += 1
                else:
                    err += 1
                el = time.time() - t0
                eta = el / done * (len(todo) - done) / 60
                print(f"  [{done}/{len(todo)}] ok={ok} err={err} "
                      f"({el/done:.1f}s/req, ETA {eta:.0f}m)", flush=True)

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
        metrics["model"] = args.model
        metrics["n_eval"] = len(completions)
        mpath = rab.OUT / f"{args.model.replace('/', '_')}_metrics.json"
        mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                         encoding="utf-8")
        print(f"[retry] DONE accuracy={metrics.get('accuracy')} "
              f"n_eval={len(completions)} -> {mpath.name}", flush=True)


if __name__ == "__main__":
    main()
