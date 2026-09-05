"""export_to_llamafactory.py — Pronoia-RLVR Step-1 RFT 数据导出（LLaMA-Factory alpaca 格式）。

输入：训练集 events.jsonl + labels.jsonl（5000 条，Q1-Q5 自检 GREEN）
输出：
  · {out_dir}/rlvr_rft_train.json   # alpaca 格式 [{instruction, input, output}]
  · {out_dir}/rlvr_rft_val.json     # 验证集（分层抽样 4%）
  · {out_dir}/dataset_info.json     # LLaMA-Factory 数据集注册（可直接并入 data/dataset_info.json）

样本构造：
  · instruction = 7 段 CoT 系统级任务说明（角色 + 输出格式硬约束）
  · input       = user_message_from_block(...)：场景（market/event_type/主 horizon）+
                  量价 4 维 + vol_regime + Router 先验 + 事件标题/正文
  · output      = build_rft_reference(...)：按 GT 生成的 7 段标准推理链（RFT bootstrap）

用法：
    python3 export_to_llamafactory.py \
        --events  backtesting/rlvr/data/rlvr_train_v1_5000/events.jsonl \
        --labels  backtesting/rlvr/data/rlvr_train_v1_5000/labels.jsonl \
        --out-dir backtesting/rlvr/data/rlvr_train_v1_5000/llamafactory \
        --val-ratio 0.04
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompt_template import build_input_block, user_message_from_block, build_rft_reference  # noqa: E402

INSTRUCTION = (
    "你是 Pronoia-RLVR 事件驱动交易分析器。基于给定的事件信息（市场、事件类型、主评估窗口、"
    "量价 regime、Router 专家先验），严格按以下 7 段结构输出推理链：\n"
    "【0. 预判时间窗口】…\n"
    "【0.5 量价 regime 校验】…（必须引用至少 1 条量价数值）\n"
    "【1. 关键信号提取】…\n"
    "【2. 横向比较】…\n"
    "【3. 反方与限制】…（至少 3 条失效条件）\n"
    "【4. 置信度校准】…（confidence ∈ [0,1] + 依据）\n"
    "【5. 最终方向】direction: up|down|neutral + 融合来源。\n"
    "只输出以上 7 段，不要输出其他内容。"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--val-ratio", type=float, default=0.04)
    ap.add_argument("--seed", type=int, default=20260822)
    ap.add_argument("--require-complete", action="store_true",
                    help="只导出 horizons_complete=True 的样本（默认开启宽松模式：跳过 5 horizon 全缺的）")
    args = ap.parse_args()
    random.seed(args.seed)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events = [json.loads(l) for l in open(args.events, encoding="utf-8") if l.strip()]
    labels = {json.loads(l)["event_id"]: json.loads(l)
              for l in open(args.labels, encoding="utf-8") if l.strip()}
    print(f"[LOAD] events={len(events)} labels={len(labels)}")

    samples = []
    skipped_incomplete = 0
    for e in events:
        eid = str(e.get("event_id") or "")
        lb = labels.get(eid)
        if not lb:
            continue
        if args.require_complete and not lb.get("horizons_complete"):
            skipped_incomplete += 1
            continue
        try:
            block = build_input_block(e, lb, include_ground_truth=True)
            user_msg = user_message_from_block(block)
            ref = build_rft_reference(block)
        except Exception:
            continue
        samples.append({
            "instruction": INSTRUCTION,
            "input": user_msg,
            "output": ref,
            "_meta": {  # LLaMA-Factory 会忽略未知字段；导出前剔除
                "event_id": eid,
                "market": e.get("market"),
                "event_type_l2": e.get("event_type_l2"),
            },
        })

    if args.require_complete:
        print(f"[FILTER] require_complete: 跳过 {skipped_incomplete} 条")
    print(f"[BUILD] 样本 {len(samples)} 条（7 段 CoT instruction/input/output）")

    # 分层抽样验证集：按 (market, event_type_l2) 分层，每层按 val_ratio 抽
    by_layer: dict[tuple, list[int]] = {}
    for i, s in enumerate(samples):
        m = s["_meta"]["market"] or "?"
        et = s["_meta"]["event_type_l2"] or "?"
        by_layer.setdefault((m, et), []).append(i)
    val_idx = set()
    for layer, idxs in by_layer.items():
        k = max(1, round(len(idxs) * args.val_ratio))
        val_idx.update(random.sample(idxs, k))
    train = [samples[i] for i in range(len(samples)) if i not in val_idx]
    val = [samples[i] for i in sorted(val_idx)]
    print(f"[SPLIT] train={len(train)} val={len(val)}（分层 {len(by_layer)} 层）")

    def _clean(rows: list[dict]) -> list[dict]:
        return [{"instruction": r["instruction"], "input": r["input"], "output": r["output"]}
                for r in rows]

    train_path = out_dir / "rlvr_rft_train.json"
    val_path = out_dir / "rlvr_rft_val.json"
    json.dump(_clean(train), open(train_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(_clean(val), open(val_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # LLaMA-Factory dataset_info 注册片段
    info = {
        "rlvr_rft_train": {
            "file_name": str(train_path.name),
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        },
        "rlvr_rft_val": {
            "file_name": str(val_path.name),
            "columns": {"prompt": "instruction", "query": "input", "response": "output"},
        },
    }
    info_path = out_dir / "dataset_info.json"
    json.dump(info, open(info_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 平均长度统计（估算 token ~ 字符/1.6 中英混合）
    avg_in = sum(len(s["input"]) for s in train) / max(1, len(train))
    avg_out = sum(len(s["output"]) for s in train) / max(1, len(train))
    print(f"[STAT] train 平均 input={avg_in:.0f} chars (~{avg_in/1.6:.0f} tok), "
          f"output={avg_out:.0f} chars (~{avg_out/1.6:.0f} tok)")
    print(f"[DONE] 写出 →\n  {train_path} ({train_path.stat().st_size/1e6:.2f} MB)\n"
          f"  {val_path} ({val_path.stat().st_size/1e6:.2f} MB)\n  {info_path}")


if __name__ == "__main__":
    main()
