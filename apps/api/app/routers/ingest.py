"""CTI analysis and user supplementation endpoints (modules 1 and 2)."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from cr_contracts import iter_errors
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import store
from app.cti.analysis import AnalysisError, analyze_source
from app.cti.missing import refresh_missing_items
from app.cti.parser import SourceParseError, parse_source

# Upload cap for the extract endpoint. Big enough for a long advisory PDF, small
# enough that a stray upload cannot exhaust memory.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class AnalyzeRequest(BaseModel):
    input_kind: Literal["text", "markdown", "stix2.1"]
    content: str
    method: Literal["single_pass", "staged", "staged_review"] = "single_pass"
    name: str | None = None
    # Token from /extract for an uploaded PDF; binds the original file to the new scenario.
    upload_token: str | None = None


class SupplementRequest(BaseModel):
    text: str = Field(min_length=1)
    # Target is optional: a supplement may resolve a specific missing item or be a free-form note.
    # Accept both field names the frontend may send.
    missing_item_id: str | None = None
    targets_missing_item: str | None = None
    # Allowed resolution statuses when a target is given.
    status: str | None = None
    host_id: str | None = None
    service_id: str | None = None
    field: str | None = None
    value: str | int | None = None

    def target_id(self) -> str | None:
        return self.missing_item_id or self.targets_missing_item


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        units, parsed_source = parse_source(request.input_kind, request.content)
    except SourceParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    scenario_name = (request.name or "").strip() or "Untitled scenario"
    try:
        ir = analyze_source(
            input_kind=request.input_kind,
            content=request.content,
            source_name=request.name,
            units=units,
            parsed_source=parsed_source,
            method=request.method,
            name=scenario_name,
        )
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        # Preserve the LLM/budget exception so a caller can retry or diagnose it.
        raise HTTPException(status_code=502, detail=f"CTI analysis failed: {type(exc).__name__}: {exc}") from exc

    ir["id"] = store.new_id()
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=502, detail={"message": "Generated Scenario IR failed contract validation.", "errors": errors})
    saved = store.create(ir)
    saved_errors = iter_errors("scenario-ir", saved)
    if saved_errors:
        raise HTTPException(status_code=500, detail={"message": "Stored Scenario IR failed contract validation.", "errors": saved_errors})
    # Keep the original report verbatim so the Import page can show it back for review.
    store.set_source(saved["id"], request.input_kind, request.content, request.name)
    if request.upload_token:
        # Best effort: the analysis already succeeded, so a missing/expired upload
        # only means the scenario has no PDF to view.
        try:
            pending = store.pop_pending_file(request.upload_token)
            if pending is not None:
                store.set_source_file(saved["id"], pending["filename"], pending["content_type"], pending["data"])
        except Exception:
            pass
    return saved


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from a PDF with poppler's pdftotext. Never executes the file."""
    if shutil.which("pdftotext") is None:
        raise HTTPException(status_code=501, detail="伺服器未安裝 pdftotext（poppler-utils），無法解析 PDF。請改貼上文字或上傳 .txt/.md。")
    with tempfile.TemporaryDirectory(prefix="cr-extract-") as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", str(src), "-"],
                capture_output=True, timeout=60, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=502, detail="PDF 解析逾時。") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace")[:300] or "pdftotext 解析失敗。"
        raise HTTPException(status_code=422, detail=f"無法解析這個 PDF：{detail}")
    return proc.stdout.decode("utf-8", "replace")


@router.post("/extract")
async def extract(file: UploadFile = File(...)):
    """Extract readable text from an uploaded file (PDF via pdftotext; text/XML as-is).

    Returns the text for review on the Import page; it does NOT analyze anything.
    The caller reviews/edits the text, then submits it through POST /analyze as usual.
    For a PDF the original bytes are held as a pending upload and an `upload_token` is
    returned; passing it to /analyze binds the PDF to the scenario for the viewer.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="檔案是空的。")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"檔案超過 {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限。")

    name = (file.filename or "upload").rsplit("/", 1)[-1]
    lower = name.lower()
    is_pdf = lower.endswith(".pdf") or data[:5] == b"%PDF-"
    if is_pdf:
        content = _extract_pdf_text(data)
        input_kind = "text"
    else:
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="這個檔案不是 PDF，也不是 UTF-8 文字，無法解析。") from exc
        input_kind = "stix2.1" if lower.endswith(".json") else "markdown" if lower.endswith((".md", ".markdown")) else "text"

    if not content.strip():
        raise HTTPException(status_code=422, detail="解析後沒有取得任何文字（PDF 可能是掃描影像，沒有文字層）。")
    result = {
        "input_kind": input_kind,
        "content": content,
        "source_name": name.rsplit(".", 1)[0],
        "filename": name,
        "chars": len(content),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if is_pdf:
        # Keeping the original is best effort; text extraction already succeeded.
        try:
            token = uuid.uuid4().hex
            store.set_pending_file(token, name, "application/pdf", data)
            result["upload_token"] = token
        except Exception:
            pass
    return result


_HOST_FIELDS = {"name", "role", "os", "os_version", "network_placement"}
_SERVICE_FIELDS = {"name", "version", "port", "os", "os_version", "configuration"}
# An answer that the lab will not run this service at all.
_NOT_ENABLED_RE = re.compile(
    r"不啟用|不要啟用|不部署|不開啟|停用|關閉|不重現|未重現|"
    r"\b(?:do\s+not|don'?t|will\s+not|won'?t|not)\s+(?:enable|deploy|run|start|reproduce)\b|\bdisabled?\b", re.IGNORECASE)
# A free-text answer longer than this is an explanation, not a field value.
_MAX_FIELD_VALUE_CHARS = 120
# Statements of not knowing, and hedged guesses. Neither is a value to build a lab from.
_UNKNOWN_ANSWER_RE = re.compile(
    r"不確定|不知道|不清楚|不曉得|未知|無法確認|無從得知|沒有資料|待確認|待查|"
    r"\b(?:unknown|not\s+sure|unsure|no\s+idea|don'?t\s+know|do\s+not\s+know|not\s+known|n/?a|tbd|tbc|unclear|"
    r"cannot\s+(?:confirm|tell)|can'?t\s+(?:confirm|tell))\b", re.IGNORECASE)
_NON_ANSWER_RE = re.compile(
    _UNKNOWN_ANSWER_RE.pattern + r"|可能|也許|或許|大概|應該是|好像|猜|[?？]|"
    r"\b(?:maybe|perhaps|probably|possibly|might\s+be|i\s+(?:think|guess)|not\s+certain)\b", re.IGNORECASE)


def _write_back(ir: dict, collection: str, entity_id: str, field: str, value, *, strict: bool) -> tuple[bool, str]:
    """Write one user-supplied value into a host/service field, with per-field provenance.

    Only the supplied field becomes user-sourced: the record's own source and
    epistemic_status describe what the report said and are left as they were.
    ``strict`` raises HTTP errors (explicit structured request); otherwise a value that
    cannot be applied is reported back as a reason and the IR is left unchanged.
    """
    def fail(status: int, detail: str) -> tuple[bool, str]:
        if strict:
            raise HTTPException(status_code=status, detail=detail)
        return False, detail

    if collection not in {"hosts", "services"}:
        return fail(422, "Unsupported supplement target.")
    entity = next((item for item in ir.get(collection, []) if item.get("id") == entity_id), None)
    if entity is None:
        return fail(404, "Service not found." if collection == "services" else "Host not found.")
    if field not in (_SERVICE_FIELDS if collection == "services" else _HOST_FIELDS):
        return fail(422, "Unsupported service field." if collection == "services" else "Unsupported host field.")
    if isinstance(value, str):
        value = value.strip()
        if field == "configuration":
            # Free text by nature. What matters to planning is whether the service runs at all.
            entity["configuration"] = value
            entity.setdefault("field_sources", {})["configuration"] = "user"
            if _NOT_ENABLED_RE.search(value):
                entity["lab_enabled"] = False
                entity["field_sources"]["lab_enabled"] = "user"
            else:
                entity.pop("lab_enabled", None)
            return True, ""
        if not strict and (len(value) > _MAX_FIELD_VALUE_CHARS or "\n" in value):
            return False, "回答是一段說明而不是單一欄位值，已保留為補充文字，未寫入欄位。"
        if not strict and _NON_ANSWER_RE.search(value):
            return False, "回答表示不確定或未知，不是可用的欄位值，未寫入欄位。"
    if field == "port":
        try:
            value = int(value)
        except (TypeError, ValueError):
            return fail(422, "port must be an integer.")
        if not 1 <= value <= 65535:
            return fail(422, "port must be between 1 and 65535.")
    if field in {"os", "os_version"}:
        os_name = str(value if field == "os" else entity.get("os", "")).casefold()
        version = str(value if field == "os_version" else entity.get("os_version", "")).casefold()
        if ("windows" in os_name and any(token in version for token in ("alpine", "ubuntu", "debian", "linux"))) or (
            any(token in os_name for token in ("linux", "alpine", "ubuntu", "debian")) and "windows" in version
        ):
            return fail(422, "OS and OS version are inconsistent.")
    entity[field] = value
    entity.setdefault("field_sources", {})[field] = "user"
    return True, ""


@router.post("/{scenario_id}/supplement")
def supplement(scenario_id: str, request: SupplementRequest):
    ir = store.get(scenario_id)
    if ir is None:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Supplement text must not be empty.")
    target_id = request.target_id()
    missing_items = ir.get("missing_items", [])
    target = next((item for item in missing_items if item.get("id") == target_id), None)
    if target_id and target is None:
        raise HTTPException(status_code=404, detail="Missing item not found.")

    supplement_id = "supplement-" + uuid.uuid4().hex[:12]
    ir.setdefault("supplements", []).append({
        "id": supplement_id,
        "text": text,
        **({"targets_missing_item": target_id} if target_id else {}),
        "source": "user",
    })
    if target is not None:
        _allowed = {"user_supplied", "substitute_chosen", "accepted_unknown"}
        target["status"] = request.status if request.status in _allowed else "user_supplied"
        target["resolution"] = text
        target["resolution_source"] = "user"

    # Structured answers can be written directly to one selected entity. When
    # resolving a host-scoped missing item, its host_ref also selects the host.
    host_id = request.host_id or (target.get("host_ref") if target else None)
    if request.field or request.value is not None:
        if not request.field or request.value is None:
            raise HTTPException(status_code=422, detail="field and value must be provided together.")
        if request.service_id:
            collection, entity_id = "services", request.service_id
        elif host_id:
            collection, entity_id = "hosts", host_id
        else:
            raise HTTPException(status_code=422, detail="host_id or service_id is required for a structured supplement.")
        _write_back(ir, collection, entity_id, request.field, request.value, strict=True)
        if target is not None:
            target["applied_to"] = {"collection": collection, "id": entity_id, "field": request.field}
    elif target is not None and isinstance(target.get("target"), dict) and target["status"] != "accepted_unknown":
        # The question itself says where its answer belongs; without this the answer would
        # only live in the resolution text and the planning modules would never see it.
        where = target["target"]
        applied, reason = _write_back(ir, str(where.get("collection")), str(where.get("id")), str(where.get("field")), text, strict=False)
        if applied:
            target["applied_to"] = dict(where)
            target.pop("write_back", None)
        else:
            target["write_back"] = reason
            if _UNKNOWN_ANSWER_RE.search(text):
                # "I don't know" is a decision to leave it unknown, not a supplied value.
                target["status"] = "accepted_unknown"
            elif _NON_ANSWER_RE.search(text):
                # A hedged guess settles nothing: keep the note, leave the question open.
                target["status"] = "open"

    ir["missing_items"] = refresh_missing_items(ir)
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=500, detail={"message": "Supplemented Scenario IR failed contract validation.", "errors": errors})
    return store.update(scenario_id, ir, note="user supplement", bump_version=True)
