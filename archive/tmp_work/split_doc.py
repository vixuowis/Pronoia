#!/usr/bin/env python3
"""Split the fetched doc XML into h1 sections for reorganization."""
import re, json, os

raw = open('/workspace/tmp_work/nx8_doc_full_raw.txt', encoding='utf-8').read().strip()
if raw.startswith('"'):
    raw = json.loads(raw)

m = re.match(r'<title>(.*?)</title>', raw)
title = m.group(1) if m else ''
body = raw[m.end():] if m else raw

h1_positions = [mm.start() for mm in re.finditer(r'<h1\b', body)]
print(f'title: {title}')
print(f'h1 count: {len(h1_positions)}')

sections = []
for i, pos in enumerate(h1_positions):
    end = h1_positions[i+1] if i+1 < len(h1_positions) else len(body)
    seg = body[pos:end]
    hm = re.match(r'<h1[^>]*>(.*?)</h1>', seg, re.S)
    htext = re.sub(r'<[^>]+>', '', hm.group(1)) if hm else '?'
    sections.append({'idx': i, 'title': htext, 'start': pos, 'end': end, 'len': end-pos})

prelude = body[:h1_positions[0]] if h1_positions else body
print(f'prelude len: {len(prelude)}')
for s in sections:
    print(f"  [{s['idx']:02d}] {s['title']}  ({s['len']} chars)")

outdir = '/tmp/nx8_sections'
os.makedirs(outdir, exist_ok=True)
open(f'{outdir}/_prelude.xml', 'w', encoding='utf-8').write(prelude)
for s in sections:
    open(f"{outdir}/{s['idx']:02d}.xml", 'w', encoding='utf-8').write(body[s['start']:s['end']])
json.dump(sections, open(f'{outdir}/_meta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
