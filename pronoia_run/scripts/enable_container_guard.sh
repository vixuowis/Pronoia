#!/usr/bin/env bash
# =========================================================
# enable_container_guard.sh  —— 一键启用「容器重启不丢」的完整防护链
#  1. 把 watchdog 装到 /etc/supervisor/conf.d/（容器内 PID 级守护，autorestart）
#  2. 备份主 supervisord.conf 并加 include（保证下次 supervisor reload 也生效）
#  3. 立即 reload supervisor + start watchdog
#  4. 再启动一个独立 setsid watchdog 进程兜底（即使 supervisor 配置被误删，兜底还在）
#  5. 写入 enable_guard.manifest，下次 restore_after_reboot 能自动重复本步骤
# =========================================================
set -u
RUN_DIR=/workspace/pronoia_run
SCRIPTS=$RUN_DIR/scripts
WATCHDOG_SRC=$SCRIPTS/pronoia_watchdog.sh
CONF_SRC=$SCRIPTS/supervisor_pronoia_watchdog.conf
CONF_TARGET=/etc/supervisor/conf.d/pronoia_watchdog.conf
SUP_MAIN=/app/supervisord.conf
MANIFEST=$RUN_DIR/logs/enable_guard.manifest

mkdir -p "$RUN_DIR/logs"
chmod +x "$WATCHDOG_SRC"
echo "[guard] Step 1/6 — 复制配置到 $CONF_TARGET"
cp "$CONF_SRC" "$CONF_TARGET"

echo "[guard] Step 2/6 — 主配置 $SUP_MAIN 加 [include]（若尚无 files 指令）"
if ! grep -qE '^\s*\[include\]' "$SUP_MAIN"; then
    cp -a "$SUP_MAIN" "$SUP_MAIN.bak.pronoia_$(date +%Y%m%d)"
    cat >> "$SUP_MAIN" << 'EOF'

[include]
files = /etc/supervisor/conf.d/*.conf
EOF
    echo "  已追加 [include]。"
else
    echo "  已有 [include]，跳过。"
fi

echo "[guard] Step 3/6 — 持久化备份 supervisord.conf 与新 conf"
cp -a "$SUP_MAIN"      "$SCRIPTS/_host_supervisord.conf.saved"
cp -a "$CONF_TARGET"   "$SCRIPTS/_host_pronoia_watchdog.conf.saved"

echo "[guard] Step 4/6 — supervisorctl reread + update 使 watchdog 生效"
supervisorctl reread
supervisorctl update
sleep 3
echo
echo "[guard] 当前 supervisor 程序状态:"
supervisorctl status | tee -a "$MANIFEST"

echo
echo "[guard] Step 5/6 — 兜底：setsid 启动独立 watchdog（非 supervisor 子进程，父进程 PID=1，更稳）"
setsid bash "$WATCHDOG_SRC" </dev/null >> /workspace/pronoia_run/logs/watchdog.setsid.log 2>&1 &
FALLBACK_PID=$!
echo "  兜底 watchdog PID=$FALLBACK_PID"
disown 2>/dev/null

echo
echo "[guard] Step 6/6 — 写入 manifest"
cat > "$MANIFEST" << EOF
generated_at=$(date -Iseconds)
watchdog_script=$WATCHDOG_SRC
supervisor_conf_source=$CONF_SRC
supervisor_conf_installed=$CONF_TARGET
supervisor_include_patched_sup_main=$SUP_MAIN
supervisor_programs=$(supervisorctl status | paste -sd';')
setsid_fallback_pid=$FALLBACK_PID
EOF
cat "$MANIFEST"

echo
echo "===== enable_container_guard 完成 ====="
echo "1) 容器级 (PID 1 / supervisord): program:pronoia_watchdog  autorestart=true  → 进程挂就自动重拉"
echo "2) 兜底级 (setsid, 父 PID=1)   : 独立进程，即使 supervisor 配置丢失也运行"
echo "3) 数据层 (pronoia_watchdog.sh) : 每 15min 快照 rc_team + traj，保留最近 24 份；每 60s JSON sanity / traj 对齐校验"
echo "4) 进程层 (restore_after_reboot.sh) : 检测到 team full 进程没了 → 自动 .env 还原 + pip 依赖补齐 + err 行清理 + 断点续跑启动"
echo
echo "查看 watchdog 日志: tail -50 $RUN_DIR/logs/watchdog.log"
echo "手动停守护:        supervisorctl stop pronoia_watchdog ; pgrep -f pronoia_watchdog.sh | xargs -r kill"
