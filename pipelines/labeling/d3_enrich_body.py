"""d3: 单薄事件 body 补齐
策略：
  1. 所有事件：body = 优先用 event_text（非 notice 的已经是结构化正文）
  2. notice 类额外：body = "【公告标题】" + title + "\n【公告类型】" + event_type_l2 + "\n【摘要】" + event_text
  3. 保留 _body_source 字段标记补全来源，后续可重新遍历补深正文
输出：pronoia_run/data_v3/events_enriched.jsonl
"""
import json
from pathlib import Path
from collections import Counter

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = _PROJECT_ROOT / "pronoia_run" / "data_v3" / "events.jsonl"
DST = _PROJECT_ROOT / "pronoia_run" / "data_v3" / "events_enriched.jsonl"

rows_in = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
print(f"Read {len(rows_in)} rows from {SRC}")

cnt_body_source = Counter()
notice_written = 0
out_rows = []

for r in rows_in:
    r2 = dict(r)
    src = r.get("_source", "?")
    title = str(r.get("title") or "").strip()
    et = str(r.get("event_text") or "").strip()
    et2 = str(r.get("event_type_l2") or "").strip()
    existing_body = str(r.get("body") or r.get("content") or "").strip()

    if existing_body and len(existing_body) > 50:
        r2["body"] = existing_body
        r2["_body_source"] = "original"
        cnt_body_source["original"] += 1
    elif src == "notice":
        # notice 类：标题 + 类型 + 摘要
        parts = []
        if title:
            parts.append(f"【公告标题】{title}")
        if et2:
            parts.append(f"【公告类型】{et2}")
        if et:
            parts.append(f"【摘要】{et}")
        body = "\n".join(parts) if parts else (title or et or "")
        r2["body"] = body
        r2["_body_source"] = "notice_title_fallback"
        cnt_body_source["notice_title_fallback"] += 1
        notice_written += 1
    else:
        # 其他源（yjyg / yjkb / 宏观等）：event_text 已经是结构化正文
        body = et if et else (title or "")
        r2["body"] = body
        r2["_body_source"] = "event_text"
        cnt_body_source["event_text"] += 1

    out_rows.append(r2)

with open(DST, "w", encoding="utf-8") as f:
    for r in out_rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# 统计
print(f"Wrote {len(out_rows)} rows to {DST}")
print(f"Body source: {dict(cnt_body_source)}")
print(f"Notice title fallback: {notice_written}")

# body 长度分布
lens = sorted([len(str(r.get("body",""))) for r in out_rows])
print(f"Body len: min={lens[0]} p10={lens[len(lens)//10]} p50={lens[len(lens)//2]} p90={lens[9*len(lens)//10]} max={lens[-1]}")

# 样例
for tag, src in [("notice fallback", "notice_title_fallback"), ("event_text yjyg", "event_text")]:
    for r in out_rows:
        if r.get("_body_source") == src:
            print(f"\n=== Sample: {tag} ===")
            print(f"  market={r['market']} sym={r['symbol']} type={r.get('event_type_l2')}")
            print(f"  title={r.get('title')}")
            print(f"  body (len={len(r['body'])}):\n{r['body'][:600]}")
            break
