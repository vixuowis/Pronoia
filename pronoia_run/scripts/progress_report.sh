#!/usr/bin/env bash
# progress_report.sh — Team full 30 分钟进度汇报
# 输出 Markdown：stdout + /workspace/pronoia_run/logs/report_YYYYmmdd_HHMM.md
set -u
RUN=/workspace/pronoia_run
RC=$RUN/data_v3/audit/research_cache_team.jsonl
TRAJ=$RUN/team_traj_v3
LOG_RC=$RUN/logs/team_batch.log
LOG_WD=$RUN/logs/watchdog.log
OUTDIR=$RUN/logs
STATE=$OUTDIR/.report_state.json
PY=python3
mkdir -p "$OUTDIR"
TOTAL=5174

ts=$(date '+%Y%m%d_%H%M')
ts_sec=$(date '+%s')
ts_hr=$(date '+%Y-%m-%d %H:%M')
out_md=$OUTDIR/report_${ts}.md
LOCK=/var/run/pronoia_watchdog.lock

# ---------- 单次 Python 脚本：算出所有数值（避免反复在 shell/python 间解析出错）----------
metrics=$($PY - "$RC" "$TRAJ" "$LOG_RC" "$LOG_WD" "$STATE" "$ts_sec" "$TOTAL" "$LOCK" <<'PYEOF'
import json, os, re, statistics, sys
RC, TRAJ, LOG_RC, LOG_WD, STATE, TS_SEC, TOTAL, LOCK = sys.argv[1:9]
TS_SEC = int(TS_SEC); TOTAL = int(TOTAL)

prev = json.load(open(STATE)) if os.path.exists(STATE) else {}
prev_ok = int(prev.get('ok',0))
prev_traj = int(prev.get('traj',0))
prev_rc = int(prev.get('rc',0))
prev_ts = int(prev.get('ts_sec', TS_SEC))
prev_wall = float(prev.get('wall_p50',0))

rows=[]; badjson=0
if os.path.exists(RC):
    with open(RC) as f:
        for i,l in enumerate(f,1):
            l=l.strip()
            if not l: continue
            try: rows.append(json.loads(l))
            except Exception: badjson += 1
rc_lines = len(rows)
ok=sum(1 for r in rows if r.get('ok'))
err=rc_lines-ok
dirs=[r.get('direction','?') for r in rows if r.get('ok')]
up=dirs.count('up'); neu=dirs.count('neutral'); down=dirs.count('down')
confs=[r.get('confidence',0) for r in rows if r.get('ok')]
walls=[r.get('wall_sec',0) for r in rows if r.get('ok')]
conf_mean = round(sum(confs)/len(confs),3) if confs else 0
wall_mean = round(sum(walls)/len(walls),0) if walls else 0
wall_p50 = round(statistics.median(walls),1) if walls else 0
rc_ids=set(r['event_id'] for r in rows if r.get('ok'))
traj_ids=set(fn[:-5] for fn in (os.listdir(TRAJ) if os.path.isdir(TRAJ) else []) if fn.endswith('.json'))
traj_files = len(traj_ids)
rc_only = len(rc_ids - traj_ids)
traj_only = len(traj_ids - rc_ids)
todo = TOTAL - ok
pct_ok = round(100*ok/TOTAL,2)

delta_sec = TS_SEC - prev_ts
if delta_sec <= 0 and prev_ts != TS_SEC:
    delta_sec = 1  # 防 0
delta_ok = ok - prev_ok
delta_traj = traj_files - prev_traj
delta_rc = rc_lines - prev_rc
if prev_ts == TS_SEC:
    delta_min_str = '<1'; delta_min_val = 0.5
    real_tph='n/a'; eta_h_real='n/a'
else:
    dm = delta_sec/60
    delta_min_str = str(round(dm,1)) if dm>=1 else '<1'
    delta_min_val = dm if dm>=1 else 0.5
    if delta_min_val>0 and delta_ok>=0 and dm>=1:
        # 只有 Δ≥1min 才提供"真实吞吐"，否则 0.5min 的 377→ 会被夸大成 4w/h
        real_tph = round(delta_ok*60/delta_min_val,0)
        eta_h_real = round(todo/real_tph,1) if real_tph>0 else 'n/a'
    else:
        real_tph='n/a'; eta_h_real='n/a'
eta_d_real = round(float(eta_h_real)/24,1) if isinstance(eta_h_real,(int,float)) else 'n/a'

wall_p50_num = wall_p50 if isinstance(wall_p50,(int,float)) else 0
tph_p50 = round(32*3600/wall_p50_num,0) if wall_p50_num>0 else 0
eta_h_p50 = round(todo/tph_p50,1) if tph_p50>0 else 'n/a'

# PROG
prog_lines=[]
if os.path.exists(LOG_RC):
    prog_lines = [l.rstrip() for l in open(LOG_RC) if l.startswith('[PROG]')]
prog_section = []
pts=[]
for l in prog_lines:
    m=re.search(r'([0-9]+)/[0-9]+ ok=([0-9]+).* el=([0-9.]+)min',l)
    if m: pts.append((float(m.group(3)), int(m.group(1)), int(m.group(2))))
if len(pts)>=2:
    a=pts[0]; b=pts[-1]
    dn=b[1]-a[1]; dt=b[0]-a[0]
    per_min=dn/dt if dt>0 else 0
    per_h=round(per_min*60,0)
    rates=[(pts[i][1]-pts[i-1][1])/(pts[i][0]-pts[i-1][0])*60 for i in range(1,len(pts)) if pts[i][0]-pts[i-1][0]>0]
    avg=round(sum(rates)/len(rates),0) if rates else 'n/a'
    med=round(statistics.median(rates),0) if rates else 'n/a'
    prog_section += [
        f"最近 {b[1]} done（总起点 {a[1]}），历时 {dt:.1f}min",
        f"  区间整体速率: {dn}条/{dt:.1f}min = {per_h:.0f}条/小时",
        f"  分段速率 avg/median = {avg} / {med} 条/小时",
        "  PROG 最近 5 条:",
    ] + ["   "+l for l in prog_lines[-5:]]
else:
    prog_section = ["  (PROG 记录不足，可能刚启动)"]

# 异常计数
wdog_err=0; team_err=0; recent_wdog=[]
if os.path.exists(LOG_WD):
    lines=open(LOG_WD).read().splitlines()
    for l in lines:
        if any(k in l for k in ['ERROR','WARN','sanity_fail']):
            wdog_err += 1
    for l in lines:
        if any(k in l for k in ['ERROR','WARN','sanity_fail','自动拉起成功','拉起失败','heartbeat OK']):
            recent_wdog.append(l)
    recent_wdog = recent_wdog[-10:]
if os.path.exists(LOG_RC):
    for l in open(LOG_RC):
        if any(k in l for k in ['OpenAIError','Missing credentials','429','Rate limit','Traceback']):
            team_err += 1

# 保存 state
json.dump({'ok':ok,'traj':traj_files,'rc':rc_lines,'ts_sec':TS_SEC,'wall_p50':wall_p50_num}, open(STATE,'w'))

# 一次输出所有 key=value 行（shell 用 `declare` 或 `grep` 解析）
def KV(k,v):
    # v 必须为单 line string
    s = str(v).replace('\n','\\n').replace('\r','')
    print(f"{k}={s}")

KV('ok', ok); KV('rc_lines',rc_lines); KV('err',err); KV('badjson',badjson)
KV('up',up); KV('neu',neu); KV('down',down)
KV('conf_mean',conf_mean); KV('wall_mean',wall_mean); KV('wall_p50',wall_p50)
KV('todo',todo); KV('pct_ok',pct_ok); KV('traj_files',traj_files)
KV('rc_only',rc_only); KV('traj_only',traj_only)
KV('prev_ok',prev_ok); KV('prev_traj',prev_traj); KV('prev_rc',prev_rc)
KV('delta_min_str',delta_min_str); KV('delta_min_val',delta_min_val)
KV('delta_ok',delta_ok); KV('delta_traj',delta_traj); KV('delta_rc',delta_rc)
KV('real_tph',real_tph); KV('eta_h_real',eta_h_real); KV('eta_d_real',eta_d_real)
KV('tph_p50',tph_p50); KV('eta_h_p50',eta_h_p50)
KV('prog_section','||'.join(prog_section))
KV('wdog_err',wdog_err); KV('team_err',team_err)
KV('recent_wdog','||'.join(recent_wdog))
PYEOF
)

# ---------- 解析 KV 到 shell 变量 ----------
declare -A KV=()
while IFS='=' read -r k v; do
    [ -z "${k:-}" ] && continue
    KV[$k]="${v//\\n/$'\n'}"
done <<< "$metrics"

ok=${KV[ok]}; rc_lines=${KV[rc_lines]}; err=${KV[err]}; badjson=${KV[badjson]}
up=${KV[up]}; neu=${KV[neu]}; down=${KV[down]}
conf_mean=${KV[conf_mean]}; wall_mean=${KV[wall_mean]}; wall_p50=${KV[wall_p50]}
todo=${KV[todo]}; pct_ok=${KV[pct_ok]}; traj_files=${KV[traj_files]}
rc_only=${KV[rc_only]}; traj_only=${KV[traj_only]}
delta_min_str=${KV[delta_min_str]}
delta_ok=${KV[delta_ok]}; delta_traj=${KV[delta_traj]}; delta_rc=${KV[delta_rc]}
real_tph=${KV[real_tph]}; eta_h_real=${KV[eta_h_real]}; eta_d_real=${KV[eta_d_real]}
tph_p50=${KV[tph_p50]}; eta_h_p50=${KV[eta_h_p50]}
prog_section_str=${KV[prog_section]}
wdog_err=${KV[wdog_err]}; team_err=${KV[team_err]}
recent_wdog_str=${KV[recent_wdog]}
wall_p50_min=$($PY -c "print(round(float('$wall_p50')/60,1))")

# ---------- 守护 / 进程 ----------
super=$(supervisorctl status 2>&1 | paste -sd' ; ' || true)
if command -v supervisorctl >/dev/null 2>&1 && [[ "$super" == *"pronoia_watchdog"*RUNNING* ]]; then
  wdog_sup="✅ RUNNING"
else
  wdog_sup="⚠️  $super"
fi
wdog_pids=$(pgrep -af 'pronoia_watchdog.sh' 2>/dev/null | awk '{print $1}' | paste -sd, || true)
if [ -n "$wdog_pids" ]; then
  wdog_nproc=$(echo "$wdog_pids" | tr ',' '\n' | grep -c .)
  lock_holder=''
  for p in $(echo "$wdog_pids" | tr ',' ' '); do
    if ls -l /proc/$p/fd 2>/dev/null | grep -q "$LOCK"; then lock_holder+=" $p"; fi
  done
  wdog_detail="✅ 进程 ${wdog_nproc} 个，持锁主实例=${lock_holder:-未知}，PIDs=$wdog_pids"
else
  wdog_detail="❌ 无 watchdog！"
fi
team_pids=$(pgrep -f 'team_research_batch.py.*audit/research_cache_team' 2>/dev/null | paste -sd, || true)
if [ -z "$team_pids" ]; then
  team_stat="❌ 未运行"
else
  team_stat="✅ 运行中 PIDs=$team_pids"
  last_p=$(echo "$team_pids" | awk -F, '{print $NF}')
  conc=$(ps -o args= -p "$last_p" 2>/dev/null | grep -oE 'concurrency [0-9]+' | tail -1 || echo 'concurrency ?')
  team_stat+="  ($conc)"
fi

# ---------- 组装 Markdown ----------
prog_section_fmt=$(printf '%s' "$prog_section_str" | tr '|' '\n')
recent_wdog_fmt=$(printf '%s' "$recent_wdog_str" | tr '|' '\n' | sed 's/^/  - /')
[ -z "$recent_wdog_fmt" ] && recent_wdog_fmt="  （无事件）"

cat > "$out_md" << MD
# 📊 Team full 30 分钟进度汇报 — $ts_hr

**总事件 5174** · 已完成 **$ok/5174 = ${pct_ok}%** · ok=$ok err=$err badjson=$badjson

| 指标 | 本时刻 | 距上次（Δ≈${delta_min_str}min） |
|---|---|---|
| ✅ research_cache (ok=true) | $ok 行 | Δok = **+$delta_ok** |
| ✅ trajectory JSON 数 | $traj_files | Δtraj = **+$delta_traj** |
| ✅ rc_lines 原始文件 | $rc_lines 行 | Δrc = +$delta_rc |
| ↔️ 一致性 (rc_only / traj_only) | $rc_only / $traj_only | 0 为最佳 |
| 🧭 方向 up / neutral / down | $up / $neu / $down | — |
| 🎯 置信度 均值 | $conf_mean | — |
| ⏱ 单条 wall p50 | ${wall_p50}s ≈ ${wall_p50_min} min | — |
| 📦 剩余 todo | $todo 条 | — |

## 🚀 吞吐与 ETA

| 方法 | 吞吐 | ETA |
|---|---|---|
| 📈 **真实 Δok / Δmin**（最可信） | ${real_tph} 条/小时 | ≈ ${eta_h_real} h = ≈ ${eta_d_real} 天 |
| 📐 基准 p50 × 并发 32 | ${tph_p50} 条/小时 | ≈ ${eta_h_p50} h |

**最近 PROG 区间**
$prog_section_fmt

## 🛡 守护 / 进程健康

| 项目 | 状态 |
|---|---|
| Team full 进程 | $team_stat |
| Watchdog (supervisor program) | $wdog_sup |
| Watchdog 双活 + flock 主/备 | $wdog_detail |

## ⚠️ 异常扫描（累计）

- \`watchdog.log\` WARN/ERROR/sanity_fail = **$wdog_err** 条
- \`team_batch.log\` OpenAIError / 429 / Traceback = **$team_err** 条

**最近 watchdog 关键事件**
$recent_wdog_fmt

---

> 归档位置：$out_md · 下次自动汇报 ≈ 30 min 后
MD

echo "===REPORT_PATH=$out_md==="
cat "$out_md"
