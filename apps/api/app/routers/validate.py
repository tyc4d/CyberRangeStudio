"""Module router: validate. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/validate", tags=["validate"])

@router.get("/_status")
def _status():
    return {"router": "validate", "implemented": False}
