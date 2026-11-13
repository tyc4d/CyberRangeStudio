"""Module router: ingest. STUB — implemented by the owning worker. Do not leave as a stub."""
from fastapi import APIRouter
router = APIRouter(prefix="/api/ingest", tags=["ingest"])

@router.get("/_status")
def _status():
    return {"router": "ingest", "implemented": False}
