"""Run the real pipeline (modules 1,2,4,5) on a fixture and save input/output evidence.

Usage: run_real.py <fixture path> <input_kind> <method> <out_dir> [name]
Loads the OpenAI key from the main repo .env; budget caps come from the environment.
"""
import json, os, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[4]
for line in pathlib.Path("/home/tyc4d/cr-project/.env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
os.environ.setdefault("CR_DATA_DIR", str(ROOT / ".data"))
os.environ["CR_BUDGET_HARD_CAP_USD"] = "5"
os.environ["CR_BUDGET_STOP_NEW_USD"] = "4"
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.cti.parser import parse_source  # noqa: E402
from app.cti.analysis import analyze_source  # noqa: E402
from app.planner.dependencies import plan_dependencies  # noqa: E402
from app.planner.topology import attach_environment_plan  # noqa: E402
from cr_contracts import iter_errors  # noqa: E402

path, kind, method, out_dir = sys.argv[1:5]
name = sys.argv[5] if len(sys.argv) > 5 else pathlib.Path(path).stem
out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
content = pathlib.Path(path).read_text(encoding="utf-8")
units, parsed = parse_source(kind, content)
(out / "00-input.txt").write_text(content, encoding="utf-8")
(out / "00-units.json").write_text(json.dumps([{"id": u.id, "text": u.text} for u in units], ensure_ascii=False, indent=1))
ir = analyze_source(input_kind=kind, content=content, source_name=name, units=units, parsed_source=parsed, method=method, name=name)
ir["id"] = "scn_evidence"
(out / "01-ir.json").write_text(json.dumps(ir, ensure_ascii=False, indent=1))
print("ir schema errors:", iter_errors("scenario-ir", ir))
deps = plan_dependencies(ir)
(out / "02-dependencies.json").write_text(json.dumps(deps, ensure_ascii=False, indent=1))
topo = attach_environment_plan(deps)
(out / "03-topology.json").write_text(json.dumps(topo.get("environment_plan"), ensure_ascii=False, indent=1))
print("actions", len(ir["actions"]), "relations", len(ir["relations"]), "hosts", len(ir["hosts"]),
      "services", len(ir["services"]), "missing", len(ir["missing_items"]), "quality", ir["quality"])
