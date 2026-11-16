"""Module 9 persistence (SQLite). Separate DB file under DATA_DIR, like deployments/validation.

Five tables (per CONTRACT.md): poc_plans, poc_candidates, poc_runs, poc_chains, poc_exports.
Each stores the contract JSON verbatim plus index columns. A `job` row tracks long synchronous
runs (state/cancel/timeout) so the GUI can poll. Raw evidence bytes are NEVER stored here — only
paths under DATA_DIR artifacts (CONTRACT §Evidence); DB text must stay secret-free.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Optional

from app import config

_LOCK = threading.Lock()
_DB = config.DATA_DIR / "poc.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_plans (
            scenario_id TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            generated_at TEXT,
            updated_at REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            action_id TEXT,
            cve TEXT,
            compatibility_score REAL,
            candidate TEXT NOT NULL,
            generated_at TEXT,
            ts REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_manifests (
            scenario_id TEXT PRIMARY KEY,
            generated_at TEXT,
            ts REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            action_id TEXT,
            status TEXT,
            payload_sha256 TEXT,
            target_ownership_verified INTEGER,
            result TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            ts REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_chains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            passes INTEGER,
            objective_reached INTEGER,
            chain TEXT NOT NULL,
            ts REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            scenario_version TEXT,
            bundle_path TEXT,
            rebuildable INTEGER,
            manifest TEXT NOT NULL,
            ts REAL
        )"""
    )
    # Job tracking for long synchronous runs: state machine and live operation ID
    # the GUI and cross-worker cancellation endpoint use to reconcile cleanup.
    c.execute(
        """CREATE TABLE IF NOT EXISTS poc_jobs (
            id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            cancel INTEGER NOT NULL DEFAULT 0,
            timeout_s REAL,
            operation_id TEXT,
            operation_service_id TEXT,
            operation_action_id TEXT,
            operation_vmid INTEGER,
            operation_host_id TEXT,
            operation_generation_id TEXT,
            worker_vmid INTEGER,
            worker_host_id TEXT,
            worker_generation_id TEXT,
            detail TEXT,
            created_at REAL,
            updated_at REAL
        )"""
    )
    job_columns = {row[1] for row in c.execute("PRAGMA table_info(poc_jobs)").fetchall()}
    operation_columns = {
        "operation_id": "TEXT",
        "operation_service_id": "TEXT",
        "operation_action_id": "TEXT",
        "operation_vmid": "INTEGER",
        "operation_host_id": "TEXT",
        "operation_generation_id": "TEXT",
        "worker_vmid": "INTEGER",
        "worker_host_id": "TEXT",
        "worker_generation_id": "TEXT",
    }
    for name, column_type in operation_columns.items():
        if name not in job_columns:
            try:
                c.execute(f"ALTER TABLE poc_jobs ADD COLUMN {name} {column_type}")
            except sqlite3.OperationalError as exc:
                # Concurrent API workers may both observe the old schema before
                # one of them applies this additive migration.
                if "duplicate column name" not in str(exc).lower():
                    raise
    return c


def init() -> None:
    """Create all tables (idempotent)."""
    with _LOCK:
        _conn().close()


# --- plans ------------------------------------------------------------------
def save_plan(scenario_id: str, plan: dict[str, Any]) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO poc_plans (scenario_id, plan, generated_at, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(scenario_id) DO UPDATE SET "
                "plan=excluded.plan, generated_at=excluded.generated_at, updated_at=excluded.updated_at",
                (scenario_id, json.dumps(plan), plan.get("generated_at"), time.time()),
            )
            c.commit()
        finally:
            c.close()


def get_plan(scenario_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute(
                "SELECT plan FROM poc_plans WHERE scenario_id=?", (scenario_id,)
            ).fetchone()
        finally:
            c.close()
    return json.loads(row["plan"]) if row else None


# --- candidates -------------------------------------------------------------
def save_manifest(scenario_id: str, manifest: dict[str, Any]) -> None:
    with _LOCK:
        c = _conn()
        try:
            # Record that a discovery completed for this scenario, even with 0 candidates,
            # so export can distinguish "discovery ran, found nothing" from "never ran".
            c.execute(
                "INSERT INTO poc_manifests (scenario_id, generated_at, ts) VALUES (?,?,?) "
                "ON CONFLICT(scenario_id) DO UPDATE SET generated_at=excluded.generated_at, ts=excluded.ts",
                (scenario_id, manifest.get("generated_at"), time.time()),
            )
            c.execute("DELETE FROM poc_candidates WHERE scenario_id=?", (scenario_id,))
            for cand in manifest.get("items", []):
                c.execute(
                    "INSERT INTO poc_candidates (scenario_id, action_id, cve, "
                    "compatibility_score, candidate, generated_at, ts) VALUES (?,?,?,?,?,?,?)",
                    (
                        scenario_id,
                        cand.get("action_id"),
                        cand.get("cve"),
                        cand.get("compatibility_score"),
                        json.dumps(cand),
                        manifest.get("generated_at"),
                        time.time(),
                    ),
                )
            c.commit()
        finally:
            c.close()


def get_manifest(scenario_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT candidate, generated_at FROM poc_candidates WHERE scenario_id=? "
                "ORDER BY compatibility_score DESC",
                (scenario_id,),
            ).fetchall()
            marker = c.execute(
                "SELECT generated_at FROM poc_manifests WHERE scenario_id=?",
                (scenario_id,),
            ).fetchone()
        finally:
            c.close()
    if not rows:
        # A completed discovery with zero candidates is still a recorded manifest.
        if marker is not None:
            return {"scenario_id": scenario_id, "generated_at": marker["generated_at"], "items": []}
        return None
    return {
        "scenario_id": scenario_id,
        "generated_at": rows[0]["generated_at"],
        "items": [json.loads(r["candidate"]) for r in rows],
    }


# --- runs -------------------------------------------------------------------
def save_run(scenario_id: str, result: dict[str, Any]) -> int:
    with _LOCK:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO poc_runs (scenario_id, action_id, status, payload_sha256, "
                "target_ownership_verified, result, started_at, ended_at, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    scenario_id,
                    result.get("action_id"),
                    result.get("status"),
                    result.get("payload_sha256"),
                    1 if result.get("target_ownership_verified") else 0,
                    json.dumps(result),
                    result.get("started_at"),
                    result.get("ended_at"),
                    time.time(),
                ),
            )
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()


def get_runs(scenario_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT result FROM poc_runs WHERE scenario_id=? ORDER BY id", (scenario_id,)
            ).fetchall()
        finally:
            c.close()
    return [json.loads(r["result"]) for r in rows]


# --- chains -----------------------------------------------------------------
def save_chain(scenario_id: str, chain: dict[str, Any]) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO poc_chains (scenario_id, passes, objective_reached, chain, ts) "
                "VALUES (?,?,?,?,?)",
                (
                    scenario_id,
                    1 if chain.get("passes") else 0,
                    1 if chain.get("objective_reached") else 0,
                    json.dumps(chain),
                    time.time(),
                ),
            )
            c.commit()
        finally:
            c.close()


def get_chain(scenario_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute(
                "SELECT chain FROM poc_chains WHERE scenario_id=? ORDER BY id DESC LIMIT 1",
                (scenario_id,),
            ).fetchone()
        finally:
            c.close()
    return json.loads(row["chain"]) if row else None


# --- exports ----------------------------------------------------------------
def save_export(scenario_id: str, bundle_path: str, manifest: dict[str, Any]) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO poc_exports (scenario_id, scenario_version, bundle_path, "
                "rebuildable, manifest, ts) VALUES (?,?,?,?,?,?)",
                (
                    scenario_id,
                    str(manifest.get("scenario_version", "")),
                    bundle_path,
                    1 if manifest.get("rebuildable") else 0,
                    json.dumps(manifest),
                    time.time(),
                ),
            )
            c.commit()
        finally:
            c.close()


# --- jobs (poll state for the GUI) -----------------------------------------
def create_job(job_id: str, scenario_id: str, kind: str, timeout_s: float | None = None,
               worker_identity: dict[str, Any] | None = None) -> None:
    now = time.time()
    worker_identity = worker_identity if isinstance(worker_identity, dict) else {}
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO poc_jobs (id, scenario_id, kind, state, cancel, timeout_s, "
                "worker_vmid,worker_host_id,worker_generation_id,created_at,updated_at) "
                "VALUES (?,?,?,?,0,?,?,?,?,?,?)",
                (job_id, scenario_id, kind, "pending", timeout_s, worker_identity.get("vmid"),
                 worker_identity.get("host_id"), worker_identity.get("generation_id"), now, now),
            )
            c.commit()
        finally:
            c.close()


def set_job_state(job_id: str, state: str, detail: str | None = None) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "UPDATE poc_jobs SET state=?, detail=?, updated_at=? WHERE id=?",
                (state, detail, time.time(), job_id),
            )
            c.commit()
        finally:
            c.close()


def request_cancel(job_id: str) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "UPDATE poc_jobs SET cancel=1, updated_at=? WHERE id=?", (time.time(), job_id)
            )
            c.commit()
        finally:
            c.close()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute("SELECT * FROM poc_jobs WHERE id=?", (job_id,)).fetchone()
        finally:
            c.close()
    return dict(row) if row else None


def is_cancelled(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job["cancel"])


def register_job_operation(job_id: str, operation_id: str, service_id: str, action_id: str,
                           vmid: int, host_id: str, generation_id: str) -> bool:
    """Attach a pre-reserved worker operation to its job with the worker-generation pin."""
    with _LOCK:
        c = _conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            cursor = c.execute(
                "UPDATE poc_jobs SET operation_id=?, operation_service_id=?, operation_action_id=?, "
                "operation_vmid=?, operation_host_id=?, operation_generation_id=?, updated_at=? "
                "WHERE id=? AND state IN ('pending','running') AND operation_id IS NULL "
                "AND (worker_vmid IS NULL OR (worker_vmid=? AND worker_host_id=? AND worker_generation_id=?))",
                (operation_id, service_id, action_id, vmid, host_id, generation_id, time.time(),
                 job_id, vmid, host_id, generation_id),
            )
            c.commit()
            return cursor.rowcount == 1
        finally:
            c.close()


def clear_job_operation(job_id: str, operation_id: str) -> None:
    with _LOCK:
        c = _conn()
        try:
            c.execute(
                "UPDATE poc_jobs SET operation_id=NULL, operation_service_id=NULL, "
                "operation_action_id=NULL, operation_vmid=NULL, operation_host_id=NULL, "
                "operation_generation_id=NULL, updated_at=? WHERE id=? AND operation_id=?",
                (time.time(), job_id, operation_id),
            )
            c.commit()
        finally:
            c.close()


def get_job_operation(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute(
                "SELECT id, scenario_id, state, cancel, operation_id, operation_service_id, "
                "operation_action_id, operation_vmid, operation_host_id, operation_generation_id "
                "FROM poc_jobs WHERE id=?", (job_id,),
            ).fetchone()
        finally:
            c.close()
    if row is None or not row[4]:
        return None
    return {"job_id": row[0], "scenario_id": row[1], "state": row[2], "cancel": bool(row[3]),
            "operation_id": row[4], "service_id": row[5], "action_id": row[6],
            "vmid": row[7], "host_id": row[8], "generation_id": row[9]}


def get_job_worker_identity(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        c = _conn()
        try:
            row = c.execute(
                "SELECT worker_vmid,worker_host_id,worker_generation_id FROM poc_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        finally:
            c.close()
    if row is None or not isinstance(row[0], int) or not isinstance(row[1], str) or not isinstance(row[2], str):
        return None
    return {"vmid": row[0], "host_id": row[1], "generation_id": row[2]}


def request_cancel_operations(scenario_id: str) -> tuple[bool, list[dict[str, Any]]]:
    """Persist job cancellation and snapshot every operation that needs transport cleanup."""
    now = time.time()
    with _LOCK:
        c = _conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            updated = c.execute(
                "UPDATE poc_jobs SET cancel=1, updated_at=? "
                "WHERE scenario_id=? AND kind='execute' AND "
                "(state IN ('pending','running') OR (state='error' AND operation_id IS NOT NULL))",
                (now, scenario_id),
            )
            rows = c.execute(
                "SELECT id, scenario_id, operation_id, operation_service_id, operation_vmid, "
                "operation_host_id, operation_generation_id "
                "FROM poc_jobs WHERE scenario_id=? AND kind='execute' "
                "AND (state IN ('pending','running') OR (state='error' AND operation_id IS NOT NULL)) "
                "AND operation_id IS NOT NULL",
                (scenario_id,),
            ).fetchall()
            c.commit()
            operations = [{"job_id": row[0], "scenario_id": row[1],
                           "operation_id": row[2], "service_id": row[3], "vmid": row[4],
                           "host_id": row[5], "generation_id": row[6]} for row in rows]
            return updated.rowcount > 0, operations
        finally:
            c.close()
