"""Shared scaffolding for Phase 3 real-PoC runners.

Every runner is DOUBLE-GATED:
  1. `CR_PHASE3_AUTHORIZED=1` must be set (the Lead enables it only after the
     host-isolation fix is merged to main), AND
  2. `guard.require_isolation()` must confirm the experiment network cannot reach
     the host or the internet.
If either gate is not satisfied, nothing is deployed and the run reports NOT_TESTED.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import guard  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
EVIDENCE = HERE / ".evidence"


def authorized() -> bool:
    return os.environ.get("CR_PHASE3_AUTHORIZED") == "1"


def run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def compose(project: str, compose_file: str) -> list[str]:
    return ["docker", "compose", "-p", project, "-f", str(HERE / compose_file)]


def not_tested(chain: str, reason: str) -> dict:
    return {"chain": chain, "status": "NOT_TESTED", "reason": reason,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "note": "No vulnerable image was deployed and no exploit was executed."}


def preflight(chain: str) -> dict | None:
    """Return a NOT_TESTED result if a gate blocks the run, else None to proceed."""
    if not authorized():
        return not_tested(chain, "CR_PHASE3_AUTHORIZED is not set; Phase 3 execution is not enabled.")
    try:
        verdict = guard.require_isolation()
    except guard.IsolationNotConfirmed as exc:
        return not_tested(chain, f"isolation guard refused: {exc}")
    # Attach the proof of isolation to the caller via a side channel file.
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / f"{chain}-isolation.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2))
    return None


def wait_tcp(project: str, compose_file: str, service: str, host: str, port: int, deadline_s: int = 90) -> bool:
    script = f"import socket; socket.create_connection(('{host}',{port}),timeout=3).close(); print('ok')"
    end = time.time() + deadline_s
    while time.time() < end:
        r = run(compose(project, compose_file) + ["exec", "-T", service, "python", "-c", script], timeout=20)
        if "ok" in r.stdout:
            return True
        time.sleep(3)
    return False


def finish(result: dict) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else (0 if result.get("status") == "NOT_TESTED" else 1)
