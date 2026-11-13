"""Module router: planning. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/planning", tags=["planning"])

@router.get("/_status")
def _status():
    return {"router": "planning", "implemented": False}
