#!/usr/bin/env python3
"""patch_leakfix3.py — 强化 _asof_filter_artifact：
1. 日期识别支持紧凑格式 20260630（int/str）
2. 表行规则改为：行内任意日期单元格 > as-of 即丢弃（同时覆盖报告期列与披露日期列）"""
import sys

SKILL = "/root/Pronoia/backend/app/skills/skill.py"

OLD = '''def _looks_like_date(cell) -> bool:
    if not isinstance(cell, str) or len(cell) < 10:
        return False
    try:
        from datetime import datetime as _dt
        _dt.strptime(cell[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _asof_filter_artifact(art: dict, asof_iso: str) -> dict:
    """裁剪单个 artifact 到 as-of 日：table 按日期列过滤行；kline/line 按日期轴过滤。"""
    if not isinstance(art, dict):
        return art
    payload = art.get("payload")
    if not isinstance(payload, dict):
        return art
    kind = str(art.get("kind") or "")
    if kind == "table":
        cols = payload.get("columns") or []
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows:
            return art
        date_idx = None
        for i, c in enumerate(cols):
            cl = str(c).lower()
            if any(k in cl for k in ("日期", "date", "时间", "报告期")):
                date_idx = i
                break
        if date_idx is None:
            return art  # 无日期列（静态表），原样保留
        kept = [r for r in rows
                if not (isinstance(r, list) and len(r) > date_idx and _looks_like_date(r[date_idx])
                        and str(r[date_idx])[:10] > asof_iso)]
        payload["rows"] = kept
        note = str(payload.get("note") or "")
        payload["note"] = (note + " | " if note else "") + f"strict as-of：已过滤 {asof_iso} 之后的行"
        return art'''

NEW = '''def _norm_date_cell(cell):
    """解析单元格为 ISO 日期串；支持 2024-06-30 / 20240630（str 或 int）。失败返回 None。"""
    if isinstance(cell, bool) or cell is None:
        return None
    if isinstance(cell, int):
        if not (19000101 <= cell <= 20991231):
            return None
        s = str(cell)
    elif isinstance(cell, str):
        s = cell.strip().replace("-", "").replace("/", "")[:8]
        if not s.isdigit() or len(s) != 8:
            return None
    else:
        return None
    if s[:2] not in ("19", "20"):
        return None
    try:
        from datetime import datetime as _dt
        _dt.strptime(s, "%Y%m%d")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    except ValueError:
        return None


def _asof_filter_artifact(art: dict, asof_iso: str) -> dict:
    """裁剪单个 artifact 到 as-of 日。

    table：行内任意日期单元格（报告期/披露日/公告日…）> as-of 即整行丢弃
    （比按单一日期列更严格：含披露日期的表也能正确挡住「期末在事件前、
    披露在事件后」的报告期——那份报告在事件时点尚未公开）。
    kline/line：按日期轴过滤。
    """
    if not isinstance(art, dict):
        return art
    payload = art.get("payload")
    if not isinstance(payload, dict):
        return art
    kind = str(art.get("kind") or "")
    if kind == "table":
        rows = payload.get("rows")
        if not isinstance(rows, list) or not rows:
            return art
        kept = []
        dropped = 0
        for r in rows:
            if isinstance(r, list):
                fut = False
                for c in r:
                    if c is None or isinstance(c, bool):
                        continue
                    d = _norm_date_cell(c)
                    if d and d > asof_iso:
                        fut = True
                        break
                if fut:
                    dropped += 1
                    continue
            kept.append(r)
        if dropped:
            payload["rows"] = kept
            note = str(payload.get("note") or "")
            payload["note"] = (note + " | " if note else "") + f"strict as-of：已过滤 {asof_iso} 之后的 {dropped} 行"
        return art'''

with open(SKILL, encoding="utf-8") as f:
    src = f.read()
if OLD not in src:
    print("[FAIL] helper 原文未找到"); sys.exit(1)
if src.count(OLD) != 1:
    print(f"[FAIL] helper 非唯一({src.count(OLD)})"); sys.exit(1)
src = src.replace(OLD, NEW)
with open(SKILL, "w", encoding="utf-8") as f:
    f.write(src)
print("[OK] skill.py helper 已强化")
