"""Module 7: controlled local Docker Compose lifecycle."""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app import store
from app.deploy import manager
from app.iac.generator import PlanError, validate_id
from app.planner.topology import connections_digest

router = APIRouter(prefix="/api/deploy", tags=["deploy"])


class UpRequest(BaseModel):
    test_approved: bool = False
    expose: str = "internal"
    lan_host: str | None = None


class ResetRequest(BaseModel):
    test_approved: bool = False


def _validate(scenario_id: str) -> str:
    try:
        return validate_id(scenario_id)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)


def _require_topology_approval(scenario_id: str) -> None:
    """Refuse deployment unless the current topology was human-approved (module 2/5 gate)."""
    ir = store.get(scenario_id)
    plan = ir.get("environment_plan") if isinstance(ir, dict) else None
    approval = plan.get("approval") if isinstance(plan, dict) else None
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        manager.record(scenario_id, "up", "rejected", {"reason": "topology not approved"})
        raise HTTPException(status_code=409, detail="topology approval required: POST /api/planning/{id}/topology/approve before deploying")
    if approval.get("connections_digest") != connections_digest(plan):
        manager.record(scenario_id, "up", "rejected", {"reason": "approval stale; topology changed since approval"})
        raise HTTPException(status_code=409, detail="topology changed since approval; re-approve before deploying")


@router.post("/{scenario_id}/up")
def deploy_up(scenario_id: str, request: UpRequest):
    scenario_id = _validate(scenario_id)
    if request.test_approved is not True:
        manager.record(scenario_id, "up", "rejected", {"reason": "explicit deployment test approval required"})
        raise HTTPException(status_code=400, detail="explicit deployment test approval required: send test_approved=true")
    if request.expose not in {"internal", "lan"}:
        raise HTTPException(status_code=400, detail="expose must be 'internal' or 'lan'")
    if request.lan_host is not None and request.expose != "lan":
        raise HTTPException(status_code=400, detail="lan_host is only valid when expose='lan'")
    _require_topology_approval(scenario_id)
    try:
        result = manager.do_up(scenario_id, request.expose, request.lan_host)
    except PlanError as exc:
        raise HTTPException(status_code=400, detail=exc.errors) from exc
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/{scenario_id}/preflight")
def deployment_preflight(scenario_id: str):
    """Read-only pre-deployment check: IaC state, host isolation support, host capacity,
    and whether deploying now would rebuild an environment that is already running."""
    scenario_id = _validate(scenario_id)
    return manager.deploy_preflight(scenario_id)


@router.get("/{scenario_id}/status")
def deployment_status(scenario_id: str):
    scenario_id = _validate(scenario_id)
    return manager.do_status(scenario_id)


@router.get("/{scenario_id}/health")
def deployment_health(scenario_id: str):
    scenario_id = _validate(scenario_id)
    return manager.do_health(scenario_id)


@router.post("/{scenario_id}/down")
def deployment_down(scenario_id: str):
    scenario_id = _validate(scenario_id)
    result = manager.do_down(scenario_id)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.post("/{scenario_id}/reset")
def deployment_reset(scenario_id: str, request: ResetRequest):
    """Rollback an active Proxmox worker to its verified deployed snapshot."""
    scenario_id = _validate(scenario_id)
    if request.test_approved is not True:
        manager.record(scenario_id, "reset", "rejected", {"reason": "explicit reset approval required"})
        raise HTTPException(status_code=400, detail="explicit reset approval required: send test_approved=true")
    result = manager.do_reset(scenario_id)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/{scenario_id}/records")
def deployment_records(scenario_id: str, limit: int = 100):
    scenario_id = _validate(scenario_id)
    return {"scenario_id": scenario_id, "records": manager.records(scenario_id, limit)}
