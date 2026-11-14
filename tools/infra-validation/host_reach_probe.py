"""Runs INSIDE a lab container: try to reach the Docker host on every address it has.

Arguments: <port> <host-ipv4,...> <host-ipv6-link-local,...>
Prints one line per attempt and exits 1 if any attempt connected. Used by the real
isolation test: a lab container must not be able to open a TCP connection to a service
that the host binds on all interfaces (e.g. sshd on :22).
"""
import os
import socket
import sys

port = int(sys.argv[1])
v4 = [a for a in sys.argv[2].split(",") if a]
v6 = [a for a in sys.argv[3].split(",") if a] if len(sys.argv) > 3 else []
interfaces = [name for name in os.listdir("/sys/class/net") if name != "lo"]
reached = False


def attempt(label, family, sockaddr):
    global reached
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect(sockaddr)
        banner = b""
        try:
            banner = sock.recv(40)
        except OSError:
            pass
        reached = True
        print(f"REACHED {label} banner={banner[:20]!r}")
    except OSError as exc:
        print(f"blocked {label} ({type(exc).__name__}: {exc})")
    finally:
        sock.close()


own = set()
try:
    own = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
except OSError:
    pass
for address in v4:
    if address in own:
        print(f"skipped {address}:{port} (this is the container's own address)")
        continue
    attempt(f"{address}:{port}", socket.AF_INET, (address, port))
for address in v6:
    for name in interfaces:
        scope = socket.if_nametoindex(name)
        attempt(f"[{address}%{name}]:{port}", socket.AF_INET6, (address, port, 0, scope))
print("RESULT", "HOST_REACHABLE" if reached else "HOST_UNREACHABLE")
sys.exit(1 if reached else 0)
