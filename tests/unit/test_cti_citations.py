import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.citations import evidence_record, verify_quote  # noqa: E402
from app.cti.parser import parse_source  # noqa: E402


class CitationTests(unittest.TestCase):
  def test_paragraph_citation_requires_verbatim_quote_at_its_locator(self):
    units, parsed = parse_source("text", "The actor used PowerShell.\n\nA second fact.")

    self.assertTrue(verify_quote("used PowerShell", {"kind": "paragraph", "ref": "1"}, units, parsed))
    self.assertFalse(verify_quote("used PowerShell", {"kind": "paragraph", "ref": "2"}, units, parsed))
    self.assertFalse(verify_quote("used PowerShell!", {"kind": "paragraph", "ref": "1"}, units, parsed))

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

