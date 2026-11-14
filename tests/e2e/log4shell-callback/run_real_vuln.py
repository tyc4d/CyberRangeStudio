#!/usr/bin/env python3
"""Inert safety guard for the real-vuln Log4Shell reproduction (see run_real_vuln.md).

This script intentionally does NOT deploy or exploit anything. Running a real
vulnerable image (vulhub solr 8.11.0 / Log4j 2.14.1) is BLOCKED until the host
network isolation gap is fixed and reviewed (an `internal` bridge can currently
reach host services; measured host_gw_22=REACHED). Until then this exits with a
NOT_TESTED notice so the plan is preserved without any exploit being run.
"""
from __future__ import annotations

import json
import sys

# Flip to True ONLY after infra-eng fixes host-gateway isolation AND a reviewer
# signs off, as recorded in run_real_vuln.md. Leaving it False keeps this inert.
ISOLATION_FIXED_AND_REVIEWED = False


def main() -> int:
    status = {
        "step": "real_log4shell_b2_reproduction",
        "status": "NOT_TESTED",
        "blocked_on": "host-gateway isolation gap (internal bridge reaches host sshd:22)",
        "note": "No real vulnerable image deployed and no exploit executed by design. "
                "See run_real_vuln.md for the plan and expected results.",
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if not ISOLATION_FIXED_AND_REVIEWED:
        return 0
    print("Guard flag set but execution path intentionally not implemented here; "
          "update run_real_vuln.md and implement under review before enabling.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
