"""Local libvirt/KVM backend for Windows Server evaluation VMs (B4 phase 1).

What this module really does (verified on this host, see reports/overnight/INFRA-VALIDATION.md):

* talks to the system libvirt daemon (``qemu:///system``) without sudo, as a member of the
  ``libvirt`` group. When the current process has not picked the group up yet it re-runs
  virsh through ``sg libvirt``;
* keeps every disk and ISO inside one libvirt *storage pool*, uploaded through libvirtd.
  QEMU runs as ``libvirt-qemu`` and cannot read a 0750 home directory, so files are never
  referenced by a path under the user's home;
* builds a bootable template from the official evaluation ISO with an unattended install
  (no interaction, no network card during the build);
* starts scenario VMs as copy-on-write overlays of that template on an *isolated* libvirt
  network that has no host address, no DHCP and no forwarding;
* reports health from inside the guest through the QEMU guest agent, never from the
  hypervisor state alone;
* deletes only domains, networks and volumes that carry this product's ownership metadata.

Nothing here executes scenario actions inside the guest.
"""
from __future__ import annotations

import base64
import grp
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

VM_URI = "qemu:///system"
OWNER = "cyberrange"
METADATA_NS = "https://cyberrange.local/libvirt/1.0"
POOL = os.getenv("CR_VM_POOL", "cyberrange")
POOL_PATH = os.getenv("CR_VM_POOL_PATH", f"/var/lib/libvirt/images/{POOL}")
LIMITS = {"vcpus": 4, "memory_mib": 8192, "disk_gib": 100, "count": 4}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_VOLUME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_REQUIRED_TOOLS = ("virsh", "qemu-img", "qemu-system-x86_64", "xorriso")


class VmError(RuntimeError):
    pass


def _check_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise VmError(f"invalid identifier: {value!r}")
    return value


def _check_volume(value: str) -> str:
    if not isinstance(value, str) or not _VOLUME_RE.fullmatch(value):
        raise VmError(f"invalid volume name: {value!r}")
    return value


# --------------------------------------------------------------------------- virsh

def _in_libvirt_group_now() -> bool:
    try:
        gid = grp.getgrnam("libvirt").gr_gid
    except KeyError:
        return False
    return gid in os.getgroups() or gid == os.getegid()


def _libvirt_group_pending() -> bool:
    """User is listed in the libvirt group but this process started before that took effect."""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name in grp.getgrnam("libvirt").gr_mem
    except KeyError:
        return False


def virsh(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run one virsh command against the system daemon. Never uses sudo."""
    executable = shutil.which("virsh")
    if not executable:
        return {"returncode": 127, "stdout": "", "stderr": "virsh executable is not installed"}
    command = [executable, "-c", VM_URI, *args]
    if not _in_libvirt_group_now() and _libvirt_group_pending() and shutil.which("sg"):
        command = ["sg", "libvirt", "-c", " ".join(shlex.quote(part) for part in command)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": f"virsh {args[0]} timed out after {timeout}s"}
    except OSError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}


def _must(result: dict[str, Any], what: str) -> dict[str, Any]:
    if result["returncode"] != 0:
        raise VmError(f"{what} failed: {result['stderr'] or result['stdout']}".strip()[:800])
    return result


# ----------------------------------------------------------------------- preflight

def preflight() -> dict[str, Any]:
    """Read-only readiness check. Each failure names its category; nothing is changed."""
    tools = {name: shutil.which(name) for name in _REQUIRED_TOOLS}
    missing = [name for name, path in tools.items() if not path]
    report: dict[str, Any] = {"ok": False, "backend": "libvirt-qemu", "uri": VM_URI, "pool": POOL,
                              "tools": tools, "missing_tools": missing, "kvm": Path("/dev/kvm").exists()}
    if missing:
        return {**report, "category": "tools_unavailable", "message": "VM 工具未安裝：" + ", ".join(missing)}
    if not report["kvm"]:
        return {**report, "category": "hardware", "message": "此主機沒有 /dev/kvm（未開啟硬體虛擬化）"}
    probe = virsh(["uri"], timeout=10)
    if probe["returncode"] != 0:
        return {**report, "category": "authorization_or_configuration",
                "message": "無法連線到 libvirt 系統服務（使用者需在 libvirt 群組，且 libvirtd 需在執行）",
                "detail": probe["stderr"][:400]}
    capabilities = virsh(["domcapabilities", "--virttype", "kvm"], timeout=10)
    if capabilities["returncode"] != 0:
        return {**report, "category": "hardware", "message": "libvirt 回報 KVM 不可用",
                "detail": capabilities["stderr"][:400]}
    pool = virsh(["pool-info", POOL], timeout=10)
    report["pool_ready"] = pool["returncode"] == 0 and "running" in pool["stdout"]
    report.update(ok=True, category="ready", message="VM backend 可用")
    return report


# ------------------------------------------------------------------------- storage

def ensure_pool() -> dict[str, Any]:
    """Create/start the product's directory pool through libvirtd (no host file access needed)."""
    info = virsh(["pool-info", POOL], timeout=10)
    if info["returncode"] != 0:
        _must(virsh(["pool-define-as", POOL, "dir", "--target", POOL_PATH]), "pool-define-as")
        _must(virsh(["pool-build", POOL]), "pool-build")
        info = virsh(["pool-info", POOL], timeout=10)
    if "running" not in info["stdout"]:
        _must(virsh(["pool-start", POOL]), "pool-start")
    return {"pool": POOL, "path": POOL_PATH}


def volume_exists(name: str) -> bool:
    return virsh(["vol-info", "--pool", POOL, _check_volume(name)], timeout=10)["returncode"] == 0


def volume_path(name: str) -> str:
    return _must(virsh(["vol-path", "--pool", POOL, _check_volume(name)], timeout=10), "vol-path")["stdout"].strip()


def iso_declared_bytes(source: str | Path) -> int | None:
    """Size an ISO 9660 image says it has (primary volume descriptor), or None if not an ISO."""
    try:
        with open(source, "rb") as handle:
            handle.seek(16 * 2048)
            descriptor = handle.read(2048)
    except OSError:
        return None
    if len(descriptor) < 132 or descriptor[1:6] != b"CD001" or descriptor[0] != 1:
        return None
    blocks = int.from_bytes(descriptor[80:84], "little")
    block_size = int.from_bytes(descriptor[128:130], "little")
    return blocks * block_size


def check_media_complete(source: str | Path) -> None:
    """Reject a truncated ISO (an interrupted download still lists its files but cannot be read)."""
    declared = iso_declared_bytes(source)
    actual = Path(source).stat().st_size
    if declared is not None and actual < declared:
        raise VmError(f"media file is truncated: {source} has {actual} bytes but the image declares {declared}")


def import_media(source: str | Path, name: str, *, replace: bool = False) -> dict[str, Any]:
    """Upload a local file (ISO) into the pool as a raw volume. Idempotent on size."""
    source = Path(source)
    if not source.is_file():
        raise VmError(f"media file not found: {source}")
    check_media_complete(source)
    _check_volume(name)
    ensure_pool()
    size = source.stat().st_size
    if volume_exists(name):
        info = virsh(["vol-info", "--pool", POOL, name, "--bytes"], timeout=10)["stdout"]
        match = re.search(r"Capacity:\s+(\d+)", info)
        if match and int(match.group(1)) == size and not replace:
            return {"volume": name, "bytes": size, "uploaded": False}
        _must(virsh(["vol-delete", "--pool", POOL, name]), "vol-delete")
    _must(virsh(["vol-create-as", POOL, name, str(size), "--format", "raw"]), "vol-create-as")
    upload = virsh(["vol-upload", "--pool", POOL, name, str(source)], timeout=3600)
    if upload["returncode"] != 0:
        virsh(["vol-delete", "--pool", POOL, name])
        raise VmError(f"vol-upload failed: {upload['stderr'][:400]}")
    return {"volume": name, "bytes": size, "uploaded": True}


# ------------------------------------------------------------------------ metadata

def _metadata_xml(scenario_id: str, vm_id: str | None = None, role: str = "scenario") -> str:
    vm_attr = f" vmid='{vm_id}'" if vm_id else ""
    return (f"<metadata><cr:ownership xmlns:cr='{METADATA_NS}' owner='{OWNER}' scenario='{scenario_id}'"
            f"{vm_attr} role='{role}'/></metadata>")


def _ownership(xml_text: str) -> dict[str, str] | None:
    """Parse the ownership element from a domain/network XML dump, or None."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    node = root.find(f"./metadata/{{{METADATA_NS}}}ownership")
    if node is None or node.get("owner") != OWNER:
        return None
    return dict(node.attrib)


def domain_name(scenario_id: str, vm_id: str) -> str:
    return f"cr-{_check_id(scenario_id)}-{_check_id(vm_id)}"


def network_name(scenario_id: str, network_id: str) -> str:
    return f"cr-{_check_id(scenario_id)}-net-{_check_id(network_id)}"


def _bridge_name(scenario_id: str, network_id: str) -> str:
    # Linux interface names are limited to 15 characters.
    import hashlib
    return "crb" + hashlib.sha256(f"{scenario_id}/{network_id}".encode()).hexdigest()[:10]


def domain_owned(scenario_id: str, vm_id: str) -> bool:
    dump = virsh(["dumpxml", domain_name(scenario_id, vm_id)], timeout=15)
    owner = _ownership(dump["stdout"]) if dump["returncode"] == 0 else None
    return bool(owner and owner.get("scenario") == scenario_id and owner.get("vmid") == vm_id)


def network_owned(scenario_id: str, network_id: str) -> bool:
    dump = virsh(["net-dumpxml", network_name(scenario_id, network_id)], timeout=15)
    owner = _ownership(dump["stdout"]) if dump["returncode"] == 0 else None
    return bool(owner and owner.get("scenario") == scenario_id)


# ------------------------------------------------------------------------- network

def network_create(scenario_id: str, network_id: str) -> dict[str, Any]:
    """Define and start an isolated layer-2 network: no host address, no DHCP, no forwarding.

    Without an ``<ip>`` element libvirt gives the bridge no address, so a guest cannot
    reach any service on the host through it, and there is no route anywhere else.
    """
    name = network_name(scenario_id, network_id)
    existing = virsh(["net-info", name], timeout=10)
    if existing["returncode"] == 0:
        if not network_owned(scenario_id, network_id):
            raise VmError(f"network {name} exists but is not owned by this scenario")
    else:
        bridge = _bridge_name(scenario_id, network_id)
        xml = (f"<network><name>{name}</name>{_metadata_xml(scenario_id, role='network')}"
               f"<bridge name='{bridge}' stp='on' delay='0'/></network>")
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8") as handle:
            handle.write(xml)
            handle.flush()
            os.chmod(handle.name, 0o644)
            _must(virsh(["net-define", handle.name]), "net-define")
    info = virsh(["net-info", name], timeout=10)["stdout"]
    if not re.search(r"Active:\s+yes", info):
        _must(virsh(["net-start", name]), "net-start")
    return network_status(scenario_id, network_id)


def network_status(scenario_id: str, network_id: str) -> dict[str, Any]:
    name = network_name(scenario_id, network_id)
    dump = virsh(["net-dumpxml", name], timeout=10)
    if dump["returncode"] != 0:
        return {"name": name, "state": "absent"}
    root = ET.fromstring(dump["stdout"])
    bridge = root.find("bridge").get("name") if root.find("bridge") is not None else None
    host_addresses: list[str] = []
    if bridge and shutil.which("ip"):
        shown = subprocess.run(["ip", "-o", "addr", "show", "dev", bridge], capture_output=True, text=True)
        host_addresses = [line.split()[3] for line in shown.stdout.splitlines()
                          if " inet " in line or (" inet6 " in line and not line.split()[3].startswith("fe80"))]
    info = virsh(["net-info", name], timeout=10)["stdout"]
    return {
        "name": name, "bridge": bridge,
        "state": "active" if re.search(r"Active:\s+yes", info) else "inactive",
        "forward": root.find("forward").get("mode") if root.find("forward") is not None else None,
        "libvirt_ip_configured": root.find("ip") is not None,
        "host_addresses": host_addresses,
        "isolated": root.find("forward") is None and root.find("ip") is None and not host_addresses,
        "owned": _ownership(dump["stdout"]) is not None,
    }


def network_destroy(scenario_id: str, network_id: str) -> dict[str, Any]:
    name = network_name(scenario_id, network_id)
    if virsh(["net-info", name], timeout=10)["returncode"] != 0:
        return {"name": name, "state": "absent", "ok": True}
    if not network_owned(scenario_id, network_id):
        return {"name": name, "state": "unverified", "ok": False,
                "error": "network ownership could not be verified; not removed"}
    virsh(["net-destroy", name])
    done = virsh(["net-undefine", name])
    return {"name": name, "state": "removed" if done["returncode"] == 0 else "failed",
            "ok": done["returncode"] == 0, "error": done["stderr"] or None}


# -------------------------------------------------------------------------- domain

def _domain_xml(name: str, metadata: str, *, vcpus: int, memory_mib: int, disk_path: str,
                cdroms: list[str] | None = None, networks: list[str] | None = None,
                boot_from_cdrom: bool = False) -> str:
    """A Windows-capable machine using only drivers Windows Server ships with.

    SATA disk and e1000e NIC need no extra driver during setup; the guest-agent channel is
    virtio-serial, whose driver the unattended install adds from the virtio-win media.
    """
    devices = [
        "<emulator>/usr/bin/qemu-system-x86_64</emulator>",
        f"<disk type='file' device='disk'><driver name='qemu' type='qcow2' cache='unsafe' discard='unmap'/>"
        f"<source file='{escape(disk_path)}'/><target dev='sda' bus='sata'/>"
        f"<boot order='{2 if boot_from_cdrom else 1}'/></disk>",
    ]
    for index, path in enumerate(cdroms or []):
        boot = "<boot order='1'/>" if boot_from_cdrom and index == 0 else ""
        devices.append(
            f"<disk type='file' device='cdrom'><driver name='qemu' type='raw'/><source file='{escape(path)}'/>"
            f"<target dev='sd{chr(ord('b') + index)}' bus='sata'/><readonly/>{boot}</disk>")
    for network in networks or []:
        devices.append(f"<interface type='network'><source network='{escape(network)}'/>"
                       "<model type='e1000e'/></interface>")
    devices += [
        "<controller type='virtio-serial' index='0'/>",
        "<channel type='unix'><target type='virtio' name='org.qemu.guest_agent.0'/></channel>",
        "<input type='tablet' bus='usb'/>",
        "<video><model type='vga' vram='16384' heads='1'/></video>",
        # No graphics listener: the console is not exposed on any port. `virsh screenshot`
        # still works because it reads the video device directly.
        "<memballoon model='none'/>",
    ]
    return (
        f"<domain type='kvm'><name>{name}</name>{metadata}"
        f"<memory unit='MiB'>{memory_mib}</memory><vcpu placement='static'>{vcpus}</vcpu>"
        "<os><type arch='x86_64' machine='q35'>hvm</type></os>"
        "<features><acpi/><apic/><hyperv mode='custom'><relaxed state='on'/><vapic state='on'/>"
        "<spinlocks state='on' retries='8191'/></hyperv></features>"
        "<cpu mode='host-passthrough' check='none'/>"
        "<clock offset='localtime'><timer name='hypervclock' present='yes'/>"
        "<timer name='hpet' present='no'/></clock>"
        "<on_poweroff>destroy</on_poweroff><on_reboot>restart</on_reboot><on_crash>destroy</on_crash>"
        f"<devices>{''.join(devices)}</devices></domain>"
    )


def _define(xml: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8") as handle:
        handle.write(xml)
        handle.flush()
        os.chmod(handle.name, 0o644)
        _must(virsh(["define", handle.name]), "define")


def domain_state(name: str) -> str:
    result = virsh(["domstate", name], timeout=10)
    if result["returncode"] != 0:
        return "absent"
    return result["stdout"].strip().lower() or "unknown"


def _owned_count() -> int:
    listing = virsh(["list", "--all", "--name"], timeout=15)["stdout"].split()
    count = 0
    for candidate in listing:
        if candidate.startswith("cr-"):
            dump = virsh(["dumpxml", candidate], timeout=15)
            if dump["returncode"] == 0 and _ownership(dump["stdout"]):
                count += 1
    return count


def screenshot(name: str, destination: Path) -> bool:
    """Save the guest display to a local file (evidence only)."""
    result = virsh(["screenshot", name, str(destination)], timeout=30)
    return result["returncode"] == 0 and destination.exists()


# ---------------------------------------------------------------- template (unattended)

_AUTOUNATTEND = """<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
      <InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <DiskConfiguration>
        <WillShowUI>OnError</WillShowUI>
        <Disk wcm:action="add">
          <DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>NTFS</Format><Label>Windows</Label><Active>true</Active></ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{image_index}</Value></MetaData></InstallFrom>
          <InstallTo><DiskID>0</DiskID><PartitionID>1</PartitionID></InstallTo>
          <WillShowUI>OnError</WillShowUI>
        </OSImage>
      </ImageInstall>
      <UserData><AcceptEula>true</AcceptEula><FullName>CyberRange Lab</FullName><Organization>CyberRange Lab</Organization></UserData>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <ComputerName>{computer_name}</ComputerName><TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <OOBE><HideEULAPage>true</HideEULAPage><HideLocalAccountScreen>true</HideLocalAccountScreen><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><ProtectYourPC>3</ProtectYourPC></OOBE>
      <UserAccounts><AdministratorPassword><Value>{password}</Value><PlainText>true</PlainText></AdministratorPassword></UserAccounts>
      <AutoLogon><Enabled>true</Enabled><LogonCount>1</LogonCount><Username>Administrator</Username><Password><Value>{password}</Value><PlainText>true</PlainText></Password></AutoLogon>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add"><Order>1</Order><Description>Install guest agent and finish</Description>
          <CommandLine>powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-PSDrive -PSProvider FileSystem | Where-Object {{ Test-Path ($_.Root + 'cr-firstboot.ps1') }} | Select-Object -First 1).Root; &amp; ($d + 'cr-firstboot.ps1')"</CommandLine>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"""

# Runs once inside the guest at first logon. It only installs the Red Hat virtio-serial
# driver and the QEMU guest agent from the attached virtio-win media and writes a log.
# The host does NOT treat a power-off as completion (Windows Setup powers the machine
# off/on between phases); it waits until the guest agent answers and this log says done.
_FIRSTBOOT_PS1 = r"""
$ErrorActionPreference = 'Continue'
$log = 'C:\cr-firstboot.log'
"start $(Get-Date -Format o)" | Out-File $log
$media = (Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path ($_.Root + 'guest-agent\qemu-ga-x86_64.msi') } | Select-Object -First 1).Root
"virtio media: $media" | Out-File $log -Append
if ($media) {
  Get-ChildItem ($media + 'cert') -Filter *.cer -ErrorAction SilentlyContinue | ForEach-Object { certutil -addstore -f TrustedPublisher $_.FullName | Out-File $log -Append }
  pnputil /add-driver ($media + 'vioserial\2k22\amd64\vioser.inf') /install | Out-File $log -Append
  $p = Start-Process msiexec.exe -ArgumentList '/i', ($media + 'guest-agent\qemu-ga-x86_64.msi'), '/qn', '/norestart' -Wait -PassThru
  "qemu-ga msi exit: $($p.ExitCode)" | Out-File $log -Append
  Set-Service -Name QEMU-GA -StartupType Automatic -ErrorAction SilentlyContinue
}
"service: $((Get-Service QEMU-GA -ErrorAction SilentlyContinue).Status)" | Out-File $log -Append
"done $(Get-Date -Format o)" | Out-File $log -Append
"""


def _build_unattend_iso(directory: Path, *, image_index: int, computer_name: str, password: str) -> Path:
    staging = directory / "unattend"
    staging.mkdir()
    (staging / "autounattend.xml").write_text(
        _AUTOUNATTEND.format(image_index=image_index, computer_name=computer_name, password=escape(password)),
        encoding="utf-8")
    (staging / "cr-firstboot.ps1").write_text(_FIRSTBOOT_PS1, encoding="utf-8")
    iso = directory / "unattend.iso"
    done = subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-J", "-r", "-V", "CR_UNATTEND",
                           "-o", str(iso), str(staging)], capture_output=True, text=True, timeout=120)
    if done.returncode != 0 or not iso.exists():
        raise VmError(f"could not build unattend media: {done.stderr[:300]}")
    return iso


def build_windows_template(template: str, install_iso_volume: str, virtio_iso_volume: str, *,
                           image_index: int = 1, disk_gib: int = 40, vcpus: int = 4, memory_mib: int = 4096,
                           timeout: int = 3600, evidence_dir: Path | None = None,
                           progress: Any = None) -> dict[str, Any]:
    """Install Windows Server unattended into a new template volume.

    The build VM has no network card at all. The Administrator password is random, exists
    only inside the temporary unattend media (deleted afterwards) and is never returned:
    later access goes through the guest agent.
    """
    _check_id(template)
    template_volume = f"tpl-{template}.qcow2"
    ready = preflight()
    if not ready["ok"]:
        raise VmError(f"VM backend not ready: {ready['message']}")
    ensure_pool()
    for volume in (install_iso_volume, virtio_iso_volume):
        if not volume_exists(volume):
            raise VmError(f"media volume missing in pool {POOL}: {volume}")
    if volume_exists(template_volume):
        return {"template": template_volume, "built": False, "reason": "template volume already exists"}
    build_scenario, build_vm = "tplbuild", template
    name = domain_name(build_scenario, build_vm)
    if domain_state(name) != "absent":
        raise VmError(f"a build domain named {name} already exists; destroy it first")
    unattend_volume = f"unattend-{template}.iso"
    started = time.monotonic()
    log: list[str] = []

    def note(message: str) -> None:
        log.append(f"{int(time.monotonic() - started):5d}s {message}")
        if progress:
            progress(log[-1])

    try:
        with tempfile.TemporaryDirectory(prefix="cr-unattend-") as temporary:
            iso = _build_unattend_iso(Path(temporary), image_index=image_index,
                                      computer_name="CR-WS2022", password=secrets.token_urlsafe(18) + "aA1!")
            import_media(iso, unattend_volume, replace=True)
        _must(virsh(["vol-create-as", POOL, template_volume, f"{disk_gib}G", "--format", "qcow2"]), "vol-create-as")
        xml = _domain_xml(name, _metadata_xml(build_scenario, build_vm, role="template-build"),
                          vcpus=vcpus, memory_mib=memory_mib, disk_path=volume_path(template_volume),
                          cdroms=[volume_path(install_iso_volume), volume_path(unattend_volume),
                                  volume_path(virtio_iso_volume)],
                          networks=[], boot_from_cdrom=True)
        _define(xml)
        _must(virsh(["start", name]), "start")
        note("build VM started (no network card)")
        deadline = time.monotonic() + timeout
        shots, restarts, firstboot_log = 0, 0, ""
        finished = False
        while time.monotonic() < deadline:
            state = domain_state(name)
            if state == "shut off":
                # Setup's own restart between phases can surface as a power-off. It is
                # not evidence of completion, so boot again and keep waiting.
                restarts += 1
                if restarts > 6:
                    raise VmError("build VM powered off repeatedly without ever reporting completion")
                note(f"guest powered off before reporting completion; starting it again ({restarts})")
                _must(virsh(["start", name]), "start")
            elif _agent(name, {"execute": "guest-ping"}, timeout=8) is not None:
                # Positive confirmation from inside Windows: read the first-boot log.
                read = _guest_exec_named(name, "cmd.exe", ["/c", "type", "C:\\cr-firstboot.log"], timeout=60)
                firstboot_log = read.get("stdout", "")
                if read.get("ok") and "done " in firstboot_log:
                    note("guest agent answers and first-boot log reports done")
                    finished = True
                    break
            if evidence_dir and int(time.monotonic() - started) // 120 >= shots:
                target = evidence_dir / f"template-build-{shots:02d}.ppm"
                if screenshot(name, target):
                    note(f"screenshot {target.name}")
                shots += 1
            time.sleep(10)
        if not finished:
            if evidence_dir:
                screenshot(name, evidence_dir / "template-build-timeout.ppm")
            raise VmError(f"unattended install did not report completion within {timeout}s")
        osinfo = (_agent(name, {"execute": "guest-get-osinfo"}) or {}).get("return", {})
        note(f"installed: {osinfo.get('pretty-name')} {osinfo.get('version-id')} build {osinfo.get('kernel-version')}")
        # Clean shutdown through the agent so the template disk is consistent.
        _must(virsh(["shutdown", name, "--mode", "agent"], timeout=30), "shutdown")
        stop_deadline = time.monotonic() + 300
        while domain_state(name) != "shut off":
            if time.monotonic() > stop_deadline:
                raise VmError("build VM did not shut down cleanly")
            time.sleep(3)
        note("guest shut down cleanly; template is complete")
    except Exception:
        _remove_domain(name)
        if volume_exists(template_volume):
            virsh(["vol-delete", "--pool", POOL, template_volume])
        raise
    finally:
        if volume_exists(unattend_volume):
            virsh(["vol-delete", "--pool", POOL, unattend_volume])
    _remove_domain(name)
    return {"template": template_volume, "built": True, "seconds": int(time.monotonic() - started),
            "image_index": image_index, "restarts_during_setup": restarts, "os": osinfo,
            "firstboot_log": firstboot_log.splitlines(), "log": log}


def _remove_domain(name: str) -> dict[str, Any]:
    """Stop and undefine a domain that has already been verified as ours."""
    if domain_state(name) == "absent":
        return {"returncode": 0, "stdout": "", "stderr": ""}
    if domain_state(name) not in {"shut off", "absent"}:
        virsh(["destroy", name])
    return virsh(["undefine", name, "--nvram", "--snapshots-metadata", "--managed-save"])


# --------------------------------------------------------------------- scenario VMs

def vm_create(scenario_id: str, vm_id: str, template: str, *, networks: list[str] | None = None,
              vcpus: int = 2, memory_mib: int = 4096) -> dict[str, Any]:
    """Define a scenario VM as a copy-on-write overlay of a template, on isolated networks only."""
    _check_id(scenario_id), _check_id(vm_id), _check_id(template)
    if not (1 <= vcpus <= LIMITS["vcpus"] and 1024 <= memory_mib <= LIMITS["memory_mib"]):
        raise VmError("VM resources exceed configured limits")
    name = domain_name(scenario_id, vm_id)
    if domain_state(name) != "absent":
        raise VmError(f"refusing to replace existing domain {name}")
    if _owned_count() >= LIMITS["count"]:
        raise VmError("VM count limit reached")
    template_volume = f"tpl-{template}.qcow2"
    if not volume_exists(template_volume):
        raise VmError(f"template volume {template_volume} is missing; build it first")
    network_names = []
    for network_id in networks or []:
        status = network_create(scenario_id, network_id)
        if not status["isolated"]:
            raise VmError(f"network {status['name']} is not isolated: {status}")
        network_names.append(status["name"])
    disk_volume = f"{name}.qcow2"
    if volume_exists(disk_volume):
        raise VmError(f"volume {disk_volume} already exists")
    capacity = re.search(r"Capacity:\s+(\d+)", virsh(["vol-info", "--pool", POOL, template_volume, "--bytes"])["stdout"])
    _must(virsh(["vol-create-as", POOL, disk_volume, capacity.group(1) if capacity else "40G", "--format", "qcow2",
                 "--backing-vol", template_volume, "--backing-vol-format", "qcow2"]), "vol-create-as overlay")
    try:
        _define(_domain_xml(name, _metadata_xml(scenario_id, vm_id, role="scenario-vm"), vcpus=vcpus,
                            memory_mib=memory_mib, disk_path=volume_path(disk_volume), networks=network_names))
    except VmError:
        virsh(["vol-delete", "--pool", POOL, disk_volume])
        raise
    return {"name": name, "state": "defined", "disk_volume": disk_volume, "template": template_volume,
            "networks": network_names, "vcpus": vcpus, "memory_mib": memory_mib}


def vm_boot(scenario_id: str, vm_id: str) -> dict[str, Any]:
    if not domain_owned(scenario_id, vm_id):
        raise VmError("VM ownership could not be verified")
    name = domain_name(scenario_id, vm_id)
    if domain_state(name) != "running":
        _must(virsh(["start", name]), "start")
    return {"name": name, "state": domain_state(name)}


def _agent(name: str, payload: dict[str, Any], timeout: int = 15) -> dict[str, Any] | None:
    result = virsh(["qemu-agent-command", name, json.dumps(payload), "--timeout", str(max(1, timeout - 3))],
                   timeout=timeout)
    if result["returncode"] != 0:
        return None
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None


def guest_exec(scenario_id: str, vm_id: str, path: str, arguments: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run one fixed read-only command inside the guest through the agent and return its output."""
    if not domain_owned(scenario_id, vm_id):
        raise VmError("VM ownership could not be verified")
    return _guest_exec_named(domain_name(scenario_id, vm_id), path, arguments, timeout)


def _guest_exec_named(name: str, path: str, arguments: list[str], timeout: int = 60) -> dict[str, Any]:
    started = _agent(name, {"execute": "guest-exec",
                            "arguments": {"path": path, "arg": arguments, "capture-output": True}})
    if not started or "return" not in started:
        return {"ok": False, "error": "guest agent did not accept the command"}
    pid = started["return"]["pid"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _agent(name, {"execute": "guest-exec-status", "arguments": {"pid": pid}})
        if status and status.get("return", {}).get("exited"):
            body = status["return"]
            decode = lambda key: base64.b64decode(body.get(key, "")).decode("utf-8", "replace")  # noqa: E731
            return {"ok": body.get("exitcode") == 0, "exit_code": body.get("exitcode"),
                    "stdout": decode("out-data").strip(), "stderr": decode("err-data").strip()}
        time.sleep(1)
    return {"ok": False, "error": f"guest command did not finish within {timeout}s"}


def vm_wait_ready(scenario_id: str, vm_id: str, timeout: int = 600) -> dict[str, Any]:
    """Ready means the operating system answers through the guest agent, not that QEMU runs."""
    if not domain_owned(scenario_id, vm_id):
        raise VmError("VM ownership could not be verified")
    name = domain_name(scenario_id, vm_id)
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        state = domain_state(name)
        if state != "running":
            return {"ready": False, "state": state, "guest_ready": False,
                    "seconds": int(time.monotonic() - started)}
        if _agent(name, {"execute": "guest-ping"}, timeout=8) is not None:
            return {"ready": True, "state": "running", "guest_ready": True, "probe": "qemu guest agent guest-ping",
                    "seconds": int(time.monotonic() - started)}
        time.sleep(5)
    return {"ready": False, "state": "timeout", "guest_ready": False, "seconds": int(time.monotonic() - started)}


def vm_health(scenario_id: str, vm_id: str) -> dict[str, Any]:
    """Native health: facts reported by Windows itself through the guest agent."""
    if not domain_owned(scenario_id, vm_id):
        return {"healthy": False, "state": "unverified"}
    name = domain_name(scenario_id, vm_id)
    state = domain_state(name)
    report: dict[str, Any] = {"name": name, "hypervisor_state": state, "healthy": False, "checks": []}
    if state != "running":
        return report

    def check(check_id: str, ok: bool, observed: Any) -> None:
        report["checks"].append({"id": check_id, "ok": bool(ok), "observed": observed})

    ping = _agent(name, {"execute": "guest-ping"}, timeout=8)
    check("guest_agent_ping", ping is not None, "answered" if ping is not None else "no answer")
    if ping is None:
        return report
    osinfo = (_agent(name, {"execute": "guest-get-osinfo"}) or {}).get("return", {})
    check("os_identity", "Windows Server" in str(osinfo.get("pretty-name", "")),
          {key: osinfo.get(key) for key in ("pretty-name", "version", "version-id", "kernel-version", "machine")})
    hostname = (_agent(name, {"execute": "guest-get-host-name"}) or {}).get("return", {}).get("host-name")
    check("hostname", bool(hostname), hostname)
    interfaces = (_agent(name, {"execute": "guest-network-get-interfaces"}) or {}).get("return", [])
    addresses = [{"name": item.get("name"), "mac": item.get("hardware-address"),
                  "ips": [ip.get("ip-address") for ip in item.get("ip-addresses", [])]} for item in interfaces]
    check("network_interfaces", bool(interfaces), addresses)
    services = guest_exec(scenario_id, vm_id, "powershell.exe", [
        "-NoProfile", "-NonInteractive", "-Command",
        "$os=Get-CimInstance Win32_OperatingSystem; "
        "[pscustomobject]@{Caption=$os.Caption;Version=$os.Version;BuildNumber=$os.BuildNumber;"
        "LastBoot=$os.LastBootUpTime.ToString('o');"
        "Services=@(Get-Service LanmanServer,EventLog,Winmgmt | ForEach-Object { $_.Name + '=' + $_.Status })}"
        " | ConvertTo-Json -Compress"], timeout=90)
    parsed: Any = services.get("stdout")
    try:
        parsed = json.loads(services.get("stdout") or "")
    except json.JSONDecodeError:
        pass
    running = isinstance(parsed, dict) and all(str(item).endswith("=Running") for item in parsed.get("Services", []))
    check("windows_core_services", bool(services.get("ok")) and running, parsed or services)
    report["healthy"] = all(item["ok"] for item in report["checks"])
    return report


def vm_stop(scenario_id: str, vm_id: str, timeout: int = 180) -> dict[str, Any]:
    """Ask Windows to shut down cleanly and wait until it has."""
    if not domain_owned(scenario_id, vm_id):
        raise VmError("VM ownership could not be verified")
    name = domain_name(scenario_id, vm_id)
    if domain_state(name) == "shut off":
        return {"name": name, "state": "shut off", "clean": True}
    request = virsh(["shutdown", name, "--mode", "agent"], timeout=30)
    if request["returncode"] != 0:
        request = virsh(["shutdown", name, "--mode", "acpi"], timeout=30)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if domain_state(name) == "shut off":
            return {"name": name, "state": "shut off", "clean": True}
        time.sleep(3)
    return {"name": name, "state": domain_state(name), "clean": False,
            "error": request["stderr"] or "guest did not power off in time"}


def vm_destroy(scenario_id: str, vm_id: str) -> dict[str, Any]:
    """Remove the VM and its overlay disk. Refuses anything without this scenario's metadata."""
    name = domain_name(scenario_id, vm_id)
    disk_volume = f"{name}.qcow2"
    if domain_state(name) == "absent":
        removed = False
        if volume_exists(disk_volume):
            removed = virsh(["vol-delete", "--pool", POOL, disk_volume])["returncode"] == 0
        return {"name": name, "state": "absent", "ok": True, "removed_volume": removed}
    if not domain_owned(scenario_id, vm_id):
        return {"name": name, "state": "unverified", "ok": False,
                "error": "VM ownership could not be verified; nothing was removed"}
    done = _remove_domain(name)
    removed = False
    if done["returncode"] == 0 and volume_exists(disk_volume):
        removed = virsh(["vol-delete", "--pool", POOL, disk_volume])["returncode"] == 0
    return {"name": name, "state": "destroyed" if done["returncode"] == 0 else "failed",
            "ok": done["returncode"] == 0, "removed_volume": removed, "error": done["stderr"] or None}


def scenario_inventory(scenario_id: str) -> dict[str, Any]:
    """Everything libvirt still holds for a scenario (used to prove cleanup)."""
    _check_id(scenario_id)
    prefix = f"cr-{scenario_id}-"
    domains = [name for name in virsh(["list", "--all", "--name"], timeout=15)["stdout"].split() if name.startswith(prefix)]
    networks = [name for name in virsh(["net-list", "--all", "--name"], timeout=15)["stdout"].split() if name.startswith(prefix)]
    volumes = [line.split()[0] for line in virsh(["vol-list", "--pool", POOL], timeout=15)["stdout"].splitlines()[2:]
               if line.split() and line.split()[0].startswith(prefix)]
    return {"domains": domains, "networks": networks, "volumes": volumes,
            "clean": not domains and not networks and not volumes}
