import json, random, os

rows = [json.loads(l) for l in open("pronoia_run/data_v3/audit/research_cache_team.jsonl") if json.loads(l).get("ok")]
print(f"total ok: {len(rows)}")

samples = random.sample(rows, 3)
for i, r in enumerate(samples):
    eid = r["event_id"]
    d = r.get("direction","?")
    c = r.get("confidence","?")
    rat = r.get("rationale","") or r.get("summary","")
    print(f"\n===== Case {i+1}: event_id={eid} =====")
    print(f"direction={d}  confidence={c}")
    print(f"rationale ({len(rat)} chars): {rat[:600]}")

    traj_dir = "pronoia_run/team_traj_v3"
    found = None
    for fn in os.listdir(traj_dir):
        if fn.endswith(".json"):
            try:
                tf = json.load(open(os.path.join(traj_dir, fn)))
                if tf.get("event_id") == eid:
                    found = fn
                    break
            except:
                continue

    if found:
        tf = json.load(open(os.path.join(traj_dir, found)))
        agents = tf.get("agents", {})
        keys = list(agents.keys()) if agents else []
        print(f"trajectory: {found}")
        print(f"agents: {keys}")
        for name in keys:
            data = agents[name]
            if isinstance(data, dict):
                rounds = data.get("rounds", [])
                print(f"  {name}: {len(rounds)} rounds")
                if rounds and isinstance(rounds[-1], dict):
                    content = rounds[-1].get("content","")
                    print(f"    last content ({len(content)} chars): {content[:400]}")
    else:
        print("trajectory: not found")
