"""d3b: 清理 research_cache_team.jsonl — 剔 ok=false，去重（同一 event_id 留最后一条）。"""
import json, shutil
from collections import OrderedDict
src='/workspace/pronoia_run/data_v3/audit/research_cache_team.jsonl'
rows=[]
with open(src) as f:
    for l in f:
        l=l.strip()
        if l: rows.append(json.loads(l))

# 留 ok=true 的，同一 event_id 覆盖（最后一条为准）
dedup=OrderedDict()
err_cnt=0
for r in rows:
    if r.get('ok'):
        dedup[r['event_id']]=r
    else:
        err_cnt+=1

shutil.copy2(src, src + '.bak_err')
with open(src, 'w', encoding='utf-8') as f:
    for r in dedup.values():
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'before: {len(rows)}   err_rows: {err_cnt}   after dedup_ok_only: {len(dedup)}')
