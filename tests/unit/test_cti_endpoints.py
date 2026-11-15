import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app import store  # noqa: E402
from app.cti import analysis  # noqa: E402
from app.cti.citations import evidence_record  # noqa: E402
from app.cti.parser import parse_source  # noqa: E402
from app.main import app  # noqa: E402


class IngestEndpointTests(unittest.TestCase):
  def test_equifax_pdf_extract_preserves_query_quote_without_verifying_rewrites(self):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "cti-candidates" / "equifax-2017-struts-db" / "evidence-brief.pdf"
    with patch.object(store, "set_pending_file", lambda *args: None):
      response = TestClient(app).post(
          "/api/ingest/extract",
          files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
      )

    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual(response.json()["input_kind"], "text")
    extracted = response.json()["content"]
    units, parsed = parse_source("text", extracted)
    self.assertGreater(len(units), 1, "PDF extraction should preserve paragraph locators")
    source_ref = next(unit.id for unit in units if "9,000" in unit.text)
    exact_quote = (
        "The credentials enabled access to 48 unrelated databases. Investigators reported roughly 9,000 "
        "queries; the House report says 265 located unencrypted personal data."
    )
    exact = evidence_record("pdf-exact", exact_quote, source_ref, units, parsed)
    self.assertTrue(exact["quote_verified"])
    self.assertEqual(exact["quote_match"], "exact")

    # Preserve the captured model rewrites as partial evidence, never verified quotes.
    rewrites = {
        "evidence-15": (
            "Foothold to broader access: those credentials enabled access to databases outside the normal ACIS set.",
            "normal ACIS set",
        ),
        "evidence-16": (
            "The application needed three databases for its business function but could reach unrelated databases "
            "because segmentation was insufficient.",
            "application needed three databases",
        ),
    }
    for evidence_id, (quote, anchor) in rewrites.items():
      with self.subTest(evidence_id=evidence_id):
        rewrite_ref = next(unit.id for unit in units if anchor in unit.text)
        record = evidence_record(evidence_id, quote, rewrite_ref, units, parsed)
        self.assertEqual(record["quote_match"], "partial")
        self.assertFalse(record["quote_verified"])

  def test_pdf_extract_preserves_hyphenated_citation_across_line_wrap(self):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "cti-candidates" / "aa23-289a-confluence-cve-2023-22515" / "source.pdf"
    with patch.object(store, "set_pending_file", lambda *args: None):
      response = TestClient(app).post(
          "/api/ingest/extract",
          files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
      )

    self.assertEqual(response.status_code, 200, response.text)
    units, parsed = parse_source("text", response.json()["content"])
    quote = (
        "Threat actors exploited CVE-2023-22515 as a zero-day to obtain access to victim systems and "
        "continue active exploitation post-patch."
    )
    source_ref = next(unit.id for unit in units if "Threat actors exploited CVE-2023-22515" in unit.text)
    record = evidence_record("confluence-hyphen", quote, source_ref, units, parsed)
    self.assertTrue(record["quote_verified"])
    self.assertEqual(record["quote_match"], "exact")

  def test_analyze_returns_valid_full_ir_with_program_checked_citation(self):
    model_result = {
        "actions": [{
            "id": "a1", "name": "PowerShell execution", "epistemic_status": "supported",
            "evidence": [{"quote": "The actor used PowerShell.", "source_ref": "p1"}],
        }],
        "relations": [],
        "target_context": {"hosts": [], "services": []},
        "artifacts": [],
    }
    complete_patch = patch.object(analysis, "complete", lambda *args, **kwargs: {"text": json.dumps(model_result)})

    def create(ir):
        return {**ir, "id": "scn_test", "ir_version": 1, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}

    with complete_patch, patch.object(store, "create", create):
      response = TestClient(app).post("/api/ingest/analyze", json={"input_kind": "text", "content": "The actor used PowerShell.", "method": "single_pass", "name": "Test"})

    self.assertEqual(response.status_code, 200, response.text)
    ir = response.json()
    self.assertEqual(ir["id"], "scn_test")
    self.assertEqual(ir["actions"][0]["evidence_refs"], ["evidence-1"])
    self.assertTrue(ir["evidence"][0]["quote_verified"])
    self.assertEqual(ir["quality"]["method"], "single_pass")
    self.assertTrue(ir["quality"]["provisional"])
    self.assertTrue(ir["hosts"] and ir["services"])

  def test_supplement_returns_updated_ir_and_preserves_user_source(self):
    existing = {
        "schema_version": "1.0", "id": "scn_test", "name": "Test",
        "provenance": {"input_kind": "text", "input_sha256": "abc"},
        "actions": [], "relations": [],
        "missing_items": [{"id": "missing-1", "field": "target host OS", "category": "host", "reason": "Not stated.", "status": "open"}],
    }
    with patch.object(store, "get", lambda scenario_id: existing if scenario_id == "scn_test" else None), patch.object(store, "update", lambda scenario_id, ir, note=None, bump_version=False: ir):
      response = TestClient(app).post("/api/ingest/scn_test/supplement", json={"missing_item_id": "missing-1", "text": "User reports Ubuntu 22.04."})

    self.assertEqual(response.status_code, 200, response.text)
    ir = response.json()
    self.assertEqual(ir["supplements"][0]["source"], "user")
    self.assertEqual(ir["supplements"][0]["text"], "User reports Ubuntu 22.04.")
    self.assertEqual(ir["missing_items"][0]["status"], "user_supplied")
    self.assertEqual(ir["missing_items"][0]["resolution_source"], "user")

  def test_unverified_model_quote_is_retained_and_claim_downgraded(self):
    model_result = {
        "actions": [{
            "id": "a1", "name": "Unsupported action", "epistemic_status": "supported",
            "evidence": [{"quote": "This wording is not in the report.", "source_ref": "p1"}],
        }],
        "relations": [], "target_context": {"hosts": [], "services": []}, "artifacts": [],
    }
    complete_patch = patch.object(analysis, "complete", lambda *args, **kwargs: {"text": json.dumps(model_result)})
    create_patch = patch.object(store, "create", lambda ir: {**ir, "id": "scn_test", "ir_version": 1})
    with complete_patch, create_patch:
      response = TestClient(app).post("/api/ingest/analyze", json={"input_kind": "text", "content": "Actual source wording.", "method": "single_pass"})

    self.assertEqual(response.status_code, 200, response.text)
    ir = response.json()
    self.assertEqual(ir["evidence"][0]["quote"], "This wording is not in the report.")
    self.assertFalse(ir["evidence"][0]["quote_verified"])
    self.assertEqual(ir["actions"][0]["epistemic_status"], "insufficient")
    self.assertEqual(ir["quality"]["unsupported_claim_count"], 1)
