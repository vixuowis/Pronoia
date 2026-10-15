#!/usr/bin/env python3
"""run_judge_market.py — LLM-as-judge vs 市场结算一致性（WWW 论文 P0#2）。

论文核心动机的实证：judge 与被评者共享盲区、judge 分数与市场真值系统性不一致。

设计：
  · 素材 = base / v6.2 两个模型在 OOS 集上的已有 completions（不重新生成）；
  · 解析其中全部可结算 claim，分层抽样 N 条（模型来源 × TRUE/FALSE 判断均衡）；
  · judge（glm-5.3）看与当事人完全相同的信息（事件 + 研究上下文 + 指标面板定义，
    不含任何事后数据），对每条 claim 独立给出 TRUE/FALSE + 置信度；
  · 结算口径与主实验一致（settle_claim_truth）。

指标：judge accuracy / Cohen's kappa(judge vs market) / 分置信度校准 /
      与当事人自身 accuracy 的对照。

输出：outputs/judge_market_results.json + judge_verdicts.jsonl（断点续跑）
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import concurrent.futures as cf
from pathlib import Path

import requests

_HERE = Path(__file__).resolve().parent
_TRAIN = _HERE.parent / "rlvr" / "training"
sys.path.insert(0, str(_TRAIN))

from papv_claims import parse_claims, settle_claim_truth          # noqa: E402
from prompt_template import render_research_context              # noqa: E402

ARK_BASE = os.environ.get("ARK_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3")
ARK_KEY = os.environ.get("ARK_API_KEY", "")
if not ARK_KEY:
    raise SystemExit("set ARK_API_KEY in the environment")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "glm-5.3")

DATA = _HERE / "data_v61_test"
JM = _HERE / "judge_market"
OUT = _HERE / "outputs"

JUDGE_SYSTEM = """你是金融事件断言审查员（judge）。你将看到一条针对某事件的可验证二值断言
（指标 + 关系符 + 阈值 + 验证时点），以及与断言提出时完全相同的信息（事件、前置研究上下文、指标定义）。
你的任务：独立判断这条断言在事后是否成立（TRUE 或 FALSE），并给出置信度。

要求：
· 只依据给定信息推理，不得假设能获取事后数据；
· 判断行格式（必须严格遵守）：
  VERDICT: TRUE | 置信度: 0.65 | 理由: 一句话
· 判断只写 TRUE 或 FALSE；置信度 ∈ [0,1]；
· 先输出不超过 3 句的分析，再输出判断行。"""


def load_base() -> tuple[dict, dict, dict]:
    events, labels, cache = {}, {}, {}
    for fn, store in (("events_enriched.jsonl", events),
                      ("labels.jsonl", labels),
                      ("research_cache.jsonl", cache)):
        with open(DATA / fn, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    store[d["event_id"]] = d
    return events, labels, cache


def build_judge_messages(event: dict, research: dict | None, claim_raw: str) -> list[dict]:
    symbol = str(event.get("symbol") or "?")
    market = str(event.get("market") or "?").upper()
    etime = str(event.get("event_time") or "?")[:10]
    etype = str(event.get("event_type_l2") or "?")
    title = str(event.get("title") or "")[:120]
    body = str(event.get("event_text") or event.get("body") or "").strip()
    if len(body) > 900:
        body = body[:900] + "…（截断）"

    parts = [f"## 事件（Market={market} Symbol={symbol} Date={etime} Type={etype}）",
             f"标题：{title}", "", body]
    if research:
        ctx = render_research_context(research)
        if ctx:
            parts += ["", ctx]
    parts += ["", "## 待审断言",
              f"- {claim_raw}",
              "", "## 判断"]
    return [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": "\n".join(parts)}]


def parse_verdict(text: str) -> tuple[bool | None, float | None]:
    m = re.search(r"VERDICT:\s*(TRUE|FALSE)\s*\|\s*置信度:\s*([0-9.]+)", text)
    if not m:
        return None, None
    return m.group(1) == "TRUE", min(max(float(m.group(2)), 0.0), 1.0)


def call_ark(messages: list[dict]) -> str:
    payload = {"model": JUDGE_MODEL, "messages": messages,
               "temperature": 0.2, "max_tokens": 4096}
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {ARK_KEY}"}
    for i in range(4):
        try:
            r = requests.post(f"{ARK_BASE}/chat/completions", json=payload,
                               headers=headers, timeout=240)
            if r.status_code == 200:
                c = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if c:
                    return c
            elif r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 * (i + 1))
            else:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))
    raise RuntimeError("exhausted retries")


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa = sum(a) / n
    pb = sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="sample size")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    events, labels, cache = load_base()
    JM.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    # ---- 收集全部可结算 claim（base + v62，来源均衡）----
    pool = []
    for src, fn in (("base", "oos_v61_base_t06_completions.jsonl"),
                    ("v62", "oos_v62_adapter_t06_completions.jsonl")):
        with open(JM / fn, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                eid = d.get("event_id") or d.get("id") or ""
                text = d.get("completion") or d.get("content") or d.get("output") or ""
                if eid not in labels or not text:
                    continue
                for c in parse_claims(text):
                    truth = settle_claim_truth(c, labels[eid])
                    if truth is None:
                        continue
                    h = re.search(r"_t(\d+)", c["metric"])
                    raw = (f"CLAIM: {c['metric']} {c['op']} {c['thr_raw']} "
                           f"@t{h.group(1) if h else '?'} | 判断: "
                           f"{'TRUE' if c['judge'] else 'FALSE'}")
                    pool.append({"src": src, "event_id": eid, "claim": c,
                                 "claim_raw": raw, "truth": truth,
                                 "model_judge": c["judge"]})
    true_pool = [p for p in pool if p["model_judge"]]
    false_pool = [p for p in pool if not p["model_judge"]]
    print(f"pool={len(pool)} (model-TRUE {len(true_pool)} / model-FALSE {len(false_pool)})")

    rng = random.Random(42)
    half = args.n // 2
    sample = (rng.sample(true_pool, min(half, len(true_pool)))
              + rng.sample(false_pool, min(args.n - half, len(false_pool))))
    rng.shuffle(sample)
    print(f"sampled {len(sample)} claims")

    # ---- 断点续跑 ----
    vpath = OUT / "judge_verdicts.jsonl"
    done: set[str] = set()
    if vpath.exists():
        with open(vpath, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done.add(json.loads(line)["key"])
                    except Exception:
                        pass
    todo = [(i, p) for i, p in enumerate(sample)
            if f"{p['src']}:{p['event_id']}:{p['claim_raw']}" not in done]
    print(f"todo={len(todo)} (done={len(done)})")

    def work(item):
        i, p = item
        key = f"{p['src']}:{p['event_id']}:{p['claim_raw']}"
        try:
            msgs = build_judge_messages(events[p["event_id"]],
                                        cache.get(p["event_id"]), p["claim_raw"])
            text = call_ark(msgs)
            v, conf = parse_verdict(text)
            return {"key": key, "src": p["src"], "event_id": p["event_id"],
                    "claim": p["claim_raw"], "truth": p["truth"],
                    "model_judge": p["model_judge"],
                    "judge": v, "judge_conf": conf}
        except Exception as exc:
            return {"key": key, "error": str(exc)[:150]}

    buf = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(work, todo), 1):
            buf.append(res)
            if i % 10 == 0 or i == len(todo):
                with open(vpath, "a", encoding="utf-8") as f:
                    for w in buf:
                        f.write(json.dumps(w, ensure_ascii=False) + "\n")
                buf = []
                el = time.time() - t0
                print(f"  {i}/{len(todo)} ({el/i:.1f}s/req)")

    # ---- 汇总 ----
    verdicts = []
    with open(vpath, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                if d.get("judge") is not None:
                    verdicts.append(d)

    j, t = [v["judge"] for v in verdicts], [v["truth"] for v in verdicts]
    mj = [v["model_judge"] for v in verdicts]
    n = len(verdicts)
    results = {
        "judge_model": JUDGE_MODEL, "n": n,
        "judge_accuracy": sum(a == b for a, b in zip(j, t)) / n,
        "model_self_accuracy": sum(a == b for a, b in zip(mj, t)) / n,
        "judge_vs_market_kappa": kappa(j, t),
        "judge_vs_model_agreement": sum(a == b for a, b in zip(j, mj)) / n,
        "judge_TRUE_ratio": sum(j) / n,
        "market_TRUE_ratio": sum(t) / n,
    }
    # 分置信度
    bins = {}
    for v in verdicts:
        c = v.get("judge_conf")
        if c is None:
            continue
        b = min(9, int(c * 10))
        bins.setdefault(b, [0, 0])
        bins[b][0] += 1
        bins[b][1] += int(v["judge"] == v["truth"])
    results["judge_conf_bins"] = {
        f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": n_, "acc": round(k / n_, 4)}
        for b, (n_, k) in sorted(bins.items())}
    (OUT / "judge_market_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
