"""从已落盘的 trajectory ckpt 里直接抽 preds，无需重跑 LLM。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CKPT_DIR = DATA / "_trajectory_ckpt_case_study_v2"
OUT_PREDS = DATA / "preds_case_study_v2_new_pipeline.jsonl"


def main() -> None:
    preds = []
    for cf in sorted(CKPT_DIR.glob("*.json")):
        try:
            ck = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            continue
        eid = ck.get("event_id") or cf.stem
        sex = ck.get("structured_extract") or {}
        pred = ck.get("prediction") or {}
        direction = pred.get("pred_direction") or sex.get("direction") or "neutral"
        confidence = pred.get("confidence") or sex.get("confidence") or 0.5
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.5
        preds.append({
            "event_id": eid,
            "pred_direction": direction,
            "confidence": confidence,
            "run_id": ck.get("run_id", ""),
            "model_version": ck.get("model_version", ""),
            "reasoning": (ck.get("final_reasoning") or "")[:200],
        })
    with open(OUT_PREDS, "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"写 {len(preds)} 条到 {OUT_PREDS}")


if __name__ == "__main__":
    main()
