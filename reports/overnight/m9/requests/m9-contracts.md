# m9-contracts → Lead (t31): main.py ROUTER_STATUS registration

I do not edit `apps/api/app/main.py` (Lead-owned). Please add the PoC router to the
`ROUTER_STATUS` dict in `apps/api/app/main.py` (alongside the other `_safe_include` lines):

```python
    "poc": _safe_include("app.routers.poc"),            # module 9    (poc discovery/validation/export)
```

Nothing else in main.py needs to change. `app.routers.poc` imports cleanly and registers all
6 routes under `/api/poc`; the import-guarded `_safe_include` keeps the app booting even while
other m9 workers are still filling their modules.
