"""Scenario persistence (SQLite). Shared by all modules. Stores Scenario IR JSON + edit versions."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from app import config

_LOCK = threading.Lock()
_DB = config.DATA_DIR / "scenarios.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY, name TEXT, ir TEXT, created_at REAL, updated_at REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS scenario_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id TEXT, ir_version INTEGER,
            ir TEXT, note TEXT, ts REAL
        )"""
    )
    # Original imported report, kept verbatim so the Import page can show it back
    # for review. Held apart from the IR so it is never re-sent to the LLM and
    # never snapshotted into every edit version.
    c.execute(
        """CREATE TABLE IF NOT EXISTS scenario_sources (
            scenario_id TEXT PRIMARY KEY, input_kind TEXT, source_name TEXT,
            content TEXT, sha256 TEXT, ts REAL
        )"""
    )
    return c


def new_id() -> str:
    return "scn_" + uuid.uuid4().hex[:12]


def create(ir: dict[str, Any]) -> dict[str, Any]:
    ir = dict(ir)
    ir.setdefault("id", new_id())
    ir.setdefault("ir_version", 1)
    now = time.time()
    ir.setdefault("created_at", _iso(now))
    ir["updated_at"] = _iso(now)
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO scenarios(id,name,ir,created_at,updated_at) VALUES(?,?,?,?,?)",
            (ir["id"], ir.get("name", ""), json.dumps(ir, ensure_ascii=False), now, now),
        )
        c.execute(
            "INSERT INTO scenario_versions(scenario_id,ir_version,ir,note,ts) VALUES(?,?,?,?,?)",
            (ir["id"], ir.get("ir_version", 1), json.dumps(ir, ensure_ascii=False), "create", now),
        )
    return ir


def get(scenario_id: str) -> dict[str, Any] | None:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT ir FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
    return json.loads(row["ir"]) if row else None


def list_all() -> list[dict[str, Any]]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT id,name,created_at,updated_at FROM scenarios ORDER BY updated_at DESC").fetchall()
    return [{"id": r["id"], "name": r["name"],
             "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])} for r in rows]


def update(scenario_id: str, ir: dict[str, Any], note: str = "update", bump_version: bool = False) -> dict[str, Any]:
    """Replace the stored IR. If bump_version, increment ir_version and snapshot (module 3 user edits)."""
    cur = get(scenario_id)
    if cur is None:
        raise KeyError(scenario_id)
    ir = dict(ir)
    ir["id"] = scenario_id
    if bump_version:
        ir["ir_version"] = int(cur.get("ir_version", 1)) + 1
    else:
        ir["ir_version"] = cur.get("ir_version", 1)
    now = time.time()
    ir["created_at"] = cur.get("created_at")
    ir["updated_at"] = _iso(now)
    with _LOCK, _conn() as c:
        c.execute("UPDATE scenarios SET name=?,ir=?,updated_at=? WHERE id=?",
                  (ir.get("name", ""), json.dumps(ir, ensure_ascii=False), now, scenario_id))
        if bump_version:
            c.execute("INSERT INTO scenario_versions(scenario_id,ir_version,ir,note,ts) VALUES(?,?,?,?,?)",
                      (scenario_id, ir["ir_version"], json.dumps(ir, ensure_ascii=False), note, now))
    return ir


def set_source(scenario_id: str, input_kind: str, content: str, source_name: str | None) -> None:
    """Keep the original imported report verbatim for later review."""
    import hashlib

    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO scenario_sources(scenario_id,input_kind,source_name,content,sha256,ts) "
            "VALUES(?,?,?,?,?,?)",
            (scenario_id, input_kind, source_name or "", content, sha, time.time()),
        )


def get_source(scenario_id: str) -> dict[str, Any] | None:
    with _LOCK, _conn() as c:
        row = c.execute(
            "SELECT input_kind,source_name,content,sha256 FROM scenario_sources WHERE scenario_id=?",
            (scenario_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "input_kind": row["input_kind"],
        "source_name": row["source_name"] or None,
        "content": row["content"],
        "sha256": row["sha256"],
        "chars": len(row["content"]),
    }


def versions(scenario_id: str) -> list[dict[str, Any]]:
    with _LOCK, _conn() as c:
        rows = c.execute(
            "SELECT ir_version,note,ts FROM scenario_versions WHERE scenario_id=? ORDER BY ir_version DESC",
            (scenario_id,)).fetchall()
    return [{"ir_version": r["ir_version"], "note": r["note"], "ts": _iso(r["ts"])} for r in rows]


def _iso(ts: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
