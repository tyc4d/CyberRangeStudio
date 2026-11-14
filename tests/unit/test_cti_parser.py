import json
import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.parser import SourceParseError, extract_stix_candidates, parse_source  # noqa: E402
from app.cti.citations import verify_quote  # noqa: E402


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

  def test_public_mitre_attack_stix_subset_preserves_candidate_scope_and_relationship_type(self):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "sample-scenarios" / "mitre-attack-apt29-external-remote-services.stix.json"
    content = fixture.read_text(encoding="utf-8")

    units, parsed = parse_source("stix2.1", content)
    candidates = extract_stix_candidates(parsed, units)
    unit_by_id = {unit.id: unit for unit in units}

    self.assertEqual(len(candidates["actions"]), 1)
    action = candidates["actions"][0]
    self.assertEqual(action["name"], "External Remote Services")
    self.assertEqual(action["source"], "stix")
    self.assertEqual(action["epistemic_status"], "insufficient")
    self.assertEqual(action["candidate_type"], "technique_definition")
    self.assertTrue(action["evidence_refs"])

    self.assertEqual(len(candidates["relations"]), 1)
    relation = candidates["relations"][0]
    self.assertEqual(relation["relationship_type"], "uses")
    self.assertEqual(relation["kind"], "unclassified")
    self.assertEqual(relation["source"], "stix")
    self.assertNotIn("from_action", relation)
    self.assertNotIn("to_action", relation)
    self.assertEqual(candidates["hosts"], [])
    self.assertEqual(candidates["services"], [])

  def test_stix_indicator_observables_and_relationships_remain_distinct(self):
    objects = [
      self._attack_pattern("attack-pattern--11111111-1111-4111-8111-111111111111", "First action"),
      self._attack_pattern("attack-pattern--22222222-2222-4222-8222-222222222222", "Second action"),
      self._relationship("relationship--33333333-3333-4333-8333-333333333333", "precedes", "attack-pattern--11111111-1111-4111-8111-111111111111", "attack-pattern--22222222-2222-4222-8222-222222222222"),
      self._relationship("relationship--44444444-4444-4444-8444-444444444444", "requires", "attack-pattern--22222222-2222-4222-8222-222222222222", "attack-pattern--11111111-1111-4111-8111-111111111111"),
      self._relationship("relationship--55555555-5555-4555-8555-555555555555", "uses", "attack-pattern--11111111-1111-4111-8111-111111111111", "attack-pattern--22222222-2222-4222-8222-222222222222"),
      {
        "type": "indicator", "spec_version": "2.1",
        "id": "indicator--66666666-6666-4666-8666-666666666666",
        "created": "2025-01-01T00:00:00.000Z", "modified": "2025-01-01T00:00:00.000Z",
        "name": "Example detection pattern", "indicator_types": ["malicious-activity"],
        "pattern_type": "stix", "pattern": "[domain-name:value = 'example.invalid']",
        "valid_from": "2025-01-01T00:00:00.000Z",
      },
      {
        "type": "domain-name", "spec_version": "2.1",
        "id": "domain-name--77777777-7777-4777-8777-777777777777",
        "value": "example.invalid",
      },
      {
        "type": "domain-name", "spec_version": "2.1",
        "id": "domain-name--bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "value": "client.invalid",
      },
      {
        "type": "software", "spec_version": "2.1",
        "id": "software--88888888-8888-4888-8888-888888888888",
        "name": "Example web application", "software_types": ["application"], "version": "2.4",
      },
      {
        "type": "network-traffic", "spec_version": "2.1",
        "id": "network-traffic--99999999-9999-4999-8999-999999999999",
        "src_ref": "domain-name--bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "dst_ref": "domain-name--77777777-7777-4777-8777-777777777777",
        "protocols": ["tcp"], "src_port": 51000, "dst_port": 8443,
      },
    ]
    content = json.dumps({
      "type": "bundle", "id": "bundle--aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "objects": objects,
    })

    units, parsed = parse_source("stix2.1", content)
    candidates = extract_stix_candidates(parsed, units)
    unit_by_id = {unit.id: unit for unit in units}

    relations = {item["relationship_type"]: item for item in candidates["relations"]}
    first_id = "attack-pattern--11111111-1111-4111-8111-111111111111"
    second_id = "attack-pattern--22222222-2222-4222-8222-222222222222"
    self.assertEqual((relations["precedes"]["kind"], relations["precedes"]["from_action"], relations["precedes"]["to_action"]), ("temporal", first_id, second_id))
    self.assertEqual((relations["requires"]["kind"], relations["requires"]["from_action"], relations["requires"]["to_action"]), ("dependency", first_id, second_id))
    self.assertEqual(relations["uses"]["kind"], "unclassified")

    indicator = candidates["artifacts"][0]
    self.assertEqual(indicator["source"], "stix")
    self.assertEqual(indicator["epistemic_status"], "supported")
    self.assertIn("does not assert a sighting", indicator["claim_scope"])
    self.assertEqual(candidates["hosts"][0]["value"], "example.invalid")
    self.assertEqual(candidates["hosts"][0]["epistemic_status"], "insufficient")
    named_service = next(item for item in candidates["services"] if item.get("name"))
    self.assertEqual((named_service["name"], named_service["version"]), ("Example web application", "2.4"))
    self.assertEqual(named_service["epistemic_status"], "insufficient")
    port_candidate = next(item for item in candidates["services"] if item.get("port") == 8443)
    self.assertNotIn("name", port_candidate)
    self.assertEqual(port_candidate["protocol"], "tcp")
    for candidate in [*candidates["actions"], *candidates["relations"], *candidates["hosts"], *candidates["services"], *candidates["artifacts"]]:
      self.assertTrue(candidate["evidence_refs"])
      for evidence_ref in candidate["evidence_refs"]:
        unit = unit_by_id[evidence_ref]
        self.assertTrue(verify_quote(unit.text, unit.locator, units, parsed))

  @staticmethod
  def _attack_pattern(object_id, name):
    return {
      "type": "attack-pattern", "spec_version": "2.1", "id": object_id,
      "created": "2025-01-01T00:00:00.000Z", "modified": "2025-01-01T00:00:00.000Z",
      "name": name, "description": f"Definition for {name}.",
    }

  @staticmethod
  def _relationship(object_id, relationship_type, source_ref, target_ref):
    return {
      "type": "relationship", "spec_version": "2.1", "id": object_id,
      "created": "2025-01-01T00:00:00.000Z", "modified": "2025-01-01T00:00:00.000Z",
      "relationship_type": relationship_type, "source_ref": source_ref, "target_ref": target_ref,
    }

  def test_invalid_stix_is_reported_instead_of_discarded(self):
    invalid_inputs = ["{not json}", '{"type":"bundle","spec_version":"2.0","objects":[]}', '{"type":"bundle","id":"bundle--not-an-id","spec_version":"2.1","objects":[]}']
    for content in invalid_inputs:
      with self.subTest(content=content), self.assertRaisesRegex(SourceParseError, "Invalid STIX 2.1"):
        parse_source("stix2.1", content)

