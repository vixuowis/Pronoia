"""report_struct_probe.py — 查看 report 结构 + 汇总校准指标."""
import json

RUN = "/root/Pronoia/pronoia_run"
for tag in ("v62", "v61"):
    r = json.load(open(f"{RUN}/eval_papv_{tag}_t06_report.json"))
    print("=" * 60)
    print(f"[{tag}] top keys:", list(r.keys()))
    for k, v in r.items():
        if k == "ev_detail":
            print(f"  ev_detail: n={len(v)}; entry keys:", list(v[0].keys()))
        elif k == "sides":
            for side, sv in v.items():
                print(f"  sides.{side}:", json.dumps(sv, ensure_ascii=False)[:400])
        else:
            print(f"  {k}:", json.dumps(v, ensure_ascii=False)[:300])
