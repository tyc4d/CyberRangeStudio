"""Harmless in-lab callback listener (stands in for the attacker LDAP server).

This reproduces only the *observable* half of a Log4Shell JNDI/LDAP callback
(expected.md B2, "真實重現"): it accepts an inbound TCP connection on the LDAP
port and RECORDS it. It never returns an LDAP referral, a Java class, or any
payload, so nothing is executed anywhere. It is the safe detection pattern:
prove the lookup fired, do not weaponise it.

Every connection is appended as one JSON line to CALLBACK_LOG so the runner can
assert on real evidence (source address, timestamp, bytes seen) rather than a
hard-coded result.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timezone

PORT = int(os.environ.get("LISTENER_PORT", "1389"))
CALLBACK_LOG = os.environ.get("CALLBACK_LOG", "/evidence/callbacks.jsonl")


def _record(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(event, ensure_ascii=False)
    with open(CALLBACK_LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print("CALLBACK " + line, flush=True)


def _handle(conn: socket.socket, addr) -> None:
    with conn:
        conn.settimeout(2.0)
        try:
            data = conn.recv(256)
        except OSError:
            data = b""
        # Deliberately send nothing back. A real attacker server would answer with
        # an LDAP referral pointing at a malicious class; refusing to do so keeps
        # this a detection-only listener with no code execution path.
        _record({"event": "callback", "peer_ip": addr[0], "peer_port": addr[1],
                 "first_bytes_hex": data[:32].hex()})


def main() -> None:
    open(CALLBACK_LOG, "a", encoding="utf-8").close()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(16)
    print(f"listener-ready port={PORT}", flush=True)
    while True:
        try:
            conn, addr = srv.accept()
        except OSError:
            continue
        threading.Thread(target=_handle, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
