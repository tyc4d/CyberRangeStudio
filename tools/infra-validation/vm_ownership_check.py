"""Real check: resources that merely share our naming are never removed by the VM backend.

  CR_VM_POOL=<pool> PYTHONPATH=apps/api python tools/infra-validation/vm_ownership_check.py

Creates, directly with virsh and WITHOUT the product's ownership metadata, a shut-off
domain, a network and a disk volume that use the names the backend would use for
scenario "infra-eng-own" / vm "win1" / network "lab". Then asks the backend to destroy
them and shows it refuses. Finally removes the three stand-ins itself.
"""
from __future__ import annotations

import json
import os
import tempfile

from app.deploy import vm

S, V, N = "infra-eng-own", "win1", "lab"
domain, network, volume = vm.domain_name(S, V), vm.network_name(S, N), f"{vm.domain_name(S, V)}.qcow2"


def define(kind: str, xml: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".xml") as handle:
        handle.write(xml)
        handle.flush()
        os.chmod(handle.name, 0o644)
        result = vm.virsh([kind, handle.name])
        assert result["returncode"] == 0, result


def show(label: str, value) -> None:
    print(f"## {label}\n   {json.dumps(value, ensure_ascii=False, default=str)}")


def present() -> dict:
    return {"domain": vm.domain_state(domain) != "absent",
            "network": vm.virsh(["net-info", network])["returncode"] == 0,
            "volume": vm.volume_exists(volume)}


try:
    # stand-ins with our names but no ownership metadata / not an overlay of a template
    define("net-define", f"<network><name>{network}</name><bridge name='crbforeign0' stp='on' delay='0'/></network>")
    define("define", f"<domain type='kvm'><name>{domain}</name><memory unit='MiB'>64</memory><vcpu>1</vcpu>"
                     "<os><type arch='x86_64' machine='q35'>hvm</type></os></domain>")
    assert vm.virsh(["vol-create-as", vm.POOL, volume, "1M", "--format", "qcow2"])["returncode"] == 0
    show("stand-ins created without ownership metadata", present())

    show("backend: vm_destroy on the foreign domain", vm.vm_destroy(S, V))
    show("backend: network_destroy on the foreign network", vm.network_destroy(S, N))
    show("still present after the backend was asked to remove them", present())

    # domain gone, same-named plain disk left: the orphan-disk path must also refuse
    assert vm.virsh(["undefine", domain])["returncode"] == 0
    show("backend: vm_destroy with no domain and a same-named disk that is not our overlay", vm.vm_destroy(S, V))
    show("disk still present", {"volume": vm.volume_exists(volume)})
    for call in (lambda: vm.vm_boot(S, V), lambda: vm.vm_stop(S, V), lambda: vm.guest_exec(S, V, "cmd.exe", ["/c", "ver"])):
        try:
            call()
            print("   UNEXPECTED: call was accepted")
        except vm.VmError as exc:
            print(f"   refused: {exc}")
finally:
    vm.virsh(["undefine", domain])
    vm.virsh(["net-undefine", network])
    vm.virsh(["vol-delete", "--pool", vm.POOL, volume])
    show("stand-ins removed by this script (not by the backend)", present())
