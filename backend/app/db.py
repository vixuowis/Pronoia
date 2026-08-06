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
            CREATE INDEX IF NOT EXISTS idx_simulation_jobs_case ON simulation_jobs(case_id, created_at);
            """
        )
        conn.commit()


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
