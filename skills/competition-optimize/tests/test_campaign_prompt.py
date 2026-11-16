from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from campaign_prompt import prompt_for_turn


class CampaignPromptTests(unittest.TestCase):
    def state(self, **changes):
        return {"next_mode": "work", "archive": "/tmp/test/archive.jsonl", "recovery_needed": False,
                "completion_check": None, "context_refresh_reason": "", "progress": {},
                "last_summary": "", "next_action": "Implement the next mechanism", **changes}

    def render(self, context=None, **changes):
        return prompt_for_turn(self.state(**changes), Path("/tmp/test/campaign"), 1, context or {})

    def test_empty_evidence_retains_obligations_without_unrelated_feature_manual(self):
        prompt = self.render()
        for obligation in ("actual user/resource limits", "No default", "matching contracts",
                           "confirmation outcomes", "Do not submit", "local child jobs", "next_action"):
            self.assertIn(obligation, prompt)
        for absent in ("scoped_learning", "resource_tradeoffs", "complementary_evidence", "measure-plan"):
            self.assertNotIn(absent, prompt)
        self.assertLess(len(prompt.encode()), 4000)

    def test_feature_guidance_follows_delivered_cards_without_mutating_context(self):
        context = {"development_brief": {"resource_tradeoffs": {"selection": [{"candidate_id": "fast"}]},
                                         "scoped_learning": {"selection": []}}}
        original = copy.deepcopy(context)
        prompt = self.render(context)
        self.assertIn("Total evaluator time is not inferred candidate latency", prompt)
        self.assertNotIn("use learning_from", prompt)
        self.assertEqual(context, original)

    def test_repair_and_measurement_keep_distinct_executable_instructions(self):
        repair = self.render(next_mode="repair")
        measure = self.render({"measurement_plan": {"plan_id": "frozen"}}, next_mode="measure")
        self.assertIn("measure-stop", repair)
        self.assertNotIn("strategy review", repair)
        self.assertIn("measure-status", measure)
        self.assertIn("measurement_run_id", measure)
        self.assertIn("measure-decide", measure)

    def test_frozen_instruction_pointer_replaces_live_skill_pointer(self):
        prompt = self.render(instruction_snapshot={"skill_path": "/tmp/test/instructions/v1/SKILL.md"})
        self.assertIn("Read /tmp/test/instructions/v1/SKILL.md", prompt)
        self.assertNotIn("Read " + str(Path(__file__).resolve().parents[1] / "SKILL.md"), prompt)


if __name__ == "__main__":
    unittest.main()
