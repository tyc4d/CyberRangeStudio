import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.cti.missing import calculate_missing_items  # noqa: E402


class MissingItemTests(unittest.TestCase):
  def test_gaps_are_derived_from_ir_entities_not_a_fixed_list(self):
    # Gaps are grounded in real IR entities, so an IR with nothing to build on
    # asks nothing (the old fixed MINIMUM_REQUIRED_FIELDS checklist is gone).
    self.assertEqual(calculate_missing_items({"hosts": [], "services": [], "actions": []}), [])

  def test_host_without_os_raises_grounded_open_gaps(self):
    ir = {
        "hosts": [{"id": "h1", "role": "victim-web", "epistemic_status": "supported"}],
        "services": [],
        "actions": [{"id": "a1", "name": "Exploit", "target_host_ref": "h1", "epistemic_status": "supported"}],
    }
    gaps = calculate_missing_items(ir)
    self.assertTrue(gaps, "a host with no OS should raise gaps")
    self.assertTrue(all(g["status"] == "open" for g in gaps))
    # every gap names the real host it concerns (grounding, never invented)
    for g in gaps:
      self.assertTrue(any("h1" in a for a in g.get("affects", [])), g.get("field"))
    self.assertTrue({"host", "version", "network"} & {g["category"] for g in gaps})

  def test_fully_specified_context_leaves_no_gaps(self):
    ir = {
        "hosts": [{"id": "h", "role": "victim-web", "os": "Linux", "os_version": "6.1", "network_placement": "dmz", "epistemic_status": "supported"}],
        "services": [{"id": "s", "name": "nginx", "version": "1.25", "epistemic_status": "supported"}],
        "actions": [{"id": "a", "name": "x", "precondition": "y", "target_host_ref": "h", "epistemic_status": "supported"}],
    }
    self.assertEqual(calculate_missing_items(ir), [])


if __name__ == "__main__":
  unittest.main()
