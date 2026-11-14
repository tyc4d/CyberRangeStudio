"""CTI analysis and user supplementation endpoints (modules 1 and 2)."""
from __future__ import annotations

import hashlib
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


class SupplementRequest(BaseModel):
    text: str = Field(min_length=1)
    # Target is optional: a supplement may resolve a specific missing item or be a free-form note.
    # Accept both field names the frontend may send.
    missing_item_id: str | None = None
    targets_missing_item: str | None = None
    # Allowed resolution statuses when a target is given.
    status: str | None = None

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

    Returns the text for review on the Import page; it does NOT analyze or store anything.
    The caller reviews/edits the text, then submits it through POST /analyze as usual.
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
    return {
        "input_kind": input_kind,
        "content": content,
        "source_name": name.rsplit(".", 1)[0],
        "filename": name,
        "chars": len(content),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


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

    # Keep the generated checklist and record this response as a separate user
    # supplement instead of rewriting original report evidence or inventing a
    # structured host/service fact from free text.
    errors = iter_errors("scenario-ir", ir)
    if errors:
        raise HTTPException(status_code=500, detail={"message": "Supplemented Scenario IR failed contract validation.", "errors": errors})
    return store.update(scenario_id, ir, note="user supplement")
