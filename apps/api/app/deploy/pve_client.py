"""Restricted Proxmox VE API transport and request guard for the runtime backend."""
from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Mapping

PROTECTED_VMIDS = frozenset({501, 2001, 2002, 3001, 3002, 3003, 3004, 80000, 80001})
VMID_MIN, VMID_MAX = 900000, 900999
APPROVED_FINGERPRINT = "4dbfcdb1eb96af751c42d3c14e5a128a582fcff3e40b7149585fcc52619e05b7"
TEMPLATE_IDS = frozenset({900000})
_SECRET_KEYS = re.compile(r"(?i)(token|password|secret|authorization|ticket|private.?key)")
_SECRET_TEXT = re.compile(r"(?i)(PVEAPIToken=[^:=\s]+:[^:=\s]+=[^\s,;]+|Authorization\s*[:=]\s*[^\s,;]+|(?:password|secret|token)\s*[:=]\s*[^\s,;]+)")
PVE_ORIGIN = ("192.168.16.214", 8006)
_UPID_RE = re.compile(
    r"^UPID:(?P<node>[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?):"
    r"(?P<pid>[0-9A-Fa-f]{8}):(?P<pstart>[0-9A-Fa-f]{8,9}):"
    r"(?P<starttime>[0-9A-Fa-f]{8}):(?P<task>[A-Za-z0-9_-]+):"
    r"(?P<id>[A-Za-z0-9_.-]*):"
    r"(?P<user>[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+(?:![A-Za-z0-9_.-]+)?):$"
)


class PveError(RuntimeError):
    pass


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): ("[REDACTED]" if _SECRET_KEYS.search(str(key)) else redact(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[REDACTED]", value)[:8000]
    return value


def _request_summary(method: str, path: str, params: Mapping[str, Any],
                     data: Mapping[str, Any], purpose: str) -> dict[str, Any]:
    """Journal request intent without retaining commands, Compose, or secret values."""
    import hashlib

    summary: dict[str, Any] = {"method": method, "path": path, "purpose": str(redact(purpose))[:200]}
    if params:
        summary["params"] = redact({key: value for key, value in params.items()
                                     if key.lower() not in {"upid", "pid"}})
    safe: dict[str, Any] = {}
    payload_hash = hashlib.sha256()
    payload_bytes = 0
    for key, value in data.items():
        if key in {"content", "command", "input-data"}:
            if key == "content" or key == "input-data":
                encoded = str(value).encode("utf-8")
            elif isinstance(value, (list, tuple)):
                encoded = b"\0".join(str(part).encode("utf-8") for part in value)
            else:
                encoded = str(value).encode("utf-8")
            payload_hash.update(key.encode("utf-8") + b"\0" + encoded)
            payload_bytes += len(encoded)
        else:
            safe[key] = redact(value)
    if payload_bytes:
        summary["payload"] = {"sha256": payload_hash.hexdigest(), "byte_length": payload_bytes}
    if safe:
        summary["metadata"] = safe
    return summary


@dataclass
class PveSettings:
    base_url: str
    fingerprint: str
    token_id: str
    token_secret: str = field(repr=False)
    mode: str = "probe"
    live_enabled: bool = False
    node: str = "pve4-bbf"
    pool: str = "cr-range"
    datastore: str = "local-lvm"
    bridge: str = "vmbr990"
    template_vmid: int = 900000
    request_timeout: float = 15.0
    task_timeout: float = 240.0
    task_poll_interval: float = 1.0
    max_task_polls: int = 240
    max_response_bytes: int = 4_000_000
    reserved_memory_mib: int = 3072
    pool_memory_mib: int = 16384
    datastore_reserve_gib: int = 40
    reservation_db: str = ""
    reservation_db_explicit: bool = False

    @classmethod
    def from_env(cls) -> "PveSettings":
        """Explicit opt-in configuration. Credentials are read only when this is called."""
        return cls(
            base_url=os.getenv("CR_PVE_URL", ""), fingerprint=os.getenv("CR_PVE_FINGERPRINT", APPROVED_FINGERPRINT),
            token_id=os.getenv("CR_PVE_TOKEN_ID", ""), token_secret=os.getenv("CR_PVE_TOKEN_SECRET", ""),
            mode=os.getenv("CR_PVE_MODE", "probe"), live_enabled=os.getenv("CR_PVE_LIVE_ENABLED", "").lower() == "true",
            node=os.getenv("CR_PVE_NODE", "pve4-bbf"), pool=os.getenv("CR_PVE_POOL", "cr-range"),
            datastore=os.getenv("CR_PVE_STORAGE", os.getenv("CR_PVE_DATASTORE", "local-lvm")), bridge=os.getenv("CR_PVE_BRIDGE", "vmbr990"),
            template_vmid=int(os.getenv("CR_PVE_TEMPLATE_VMID", "900000")),
            request_timeout=float(os.getenv("CR_PVE_REQUEST_TIMEOUT", "15")),
            task_timeout=float(os.getenv("CR_PVE_TASK_TIMEOUT", "240")),
            task_poll_interval=float(os.getenv("CR_PVE_TASK_POLL_INTERVAL", "1")),
            max_task_polls=int(os.getenv("CR_PVE_MAX_TASK_POLLS", "240")),
            max_response_bytes=int(os.getenv("CR_PVE_MAX_RESPONSE_BYTES", "4000000")),
            reserved_memory_mib=int(os.getenv("CR_PVE_RESERVED_MEMORY_MIB", "3072")),
            pool_memory_mib=int(os.getenv("CR_PVE_POOL_MEMORY_MIB", "16384")),
            datastore_reserve_gib=int(os.getenv("CR_PVE_DATASTORE_RESERVE_GIB", "40")),
            reservation_db=os.getenv("CR_PVE_RESERVATION_DB", os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "data", "pve-reservations.sqlite3"))),
            reservation_db_explicit=bool(os.getenv("CR_PVE_RESERVATION_DB")),
        )

    def validate(self) -> None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
            raise PveError("PVE URL must be an HTTPS origin without embedded credentials or path")
        if (parsed.hostname, parsed.port or 443) != PVE_ORIGIN:
            raise PveError("PVE origin must match the approved 192.168.16.214:8006 endpoint")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.fingerprint.replace(":", "")):
            raise PveError("PVE SHA-256 TLS fingerprint is missing or invalid")
        if not self.token_id or not self.token_secret:
            raise PveError("PVE API token is not configured")
        if self.mode not in {"probe", "dry-run", "live"}:
            raise PveError("CR_PVE_MODE must be probe, dry-run, or live")
        if self.mode == "live" and not self.live_enabled:
            raise PveError("live mode requires CR_PVE_LIVE_ENABLED=true")
        if self.mode == "live":
            if not self.reservation_db_explicit or not self.reservation_db.strip():
                raise PveError("live mode requires a non-empty CR_PVE_RESERVATION_DB setting")
            if not os.path.isabs(self.reservation_db):
                raise PveError("CR_PVE_RESERVATION_DB must be an absolute shared path for all API workers")
        if self.node != "pve4-bbf" or self.pool != "cr-range" or self.datastore != "local-lvm" or self.bridge != "vmbr990":
            raise PveError("runtime PVE node, pool, datastore, and isolated bridge are fixed by approved design")
        if self.template_vmid not in TEMPLATE_IDS:
            raise PveError("only the product Linux template 900000 may be used")
        if min(self.request_timeout, self.task_timeout, self.task_poll_interval) <= 0 or self.max_task_polls < 1:
            raise PveError("timeouts and task polling limits must be positive")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Verify the server certificate pin in connect(), before request bytes are sent."""

    def __init__(self, host: str, *, port: int, context: ssl.SSLContext, fingerprint: str, timeout: float):
        super().__init__(host, port=port, context=context, timeout=timeout)
        self._fingerprint = fingerprint.replace(":", "").lower()

    def connect(self) -> None:
        super().connect()
        import hashlib
        import hmac
        certificate = self.sock.getpeercert(binary_form=True)
        actual = hashlib.sha256(certificate).hexdigest()
        if not hmac.compare_digest(actual, self._fingerprint):
            self.close()
            raise ssl.SSLError("PVE TLS fingerprint mismatch")


class PveClient:
    """HTTPS API client whose allowlist is the final gate before transport."""

    def __init__(self, settings: PveSettings):
        settings.validate()
        self.settings = settings
        self.records: list[dict[str, Any]] = []
        # PVE may use a self-signed certificate. The exact SHA-256 pin is checked in
        # HTTPSConnection.connect before any HTTP headers (including Authorization) are sent.
        self._context = ssl._create_unverified_context()

    def _guard(self, method: str, path: str, params: Mapping[str, Any], data: Mapping[str, Any]) -> None:
        if not path.startswith("/api2/json/") or ".." in path or "//" in path:
            raise PveError("invalid API path")
        if method == "GET":
            if path == "/api2/json/cluster/nextid":
                if set(params) != {"vmid"} or not _worker_vmid(params.get("vmid")):
                    raise PveError("nextid lookup requires a worker-range vmid")
                return
            if re.fullmatch(r"/api2/json/nodes/pve4-bbf/qemu/900[1-9]\d{2}/agent/exec-status", path):
                if set(params) != {"pid"} or not str(params.get("pid", "")).isdigit():
                    raise PveError("QGA exec-status requires a numeric pid")
                return
            if path not in {
                "/api2/json/version", "/api2/json/nodes", "/api2/json/pools/cr-range",
                "/api2/json/nodes/pve4-bbf/status", "/api2/json/nodes/pve4-bbf/storage/local-lvm/status",
                "/api2/json/nodes/pve4-bbf/network",
                "/api2/json/nodes/pve4-bbf/qemu/900000/config",
                "/api2/json/nodes/pve4-bbf/qemu/900000/status/current",
                "/api2/json/cluster/nextid",
                "/api2/json/nodes/pve4-bbf/tasks/_TASK_/status",
            } and not re.fullmatch(r"/api2/json/cluster/nextid", path):
                if not (path in {"/api2/json/nodes/pve4-bbf/qemu/900000/config",
                                 "/api2/json/nodes/pve4-bbf/qemu/900000/status/current"}
                        or re.fullmatch(r"/api2/json/nodes/pve4-bbf/qemu/900[1-9]\d{2}/(?:config|status/current|agent/exec-status|snapshot(?:/deployed/config)?)", path)
                        or re.fullmatch(r"/api2/json/nodes/pve4-bbf/tasks/[^/]+/status", path)):
                    raise PveError("GET endpoint is not allowlisted")
            if params:
                raise PveError("query parameters are not allowed on this endpoint")
            return
        if params:
            raise PveError("query parameters are not allowed for writes")
        if method not in {"POST", "PUT", "DELETE"}:
            raise PveError("HTTP method is not allowlisted")
        if self.settings.mode == "probe":
            raise PveError("writes are disabled in probe mode")
        if method == "POST" and re.fullmatch(r"/api2/json/nodes/pve4-bbf/qemu/900000/clone", path):
            if set(data) - {"newid", "name", "pool", "full"}:
                raise PveError("clone parameters are not allowlisted")
            source = 900000
            target = data.get("newid")
            if source in PROTECTED_VMIDS or not _worker_vmid(target) or int(target) in PROTECTED_VMIDS:
                raise PveError("clone source/target VMID is outside the product policy")
            if data.get("pool") != "cr-range" or str(data.get("full")) != "0":
                raise PveError("clone must be linked and remain in cr-range")
            if not re.fullmatch(r"cr-pending-[a-z0-9_-]{1,52}", str(data.get("name", ""))):
                raise PveError("clone name must be a unique validated provisional name")
            return
        vm_match = re.fullmatch(r"/api2/json/nodes/pve4-bbf/qemu/(\d{1,9})(?:/(.*))?", path)
        if not vm_match:
            raise PveError("write path is not allowlisted")
        vmid, suffix = int(vm_match.group(1)), vm_match.group(2) or ""
        if vmid in PROTECTED_VMIDS or not _worker_vmid(vmid):
            raise PveError("write VMID is protected or outside the worker range")
        if method == "DELETE" and not suffix:
            delete_proof = getattr(self, "_delete_proof", None)
            owned_proof = (isinstance(delete_proof, tuple) and len(delete_proof) == 2
                           and delete_proof[0] == vmid
                           and isinstance(delete_proof[1], str)
                           and re.fullmatch(r"[a-f0-9]{12}", delete_proof[1]))
            if not owned_proof:
                raise PveError("VM deletion requires fresh client-side ownership proof")
        if suffix == "config" and getattr(self, "_config_proof", None) != vmid:
            raise PveError("worker configuration requires fresh provisional-clone ownership proof")
        if suffix in {"status/start", "status/shutdown", "agent/exec", "agent/file-write", "snapshot", "snapshot/deployed/rollback"} and getattr(self, "_owner_proof", None) != vmid:
            raise PveError("worker write requires fresh pool/tag/description ownership proof")
        if data.get("pool", "cr-range") != "cr-range":
            raise PveError("write may not leave the approved resource pool")
        allowed = (
            (method in {"PUT", "POST"} and suffix == "config") or
            (method == "POST" and suffix in {"status/start", "status/shutdown", "agent/exec", "agent/file-write"}) or
            (method == "POST" and suffix == "snapshot") or
            (method == "POST" and suffix == "snapshot/deployed/rollback" and not data) or
            (method == "DELETE" and suffix == "")
        )
        if not allowed:
            raise PveError("write path is not in the strict PVE allowlist")
        allowed_fields = {
            "config": {"name", "cores", "memory", "tags", "description"},
            "status/start": set(), "status/shutdown": set(),
            "agent/exec": {"command", "input-data"},
            "agent/file-write": {"file", "content"},
            "snapshot": {"snapname", "description"}, "snapshot/deployed/rollback": set(),
        }
        if suffix in allowed_fields and set(data) - allowed_fields[suffix]:
            raise PveError("write parameters are not allowlisted")
        if suffix == "config":
            metadata = _parse_description(data.get("description", ""))
            scenario_id = metadata.get("scenario_id")
            if (not isinstance(scenario_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", scenario_id)
                    or data.get("name") != f"cr-{scenario_id[:20].replace('_', '-')}-worker"):
                raise PveError("worker configuration requires a validated scenario name")
            if data.get("cores", 2) != 2 or data.get("memory", 4096) != 4096:
                raise PveError("worker CPU and memory must match approved limits")
            if "tags" in data and not set(str(data["tags"]).split(";")) >= {"cyberrange", "cr-role-worker"}:
                raise PveError("worker ownership tags are incomplete")
            tags = set(str(data.get("tags", "")).split(";"))
            if (metadata.get("created_by") != "cyberrange" or metadata.get("role") != "worker"
                    or metadata.get("template") != 900000 or not metadata.get("scenario_id")
                    or not metadata.get("host_id") or not re.fullmatch(r"[a-f0-9]{12}", str(metadata.get("creation_nonce", "")))
                    or f"cr-scn-{scenario_id[:20].replace('_', '-')}" not in tags
                    or not any(tag.startswith("cr-inst-") for tag in tags)):
                raise PveError("worker ownership description is incomplete")
        if suffix == "agent/file-write":
            allowed_guest_files = {
                "/opt/cr-runtime/docker-compose.yml",
                "/opt/cr-runtime/compose.env",
                "/opt/cr-runtime/demo-app/Dockerfile",
                "/opt/cr-runtime/demo-app/server.py",
                "/opt/cr-runtime/probe-supervisor.sh",
            }
            if (data.get("file") not in allowed_guest_files
                    or not isinstance(data.get("content"), str)
                    or len(data["content"]) > 61440):
                raise PveError("guest file-write path or content exceeds the strict allowlist/bound")
        for key in ("vmid", "newid"):
            if key in data and (not _worker_vmid(data[key]) or int(data[key]) in PROTECTED_VMIDS):
                raise PveError(f"{key} is outside the product worker VMID range")

    def request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None,
                data: Mapping[str, Any] | None = None, purpose: str = "") -> Any:
        method = method.upper(); params = dict(params or {}); data = dict(data or {})
        self._guard(method, path, params, data)
        record = _request_summary(method, path, params, data, purpose)
        self.records.append(record)
        if method != "GET" and self.settings.mode == "dry-run":
            record["result"] = {"dry_run": True, "sequence": len(self.records)}
            return record["result"]
        url = self.settings.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data, doseq=True).encode() if data else None
        headers = {"Accept": "application/json", "Authorization": f"PVEAPIToken={self.settings.token_id}={self.settings.token_secret}"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        parsed = urllib.parse.urlsplit(url)
        request_target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        connection = _PinnedHTTPSConnection(parsed.hostname or "", port=parsed.port or 443,
                                             context=self._context, fingerprint=self.settings.fingerprint,
                                             timeout=min(self.settings.request_timeout, 30))
        try:
            connection.request(method, request_target, body=body, headers=headers)
            response = connection.getresponse()
            record["http_status"] = response.status
            payload = response.read(self.settings.max_response_bytes + 1)
            if len(payload) > self.settings.max_response_bytes:
                raise PveError("PVE response exceeded size limit")
            if response.status < 200 or response.status >= 300:
                safe = redact(payload[:2048].decode("utf-8", "replace"))
                record["error"] = f"HTTP {response.status}: {safe}"
                raise PveError(record["error"])
            result = json.loads(payload.decode("utf-8"))
        except PveError:
            raise
        except (http.client.HTTPException, TimeoutError, OSError, ValueError) as exc:
            detail = redact(str(exc))
            record["error"] = str(detail)[:500]
            raise PveError(f"PVE request failed: {record['error']}") from None
        finally:
            connection.close()
        record["result"] = _response_summary(method, path, result)
        return result

    def delete_owned_vmid(self, vmid: int, *, scenario_id: str, host_id: str,
                          backend_instance: str, creation_nonce: str) -> Any:
        """Fresh pool, range, tag, and description proof immediately before delete."""
        if not _worker_vmid(vmid):
            raise PveError("delete VMID is outside the worker range")
        if not isinstance(creation_nonce, str) or not re.fullmatch(r"[a-f0-9]{12}", creation_nonce):
            raise PveError("delete requires the expected 12-character creation nonce")
        pool = self.request("GET", "/api2/json/pools/cr-range")
        members = _response_data(pool).get("members", [])
        if vmid not in _pool_vmids(members):
            raise PveError("delete refused: VM is not a cr-range member")
        config = _response_data(self.request("GET", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/config"))
        tags = set(filter(None, str(config.get("tags", "")).split(";")))
        description = _parse_description(config.get("description", ""))
        if not {"cyberrange", f"cr-scn-{scenario_id[:20].replace('_', '-')}", "cr-role-worker",
                f"cr-inst-{backend_instance}"}.issubset(tags):
            raise PveError("delete refused: worker ownership tags do not match")
        if (description.get("created_by") != "cyberrange" or description.get("scenario_id") != scenario_id
                or description.get("host_id") != host_id or description.get("role") != "worker"
                or description.get("template") != 900000
                or description.get("backend_instance") != backend_instance
                or description.get("creation_nonce") != creation_nonce):
            raise PveError("delete refused: worker ownership description does not match")
        self._delete_proof = (vmid, creation_nonce)
        try:
            return self.request("DELETE", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}", purpose="delete freshly verified owned worker")
        finally:
            self._delete_proof = None

    def request_owned(self, method: str, path: str, *, scenario_id: str, host_id: str,
                      backend_instance: str, data: Mapping[str, Any] | None = None,
                      purpose: str = "") -> Any:
        """Send an allowlisted worker write only after live ownership revalidation."""
        match = re.fullmatch(r"/api2/json/nodes/pve4-bbf/qemu/(900[1-9]\d{2})/(?:status/(?:start|shutdown)|agent/(?:exec|file-write)|snapshot|snapshot/deployed/rollback)", path)
        if not match:
            raise PveError("owned write path is not allowlisted")
        vmid = int(match.group(1))
        self._verify_owned_vmid(vmid, scenario_id, host_id, backend_instance)
        self._owner_proof = vmid
        try:
            return self.request(method, path, data=data, purpose=purpose)
        finally:
            self._owner_proof = None

    def configure_creating_clone(self, vmid: int, *, pending_name: str,
                                 source_metadata: Mapping[str, Any], creation_nonce: str,
                                 data: Mapping[str, Any]) -> Any:
        """Configure only the exact freshly cloned provisional VM."""
        if self.settings.mode == "live":
            self._verify_provisional_clone(vmid, pending_name, source_metadata,
                                           creation_nonce=creation_nonce, absent_ok=False)
        elif not _worker_vmid(vmid) or not re.fullmatch(r"cr-pending-[a-z0-9_-]{1,52}", pending_name):
            raise PveError("provisional clone identity is invalid")
        self._config_proof = vmid
        try:
            return self.request("PUT", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/config",
                                data=data, purpose="configure verified provisional worker")
        finally:
            self._config_proof = None

    def delete_creating_clone(self, vmid: int, *, pending_name: str,
                              source_metadata: Mapping[str, Any], creation_nonce: str) -> Any:
        """Clean only the exact provisional clone whose inherited template metadata matches."""
        if not self._verify_provisional_clone(vmid, pending_name, source_metadata,
                                              creation_nonce=creation_nonce, absent_ok=True):
            return {"absent": True, "deleted": False}
        self._delete_proof = (vmid, creation_nonce)
        try:
            return self.request("DELETE", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}", purpose="cleanup exact provisional clone")
        finally:
            self._delete_proof = None

    def _verify_provisional_clone(self, vmid: int, pending_name: str,
                                  source_metadata: Mapping[str, Any], *, creation_nonce: str,
                                  absent_ok: bool) -> bool:
        pending_match = (re.fullmatch(r"cr-pending-[a-z0-9_-]{1,52}-([a-f0-9]{12})", pending_name)
                         if isinstance(pending_name, str) else None)
        if (not _worker_vmid(vmid) or not pending_match
                or not isinstance(creation_nonce, str)
                or not re.fullmatch(r"[a-f0-9]{12}", creation_nonce)
                or pending_match.group(1) != creation_nonce):
            raise PveError("provisional clone identity is invalid")
        pool = self.request("GET", "/api2/json/pools/cr-range")
        if vmid not in _pool_vmids(_response_data(pool).get("members", [])):
            if absent_ok:
                return False
            raise PveError("provisional clone is not a cr-range member")
        config = _response_data(self.request("GET", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/config"))
        inherited = _parse_description(config.get("description", ""))
        if config.get("name") != pending_name:
            raise PveError("provisional clone name changed; refusing operation")
        for key in ("source_sha256", "source_commit", "host_id"):
            if not source_metadata.get(key) or inherited.get(key) != source_metadata.get(key):
                raise PveError("provisional clone template source metadata does not match")
        return True

    def _verify_owned_vmid(self, vmid: int, scenario_id: str, host_id: str,
                           backend_instance: str) -> None:
        if not _worker_vmid(vmid):
            raise PveError("worker VMID is outside the product range")
        pool = self.request("GET", "/api2/json/pools/cr-range")
        if vmid not in _pool_vmids(_response_data(pool).get("members", [])):
            raise PveError("worker is not a member of cr-range")
        config = _response_data(self.request("GET", f"/api2/json/nodes/pve4-bbf/qemu/{vmid}/config"))
        tags = set(filter(None, str(config.get("tags", "")).split(";")))
        description = _parse_description(config.get("description", ""))
        if not {"cyberrange", f"cr-scn-{scenario_id[:20].replace('_', '-')}", "cr-role-worker",
                f"cr-inst-{backend_instance}"}.issubset(tags):
            raise PveError("worker ownership tags do not match")
        if (description.get("created_by") != "cyberrange" or description.get("scenario_id") != scenario_id
                or description.get("host_id") != host_id or description.get("role") != "worker"
                or description.get("template") != 900000
                or description.get("backend_instance") != backend_instance):
            raise PveError("worker ownership description does not match")

    def wait_task(self, upid: str) -> dict[str, Any]:
        match = _UPID_RE.fullmatch(upid) if isinstance(upid, str) else None
        if not match or match.group("node") != self.settings.node:
            raise PveError("invalid PVE task identifier")
        task_segment = urllib.parse.quote(upid, safe="")
        task_path = f"/api2/json/nodes/{self.settings.node}/tasks/{task_segment}/status"
        deadline = time.monotonic() + self.settings.task_timeout
        for attempt in range(self.settings.max_task_polls):
            result = self.request("GET", task_path, purpose="poll task")
            data = result.get("data", {})
            if data.get("status") == "stopped":
                if data.get("exitstatus", "OK") != "OK":
                    raise PveError("PVE asynchronous task failed")
                return result
            if attempt + 1 >= self.settings.max_task_polls or time.monotonic() >= deadline:
                break
            time.sleep(min(self.settings.task_poll_interval, max(0.0, deadline - time.monotonic())))
        raise PveError("PVE asynchronous task exceeded configured bounds")

    def wait_task_exact(self, upid: str, *, task: str, task_id: str) -> dict[str, Any]:
        """Wait only for one exact PVE task and require an explicit successful terminal result."""
        match = _UPID_RE.fullmatch(upid) if isinstance(upid, str) else None
        if (not match or match.group("node") != self.settings.node
                or match.group("task") != task or match.group("id") != task_id):
            raise PveError("PVE task UPID does not match the expected node, operation, and VMID")
        task_segment = urllib.parse.quote(upid, safe="")
        task_path = f"/api2/json/nodes/{self.settings.node}/tasks/{task_segment}/status"
        deadline = time.monotonic() + self.settings.task_timeout
        for attempt in range(self.settings.max_task_polls):
            result = self.request("GET", task_path, purpose="verify exact destructive task completion")
            data = _response_data(result)
            if not isinstance(data, Mapping):
                raise PveError("PVE task response is not an object")
            status = data.get("status")
            if status == "stopped":
                if data.get("exitstatus") != "OK":
                    raise PveError("PVE destructive task lacks an explicit successful terminal status")
                return result
            if status != "running":
                raise PveError("PVE destructive task status is unknown")
            if attempt + 1 >= self.settings.max_task_polls or time.monotonic() >= deadline:
                break
            time.sleep(min(self.settings.task_poll_interval, max(0.0, deadline - time.monotonic())))
        raise PveError("PVE asynchronous task exceeded configured bounds")

    def task_status(self, upid: str) -> dict[str, str | None]:
        """Read one exact task status for crash recovery; never infer a missing task succeeded."""
        match = _UPID_RE.fullmatch(upid) if isinstance(upid, str) else None
        if not match or match.group("node") != self.settings.node:
            raise PveError("invalid PVE task identifier")
        task_segment = urllib.parse.quote(upid, safe="")
        task_path = f"/api2/json/nodes/{self.settings.node}/tasks/{task_segment}/status"
        result = self.request("GET", task_path, purpose="verify persisted clone task before recovery")
        data = _response_data(result)
        if not isinstance(data, Mapping) or data.get("status") not in {"running", "stopped"}:
            raise PveError("PVE clone task status is unknown")
        status = str(data["status"])
        exitstatus = data.get("exitstatus")
        if status == "stopped" and not isinstance(exitstatus, str):
            raise PveError("stopped PVE clone task has no terminal exit status")
        return {"status": status, "exitstatus": exitstatus if isinstance(exitstatus, str) else None,
                "task": match.group("task"), "id": match.group("id"), "node": match.group("node")}


def _worker_vmid(value: Any) -> bool:
    try:
        number = int(value)
        return not isinstance(value, bool) and str(value) == str(number) and 900100 <= number <= VMID_MAX
    except (TypeError, ValueError):
        return False


def _response_summary(method: str, path: str, result: Any) -> Any:
    if method == "GET" and re.fullmatch(
            r"/api2/json/nodes/pve4-bbf/qemu/900[1-9]\d{2}/agent/exec-status", path):
        payload = result.get("data", {}) if isinstance(result, Mapping) else {}
        summary: dict[str, Any] = {}
        for name in ("exited", "exitcode", "signal", "out-truncated", "err-truncated"):
            if name in payload:
                summary[name] = payload[name]
        for name in ("out-data", "err-data"):
            value = str(payload.get(name, "") or "")
            encoded = value.encode("utf-8")
            summary[name] = {"byte_length": len(encoded), "sha256": __import__("hashlib").sha256(encoded).hexdigest()}
        return summary
    return redact(result)


def _response_data(result: Any) -> Any:
    return result.get("data", result) if isinstance(result, Mapping) else result


def _pool_vmids(members: Any) -> set[int]:
    vmids: set[int] = set()
    if not isinstance(members, list):
        return vmids
    for item in members:
        value = item.get("vmid") if isinstance(item, Mapping) else item
        try:
            vmids.add(int(value))
        except (TypeError, ValueError):
            continue
    return vmids


def _parse_description(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or len(value) > 4096:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}
