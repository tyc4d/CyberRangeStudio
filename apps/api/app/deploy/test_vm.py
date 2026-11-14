"""Offline checks for the libvirt VM backend (no hypervisor needed).

The real boot/health/cleanup run is recorded by tools/infra-validation/vm_e2e.py; these
tests pin the safety properties that must not regress: isolation of generated networks,
Windows-bootable machine definition, ownership checks before anything is removed, and
"hypervisor running" never counting as healthy.
"""
from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.deploy import manager, vm


def _ok(stdout: str = "") -> dict:
    return {"returncode": 0, "stdout": stdout, "stderr": ""}


def _fail(stderr: str = "error: not found") -> dict:
    return {"returncode": 1, "stdout": "", "stderr": stderr}


OWNED_DOMAIN = (f"<domain type='kvm'><name>cr-scn-win1</name>"
                f"{vm._metadata_xml('scn', 'win1')}<devices/></domain>")
FOREIGN_DOMAIN = "<domain type='kvm'><name>cr-scn-win1</name><devices/></domain>"


class DomainDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.xml = vm._domain_xml("cr-scn-win1", vm._metadata_xml("scn", "win1"), vcpus=2, memory_mib=4096,
                                  disk_path="/pool/cr-scn-win1.qcow2", networks=["cr-scn-net-lab"])
        self.root = ET.fromstring(self.xml)

    def test_machine_can_boot_and_shut_down_windows(self):
        features = self.root.find("features")
        self.assertIsNotNone(features.find("acpi"))
        self.assertIsNotNone(features.find("apic"))
        # inbox drivers only: Windows Setup has no virtio storage/network driver
        self.assertEqual(self.root.find("devices/disk/target").get("bus"), "sata")
        self.assertEqual(self.root.find("devices/interface/model").get("type"), "e1000e")

    def test_guest_agent_channel_is_present(self):
        target = self.root.find("devices/channel/target")
        self.assertEqual(target.get("name"), "org.qemu.guest_agent.0")

    def test_no_console_or_port_is_exposed(self):
        self.assertIsNone(self.root.find("devices/graphics"))
        self.assertNotIn("hostfwd", self.xml)
        self.assertNotIn("type='user'", self.xml)

    def test_only_the_named_isolated_network_is_attached(self):
        sources = [node.get("network") for node in self.root.findall("devices/interface/source")]
        self.assertEqual(sources, ["cr-scn-net-lab"])
        self.assertNotIn("default", sources)

    def test_ownership_metadata_round_trips(self):
        self.assertEqual(vm._ownership(self.xml)["scenario"], "scn")
        self.assertEqual(vm._ownership(self.xml)["vmid"], "win1")
        self.assertIsNone(vm._ownership(FOREIGN_DOMAIN))
        self.assertIsNone(vm._ownership("not xml"))

    def test_identifiers_cannot_inject_xml_or_shell(self):
        for bad in ("a b", "x'/><y", "../etc", "", "UPPER", "a;rm"):
            with self.assertRaises(vm.VmError):
                vm.domain_name("scn", bad)
        with self.assertRaises(vm.VmError):
            vm._check_volume("../../etc/passwd")


class NetworkIsolationTests(unittest.TestCase):
    def test_generated_network_has_no_address_dhcp_or_forwarding(self):
        defined = {}

        def fake_virsh(args, timeout=60):
            if args[0] == "net-info":
                return _ok("Active: yes") if defined else _fail()
            if args[0] == "net-define":
                defined["xml"] = Path(args[1]).read_text()
                return _ok()
            if args[0] == "net-dumpxml":
                return _ok(defined["xml"])
            return _ok()

        with patch.object(vm, "virsh", side_effect=fake_virsh), patch.object(vm.shutil, "which", return_value=None):
            status = vm.network_create("scn", "lab")
        root = ET.fromstring(defined["xml"])
        self.assertIsNone(root.find("ip"))
        self.assertIsNone(root.find("forward"))
        self.assertIsNone(root.find("dns"))
        self.assertLessEqual(len(root.find("bridge").get("name")), 15)
        self.assertTrue(status["isolated"])
        self.assertTrue(status["owned"])

    def test_nat_or_addressed_network_is_reported_as_not_isolated(self):
        nat = ("<network><name>cr-scn-net-lab</name><forward mode='nat'/><bridge name='virbr9'/>"
               "<ip address='192.168.122.1' netmask='255.255.255.0'/></network>")
        with patch.object(vm, "virsh", side_effect=lambda args, timeout=60: _ok(nat if args[0] == "net-dumpxml" else "")), \
                patch.object(vm.shutil, "which", return_value=None):
            status = vm.network_status("scn", "lab")
        self.assertFalse(status["isolated"])
        self.assertEqual(status["forward"], "nat")

    def test_vm_is_not_created_on_a_network_that_is_not_isolated(self):
        with patch.object(vm, "domain_state", return_value="absent"), patch.object(vm, "_owned_count", return_value=0), \
                patch.object(vm, "volume_exists", return_value=True), \
                patch.object(vm, "network_create", return_value={"name": "cr-scn-net-lab", "isolated": False}), \
                patch.object(vm, "virsh") as virsh:
            with self.assertRaises(vm.VmError):
                vm.vm_create("scn", "win1", "ws2022", networks=["lab"])
        virsh.assert_not_called()


class OwnershipAndCleanupTests(unittest.TestCase):
    def test_foreign_domain_with_our_name_is_never_removed(self):
        calls = []

        def fake_virsh(args, timeout=60):
            calls.append(args[0])
            if args[0] == "domstate":
                return _ok("running\n")
            if args[0] == "dumpxml":
                return _ok(FOREIGN_DOMAIN)
            return _ok()

        with patch.object(vm, "virsh", side_effect=fake_virsh):
            outcome = vm.vm_destroy("scn", "win1")
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["state"], "unverified")
        self.assertNotIn("destroy", calls)
        self.assertNotIn("undefine", calls)
        self.assertNotIn("vol-delete", calls)

    def test_owned_domain_is_stopped_undefined_and_its_overlay_deleted(self):
        calls = []
        state = {"value": "running"}

        def fake_virsh(args, timeout=60):
            calls.append(args)
            if args[0] == "domstate":
                return _ok(state["value"] + "\n")
            if args[0] == "dumpxml":
                return _ok(OWNED_DOMAIN)
            if args[0] == "destroy":
                state["value"] = "shut off"
            return _ok()

        with patch.object(vm, "virsh", side_effect=fake_virsh):
            outcome = vm.vm_destroy("scn", "win1")
        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["removed_volume"])
        order = [args[0] for args in calls if args[0] in {"destroy", "undefine", "vol-delete"}]
        self.assertEqual(order, ["destroy", "undefine", "vol-delete"])
        deleted = next(args for args in calls if args[0] == "vol-delete")
        self.assertEqual(deleted[-1], "cr-scn-win1.qcow2")  # only the overlay, never the template

    def test_foreign_network_is_never_removed(self):
        foreign = "<network><name>cr-scn-net-lab</name><bridge name='virbr0'/></network>"
        calls = []

        def fake_virsh(args, timeout=60):
            calls.append(args[0])
            return _ok(foreign if args[0] == "net-dumpxml" else "")

        with patch.object(vm, "virsh", side_effect=fake_virsh):
            outcome = vm.network_destroy("scn", "lab")
        self.assertFalse(outcome["ok"])
        self.assertNotIn("net-undefine", calls)

    def test_existing_domain_is_never_replaced(self):
        with patch.object(vm, "domain_state", return_value="shut off"):
            with self.assertRaises(vm.VmError):
                vm.vm_create("scn", "win1", "ws2022")

    def test_vm_count_limit(self):
        with patch.object(vm, "domain_state", return_value="absent"), \
                patch.object(vm, "_owned_count", return_value=vm.LIMITS["count"]):
            with self.assertRaises(vm.VmError):
                vm.vm_create("scn", "win1", "ws2022")


class HealthTests(unittest.TestCase):
    def test_running_hypervisor_without_guest_agent_is_not_healthy(self):
        with patch.object(vm, "domain_owned", return_value=True), patch.object(vm, "domain_state", return_value="running"), \
                patch.object(vm, "_agent", return_value=None):
            report = vm.vm_health("scn", "win1")
        self.assertFalse(report["healthy"])
        self.assertEqual(report["checks"][0], {"id": "guest_agent_ping", "ok": False, "observed": "no answer"})

    def test_ready_requires_guest_ping(self):
        answers = iter([None, None, {"return": {}}])
        with patch.object(vm, "domain_owned", return_value=True), patch.object(vm, "domain_state", return_value="running"), \
                patch.object(vm, "_agent", side_effect=lambda *a, **k: next(answers)), patch.object(vm.time, "sleep"):
            ready = vm.vm_wait_ready("scn", "win1", timeout=60)
        self.assertTrue(ready["guest_ready"])

    def test_stopped_vm_is_never_ready(self):
        with patch.object(vm, "domain_owned", return_value=True), patch.object(vm, "domain_state", return_value="shut off"):
            ready = vm.vm_wait_ready("scn", "win1", timeout=60)
        self.assertFalse(ready["ready"])
        self.assertEqual(ready["state"], "shut off")

    def test_unowned_vm_is_not_inspected(self):
        with patch.object(vm, "domain_owned", return_value=False):
            self.assertEqual(vm.vm_health("scn", "win1"), {"healthy": False, "state": "unverified"})


class UnattendMediaTests(unittest.TestCase):
    def test_unattend_media_is_fully_automatic_and_holds_no_fixed_credential(self):
        if not vm.shutil.which("xorriso"):
            self.skipTest("xorriso is not installed")
        with TemporaryDirectory() as temporary:
            iso = vm._build_unattend_iso(Path(temporary), image_index=1, computer_name="CR-WS2022", password="Rand0m!pw")
            self.assertGreater(iso.stat().st_size, 0)
            answer = (Path(temporary) / "unattend" / "autounattend.xml").read_text()
        ET.fromstring(answer)  # well-formed
        self.assertIn("<WillWipeDisk>true</WillWipeDisk>", answer)
        self.assertIn("<Key>/IMAGE/INDEX</Key><Value>1</Value>", answer)
        self.assertIn("<AcceptEula>true</AcceptEula>", answer)
        self.assertNotIn("ProductKey", answer)  # evaluation media: no key is supplied or invented
        # the password is generated per build, not a constant in the source tree
        self.assertNotIn("Rand0m!pw", vm._AUTOUNATTEND)
        self.assertIn("{password}", vm._AUTOUNATTEND)


class ManagerWrapperTests(unittest.TestCase):
    def test_licence_acknowledgement_is_required(self):
        ready = {"ok": True, "category": "ready", "message": "ok"}
        with patch.object(vm, "preflight", return_value=dict(ready)), patch.object(vm, "volume_exists", return_value=True):
            refused = manager.vm_preflight("ws2022", authorized=False)
            allowed = manager.vm_preflight("ws2022", authorized=True)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["category"], "authorization_or_configuration")
        self.assertTrue(allowed["ok"])

    def test_missing_template_is_reported_as_image_missing(self):
        with patch.object(vm, "preflight", return_value={"ok": True, "category": "ready"}), \
                patch.object(vm, "volume_exists", return_value=False):
            report = manager.vm_preflight("ws2022", authorized=True)
        self.assertEqual(report["category"], "image_missing")

    def test_create_without_acknowledgement_touches_nothing(self):
        with patch.object(vm, "preflight", return_value={"ok": True, "category": "ready"}), \
                patch.object(vm, "volume_exists", return_value=True), patch.object(vm, "vm_create") as create, \
                patch.object(manager, "record", return_value={}):
            outcome = manager.vm_create("scn", "win1", "ws2022", authorized=False)
        self.assertEqual(outcome["state"], "preflight_failed")
        create.assert_not_called()

    def test_status_distinguishes_absent_unverified_running(self):
        with patch.object(vm, "domain_state", return_value="absent"):
            self.assertEqual(manager.vm_status("scn", "win1")["state"], "absent")
        with patch.object(vm, "domain_state", return_value="running"), patch.object(vm, "domain_owned", return_value=False):
            self.assertEqual(manager.vm_status("scn", "win1")["state"], "unverified")
        with patch.object(vm, "domain_state", return_value="running"), patch.object(vm, "domain_owned", return_value=True):
            self.assertEqual(manager.vm_status("scn", "win1")["state"], "running")

    def test_legacy_virsh_command_line_is_routed_to_the_backend(self):
        with patch.object(vm, "virsh", return_value=_ok("x")) as virsh:
            manager._vm_run(["/usr/bin/virsh", "-c", manager.VM_URI, "domstate", "cr-scn-win1"], timeout=5)
        virsh.assert_called_once_with(["domstate", "cr-scn-win1"], timeout=5)


class MediaIntegrityTests(unittest.TestCase):
    def _iso(self, directory: Path, blocks: int, written_blocks: int) -> Path:
        descriptor = bytearray(2048)
        descriptor[0] = 1
        descriptor[1:6] = b"CD001"
        descriptor[80:84] = blocks.to_bytes(4, "little")
        descriptor[128:130] = (2048).to_bytes(2, "little")
        path = directory / "media.iso"
        path.write_bytes(bytes(16 * 2048) + bytes(descriptor) + bytes((written_blocks - 17) * 2048))
        return path

    def test_truncated_iso_is_rejected_before_upload(self):
        with TemporaryDirectory() as temporary:
            truncated = self._iso(Path(temporary), blocks=400, written_blocks=40)
            self.assertEqual(vm.iso_declared_bytes(truncated), 400 * 2048)
            with patch.object(vm, "virsh") as virsh:
                with self.assertRaises(vm.VmError) as caught:
                    vm.import_media(truncated, "media.iso")
            self.assertIn("truncated", str(caught.exception))
            virsh.assert_not_called()

    def test_complete_iso_passes_and_non_iso_is_not_judged(self):
        with TemporaryDirectory() as temporary:
            complete = self._iso(Path(temporary), blocks=40, written_blocks=40)
            vm.check_media_complete(complete)
            other = Path(temporary) / "disk.raw"
            other.write_bytes(b"x" * 4096)
            self.assertIsNone(vm.iso_declared_bytes(other))
            vm.check_media_complete(other)
