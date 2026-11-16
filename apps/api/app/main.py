"""CyberRange API. Single FastAPI process. Routers are owned per-module (see docs/decisions/0001)."""
from __future__ import annotations

import ipaddress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.llm import budget

app = FastAPI(title="CyberRange API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def restrict_source_ip(request: Request, call_next):
    """Reject callers outside config.ALLOWED_CIDRS (loopback + LAN by default)."""
    host = request.client.host if request.client else None
    try:
        ip = ipaddress.ip_address(host) if host else None
    except ValueError:
        ip = None  # non-TCP peer (unix socket, in-process test client)
    if ip is not None:
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not any(ip in net for net in config.ALLOWED_CIDRS):
            return JSONResponse({"detail": "source address not allowed"}, status_code=403)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/budget")
def budget_status():
    return budget.summary()


# --- module routers; each is implemented by its owning worker ---
# Import guarded so the app still boots if a router has an import error during parallel dev.
def _safe_include(module_path: str, attr: str = "router") -> str:
    try:
        mod = __import__(module_path, fromlist=[attr])
        app.include_router(getattr(mod, attr))
        return "ok"
    except Exception as e:  # pragma: no cover
        return f"skipped: {type(e).__name__}: {e}"


ROUTER_STATUS = {
    "ingest": _safe_include("app.routers.ingest"),       # module 1-2  (CTI backend)
    "scenario": _safe_include("app.routers.scenario"),   # module 3    (scenario)
    "planning": _safe_include("app.routers.planning"),   # module 4-5  (scenario)
    "iac": _safe_include("app.routers.iac"),             # module 6    (infra)
    "deploy": _safe_include("app.routers.deploy"),       # module 7    (infra)
    "validate": _safe_include("app.routers.validate"),   # module 8    (infra)
    "attackflow": _safe_include("app.routers.attackflow"), # module 1-3 (Attack Flow STIX)
    "poc": _safe_include("app.routers.poc"),             # module 9    (poc discovery/validation/export)
}


@app.get("/api/_routers")
def routers_status():
    return ROUTER_STATUS
