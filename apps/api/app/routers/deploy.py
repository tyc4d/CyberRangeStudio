"""Module 7: controlled local Docker Compose lifecycle."""
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.deploy import manager
from app.iac.generator import PlanError, validate_id

router = APIRouter(prefix="/api/deploy", tags=["deploy"])


class UpRequest(BaseModel):
    test_approved: bool = False


def _validate(scenario_id: str) -> str:
    try:
        return validate_id(scenario_id)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)


@router.post("/{scenario_id}/up")
def deploy_up(scenario_id: str, request: UpRequest):
    scenario_id = _validate(scenario_id)
    if request.test_approved is not True:
        manager.record(scenario_id, "up", "rejected", {"reason": "explicit local PoC approval required"})
        raise HTTPException(status_code=400, detail="explicit local PoC approval required: send test_approved=true")
    result = manager.do_up(scenario_id)
    if not result["ok"]:
        raise HTTPException(status_code=503, detail=result)
    return result


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


@router.get("/{scenario_id}/records")
def deployment_records(scenario_id: str, limit: int = 100):
    scenario_id = _validate(scenario_id)
    return {"scenario_id": scenario_id, "records": manager.records(scenario_id, limit)}
