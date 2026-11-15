"""Runner request and adapter transport types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionRequest:
    action_id: str
    scenario_id: str
    service_ref: str
    source_url: str
    ref: dict[str, str]
    sha256: str
    exec_method: str
    payload: str
    expected_marker: str
    target_host_ref: str | None = None
    timeout: int = 30
    cancel: Any = None
    on_progress: Callable[[dict[str, Any]], None] | None = None
    proof_id: str | None = None
    job_id: str | None = None
    required_predecessors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterInput:
    payload: str


@dataclass(frozen=True)
class AdapterOutput:
    runtime: str
    payload: str
    blocked_reason: str | None = None
