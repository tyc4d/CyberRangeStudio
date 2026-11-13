"""Module 8: harmless local service, network, dependency, and behavior checks."""
from fastapi import APIRouter, HTTPException

from app.iac.generator import PlanError, validate_id
from app.validator import runner

router = APIRouter(prefix="/api/validate", tags=["validate"])


def _validate(scenario_id: str) -> str:
    try:
        return validate_id(scenario_id)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)


@router.post("/{scenario_id}/run")
def run_validation(scenario_id: str):
    scenario_id = _validate(scenario_id)
    try:
        return runner.run(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scenario not found")
    except PlanError as exc:
        raise HTTPException(status_code=409, detail={"errors": exc.errors, "report": exc.report})


@router.get("/{scenario_id}/report")
def latest_report(scenario_id: str):
    scenario_id = _validate(scenario_id)
    report = runner.get_latest_report(scenario_id)
    if report is None:
        raise HTTPException(status_code=404, detail="no validation report exists for this scenario")
    return report
