"""Run this worktree's tests against read-only m9-base chain/shared-model source.

The Lead authorized this temporary import overlay because the runner branch's
chain predates scenario_digest. No product files or verifier behavior are changed.
Run from apps/api with this worktree's contracts on PYTHONPATH, passing pytest args.
The authoritative post-merge integration run belongs to the Lead in m9-base.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("M9_INTEGRATION_BASE", ROOT.parent / "m9-base"))
BASE_POC = BASE / "apps/api/app/poc"
sys.path.insert(0, str(ROOT / "apps/api"))


class IntegrationSource(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.poc.chain":
            return importlib.util.spec_from_file_location(
                fullname, BASE_POC / "chain/__init__.py",
                submodule_search_locations=[str(BASE_POC / "chain")])
        if fullname == "app.poc.models":
            return importlib.util.spec_from_file_location(fullname, BASE_POC / "models.py")
        return None


sys.meta_path.insert(0, IntegrationSource())

from app.poc.chain import evidence  # noqa: E402
from app.poc import models  # noqa: E402
from app.poc.runner import runner  # noqa: E402
import cr_contracts  # noqa: E402

assert Path(runner.__file__).resolve().is_relative_to(ROOT)
assert Path(cr_contracts.__file__).resolve().is_relative_to(ROOT / "packages/contracts")
for module in (runner, evidence, models, cr_contracts):
    source = Path(module.__file__).resolve()
    print(f"{module.__name__}: {source} sha256={hashlib.sha256(source.read_bytes()).hexdigest()}", flush=True)

raise SystemExit(pytest.main(sys.argv[1:]))
