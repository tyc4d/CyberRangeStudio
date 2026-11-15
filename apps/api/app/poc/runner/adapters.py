"""Adapters for the execution methods in the PoC contract.

Adapters produce commands for the pinned sandbox image only.  They never execute on
the API host.  Network-only HTTP sequences are the only built-in adapter; arbitrary
third-party code must be supplied as a locally vendored, SHA-pinned payload.
"""
from __future__ import annotations

from typing import Protocol

from .models import AdapterInput, AdapterOutput


class Adapter(Protocol):
    method: str

    def prepare(self, request: AdapterInput) -> AdapterOutput: ...


class PythonAdapter:
    method = "python"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("python", request.payload)


class BashAdapter:
    method = "bash"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("bash", request.payload, blocked_reason="bash payloads require a pinned sandbox image with bash")


class GoAdapter:
    method = "go"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("go", request.payload, blocked_reason="Go payloads require a prebuilt, SHA-pinned executable")


class MetasploitAdapter:
    method = "metasploit"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("metasploit", request.payload, blocked_reason="Metasploit is not present in the pinned sandbox image")


class HttpSequenceAdapter:
    method = "http_seq"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("python", request.payload)


class ManualAdapter:
    method = "manual"

    def prepare(self, request: AdapterInput) -> AdapterOutput:
        return AdapterOutput("manual", "", blocked_reason="manual PoCs require a documented operator procedure")


ADAPTERS: dict[str, Adapter] = {
    adapter.method: adapter for adapter in (
        PythonAdapter(), BashAdapter(), GoAdapter(), MetasploitAdapter(),
        HttpSequenceAdapter(), ManualAdapter(),
    )
}


def get_adapter(method: str) -> Adapter | None:
    return ADAPTERS.get(method)
