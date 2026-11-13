"""Module router: deploy. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/deploy", tags=["deploy"])

@router.get("/_status")
def _status():
    return {"router": "deploy", "implemented": False}
