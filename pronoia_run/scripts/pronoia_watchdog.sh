#!/usr/bin/env bash
# =====================================================
# pronoia_watchdog.sh
#  双职责（30s 循环轮巡）：
#   ① 进程守护：team_research_batch 不在了就调 restore_after_reboot.sh 拉起
#   ② 数据防丢：每 BACKUP_EVERY_SEC 秒把 rc_team / traj 快照到 backup/
#   ③ 数据一致性：rc_team 行数 sanity / JSON 语法 / traj 数对齐，异常报警
# =====================================================
set -u
RUN_DIR=/workspace/pronoia_run
SCRIPTS=$RUN_DIR/scripts
RC=$RUN_DIR/data_v3/audit/research_cache_team.jsonl
TRAJ=$RUN_DIR/team_traj_v3
ENV_BACKUP=$RUN_DIR/dotenv_backup.env
BACKUP_DIR=$RUN_DIR/backup
LOG=$RUN_DIR/logs/watchdog.log

CHECK_INTERVAL_SEC=30            # 主循环 tick
BACKUP_EVERY_SEC=900             # 每 15 分钟做一次数据快照
HEARTBEAT_EVERY_SEC=600          # 每 10 分钟无论如何打一条 heartbeat
REPORT_EVERY_SEC=1800            # 每 30 分钟产出 progress_report 归档（配合外部 Schedule 触发）
MAX_BACKUPS=24                   # 最多保留 24 份（≈ 6 小时 / 15m 一份；够用）

PROCFEATURE='team_research_batch.py.*audit/research_cache_team'  # 稳定特征，避免误匹配
PY=python3
REPORT_SCRIPT=$SCRIPTS/progress_report.sh

mkdir -p "$BACKUP_DIR" "$RUN_DIR/logs"

log()   { printf '[wdog] %s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
warn()  { printf '[wdog] %s  WARN  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
err()   { printf '[wdog] %s  ERROR %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

last_backup=0
last_heartbeat=0
last_report=0

# ---------- helper: 快照 ----------
snapshot(){
    local tag=$1
    local ts=$(date '+%Y%m%d_%H%M%S')
    local dir="$BACKUP_DIR/${tag}_${ts}"
    mkdir -p "$dir/audit" "$dir/team_traj_v3"
    [ -f "$RC"   ] && cp -a "$RC"   "$dir/audit/research_cache_team.jsonl"
    # traj 很多文件，用 rsync 风格 cp（保留软链/权限，增量级）
    if [ -d "$TRAJ" ]; then
        # 只 cp 新增/变更的（用 -u 可按 mtime，比全 cp 快）
        cp -au "$TRAJ"/* "$dir/team_traj_v3/" 2>/dev/null
    fi
    # 元信息：rc_lines / traj 数
    local rc_lines=0; [ -f "$RC" ] && rc_lines=$(wc -l < "$RC")
    local traj_n=0;   [ -d "$TRAJ" ] && traj_n=$(find "$TRAJ" -maxdepth 1 -name "*.json" | wc -l)
    {
        echo "timestamp=$(date -Iseconds)"
        echo "tag=$tag"
        echo "rc_lines=$rc_lines"
        echo "traj_files=$traj_n"
        echo "rc_sha256=$( (sha256sum "$RC" 2>/dev/null || echo '-') | awk '{print $1}' )"
    } > "$dir/manifest.txt"
    echo "$ts $tag rc=$rc_lines traj=$traj_n" >> "$BACKUP_DIR/backup.log"
    # 保留最近 MAX_BACKUPS 份，旧的删（按名字顺序）
    total=$(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d | sort | wc -l)
    if [ "$total" -gt "$MAX_BACKUPS" ]; then
        n_del=$((total - MAX_BACKUPS))
        find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d | sort | head -n "$n_del" | xargs -r rm -rf
        log "backup 清理旧快照 $n_del 份，保留 <=$MAX_BACKUPS"
    fi
    log "数据快照完成: $dir  (rc=$(wc -l < "$dir/audit/research_cache_team.jsonl" 2>/dev/null || echo 0)  traj=$(find "$dir/team_traj_v3" -name "*.json" | wc -l))"
}

# ---------- helper: 一致性校验 ----------
sanity_check(){
    # 返回 0=ok, 非0=报警
    local bad=0
    # .env 备份在
    [ -f "$ENV_BACKUP" ] || { warn ".env 备份不存在 $ENV_BACKUP"; bad=$((bad+1)); }
    # rc 文件存在、可读、每行合法 JSON、ok=true 占比
    if [ ! -f "$RC" ]; then
        warn "research_cache_team.jsonl 不存在！"; bad=$((bad+1))
    else
        # JSON 解析 & 统计
        local res
        res=$($PY -c "
import json,sys
rows=[]
bad_lines=[]
with open('$RC') as f:
    for i,l in enumerate(f,1):
        l=l.strip()
        if not l: continue
        try: rows.append(json.loads(l))
        except Exception as e: bad_lines.append((i,str(e)))
ok=sum(1 for r in rows if r.get('ok'))
total=len(rows)
err=total-ok
rc_ids=set(r['event_id'] for r in rows if r.get('ok'))
import os
traj_ids=set(fn[:-5] for fn in os.listdir('$TRAJ') if fn.endswith('.json')) if os.path.isdir('$TRAJ') else set()
only_rc=sorted(rc_ids-traj_ids)[:10]
only_t=sorted(traj_ids-rc_ids)[:10]
print(f'TOTAL {total} OK {ok} ERR {err} BADJSON {len(bad_lines)}')
print(f'UNMATCH rc_only {len(rc_ids-traj_ids)} traj_only {len(traj_ids-rc_ids)}')
print(f'RCONLY_HEAD {only_rc}')
print(f'TONLY_HEAD {only_t}')
" 2>&1)
        echo "$res" | tee -a "$LOG"
        case "$res" in
            *' BADJSON '*[1-9]*|*' ERR '*[1-9]*' '*|*'UNMATCH rc_only '*[1-9]*|*'UNMATCH traj_only '*[1-9]*)
                bad=$((bad+1))
                warn "数据 sanity 异常，请立即检查。$res"
                ;;
        esac
    fi
    [ "$bad" -gt 0 ] && return 1
    return 0
}

# ---------- 单实例锁：用 flock 保证同一时刻只跑 1 个 watchdog（即使 setsid + supervisor 都启动）----------
LOCK=/var/run/pronoia_watchdog.lock
exec 9>"$LOCK"
if ! flock -n 9; then
    # 另一个实例已持锁 → 安静退出（定期 1min 打印一句 standby 以便人工确认进程还活着）
    while sleep 60; do
        printf '[wdog-standby] %s  PID=%s 已有主 watchdog 持锁 %s，我待命不工作\n' \
            "$(date '+%Y-%m-%d %H:%M:%S')" "$$" "$LOCK" >> "$LOG"
    done
fi

# ---------- 初始化 ----------
log "=== watchdog 启动（主实例 持锁 pid=$$） ==="
log "  PROCFEATURE=$PROCFEATURE"
log "  CHECK_INTERVAL=${CHECK_INTERVAL_SEC}s   BACKUP_EVERY=${BACKUP_EVERY_SEC}s   MAX_BACKUPS=$MAX_BACKUPS"
log "  PID=$$"

# 启动先立即做一次 sanity
sanity_check || warn "启动时 sanity 异常（见上），继续运行"

# ---------- 主循环 ----------
trap 'log "收到退出信号，watchdog 结束 pid=$$"; exit 0' TERM INT
while :; do
    now=$(date +%s)

    # ---- (1) 进程守护 ----
    PIDS=$(pgrep -f "$PROCFEATURE" | paste -sd,)
    if [ -z "$PIDS" ]; then
        err "team_research_batch 进程不存在！触发 restore_after_reboot.sh 拉起..."
        if [ -x "$SCRIPTS/restore_after_reboot.sh" ]; then
            bash "$SCRIPTS/restore_after_reboot.sh" >> "$LOG" 2>&1
            sleep 5
            NEW=$(pgrep -f "$PROCFEATURE" | paste -sd,)
            if [ -n "$NEW" ]; then
                log "✅ 自动拉起成功，新 PID=$NEW"
            else
                err "❌ 拉起失败！请人工查看 $LOG 与 $RUN_DIR/logs/team_batch.log"
            fi
        else
            err "找不到 $SCRIPTS/restore_after_reboot.sh，无法自动拉起"
        fi
    fi

    # ---- (2) 备份 ----
    if [ $(( now - last_backup )) -ge "$BACKUP_EVERY_SEC" ] || [ "$last_backup" -eq 0 ]; then
        snapshot scheduled
        last_backup=$now
    fi

    # ---- (3) 每 3 个 tick 做一次 sanity ----
    # （30s×2 = 60s 一次）
    if [ $(( now % 60 )) -lt $CHECK_INTERVAL_SEC ]; then
        sanity_check || snapshot sanity_fail_urgent
    fi

    # ---- (4) heartbeat ----
    if [ $(( now - last_heartbeat )) -ge "$HEARTBEAT_EVERY_SEC" ]; then
        rc_lines=0; [ -f "$RC" ] && rc_lines=$(wc -l < "$RC")
        traj_n=0;  [ -d "$TRAJ" ] && traj_n=$(find "$TRAJ" -maxdepth 1 -name "*.json" | wc -l)
        log "heartbeat OK. pid_worker=${PIDS:-<none>}  rc_lines=$rc_lines  traj=$traj_n"
        last_heartbeat=$now
    fi

    # ---- (5) 30 分钟进度汇报（容器内兜底触发，确保 Schedule 断了也能产出归档）----
    if [ $(( now - last_report )) -ge "$REPORT_EVERY_SEC" ] || [ "$last_report" -eq 0 ]; then
        if [ -x "$REPORT_SCRIPT" ]; then
            log "触发 30min 进度汇报（watchdog 端归档）..."
            # 只取 REPORT_PATH 行写到 wdog 日志 + 单独 LOG，不要把整篇 md 塞 wdog.log
            out=$("$REPORT_SCRIPT" 2>/dev/null | grep -E '^===REPORT_PATH=.*===$' | head -1 | sed -E 's/^===REPORT_PATH=(.*)===$/\1/')
            if [ -n "$out" ]; then
                log "✅ 汇报完成 → $out"
                echo "$(date -Iseconds) watchdog_triggered $out" >> "$RUN_DIR/logs/report_triggers.log"
            else
                warn "30min 汇报执行但未拿到 REPORT_PATH，可能 progress_report.sh 出错，检查日志 $RUN_DIR/logs/watchdog.log 附近 stderr"
            fi
        else
            warn "progress_report.sh 不存在或不可执行: $REPORT_SCRIPT"
        fi
        last_report=$now
    fi

    sleep "$CHECK_INTERVAL_SEC"
done
