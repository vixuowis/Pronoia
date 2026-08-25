"""全量自动泄漏扫描：检测 rationale 是否引用事件后可得的信息。"""
import json, os, re, collections

BASE = "/root/pronoia/data_v5"
CACHE = os.path.join(BASE, "research_cache.jsonl")
EVS = os.path.join(BASE, "events_enriched.jsonl")

def load(p):
    return [json.loads(l) for l in open(p) if l.strip()]

evs = {str(e.get("event_id") or ""): e for e in load(EVS)}

# 一、通告之后结果措辞（后视、见分晓、实际涨/跌）
PAT_FORWARD = [
    (r"(?i)(事(in|前|后)).{0,12}(果然|后来|接着|随后).{0,20}(涨|跌|收)", "前后相接+涨跌"),
    (r"(?i)(event_date|T90|T60|T30|T15|T7|T3).{0,6}(shot|标定|real|actual|已发生|已达成|坐实|兑现结果)", "事后结果"),
    (r"(?i)\b(最终收盘|收盘价定格|later|afterwards|in hindsight|as it turned out)\b", "事后措辞"),
]
# 二、引用超出事件日的日期文本（T+X 之后的明确日期）—— 交给时间线逻辑，这里先查可疑数量词
PAT_LONG = [
    (r"(?i)(未来|后续|事后|之后预计).{0,12}(\d+(\.\d+)?%|[+-]\d+(\.\d+)?(pct|bp)?)", "未来番涨跌"),
    (r"(?i)(实际上|事实上|结果是|回头看).{0,10}(涨|跌|收|突破|跌破)", "确定口吻援引结果"),
    (r"(?i)(已.{0,6}(涨|跌|收)|涨幅已达|已从.{0,10}跌到|已突破|已跌破)", "绝定口吻现状"),
]
# 三、极端：直接引用未来 y 或后续月份业绩
PAT_FUT = [
    (r"(?i)(次年|下季度|2027|2028)[^。]{0,40}(涨|跌|收|净利|eps)", "跨期业绩/行情"),
]

hits = collections.Counter()
detail = []
with open(CACHE) as f:
    for line in f:
        r = json.loads(line)
        eid = str(r.get("event_id") or "")
        txt = r.get("rationale") or ""
        ed = evs.get(eid, {}).get("event_date") or evs.get(eid, {}).get("published_at") or ""
        for pat, name in PAT_FORWARD + PAT_LONG + PAT_FUT:
            for m in re.finditer(pat, txt):
                s = max(0, m.start() - 12); e = min(len(txt), m.end() + 12)
                hits[name] += 1
                detail.append((eid, ed, name, txt[s:e]))

print("=== 命中统计 ===")
print(json.dumps({"count": len(detail), "by_pattern": hits}, ensure_ascii=False, indent=2))
print("\n=== 命中明细（最多 40 条）===")
for eid, ed, name, snip in detail[:40]:
    print(f"\n[{name}] {eid} | date={ed}\n  …{snip}…")