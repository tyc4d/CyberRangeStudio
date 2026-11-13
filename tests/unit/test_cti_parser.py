import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.parser import SourceParseError, parse_source  # noqa: E402


class ParserTests(unittest.TestCase):
  def test_text_and_markdown_are_split_into_numbered_paragraphs(self):
    units, parsed = parse_source("markdown", "# First\n\nA report sentence.\n\nSecond paragraph.")

    self.assertIsNone(parsed)
    self.assertEqual([unit.id for unit in units], ["p1", "p2", "p3"])
    self.assertEqual([unit.locator for unit in units], [
        {"kind": "paragraph", "ref": "1"},
        {"kind": "paragraph", "ref": "2"},
        {"kind": "paragraph", "ref": "3"},
    ])
    self.assertEqual(units[1].text, "A report sentence.")

  def test_stix_21_bundle_parses_objects_and_builds_property_locators(self):
    content = '{"type":"bundle","id":"bundle--11111111-1111-4111-8111-111111111111","objects":[{"type":"identity","spec_version":"2.1","id":"identity--22222222-2222-4222-8222-222222222222","created":"2025-01-01T00:00:00.000Z","modified":"2025-01-01T00:00:00.000Z","name":"Example Org","identity_class":"organization"}]}'

    units, parsed = parse_source("stix2.1", content)

    self.assertEqual(parsed["objects"][0]["type"], "identity")
    self.assertEqual(units[0].text, "Example Org")
    self.assertEqual(units[0].locator, {"kind": "stix_path", "ref": "objects[0].name"})

  def test_invalid_stix_is_reported_instead_of_discarded(self):
    invalid_inputs = ["{not json}", '{"type":"bundle","spec_version":"2.0","objects":[]}', '{"type":"bundle","id":"bundle--not-an-id","spec_version":"2.1","objects":[]}']
    for content in invalid_inputs:
      with self.subTest(content=content), self.assertRaisesRegex(SourceParseError, "Invalid STIX 2.1"):
        parse_source("stix2.1", content)

