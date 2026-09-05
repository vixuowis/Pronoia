#!/usr/bin/env bash
# progress.sh — 一行命令看 Team full 推理进度
set -u
RUN_DIR=/workspace/pronoia_run
RC=$RUN_DIR/data_v3/audit/research_cache_team.jsonl
TRAJ=$RUN_DIR/team_traj_v3
LOG=$RUN_DIR/logs/team_batch.log
TOTAL=5174

echo "========== Team full 推理进度 ($(date '+%m-%d %H:%M')) =========="
[ -f "$RC" ]   && rc_lines=$(wc -l < "$RC")   || rc_lines=0
[ -d "$TRAJ" ] && traj_n=$(find "$TRAJ" -maxdepth 1 -name "*.json" | wc -l) || traj_n=0

PY=python3
ok=0; err=0; up=0; down=0; neu=0; mean_conf=0; p50_wall=0
if [ -f "$RC" ] && [ "$rc_lines" -gt 0 ]; then
    read ok err up down neu mean_conf p50_wall < <($PY -c "
import json, statistics
rows=[json.loads(l) for l in open('$RC')]
ok=sum(1 for r in rows if r.get('ok'))
err=len(rows)-ok
dirs=[r.get('direction','') for r in rows if r.get('ok')]
up=dirs.count('up'); down=dirs.count('down'); neu=dirs.count('neutral')
confs=[r.get('confidence',0) for r in rows if r.get('ok')]
walls=[r.get('wall_sec',0) for r in rows if r.get('ok')]
walls.sort()
mc = round(sum(confs)/len(confs),3) if confs else 0
pw = round(statistics.median(walls),1) if walls else 0
print(ok, err, up, down, neu, mc, pw)
")
fi

done=$ok
todo=$((TOTAL - done))
pct=$(awk "BEGIN{printf \"%.2f\", 100*$done/$TOTAL}")

# 并发 16, p50_wall 秒 / 条，估算吞吐
if [ "$p50_wall" != "0" ]; then
    per_hour=$(awk "BEGIN{x=16*3600/$p50_wall; printf \"%.0f\", x}")
    eta_h=$(awk   "BEGIN{if($per_hour>0) printf \"%.1f\", $todo/$per_hour; else print \"?\"}")
else
    per_hour="?"; eta_h="?"
fi

printf "总事件   : %d\n"      "$TOTAL"
printf "已完成   : %d / %d    (%s%%)    rc_lines=%d, traj=%d\n" "$done" "$TOTAL" "$pct" "$rc_lines" "$traj_n"
printf "  ok=%d  err=%d  (方向 up/neutral/down = %d / %d / %d)\n" "$ok" "$err" "$up" "$neu" "$down"
printf "  置信度均值=%.3f   单条 p50 耗时=%.1fs ≈ %.1f 分钟\n" "$mean_conf" "$p50_wall" "$(awk "BEGIN{printf \"%.1f\", $p50_wall/60}")"
printf "剩余     : %d 条\n"    "$todo"
printf "吞吐估算 : ≈ %s 条/小时 (并发 16, p50)   →  ETA ≈ %s 小时 = ≈ %s 天\n" "$per_hour" "$eta_h" "$(awk "BEGIN{if(\"$eta_h\"!=\"?\") printf \"%.1f\", $eta_h/24; else print \"?\"}")"
echo
echo "--- 最近 10 条 PROG/DONE 日志 ---"
[ -f "$LOG" ] && grep -E '^\[(PROG|DONE|RESUME|PLAN)\]' "$LOG" | tail -10 || echo "(无日志 $LOG)"
