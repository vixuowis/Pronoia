import json
from collections import Counter
rows = [json.loads(l) for l in open("/root/Pronoia/pronoia_run/today_test/events_today.jsonl")]
print(f"total events: {len(rows)}")
print(f"market: {dict(Counter(e['market'] for e in rows))}")
print(f"etype:  {dict(Counter(e['event_type_l2'] for e in rows))}")
print(f"window: {dict(sorted(Counter(e['_window'] for e in rows).items()))}")
for w in sorted(set(e['_window'] for e in rows)):
    ws = [e for e in rows if e['_window'] == w]
    print(f"  [{w}] ({len(ws)} events)")
    for e in ws[:2]:
        s = e['symbol']
        print(f"    {e['market']} {s:>8s} {e['event_type_l2'][:8]} q={e['_qscore']} {e['title'][:35]}")
