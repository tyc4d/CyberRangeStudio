import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.missing import MINIMUM_REQUIRED_FIELDS, calculate_missing_items  # noqa: E402


class MissingItemTests(unittest.TestCase):
  def test_missing_items_come_from_explicit_minimum_field_list(self):
    ir = {"hosts": [], "services": [], "actions": []}

    missing = calculate_missing_items(ir)

    self.assertEqual(len(missing), len(MINIMUM_REQUIRED_FIELDS))
    self.assertTrue(all(item["status"] == "open" for item in missing))
    self.assertGreaterEqual({item["category"] for item in missing}, {"host", "software", "version", "network", "precondition"})

  def test_known_context_removes_only_matching_missing_items(self):
    ir = {
        "hosts": [{"id": "h1", "role": "victim-web", "os": "Linux", "os_version": "6.1", "network_placement": "dmz", "epistemic_status": "supported"}],
        "services": [{"id": "s1", "name": "nginx", "version": "1.25", "epistemic_status": "supported"}],
        "actions": [{"id": "a1", "name": "Initial access", "precondition": "Public web access", "epistemic_status": "supported"}],
    }

    self.assertEqual(calculate_missing_items(ir), [])

  def test_absent_service_seed_does_not_count_as_known_software(self):
    ir = {"hosts": [{"id": "h", "role": "target", "epistemic_status": "insufficient"}], "services": [{"id": "s", "name": "Unspecified service (absent)", "epistemic_status": "absent"}], "actions": []}

    self.assertIn("target service name", {item["field"] for item in calculate_missing_items(ir)})

  def test_unverified_values_do_not_clear_missing_items(self):
    ir = {
        "hosts": [{"id": "h", "role": "victim-web", "os": "Linux", "os_version": "6.1", "network_placement": "dmz", "epistemic_status": "insufficient"}],
        "services": [{"id": "s", "name": "nginx", "version": "1.25", "epistemic_status": "insufficient"}],
        "actions": [{"id": "a", "name": "Initial access", "precondition": "Public web access", "epistemic_status": "insufficient"}],
    }

    self.assertEqual(len(calculate_missing_items(ir)), len(MINIMUM_REQUIRED_FIELDS))

