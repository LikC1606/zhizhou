from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from campaign_runtime import CampaignError
from campaign_state import check_control_files, complete_state, read_state, save_state
from campaign_workflow import freeze_workflow


class CampaignWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.campaign = self.root / "campaign"
        self.campaign.mkdir()
        self.skill = self.root / "skill"
        (self.skill / "references").mkdir(parents=True)
        (self.skill / "scripts").mkdir()
        (self.skill / "SKILL.md").write_text("Read [instructions](references/task.md).\n")
        (self.skill / "references/task.md").write_text("Run ../scripts/solve.py. Version one.\n")
        (self.skill / "scripts/solve.py").write_text("print('version one')\n")
        (self.skill / "scripts/requirements.txt").write_text("fixture-package==1\n")
        self.state = {"agent_bin": "/test/fake-cli", "model": None, "turn_number": 0}

    def test_snapshot_preserves_linked_content_and_executable_after_source_upgrade(self):
        first, protected, provenance = freeze_workflow(self.campaign, self.skill, self.state)
        (self.skill / "references/task.md").write_text("Version two.\n")
        (self.skill / "scripts/solve.py").write_text("print('version two')\n")
        root = Path(first["skill_root"])
        self.assertIn("Version one", (root / "references/task.md").read_text())
        self.assertEqual((root / "scripts/requirements.txt").read_text(), "fixture-package==1\n")
        run = subprocess.run([sys.executable, str(root / "scripts/solve.py")], capture_output=True,
                             text=True, check=True)
        self.assertEqual(run.stdout, "version one\n")
        second, _, newer = freeze_workflow(self.campaign, self.skill, self.state)
        self.assertNotEqual(first["package_sha256"], second["package_sha256"])
        self.assertNotEqual(provenance["package_sha256"], newer["package_sha256"])
        check_control_files({"protected_files": protected})
        self.assertEqual(provenance["resolved_model"], "unknown")

    def test_changed_frozen_reference_blocks_instead_of_silently_rebuilding_it(self):
        snapshot, protected, _ = freeze_workflow(self.campaign, self.skill, self.state)
        (Path(snapshot["skill_root"]) / "references/task.md").write_text("edited sealed instructions")
        with self.assertRaises(CampaignError):
            check_control_files({"protected_files": protected})
        with self.assertRaises(CampaignError):
            freeze_workflow(self.campaign, self.skill, self.state)

    def test_schema_two_upgrade_preserves_legacy_inflight_bytes_and_marks_unknown_history(self):
        legacy = {"schema_version": 2, "turn_number": 3, "inflight": {"prompt": "original live instructions",
                  "command": ["original", "command"], "token": "legacy"}, **self.state}
        legacy["turn_number"] = 3
        (self.campaign / "state.json").write_text(json.dumps(legacy))
        upgraded = read_state(self.campaign)
        self.assertEqual(upgraded["inflight"], legacy["inflight"])
        self.assertIsNone(upgraded["instruction_snapshot"])
        self.assertIsNone(upgraded["workflow_provenance"])
        _, _, provenance = freeze_workflow(self.campaign, self.skill, upgraded)
        self.assertIn("not reconstructed", provenance["legacy_instructions"])
        save_state(self.campaign, upgraded)
        self.assertEqual(read_state(self.campaign)["inflight"], legacy["inflight"])

    def test_optional_state_defaults_are_not_shared_between_campaigns(self):
        left, right = complete_state({}), complete_state({})
        left["trial_exposures"]["comparison"] = {"candidate": 1}
        self.assertEqual(right["trial_exposures"], {})


if __name__ == "__main__":
    unittest.main()
