#!/usr/bin/env bash
# =============================================================
# restore_after_reboot.sh  — 容器重启 / 进程挂掉后「一键恢复」Team full 推理
# 作用：
#   1. 还原 ARK 密钥 (/workspace/.env) 从持久化备份
#   2. 补装可能丢的 pip 依赖
#   3. 检查关键数据文件行数（d1~d5 资产完整性）
#   4. 清理 research_cache_team.jsonl 里的 err 行
#   5. 优雅停掉已有 team_research_batch（避免双开）
#   6. 断点续跑：从已完成的 event_id 继续推进剩余 5xxx 条
#
# 用法:
#   bash /workspace/pronoia_run/scripts/restore_after_reboot.sh
#   bash /workspace/pronoia_run/scripts/restore_after_reboot.sh --dry-run   # 只检查，不启停
# =============================================================
set -u
DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; fi

RUN_DIR=/workspace/pronoia_run
ENV_BACKUP=$RUN_DIR/dotenv_backup.env
ENV_TARGET=/workspace/.env
SCRIPTS=$RUN_DIR/scripts
PIPELINES=$RUN_DIR/../pipelines
EVENTS=$RUN_DIR/data_v3/events.jsonl
LABELS=$RUN_DIR/data_v3/labels.jsonl
ENRICHED=$RUN_DIR/data_v3/events_enriched.jsonl
RC_TEAM=$RUN_DIR/data_v3/audit/research_cache_team.jsonl
TRAJ_DIR=$RUN_DIR/team_traj_v3
LOG_FILE=$RUN_DIR/logs/team_batch.log

BATCH_FEATURE="team_research_batch.py.*audit/research_cache_team"  # 进程识别特征（足够具体，不会误杀）
PY=python3
PIP=pip3

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
log()  { printf "\033[1;36m[restore]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m    %s\n" "$*"; }
die()  { printf "\033[1;31m[err]\033[0m     %s\n" "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1 (请先 apt install $1)" ; }

need python3
need pgrep
need wc

# ---------------------------------------------------------------------------
# Step 1 — 还原 .env
# ---------------------------------------------------------------------------
log "Step 1/6 — 还原 /workspace/.env (密钥)"
if [ ! -f "$ENV_BACKUP" ]; then
    die "持久化备份的 .env 不存在: $ENV_BACKUP  -> 请手动重新写入 ARK_API_KEY 并备份"
fi
if [ "$DRY" -eq 1 ]; then
    echo "  [dry-run] 会执行: cp $ENV_BACKUP $ENV_TARGET ; chmod 600 $ENV_TARGET"
else
    cp "$ENV_BACKUP" "$ENV_TARGET"
    chmod 600 "$ENV_TARGET"
fi
# 验证 config 能读到
KEY_LEN=$($PY -c "
import sys; sys.path.insert(0,'/workspace/backend')
from app.config import LLM_API_KEY
print(len(LLM_API_KEY) if LLM_API_KEY else 0)
" 2>/dev/null)
[ -z "$KEY_LEN" ] && KEY_LEN=0
if [ "$KEY_LEN" -ge 20 ]; then
    log "  → LLM_API_KEY 可读, len=$KEY_LEN  ✅"
else
    warn "  → LLM_API_KEY 未加载 (len=$KEY_LEN)，后续启动大概率报 OpenAIError ❌"
fi

# ---------------------------------------------------------------------------
# Step 2 — 补装依赖（容器重启后 site-packages 可能被清空）
# ---------------------------------------------------------------------------
log "Step 2/6 — 补装 pip 依赖"
PKGS=( akshare openai python-dotenv yfinance )
if [ "$DRY" -eq 1 ]; then
    echo "  [dry-run] 会执行: $PIP install -q ${PKGS[*]}"
else
    $PIP install -q "${PKGS[@]}" 2>&1 | tail -3
fi
for p in "${PKGS[@]}"; do
    have=$($PY -c "import $p; print('ok')" 2>/dev/null || echo "missing")
    if [ "$have" = "ok" ]; then log "  → $p 已安装"; else warn "  → $p 缺失"; fi
done

# ---------------------------------------------------------------------------
# Step 3 — 数据资产完整性 sanity
# ---------------------------------------------------------------------------
log "Step 3/6 — 关键数据文件 sanity"
check_lines() {
    local f=$1 want=$2 name=$3
    if [ ! -f "$f" ]; then warn "  ✗ MISSING: $name ($f)"; return; fi
    local n
    n=$(wc -l < "$f")
    if [ "$n" -ge "$want" ]; then
        log "  ✓ $name : $n lines (≥$want)"
    else
        warn "  ✗ $name : $n lines (<$want 下限) ❗"
    fi
}
check_lines "$EVENTS"    5174 "events.jsonl        (d1 原始事件)"
check_lines "$LABELS"    5171 "labels.jsonl        (d2 K线标签)"
check_lines "$ENRICHED"  5174 "events_enriched     (d3 正文补齐)"
check_lines "$RC_TEAM"   100  "research_cache_team (d5 Team推理缓存)"
traj_n=$(find "$TRAJ_DIR" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l)
if [ "$traj_n" -ge 100 ]; then log "  ✓ trajectory 数目 : $traj_n (≥100)"; else warn "  ✗ trajectory 仅 $traj_n"; fi

# ---------------------------------------------------------------------------
# Step 4 — 清理 err 行 (rc_team 里 ok=false 的会导致断点续跑时反复判定)
# ---------------------------------------------------------------------------
log "Step 4/6 — 清理 rc_team 的 err 行"
if [ ! -f "$PIPELINES/labeling/d3b_cleanup_rc.py" ]; then
    warn "  d3b_cleanup_rc.py 缺失，跳过；如需清理请手动执行"
else
    if [ "$DRY" -eq 1 ]; then
        echo "  [dry-run] 会执行: $PY $PIPELINES/labeling/d3b_cleanup_rc.py"
    else
        $PY "$PIPELINES/labeling/d3b_cleanup_rc.py" || warn "  d3b_cleanup_rc 非零退出，可能没有 err 行可清"
    fi
fi

# ---------------------------------------------------------------------------
# Step 5 — 进程守护：已有进程就保留（否则优雅关停）
# ---------------------------------------------------------------------------
log "Step 5/6 — 检查已有 team_research_batch 进程"
OLD_PIDS=$(pgrep -f "$BATCH_FEATURE" | paste -sd, -)
if [ -n "$OLD_PIDS" ]; then
    log "  已在运行 PID=$OLD_PIDS → 不重复启动（若要强制重启请先手动 kill）"
else
    log "  未发现运行中进程"
    if [ "$DRY" -eq 1 ]; then
        echo "  [dry-run] 会执行: bash $SCRIPTS/start_d5.sh"
    else
        log "Step 6/6 — 断点续跑启动 Team full (并发 16)"
        mkdir -p "$RUN_DIR/logs"
        bash "$SCRIPTS/start_d5.sh"
        sleep 3
        NEW_PIDS=$(pgrep -f "$BATCH_FEATURE" | paste -sd, -)
        if [ -n "$NEW_PIDS" ]; then
            log "  → 启动成功，新 PID=$NEW_PIDS"
            log "  → 日志: tail -f $LOG_FILE"
            log "  → 看进度: bash $SCRIPTS/progress.sh"
        else
            die "启动失败！请手动查看 $LOG_FILE 头部报错"
        fi
    fi
fi

log "===== restore_after_reboot done ====="
