import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.citations import evidence_record, verify_quote  # noqa: E402
from app.cti.missing import calculate_missing_items  # noqa: E402
from app.cti.parser import extract_stix_candidates, parse_source  # noqa: E402


class CitationTests(unittest.TestCase):
  def test_paragraph_citation_requires_verbatim_quote_at_its_locator(self):
    units, parsed = parse_source("text", "The actor used PowerShell.\n\nA second fact.")

    self.assertTrue(verify_quote("used PowerShell", {"kind": "paragraph", "ref": "1"}, units, parsed))
    self.assertFalse(verify_quote("used PowerShell", {"kind": "paragraph", "ref": "2"}, units, parsed))
    self.assertFalse(verify_quote("used PowerShell!", {"kind": "paragraph", "ref": "1"}, units, parsed))

  def test_mitre_attack_stix_candidates_keep_verifiable_source_quotes(self):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "sample-scenarios" / "mitre-attack-apt29-external-remote-services.stix.json"
    units, parsed = parse_source("stix2.1", fixture.read_text(encoding="utf-8"))
    candidates = extract_stix_candidates(parsed, units)
    unit_by_id = {unit.id: unit for unit in units}

    for candidate in [*candidates["actions"], *candidates["relations"]]:
      self.assertTrue(candidate["evidence_refs"])
      for evidence_ref in candidate["evidence_refs"]:
        unit = unit_by_id[evidence_ref]
        self.assertTrue(verify_quote(unit.text, unit.locator, units, parsed))

  def test_failed_quote_is_retained_and_marked_unverified(self):
    units, parsed = parse_source("markdown", "Exact source quote.")

    item = evidence_record("evidence-1", "invented quote", "p1", units, parsed)

    self.assertEqual(item["quote"], "invented quote")
    self.assertEqual(item["locator"], {"kind": "paragraph", "ref": "1"})
    self.assertFalse(item["quote_verified"])

  def test_stix_path_citation_checks_value_at_exact_path(self):
    content = '{"type":"bundle","id":"bundle--11111111-1111-4111-8111-111111111111","objects":[{"type":"identity","spec_version":"2.1","id":"identity--22222222-2222-4222-8222-222222222222","created":"2025-01-01T00:00:00.000Z","modified":"2025-01-01T00:00:00.000Z","name":"Example Org","identity_class":"organization"}]}'
    units, parsed = parse_source("stix2.1", content)

    self.assertTrue(verify_quote("Example Org", units[0].locator, units, parsed))
    self.assertFalse(verify_quote("Example Org", {"kind": "stix_path", "ref": "objects[0].identity_class"}, units, parsed))

  def test_public_moveit_advisory_summary_has_verifiable_quotes_and_keeps_unknowns_open(self):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "sample-scenarios" / "clop-moveit-advisory.md"
    content = fixture.read_text(encoding="utf-8")
    units, parsed = parse_source("markdown", content)
    cve_unit = next(unit for unit in units if "CVE-2023-34362" in unit.text)

    self.assertIsNone(parsed)
    self.assertTrue(verify_quote("CVE-2023-34362", cve_unit.locator, units, parsed))
    self.assertFalse(verify_quote("victim-web-01", cve_unit.locator, units, parsed))

    ir = {
      "actions": [{"id": "a1", "name": "Exploit MOVEit Transfer", "source": "stix", "epistemic_status": "insufficient"}],
      "hosts": [{"id": "h1", "role": "target", "source": "stix", "epistemic_status": "insufficient"}],
      "services": [{"id": "s1", "name": "MOVEit Transfer", "version": "unknown", "source": "stix", "epistemic_status": "insufficient"}],
    }
    missing_fields = {item["field"] for item in calculate_missing_items(ir)}
    self.assertIn("target host identity", missing_fields)
    self.assertIn("target host operating system", missing_fields)
    self.assertIn("target host OS version", missing_fields)
    self.assertIn("target network placement", missing_fields)
    self.assertIn("target service name", missing_fields)
    self.assertIn("target service version", missing_fields)
    self.assertIn("attacker access precondition", missing_fields)

