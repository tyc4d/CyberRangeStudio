"""Pre-execution isolation guard for Phase 3 real-PoC runs.

Before ANY real vulnerable image is deployed or exploited, we must prove the
experiment network cannot reach the host. An `internal` Docker bridge historically
still routed to host-gateway services (sshd:22 and other projects' ports) — running
an exploitable image one hop from the host is exactly what Phase 3 must not do.

`confirm_isolated()` stands up ONLY a harmless, pinned, non-root probe container on
the SAME network configuration the real run will use, probes the host gateway and a
set of known host-bound ports from inside it, and tears the probe down. It returns a
verdict; the real runners refuse to deploy a vulnerable image unless the verdict is
`isolated: True`. The vulnerable image is never deployed just to test isolation.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

BASE_IMAGE = "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"

# Host-bound services that MUST be unreachable from an isolated experiment network.
# sshd plus the other-project / QA-station ports named in the overnight COMMON rules.
HOST_PORTS = [22, 4000, 5173, 5177, 8000, 8077, 8080]


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# Probe executed INSIDE the isolated network: derive the bridge gateway from the
# container's own IPv4 and try each host port. Any success means NOT isolated.
_PROBE = """
import socket, json
ip = socket.gethostbyname(socket.gethostname())
gw = '.'.join(ip.split('.')[:3]) + '.1'
ports = {ports!r}
reached = []
for p in ports:
    try:
        socket.create_connection((gw, p), timeout=3).close()
        reached.append(p)
    except OSError:
        pass
# Also confirm the public internet is unreachable (defence in depth).
inet = []
for h, p in [('8.8.8.8', 53), ('1.1.1.1', 443)]:
    try:
        socket.create_connection((h, p), timeout=3).close()
        inet.append(f'{{h}}:{{p}}')
    except OSError:
        pass
print(json.dumps({{'own_ip': ip, 'gateway': gw, 'host_ports_reached': reached, 'internet_reached': inet}}))
"""


def confirm_isolated(network_name: str, *, project: str = "cr-poc-phase3-guard") -> dict:
    """Create a throwaway internal network + probe, verify isolation, tear down.

    network_name is informational; the guard always creates its own internal bridge
    so it tests the real isolation primitive without touching any other lab.
    """
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "project": project,
              "isolated": False, "detail": None, "error": None}
    net = f"{project}-net"
    cname = f"{project}-probe"
    # Clean any stale guard resources first.
    _run(["docker", "rm", "-f", cname], timeout=30)
    _run(["docker", "network", "rm", net], timeout=30)
    try:
        # Use the SAME isolation primitive the product applies to lab networks
        # (infra-eng host-isolation fix): internal + isolated IPv4 gateway mode, so the
        # guard tests the real control, not a weaker plain-internal bridge.
        created = _run(["docker", "network", "create", "--internal",
                        "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated", net], timeout=30)
        if created.returncode != 0:
            result["error"] = "could not create internal probe network: " + created.stderr[-300:]
            return result
        run = _run(["docker", "run", "-d", "--name", cname, "--network", net,
                    "--pull=never", "--user", "65532:65532", "--read-only",
                    "--cap-drop=ALL", "--security-opt", "no-new-privileges:true",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
                    BASE_IMAGE, "python", "-c", "import time; time.sleep(120)"], timeout=60)
        if run.returncode != 0:
            result["error"] = "could not start probe container: " + run.stderr[-300:]
            return result
        probe = _run(["docker", "exec", cname, "python", "-c", _PROBE.format(ports=HOST_PORTS)], timeout=40)
        try:
            detail = json.loads(probe.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            result["error"] = "probe produced no parseable output: " + (probe.stdout + probe.stderr)[-300:]
            return result
        result["detail"] = detail
        result["isolated"] = not detail["host_ports_reached"] and not detail["internet_reached"]
        return result
    finally:
        _run(["docker", "rm", "-f", cname], timeout=30)
        _run(["docker", "network", "rm", net], timeout=30)


class IsolationNotConfirmed(RuntimeError):
    """Raised when the host is reachable from the experiment network."""


def require_isolation() -> dict:
    """Confirm isolation or raise. Real runners call this before deploying a target."""
    verdict = confirm_isolated("phase3")
    if verdict.get("error"):
        raise IsolationNotConfirmed(f"isolation could not be verified: {verdict['error']}")
    if not verdict["isolated"]:
        raise IsolationNotConfirmed(
            "experiment network can reach the host/internet; refusing to deploy a vulnerable image. "
            f"detail={verdict['detail']}")
    return verdict


if __name__ == "__main__":
    print(json.dumps(confirm_isolated("phase3"), ensure_ascii=False, indent=2))
