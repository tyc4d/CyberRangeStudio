"""Module router: iac. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/iac", tags=["iac"])

@router.get("/_status")
def _status():
    return {"router": "iac", "implemented": False}
