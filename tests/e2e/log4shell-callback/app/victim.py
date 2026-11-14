"""Harmless victim web service that models the Log4Shell injection->lookup step.

This is an ASSUMED*SUBSTITUTED teaching stand-in for the real vulnerable service
(expected.md: real target was an unpatched VMware Horizon; the public substitute
is vulhub Solr 8.11.0 with Log4j 2.14.1). It is NOT real Log4j and performs NO
class loading or deserialization.

What it faithfully models: a log statement that interpolates attacker-controlled
input and, on encountering a `${jndi:ldap://HOST:PORT/...}` token, performs the
JNDI *resolution* step -- a single outbound TCP connect to HOST:PORT. That
outbound connect is the exact observable that a Log4Shell callback produces.

What it deliberately does NOT do: fetch, deserialize, or execute anything the
listener might return. The connection is opened and immediately closed.

A benign request (no jndi token) must produce NO outbound connection, which is
what lets the runner show the callback is caused by the injection and nothing else.
"""
from __future__ import annotations

import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("VICTIM_PORT", "8080"))
# Only an in-lab, private, explicitly allow-listed callback host may ever be
# contacted. This prevents the substitute from being pointed at anything off-lab.
ALLOWED_CALLBACK_HOST = os.environ.get("ALLOWED_CALLBACK_HOST", "listener")

_JNDI = re.compile(r"\$\{jndi:ldap://([A-Za-z0-9_.-]+):(\d{1,5})(?:/[^}]*)?\}")


def _simulate_lookup(host: str, port: int) -> str:
    if host != ALLOWED_CALLBACK_HOST:
        return f"refused-offlab-host:{host}"
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            # Send a short marker only; read nothing back, execute nothing.
            sock.sendall(b"jndi-resolve\n")
        return f"lookup-performed:{host}:{port}"
    except OSError as exc:
        return f"lookup-failed:{type(exc).__name__}"


class Handler(BaseHTTPRequestHandler):
    def _respond(self, logged_value: str) -> None:
        outcome = "no-jndi"
        match = _JNDI.search(logged_value)
        if match:
            outcome = _simulate_lookup(match.group(1), int(match.group(2)))
        body = f"logged={logged_value!r} outcome={outcome}".encode("utf-8", "replace")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # The "log statement" interpolates a user-controlled header, exactly like a
        # web app logging a request's User-Agent through a vulnerable logger.
        self._respond(self.headers.get("X-Api-Version", ""))

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    print(f"victim-ready port={PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
