"""CyberRange API. Single FastAPI process. Routers are owned per-module (see docs/decisions/0001)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.llm import budget

app = FastAPI(title="CyberRange API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
}


@app.get("/api/_routers")
def routers_status():
    return ROUTER_STATUS
