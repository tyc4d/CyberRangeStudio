"""Real end-to-end run of the Windows VM backend. Writes JSON evidence; asserts nothing.

  CR_VM_POOL=<pool> PYTHONPATH=apps/api python tools/infra-validation/vm_e2e.py <evidence-dir> [--skip-build]

Steps: preflight -> (build template from the evaluation ISO, unattended) -> isolated network
-> create overlay VM -> boot -> wait for guest agent -> native health -> clean stop ->
start again -> reset (destroy + recreate) -> destroy -> prove nothing is left.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.deploy import vm

evidence = Path(sys.argv[1])
evidence.mkdir(parents=True, exist_ok=True)
out = evidence / "vm-e2e.json"
log: dict = {"pool": vm.POOL, "steps": []}
SCENARIO, VM_ID, NET, TEMPLATE = "infra-eng-vm", "win1", "lab", "ws2022-eval-core"


def step(name, fn):
    started = time.time()
    try:
        result = fn()
        ok = True
    except Exception as exc:  # evidence run: record and continue where possible
        result, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
    log["steps"].append({"step": name, "at": time.strftime("%H:%M:%S"), "seconds": round(time.time() - started, 1),
                         "ok": ok, "result": result})
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str))
    print(f"[{time.strftime('%H:%M:%S')}] {name}: {'ok' if ok else 'ERROR'} {json.dumps(result, ensure_ascii=False, default=str)[:400]}", flush=True)
    return result if ok else None


step("preflight", vm.preflight)
if "--skip-build" not in sys.argv:
    step("build_template", lambda: vm.build_windows_template(
        TEMPLATE, "windows-server-2022-eval.iso", "virtio-win.iso", image_index=1,
        evidence_dir=evidence, progress=lambda line: print("   ", line, flush=True)))
step("leftover_before", lambda: vm.scenario_inventory(SCENARIO))
step("network_create", lambda: vm.network_create(SCENARIO, NET))
step("vm_create", lambda: vm.vm_create(SCENARIO, VM_ID, TEMPLATE, networks=[NET]))
step("vm_boot", lambda: vm.vm_boot(SCENARIO, VM_ID))
step("hypervisor_running_is_not_ready", lambda: {"hypervisor_state": vm.domain_state(vm.domain_name(SCENARIO, VM_ID)),
                                                  "health_right_after_start": vm.vm_health(SCENARIO, VM_ID)})
step("vm_wait_ready", lambda: vm.vm_wait_ready(SCENARIO, VM_ID, timeout=900))
step("vm_health", lambda: vm.vm_health(SCENARIO, VM_ID))
step("guest_view_of_network", lambda: vm.guest_exec(SCENARIO, VM_ID, "powershell.exe", [
    "-NoProfile", "-NonInteractive", "-Command",
    "Get-NetIPConfiguration | ForEach-Object { $_.InterfaceAlias + ' ip=' + ($_.IPv4Address.IPAddress -join ',') + ' gw=' + ($_.IPv4DefaultGateway.NextHop -join ',') }; "
    "'route-count-default=' + @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count"]))
step("network_status", lambda: vm.network_status(SCENARIO, NET))
step("screenshot", lambda: {"saved": vm.screenshot(vm.domain_name(SCENARIO, VM_ID), evidence / "vm-running.ppm")})
step("vm_stop", lambda: vm.vm_stop(SCENARIO, VM_ID))
step("vm_boot_again", lambda: vm.vm_boot(SCENARIO, VM_ID))
step("vm_wait_ready_again", lambda: vm.vm_wait_ready(SCENARIO, VM_ID, timeout=900))
step("marker_write", lambda: vm.guest_exec(SCENARIO, VM_ID, "cmd.exe", ["/c", "echo dirty> C:\\cr-reset-marker.txt && type C:\\cr-reset-marker.txt"]))
step("reset_destroy", lambda: vm.vm_destroy(SCENARIO, VM_ID))
step("reset_create", lambda: vm.vm_create(SCENARIO, VM_ID, TEMPLATE, networks=[NET]))
step("reset_boot", lambda: vm.vm_boot(SCENARIO, VM_ID))
step("reset_wait_ready", lambda: vm.vm_wait_ready(SCENARIO, VM_ID, timeout=900))
step("marker_gone_after_reset", lambda: vm.guest_exec(SCENARIO, VM_ID, "cmd.exe", ["/c", "if exist C:\\cr-reset-marker.txt (echo STILL_THERE) else (echo GONE)"]))
step("vm_health_after_reset", lambda: vm.vm_health(SCENARIO, VM_ID))
step("vm_destroy", lambda: vm.vm_destroy(SCENARIO, VM_ID))
step("network_destroy", lambda: vm.network_destroy(SCENARIO, NET))
step("leftover_after", lambda: vm.scenario_inventory(SCENARIO))
