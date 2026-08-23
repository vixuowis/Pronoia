import json, os, sys

path = '/root/Pronoia/pronoia_run/data_v3/audit/research_cache_team.jsonl'
rows = [json.loads(l) for l in open(path)]
ok_rows = [r for r in rows if r.get('ok')]
err_rows = [r for r in rows if not r.get('ok')]
print('total:', len(rows), 'ok:', len(ok_rows), 'err:', len(err_rows))

if err_rows:
    with open(path, 'w') as f:
        for r in ok_rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('after clean:', sum(1 for _ in open(path)))

    traj_dir = '/root/Pronoia/pronoia_run/team_traj_v3'
    err_ids = set(r['event_id'] for r in err_rows)
    removed = 0
    for fn in os.listdir(traj_dir):
        if fn.endswith('.json') and fn[:-5] in err_ids:
            os.remove(os.path.join(traj_dir, fn))
            removed += 1
    print('removed traj:', removed)
else:
    print('no err to clean')

print('traj now:', len([f for f in os.listdir(traj_dir) if f.endswith('.json')]))
