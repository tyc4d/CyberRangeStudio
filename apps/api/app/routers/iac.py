"""Module 6: validate environment plans and generate local Docker Compose."""
from fastapi import APIRouter, HTTPException

from app.iac.generator import PlanError, generate, get_generated, validate_id

router = APIRouter(prefix="/api/iac", tags=["iac"])


@router.post("/{scenario_id}/generate")
def generate_compose(scenario_id: str):
    try:
        validate_id(scenario_id)
        return generate(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scenario not found")
    except PlanError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors, "report": exc.report})
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write generated compose: {exc}")


@router.get("/{scenario_id}")
def read_generated(scenario_id: str):
    try:
        validate_id(scenario_id)
        return get_generated(scenario_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="generated compose not found")
    except PlanError as exc:
        raise HTTPException(status_code=409, detail={"errors": exc.errors, "report": exc.report})
