from __future__ import annotations

import copy
import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")
search = importlib.import_module("campaign_search")
policy = importlib.import_module("campaign_policy")
search_fixtures = importlib.import_module("test_campaign_search")
measurement_fixtures = importlib.import_module("test_measurement_plans")


class CampaignPolicyTests(unittest.TestCase):
    # Reuse archive fixtures without collecting the original test methods.
    setUp = search_fixtures.CampaignSearchTests.setUp
    record = search_fixtures.CampaignSearchTests.record
    records = search_fixtures.CampaignSearchTests.records

    @staticmethod
    def memory(**updates) -> dict:
        memory = {
            "next_mode": "work", "next_action": "Implement the next informative successor",
            "session_id": "existing-session", "session_turns": 0,
            "session_checkpoints": 2, "turn_number": 1,
            "context_refreshes": 0, "context_refresh_reason": "",
            "execution_review_checkpoint": None, "failure_review_window": 3,
            "strategy_review_checkpoints": {}, "comparison_review_checkpoint": None,
            "comparison_review_window": 4, "repeat_review_checkpoints": {},
            "stagnation_window": 4, "frontier_exposures": {},
            "pending_proposal_exposures": {}, "trial_exposures": {},
            "learning_exposures": {}, "turns_without_implementation": 0,
            "retry_base_seconds": 1.0, "retry_max_seconds": 8.0,
            "failures": 0, "retry_at": None, "last_error": "", "recovery_needed": False,
        }
        return {**memory, **updates}

    def receipt(self, next_action: str = "Implement a distinct successor", *, path=None) -> dict:
        return {"status": "continue", "summary": "Reviewed accepted evidence",
                "next_action": next_action, "stop_reason": "", "evidence": [str(path or self.path)]}

    def outcome(self, before: list[dict], after: list[dict], receipt: dict | None):
        self.assertEqual(after[:len(before)], before)
        evidence = search.CampaignEvidence(after)
        previous = search.CampaignEvidence(before).counts
        delta = {key: count - previous[key] for key, count in evidence.counts.items()}
        return policy.TurnOutcome(evidence=evidence, appended_events=after[len(before):],
                                  archive_delta=delta, receipt=receipt, now=100.0)

    def measurement_fixture(self):
        fixture = measurement_fixtures.MeasurementPlanTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_prepare_and_accept_leave_borrowed_inputs_unchanged(self) -> None:
        baseline = self.record("baseline", 100)
        records = self.records()
        evidence = search.CampaignEvidence(records)
        progress = evidence.signals()["objective_progress"]
        key = progress["comparison_key"]
        identity = archive.implementation_identity(baseline)["fingerprint"]
        memory = self.memory(session_turns=2,
                             frontier_exposures={key: {"previous-delivery": 2}},
                             strategy_review_checkpoints={"older-contract": {"best_candidate": "old"}})
        turn = {"number": 7, "mode": "work", "fresh_context": False,
                "frontier_exposure": {"comparison_key": key, "implementations": [identity]},
                "review_checkpoints": {"strategy": {
                    name: progress[name] for name in
                    ("comparison_key", "best_candidate", "comparable_implementations")}}}
        outcome = self.outcome(records, records, self.receipt())
        original = copy.deepcopy((memory, turn, records, outcome.receipt, outcome.archive_delta))

        planned = policy.CampaignPolicy().prepare(memory, evidence)
        accepted = policy.CampaignPolicy().accept(memory, turn, outcome)

        self.assertTrue(planned.fresh_context)
        self.assertEqual(accepted["frontier_exposures"][key], {"previous-delivery": 2, identity: 7})
        self.assertEqual((memory, turn, records, outcome.receipt, outcome.archive_delta), original)

    def test_pending_measurement_keeps_its_work_across_context_rotation(self) -> None:
        fixture = self.measurement_fixture()
        frozen = fixture.plan()
        evidence = search.CampaignEvidence(archive.read_records(fixture.path))
        for session_id, turn_number, reason in (
                ("existing-session", 3, "scheduled_rotation"),
                (None, 3, "session_recovery"), (None, 0, "initial")):
            with self.subTest(reason=reason):
                memory = self.memory(session_id=session_id, session_turns=2, turn_number=turn_number)
                planned = policy.CampaignPolicy().prepare(memory, evidence)
                self.assertEqual(planned.updates["next_mode"], "measure")
                self.assertIn(frozen["plan_id"], planned.updates["next_action"])
                self.assertTrue(planned.fresh_context)
                self.assertEqual(planned.context_refresh_reason, reason)
                self.assertIsNone(planned.updates["session_id"])
                self.assertEqual(planned.updates["session_turns"], 0)
                self.assertEqual(planned.review_requests, {})
                self.assertNotIn("repeat_review_checkpoints", planned.updates)

    def test_review_confirmation_recomputes_continuity_without_acknowledging_new_evidence(self) -> None:
        for number in range(4):
            self.record(f"isolated-{number}", comparison={"config_hash": f"contract-{number}"})
        before = self.records()
        memory = self.memory(turn_number=12)
        staged = policy.CampaignPolicy().prepare(memory, search.CampaignEvidence(before))
        self.assertEqual(staged.context_refresh_reason, "comparison_isolation")
        self.assertNotIn("comparison_review_checkpoint", staged.updates)
        sealed_key = staged.updates["objective_progress"]["comparison_key"]
        identity = archive.implementation_identity(before[-1])["fingerprint"]
        turn = {"number": 11, "mode": "measure", "review_checkpoints": staged.review_requests,
                "context": {"comparison_continuity": staged.updates["comparison_continuity"]},
                "frontier_exposure": {"comparison_key": sealed_key, "implementations": [identity]}}
        memory.update(staged.updates)
        self.record("appended-during-review", comparison={"config_hash": "contract-4"})

        accepted = policy.CampaignPolicy().accept(
            memory, turn, self.outcome(before, self.records(), self.receipt()))

        continuity = accepted["comparison_continuity"]
        self.assertEqual(accepted["comparison_review_checkpoint"], {"distinct_observations": 4})
        self.assertEqual((continuity["distinct_observations"], continuity["reviewed_observations"],
                          continuity["new_unpaired_contracts"]), (5, 4, 1))
        self.assertEqual(accepted["next_mode"], "work")
        active_key = accepted["objective_progress"]["comparison_key"]
        self.assertNotEqual(active_key, sealed_key)
        self.assertEqual(accepted["frontier_exposures"], {sealed_key: {identity: 11}})
        self.assertEqual(policy.CampaignPolicy().prepare(
            {**memory, **accepted}, search.CampaignEvidence(self.records())).updates["next_mode"], "work")

    def test_failed_delivery_accepts_new_execution_without_acknowledging_sealed_requests(self) -> None:
        baseline = self.record("baseline", 100)
        for number in range(4):
            self.record(f"nonimproving-{number}", 90 - number)
        before = self.records()
        memory = self.memory(session_turns=1, failures=2, recovery_needed=True,
                             turns_without_implementation=3)
        staged = policy.CampaignPolicy().prepare(memory, search.CampaignEvidence(before))
        self.assertEqual(staged.updates["next_mode"], "rethink")
        memory.update(staged.updates)
        turn = {"number": 4, "mode": "rethink", "review_checkpoints": staged.review_requests,
                "frontier_exposure": {
                    "comparison_key": staged.updates["objective_progress"]["comparison_key"],
                    "implementations": [archive.implementation_identity(baseline)["fingerprint"]]}}
        self.record("failed-diagnostic", None, valid=False, status="rejected", role="diagnostic", parent="baseline")

        accepted = policy.CampaignPolicy().accept(memory, turn, self.outcome(before, self.records(), None))

        self.assertTrue(accepted["execution_health"]["needs_attention"])
        self.assertEqual(accepted["execution_health"]["anchor_candidate"], "failed-diagnostic")
        self.assertEqual(accepted["objective_progress"]["best_candidate"], "baseline")
        self.assertEqual(accepted["objective_progress"]["comparable_implementations"], 5)
        self.assertEqual(accepted["turns_without_implementation"], 0)
        self.assertEqual(accepted["next_mode"], "repair")
        self.assertIsNone(accepted["session_id"])
        for key in ("session_turns", "frontier_exposures", "pending_proposal_exposures", "trial_exposures",
                    "learning_exposures", "execution_review_checkpoint", "strategy_review_checkpoints",
                    "comparison_review_checkpoint", "repeat_review_checkpoints", "failures", "recovery_needed"):
            self.assertNotIn(key, accepted)

    def test_healthy_plan_closure_returns_to_work_even_when_cli_delivery_fails(self) -> None:
        fixture = self.measurement_fixture()
        fixture.finish_plan()
        after = archive.read_records(fixture.path)
        before = after[:-1]
        self.assertEqual(after[-1]["event"], "measurement_decision")
        memory = self.memory(next_mode="measure", session_turns=1)
        staged = policy.CampaignPolicy().prepare(memory, search.CampaignEvidence(before))
        self.assertEqual(staged.updates["next_mode"], "measure")
        memory.update(staged.updates)
        turn = {"number": 3, "mode": "measure", "review_checkpoints": {},
                "context": {"comparison_continuity": staged.updates["comparison_continuity"]}}

        accepted = policy.CampaignPolicy().accept(memory, turn, self.outcome(before, after, None))

        self.assertFalse(accepted["execution_health"]["needs_attention"])
        self.assertEqual(accepted["next_mode"], "work")
        self.assertNotIn("session_turns", accepted)
        self.assertEqual(accepted["objective_progress"], staged.updates["objective_progress"])
        self.assertEqual(policy.CampaignPolicy().prepare(
            {**memory, **accepted}, search.CampaignEvidence(after)).updates["next_mode"], "work")

    def test_legacy_sealed_turns_need_no_optional_delivery_or_context_fields(self) -> None:
        self.record("baseline", 100)
        records = self.records()
        for mode, expected in (("measure", "work"), ("repair", "rethink"), ("rethink", "execute")):
            with self.subTest(mode=mode):
                memory = self.memory(session_turns=1, turns_without_implementation=1)
                turn = {"number": 2, "mode": mode}
                accepted = policy.CampaignPolicy().accept(
                    memory, turn, self.outcome(records, records, self.receipt()))
                self.assertEqual(accepted["session_turns"], 2)
                self.assertEqual(accepted["next_mode"], expected)
                self.assertEqual(accepted["retry_at"], None if mode == "measure" else 101.0)
                for key in ("frontier_exposures", "pending_proposal_exposures", "trial_exposures",
                            "learning_exposures", "execution_review_checkpoint", "strategy_review_checkpoints",
                            "comparison_review_checkpoint", "repeat_review_checkpoints"):
                    self.assertNotIn(key, accepted)

    def test_historical_measurement_resolutions_do_not_replace_current_action(self) -> None:
        for event in ("measurement_decision", "measurement_stop"):
            with self.subTest(event=event):
                fixture = self.measurement_fixture()
                if event == "measurement_decision":
                    resolution = fixture.finish_plan()
                else:
                    fixture.plan()
                    resolution = fixture.stop()
                records = archive.read_records(fixture.path)
                current_action = "Implement the newly selected structural improvement"
                self.assertNotEqual(current_action, resolution["next_action"])
                accepted = policy.CampaignPolicy().accept(
                    self.memory(), {"number": 3, "mode": "work"},
                    self.outcome(records, records, self.receipt(current_action, path=fixture.path)))
                self.assertEqual(accepted["next_action"], current_action)
                self.assertEqual(accepted["next_mode"], "work")

    def test_new_resolution_controls_action_only_for_the_post_turn_active_comparison(self) -> None:
        for change_contract in (False, True):
            with self.subTest(change_contract=change_contract):
                fixture = self.measurement_fixture()
                resolution = fixture.finish_plan()
                before = archive.read_records(fixture.path)[:-1]
                if change_contract:
                    fixture.record("new-active-contract", "other", 120, config_hash="different-contract")
                after = archive.read_records(fixture.path)
                current_action = "Continue the current contract with a complete implementation"
                accepted = policy.CampaignPolicy().accept(
                    self.memory(), {"number": 3, "mode": "work"},
                    self.outcome(before, after, self.receipt(current_action, path=fixture.path)))
                self.assertEqual(accepted["next_action"],
                                 current_action if change_contract else resolution["next_action"])
                self.assertEqual(accepted["next_mode"], "work")


if __name__ == "__main__":
    unittest.main()
