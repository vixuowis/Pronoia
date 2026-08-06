"""SQLite persistence layer (stdlib sqlite3, single conn + lock, thread-safe).

Schema (design.md §8):
  cases(id, title, created_at, updated_at)
  messages(id, case_id, role, agent, content, tool_trace, created_at)
  artifacts(id, case_id, message_id, kind, title, payload, pinned, created_at)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db() -> None:
    with _lock:
        conn = _get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages(
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                role TEXT NOT NULL,
                agent TEXT,
                content TEXT,
                tool_trace TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS artifacts(
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                message_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                payload TEXT NOT NULL,
                pinned INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS simulation_jobs(
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                graph_artifact_id TEXT NOT NULL,
                gateway_job_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                request_payload TEXT NOT NULL,
                error TEXT,
                artifact_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
                FOREIGN KEY(graph_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_case ON messages(case_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_artifacts_case ON artifacts(case_id, pinned DESC, created_at);
            -- ==================== Pronoia Backtest tables (P0) ====================
            CREATE TABLE IF NOT EXISTS bt_runs(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                runner TEXT NOT NULL,
                prompt_variant TEXT,
                model_version TEXT,
                events_path TEXT NOT NULL,
                labels_path TEXT,
                out_path TEXT NOT NULL,
                ckpt_dir TEXT,
                concurrency INTEGER DEFAULT 2,
                total_events INTEGER DEFAULT 0,
                done_events INTEGER DEFAULT 0,
                acc_t3_strict REAL,
                acc_t3_strict_lo REAL,
                acc_t3_non_neutral REAL,
                config_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_msg TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bt_runs_status ON bt_runs(status);
            CREATE INDEX IF NOT EXISTS idx_bt_runs_created ON bt_runs(created_at DESC);

            CREATE TABLE IF NOT EXISTS bt_predictions(
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                symbol TEXT,
                market TEXT,
                event_type_l2 TEXT,
                pred_direction TEXT NOT NULL,
                confidence REAL,
                abstain INTEGER DEFAULT 0,
                rationale TEXT,
                oracle_label_t3 TEXT,
                oracle_car_t3 REAL,
                is_correct_t3 INTEGER,
                trajectory_ckpt TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES bt_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bt_pred_run ON bt_predictions(run_id);
            CREATE INDEX IF NOT EXISTS idx_bt_pred_event ON bt_predictions(event_id);

            CREATE TABLE IF NOT EXISTS bt_metrics_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                done_count INTEGER NOT NULL,
                acc_t3_strict REAL,
                acc_t3_strict_lo REAL,
                acc_t3_non_neutral REAL,
                neutral_ratio REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES bt_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bt_snap_run ON bt_metrics_snapshots(run_id, done_count);

            CREATE TABLE IF NOT EXISTS bt_datasets(
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                total_events INTEGER,
                by_market_json TEXT,
                by_type_json TEXT,
                by_symbol_json TEXT,
                date_range_json TEXT,
                labels_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evolution_items(
                id TEXT PRIMARY KEY,
                level TEXT NOT NULL,
                category TEXT,
                title TEXT NOT NULL,
                description TEXT,
                trigger_run_ids TEXT,
                before_metrics_json TEXT,
                proposed_change_json TEXT NOT NULL,
                ab_test_run_id TEXT,
                after_metrics_json TEXT,
                status TEXT NOT NULL,
                applied_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_evo_level_status ON evolution_items(level, status);

            -- ==================== Pronoia Arena 横向比对 ====================
            -- arena = 同一数据集 × 多组 Run（不同 Agent/LLM/配置）的比对实验
            CREATE TABLE IF NOT EXISTS bt_arenas(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dataset_id TEXT,                   -- 对应 bt_datasets.id（可选）
                dataset_name TEXT,                 -- 显示用的数据集名（冗余，防止 dataset 被删后丢失名字）
                run_ids_json TEXT NOT NULL,        -- JSON 数组：参与比对的 run_id 列表
                description TEXT,                  -- 自由描述
                config_json TEXT,                  -- 额外配置：选定的 metric 列表、分组维度等
                status TEXT NOT NULL,              -- ready / computing / done / failed
                result_json TEXT,                  -- 完整比对结果（排名、雷达图数据、显著性检验等）
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bt_arenas_created ON bt_arenas(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bt_arenas_status ON bt_arenas(status);
            CREATE INDEX IF NOT EXISTS idx_simulation_jobs_case ON simulation_jobs(case_id, created_at);
            """
        )
        conn.commit()

        # 幂等补充缺失列（bt_runs.metrics_json）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(bt_runs)").fetchall()]
        if "metrics_json" not in cols:
            try:
                conn.execute("ALTER TABLE bt_runs ADD COLUMN metrics_json TEXT")
                conn.commit()
            except Exception:
                pass
        # bt_metrics_snapshots.metrics_json（快照也存完整指标，向后兼容）
        cols_snap = [r[1] for r in conn.execute("PRAGMA table_info(bt_metrics_snapshots)").fetchall()]
        if "metrics_json" not in cols_snap:
            try:
                conn.execute("ALTER TABLE bt_metrics_snapshots ADD COLUMN metrics_json TEXT")
                conn.commit()
            except Exception:
                pass


# ---------------------------------------------------------------- cases ----

def create_case(title: str = "新研究") -> dict:
    cid, ts = new_id(), now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO cases(id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (cid, title, ts, ts),
        )
        conn.commit()
    return {"id": cid, "title": title, "created_at": ts, "updated_at": ts}


def list_cases() -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.case_id = c.id) AS message_count
            FROM cases c ORDER BY c.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_case(case_id: str) -> Optional[dict]:
    with _lock:
        row = _get_conn().execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return dict(row) if row else None


def update_case_title(case_id: str, title: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE cases SET title=?, updated_at=? WHERE id=?",
            (title, now_iso(), case_id),
        )
        conn.commit()


def touch_case(case_id: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (now_iso(), case_id))
        conn.commit()


def delete_case(case_id: str) -> bool:
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM simulation_jobs WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM messages WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM artifacts WHERE case_id=?", (case_id,))
        cur = conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------- messages ----

def add_message(
    case_id: str,
    role: str,
    content: str = "",
    agent: Optional[str] = None,
    tool_trace: Optional[Any] = None,
    message_id: Optional[str] = None,
) -> dict:
    mid, ts = message_id or new_id(), now_iso()
    trace_json = json.dumps(tool_trace, ensure_ascii=False) if tool_trace else None
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages(id,case_id,role,agent,content,tool_trace,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (mid, case_id, role, agent, content, trace_json, ts),
        )
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (ts, case_id))
        conn.commit()
    return {
        "id": mid, "case_id": case_id, "role": role, "agent": agent,
        "content": content, "tool_trace": tool_trace, "created_at": ts,
    }


def list_messages(case_id: str, limit: Optional[int] = None) -> list[dict]:
    with _lock:
        if limit:
            rows = _get_conn().execute(
                "SELECT * FROM messages WHERE case_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = _get_conn().execute(
                "SELECT * FROM messages WHERE case_id=? ORDER BY created_at ASC, rowid ASC",
                (case_id,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tool_trace"] = json.loads(d["tool_trace"]) if d.get("tool_trace") else None
        out.append(d)
    return out


def count_messages(case_id: str, role: Optional[str] = None) -> int:
    with _lock:
        if role:
            row = _get_conn().execute(
                "SELECT COUNT(*) c FROM messages WHERE case_id=? AND role=?", (case_id, role)
            ).fetchone()
        else:
            row = _get_conn().execute(
                "SELECT COUNT(*) c FROM messages WHERE case_id=?", (case_id,)
            ).fetchone()
    return int(row["c"])


# ------------------------------------------------------------ artifacts ----

def add_artifact(
    case_id: str,
    message_id: Optional[str],
    kind: str,
    title: str,
    payload: Any,
) -> dict:
    aid, ts = new_id(), now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO artifacts(id,case_id,message_id,kind,title,payload,pinned,created_at)"
            " VALUES(?,?,?,?,?,?,0,?)",
            (aid, case_id, message_id, kind, title, payload_json, ts),
        )
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (ts, case_id))
        conn.commit()
    return {
        "id": aid, "case_id": case_id, "message_id": message_id, "kind": kind,
        "title": title, "payload": payload, "pinned": 0, "created_at": ts,
    }


def list_artifacts(case_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM artifacts WHERE case_id=? ORDER BY pinned DESC, created_at ASC",
            (case_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def get_artifact(case_id: str, artifact_id: str) -> Optional[dict]:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM artifacts WHERE case_id=? AND id=?", (case_id, artifact_id)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def toggle_pin(case_id: str, artifact_id: str) -> Optional[dict]:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT pinned FROM artifacts WHERE case_id=? AND id=?", (case_id, artifact_id)
        ).fetchone()
        if not row:
            return None
        new_val = 0 if row["pinned"] else 1
        conn.execute(
            "UPDATE artifacts SET pinned=? WHERE case_id=? AND id=?",
            (new_val, case_id, artifact_id),
        )
        conn.commit()
    return get_artifact(case_id, artifact_id)


# ===================================================== bt_runs (Backtest Run) ====

_BT_RUN_FIELDS = (
    "id,name,status,runner,prompt_variant,model_version,events_path,labels_path,"
    "out_path,ckpt_dir,concurrency,total_events,done_events,acc_t3_strict,"
    "acc_t3_strict_lo,acc_t3_non_neutral,config_json,created_at,updated_at,"
    "started_at,finished_at,error_msg"
)


def _row_to_bt_run(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config_json"]) if d.get("config_json") else None
    d["concurrency"] = int(d["concurrency"] or 2)
    d["total_events"] = int(d["total_events"] or 0)
    d["done_events"] = int(d["done_events"] or 0)
    return d


def create_bt_run(
    *,
    name: str,
    runner: str,
    events_path: str,
    out_path: str,
    run_id: str | None = None,
    labels_path: str | None = None,
    prompt_variant: str | None = None,
    model_version: str | None = None,
    ckpt_dir: str | None = None,
    concurrency: int = 2,
    total_events: int = 0,
    config: dict | None = None,
) -> dict:
    rid, ts = run_id or new_id(), now_iso()
    cfg_json = json.dumps(config or {}, ensure_ascii=False) if config else None
    with _lock:
        conn = _get_conn()
        conn.execute(
            f"INSERT INTO bt_runs({_BT_RUN_FIELDS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid, name, "pending", runner, prompt_variant, model_version,
                events_path, labels_path, out_path, ckpt_dir, concurrency,
                total_events, 0, None, None, None, cfg_json, ts, ts,
                None, None, None,
            ),
        )
        conn.commit()
    row = _get_conn().execute("SELECT * FROM bt_runs WHERE id=?", (rid,)).fetchone()
    return _row_to_bt_run(row) or {"id": rid, "name": name, "status": "pending"}


def list_bt_runs(limit: int = 100, offset: int = 0) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM bt_runs ORDER BY created_at DESC LIMIT ? OFFSET ?", (int(limit), int(offset))
        ).fetchall()
    return [_row_to_bt_run(r) for r in rows if _row_to_bt_run(r)]


def get_bt_run(run_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM bt_runs WHERE id=?", (run_id,)).fetchone()
    return _row_to_bt_run(row)


def update_bt_run_status(run_id: str, status: str, *, error_msg: str | None = None) -> dict | None:
    ts = now_iso()
    fields = ["status = ?", "updated_at = ?"]
    args: list[Any] = [status, ts]
    if status == "running":
        fields.append("started_at = COALESCE(started_at, ?)")
        args.append(ts)
        # 重新运行/恢复运行：清掉上次残留的错误信息
        fields.append("error_msg = NULL")
    if status in {"done", "failed", "cancelled"}:
        fields.append("finished_at = ?")
        args.append(ts)
    if error_msg is not None:
        fields.append("error_msg = ?")
        args.append(error_msg)
    args.append(run_id)
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE bt_runs SET {', '.join(fields)} WHERE id=?", tuple(args))
        conn.commit()
    return get_bt_run(run_id)


def update_bt_run_progress(
    run_id: str,
    *,
    done_events: int,
    acc_t3_strict: float | None = None,
    acc_t3_strict_lo: float | None = None,
    acc_t3_non_neutral: float | None = None,
) -> dict | None:
    ts = now_iso()
    fields = ["done_events = ?", "updated_at = ?"]
    args: list[Any] = [int(done_events), ts]
    if acc_t3_strict is not None:
        fields.append("acc_t3_strict = ?"); args.append(float(acc_t3_strict))
    if acc_t3_strict_lo is not None:
        fields.append("acc_t3_strict_lo = ?"); args.append(float(acc_t3_strict_lo))
    if acc_t3_non_neutral is not None:
        fields.append("acc_t3_non_neutral = ?"); args.append(float(acc_t3_non_neutral))
    args.append(run_id)
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE bt_runs SET {', '.join(fields)} WHERE id=?", tuple(args))
        conn.commit()
    return get_bt_run(run_id)


def delete_bt_run(run_id: str) -> bool:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM bt_runs WHERE id=?", (run_id,))
        conn.commit()
        return cur.rowcount > 0


# ================================================= bt_predictions (per event) ====

def add_bt_prediction(
    *,
    run_id: str,
    event_id: str,
    pred_direction: str,
    symbol: str | None = None,
    market: str | None = None,
    event_type_l2: str | None = None,
    confidence: float | None = None,
    abstain: bool = False,
    rationale: str | None = None,
    oracle_label_t3: str | None = None,
    oracle_car_t3: float | None = None,
    is_correct_t3: bool | None = None,
    trajectory_ckpt: str | None = None,
    pred_id: str | None = None,
) -> dict:
    pid, ts = pred_id or new_id(), now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO bt_predictions(id,run_id,event_id,symbol,market,event_type_l2,"
            "pred_direction,confidence,abstain,rationale,oracle_label_t3,oracle_car_t3,"
            "is_correct_t3,trajectory_ckpt,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid, run_id, event_id, symbol, market, event_type_l2,
                pred_direction, confidence, 1 if abstain else 0,
                rationale, oracle_label_t3, oracle_car_t3,
                1 if is_correct_t3 else (0 if is_correct_t3 is False else None),
                trajectory_ckpt, ts,
            ),
        )
        conn.commit()
    return {
        "id": pid, "run_id": run_id, "event_id": event_id,
        "pred_direction": pred_direction, "confidence": confidence,
        "abstain": abstain, "created_at": ts,
    }


def list_bt_predictions(
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
    market: str | None = None,
    event_type_l2: str | None = None,
    only_incorrect: bool = False,
) -> tuple[int, list[dict]]:
    where = ["run_id = ?"]
    args: list[Any] = [run_id]
    if market:
        where.append("market = ?"); args.append(market)
    if event_type_l2:
        where.append("event_type_l2 = ?"); args.append(event_type_l2)
    if only_incorrect:
        where.append("is_correct_t3 = 0")
    where_sql = " AND ".join(where)
    with _lock:
        conn = _get_conn()
        total_row = conn.execute(
            f"SELECT COUNT(*) c FROM bt_predictions WHERE {where_sql}", tuple(args)
        ).fetchone()
        total = int(total_row["c"] if total_row else 0)
        rows = conn.execute(
            f"SELECT * FROM bt_predictions WHERE {where_sql} ORDER BY created_at ASC LIMIT ? OFFSET ?",
            tuple(args + [int(limit), int(offset)]),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["abstain"] = bool(d.get("abstain"))
        d["is_correct_t3"] = bool(d["is_correct_t3"]) if d.get("is_correct_t3") is not None else None
        out.append(d)
    return total, out


def get_bt_prediction(run_id: str, event_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM bt_predictions WHERE run_id=? AND event_id=?", (run_id, event_id)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["abstain"] = bool(d.get("abstain"))
    d["is_correct_t3"] = bool(d["is_correct_t3"]) if d.get("is_correct_t3") is not None else None
    return d


# ============================================ bt_metrics_snapshots (time series) ====

def add_bt_metrics_snapshot(
    *,
    run_id: str,
    done_count: int,
    acc_t3_strict: float | None = None,
    acc_t3_strict_lo: float | None = None,
    acc_t3_non_neutral: float | None = None,
    neutral_ratio: float | None = None,
) -> int:
    ts = now_iso()
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO bt_metrics_snapshots(run_id,done_count,acc_t3_strict,"
            "acc_t3_strict_lo,acc_t3_non_neutral,neutral_ratio,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (run_id, int(done_count), acc_t3_strict, acc_t3_strict_lo,
             acc_t3_non_neutral, neutral_ratio, ts),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def list_bt_metrics_snapshots(run_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM bt_metrics_snapshots WHERE run_id=? ORDER BY done_count ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ============================================================== bt_datasets ====

def upsert_bt_dataset(
    *,
    dataset_id: str,
    path: str,
    name: str,
    total_events: int = 0,
    by_market: dict | None = None,
    by_type: dict | None = None,
    by_symbol: dict | None = None,
    date_range: dict | None = None,
    labels_path: str | None = None,
) -> dict:
    ts = now_iso()
    def _j(d): return json.dumps(d, ensure_ascii=False) if d else None
    with _lock:
        conn = _get_conn()
        existing = conn.execute("SELECT id FROM bt_datasets WHERE id=?", (dataset_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE bt_datasets SET path=?,name=?,total_events=?,by_market_json=?,"
                "by_type_json=?,by_symbol_json=?,date_range_json=?,labels_path=? WHERE id=?",
                (path, name, int(total_events), _j(by_market), _j(by_type), _j(by_symbol),
                 _j(date_range), labels_path, dataset_id),
            )
        else:
            conn.execute(
                "INSERT INTO bt_datasets(id,path,name,total_events,by_market_json,"
                "by_type_json,by_symbol_json,date_range_json,labels_path,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (dataset_id, path, name, int(total_events), _j(by_market), _j(by_type),
                 _j(by_symbol), _j(date_range), labels_path, ts),
            )
        conn.commit()
    return get_bt_dataset(dataset_id) or {"id": dataset_id, "path": path, "name": name}


def list_bt_datasets() -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM bt_datasets ORDER BY created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("by_market_json", "by_type_json", "by_symbol_json", "date_range_json"):
            short = k[:-5]
            d[short] = json.loads(d[k]) if d.get(k) else None
            d.pop(k, None)
        out.append(d)
    return out


def get_bt_dataset(dataset_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM bt_datasets WHERE id=?", (dataset_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("by_market_json", "by_type_json", "by_symbol_json", "date_range_json"):
        short = k[:-5]
        d[short] = json.loads(d[k]) if d.get(k) else None
        d.pop(k, None)
    return d


def prune_missing_bt_datasets() -> int:
    """删除 path 在磁盘上不存在的数据集记录（例如项目目录迁移后残留的旧绝对路径），返回删除条数。"""
    from pathlib import Path

    with _lock:
        rows = _get_conn().execute("SELECT id, path FROM bt_datasets").fetchall()
    stale = [r["id"] for r in rows if not r["path"] or not Path(r["path"]).is_file()]
    if not stale:
        return 0
    with _lock:
        conn = _get_conn()
        for did in stale:
            conn.execute("DELETE FROM bt_datasets WHERE id=?", (did,))
        conn.commit()
    return len(stale)


# ========================================================== evolution_items ====

def create_evolution_item(
    *,
    level: str,
    title: str,
    proposed_change: dict,
    category: str | None = None,
    description: str | None = None,
    status: str = "proposed",
) -> dict:
    eid, ts = new_id(), now_iso()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO evolution_items(id,level,category,title,description,"
            "trigger_run_ids,before_metrics_json,proposed_change_json,ab_test_run_id,"
            "after_metrics_json,status,applied_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid, level, category, title, description, None, None,
                json.dumps(proposed_change, ensure_ascii=False), None, None,
                status, None, ts,
            ),
        )
        conn.commit()
    return get_evolution_item(eid) or {"id": eid, "level": level, "title": title, "status": status}


def list_evolution_items(*, level: str | None = None, status: str | None = None) -> list[dict]:
    where = []
    args: list[Any] = []
    if level:
        where.append("level = ?"); args.append(level)
    if status:
        where.append("status = ?"); args.append(status)
    sql = "SELECT * FROM evolution_items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    with _lock:
        rows = _get_conn().execute(sql, tuple(args)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("before_metrics_json", "after_metrics_json"):
            short = k[:-5]
            d[short] = json.loads(d[k]) if d.get(k) else None
            d.pop(k, None)
        d["proposed_change"] = json.loads(d["proposed_change_json"]) if d.get("proposed_change_json") else None
        d.pop("proposed_change_json", None)
        out.append(d)
    return out


def get_evolution_item(item_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM evolution_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("before_metrics_json", "after_metrics_json"):
        short = k[:-5]
        d[short] = json.loads(d[k]) if d.get(k) else None
        d.pop(k, None)
    d["proposed_change"] = json.loads(d["proposed_change_json"]) if d.get("proposed_change_json") else None
    d.pop("proposed_change_json", None)
    return d


def update_evolution_status(item_id: str, status: str, **kwargs) -> dict | None:
    fields = ["status = ?"]
    args: list[Any] = [status]
    if status == "applied":
        fields.append("applied_at = ?")
        args.append(now_iso())
    allowed = {"ab_test_run_id"}
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        fields.append(f"{k} = ?")
        args.append(v)
    args.append(item_id)
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE evolution_items SET {', '.join(fields)} WHERE id=?", tuple(args))
        conn.commit()
    return get_evolution_item(item_id)


# ============================================================== bt_runs.metrics_json 存取 ====

def update_bt_run_metrics(run_id: str, metrics_dict: dict | None) -> dict | None:
    """将完整的 metrics_registry 结果 JSON 存入 bt_runs.metrics_json。"""
    ts = now_iso()
    m_json = json.dumps(metrics_dict, ensure_ascii=False) if metrics_dict is not None else None
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE bt_runs SET metrics_json = ?, updated_at = ? WHERE id = ?",
            (m_json, ts, run_id),
        )
        conn.commit()
    return get_bt_run(run_id)


def _row_to_bt_run(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config_json"]) if d.get("config_json") else None
    d["metrics"] = json.loads(d["metrics_json"]) if d.get("metrics_json") else None
    d["concurrency"] = int(d["concurrency"] or 2)
    d["total_events"] = int(d["total_events"] or 0)
    d["done_events"] = int(d["done_events"] or 0)
    return d


# ============================================================== bt_metrics_snapshots.metrics_json 补存取 ====

def add_bt_metrics_snapshot(
    *,
    run_id: str,
    done_count: int,
    acc_t3_strict: float | None = None,
    acc_t3_strict_lo: float | None = None,
    acc_t3_non_neutral: float | None = None,
    neutral_ratio: float | None = None,
    metrics_dict: dict | None = None,
) -> int:
    ts = now_iso()
    m_json = json.dumps(metrics_dict, ensure_ascii=False) if metrics_dict is not None else None
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO bt_metrics_snapshots(run_id,done_count,acc_t3_strict,"
            "acc_t3_strict_lo,acc_t3_non_neutral,neutral_ratio,created_at,metrics_json)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (run_id, int(done_count), acc_t3_strict, acc_t3_strict_lo,
             acc_t3_non_neutral, neutral_ratio, ts, m_json),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def list_bt_metrics_snapshots(run_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM bt_metrics_snapshots WHERE run_id=? ORDER BY done_count ASC",
            (run_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("metrics_json"):
            d["metrics"] = json.loads(d["metrics_json"])
        else:
            d["metrics"] = None
        out.append(d)
    return out


# ==================================================================== bt_arenas (Arena CRUD) ====

def _row_to_bt_arena(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    d = dict(row)
    d["run_ids"] = json.loads(d["run_ids_json"]) if d.get("run_ids_json") else []
    d.pop("run_ids_json", None)
    d["config"] = json.loads(d["config_json"]) if d.get("config_json") else None
    d.pop("config_json", None)
    d["result"] = json.loads(d["result_json"]) if d.get("result_json") else None
    d.pop("result_json", None)
    return d


def create_bt_arena(
    *,
    name: str,
    run_ids: list[str],
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    description: str | None = None,
    config: dict | None = None,
    arena_id: str | None = None,
) -> dict:
    aid, ts = arena_id or new_id(), now_iso()
    cfg_json = json.dumps(config or {}, ensure_ascii=False) if config else None
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO bt_arenas(id,name,dataset_id,dataset_name,run_ids_json,"
            "description,config_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (aid, name, dataset_id, dataset_name, json.dumps(run_ids or [], ensure_ascii=False),
             description, cfg_json, "ready", ts, ts),
        )
        conn.commit()
    row = _get_conn().execute("SELECT * FROM bt_arenas WHERE id=?", (aid,)).fetchone()
    return _row_to_bt_arena(row) or {"id": aid, "name": name, "run_ids": run_ids or [], "status": "ready"}


def list_bt_arenas(limit: int = 100, offset: int = 0) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM bt_arenas ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (int(limit), int(offset)),
        ).fetchall()
    return [_row_to_bt_arena(r) for r in rows if _row_to_bt_arena(r)]


def get_bt_arena(arena_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM bt_arenas WHERE id=?", (arena_id,)).fetchone()
    return _row_to_bt_arena(row)


def update_bt_arena_status(
    arena_id: str,
    status: str,
    *,
    result: dict | None = None,
) -> dict | None:
    ts = now_iso()
    fields = ["status = ?", "updated_at = ?"]
    args: list[Any] = [status, ts]
    if status in {"done", "failed"}:
        fields.append("finished_at = ?")
        args.append(ts)
    if result is not None:
        fields.append("result_json = ?")
        args.append(json.dumps(result, ensure_ascii=False))
    args.append(arena_id)
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE bt_arenas SET {', '.join(fields)} WHERE id=?", tuple(args))
        conn.commit()
    return get_bt_arena(arena_id)


def delete_bt_arena(arena_id: str) -> bool:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM bt_arenas WHERE id=?", (arena_id,))
        conn.commit()
        return cur.rowcount > 0


# ------------------------------------------------------ simulation jobs ----

def _decode_simulation_job(row: sqlite3.Row | None) -> Optional[dict]:
    if row is None:
        return None
    data = dict(row)
    data["request_payload"] = json.loads(data["request_payload"])
    return data


def create_simulation_job(
    case_id: str,
    graph_artifact_id: str,
    gateway_job: dict[str, Any],
    request_payload: dict[str, Any],
) -> dict:
    job_id, ts = new_id(), now_iso()
    with _lock:
        conn = _get_conn()
        existing = conn.execute(
            "SELECT * FROM simulation_jobs WHERE gateway_job_id=?",
            (str(gateway_job["job_id"]),),
        ).fetchone()
        if existing:
            return _decode_simulation_job(existing) or {}
        conn.execute(
            """
            INSERT INTO simulation_jobs(
                id,case_id,graph_artifact_id,gateway_job_id,status,stage,progress,
                request_payload,error,artifact_id,created_at,updated_at,finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id, case_id, graph_artifact_id, str(gateway_job["job_id"]),
                str(gateway_job.get("status") or "queued"),
                str(gateway_job.get("stage") or "queued"),
                float(gateway_job.get("progress") or 0),
                json.dumps(request_payload, ensure_ascii=False, default=str),
                gateway_job.get("error"), None, ts, ts, gateway_job.get("finished_at"),
            ),
        )
        conn.commit()
    return get_simulation_job(job_id) or {}


def get_simulation_job(job_id: str) -> Optional[dict]:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM simulation_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return _decode_simulation_job(row)


def list_simulation_jobs(case_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM simulation_jobs WHERE case_id=? ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    return [_decode_simulation_job(row) or {} for row in rows]


def update_simulation_job(job_id: str, **values: Any) -> Optional[dict]:
    allowed = {"status", "stage", "progress", "error", "artifact_id", "finished_at"}
    fields = {key: value for key, value in values.items() if key in allowed}
    if not fields:
        return get_simulation_job(job_id)
    fields["updated_at"] = now_iso()
    assignments = ",".join(f"{key}=?" for key in fields)
    with _lock:
        conn = _get_conn()
        conn.execute(
            f"UPDATE simulation_jobs SET {assignments} WHERE id=?",
            (*fields.values(), job_id),
        )
        conn.commit()
    return get_simulation_job(job_id)
