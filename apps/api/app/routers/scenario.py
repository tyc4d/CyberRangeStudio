"""Module router: scenario. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/scenario", tags=["scenario"])

@router.get("/_status")
def _status():
    return {"router": "scenario", "implemented": False}
