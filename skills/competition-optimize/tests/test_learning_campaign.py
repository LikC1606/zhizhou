from __future__ import annotations

import importlib
import json
import subprocess
import unittest
from pathlib import Path


fixtures = importlib.import_module("test_autonomous_campaign")
driver, runtime = fixtures.driver, fixtures.runtime


class LearningCampaignTests(unittest.TestCase):
    setUp = fixtures.AutonomousCampaignTests.setUp
    shutdown = fixtures.AutonomousCampaignTests.shutdown
    call = fixtures.AutonomousCampaignTests.call
    start_args = fixtures.AutonomousCampaignTests.start_args
    start = fixtures.AutonomousCampaignTests.start
    state = fixtures.AutonomousCampaignTests.state
    calls = fixtures.AutonomousCampaignTests.calls
    events = fixtures.AutonomousCampaignTests.events
    turn_context = fixtures.AutonomousCampaignTests.turn_context
    seed_open_branches = fixtures.AutonomousCampaignTests.seed_open_branches

    def seed_learning(self) -> list[str]:
        archive = driver.archive_tools
        parent = self.seed_open_branches(0)[0]
        folder = self.workspace / "learning"
        folder.mkdir()
        names = ["old-a", "old-b", "old-c", "related-best"]
        for number, name in enumerate(names):
            proposal = {"proposal_id": name + "-proposal", "parent_ids": [parent["candidate_id"]],
                        "feedback_from": [parent["candidate_id"]], "route": "learning",
                        "code_targets": [parent["artifact_paths"]["source"]],
                        "basis": "The existing measured development control",
                        "change": "Implement the measured mechanism " + name,
                        "expected_observation": "Observe a changed development result",
                        "validation": "Execute the fixed local development program",
                        "stop_condition": "Record the observed outcome"}
            path = folder / (name + "-proposal.json")
            path.write_text(json.dumps(proposal))
            archive.propose_candidate(archive.parser().parse_args(
                ["propose", "--archive", str(self.archive), "--proposal", str(path)]))
            source = folder / (name + ".py")
            source.write_text("# " + name + "\nprint(" + str(1001 if number == 3 else 200 + number) + ")\n")
            run = subprocess.run([fixtures.PYTHON, str(source)], capture_output=True, text=True, check=True)
            result = folder / (name + "-result.json")
            result.write_text(json.dumps({"status": "success", "valid": True,
                "candidate_hash": archive.hash_path(source), "evaluator_hash": "synthetic-evaluator-v1",
                "workload_hash": "synthetic-workload-v1", "score_model_hash": "synthetic-score-model-v1",
                "stage": "development", "score": {"kind": "proxy", "metric": "synthetic-output",
                "direction": "maximize", "value": int(run.stdout)}}))
            lesson = folder / (name + "-learning.json")
            lesson.write_text(json.dumps({"key": name, "lesson": "Measured mechanism " + name,
                "conditions": "Only this fixed development contract",
                "limitations": "An agent report, not a causal claim",
                "next_action": "Inspect the source before adapting it", "evidence_from": []}))
            archive.record_candidate(archive.parser().parse_args(["record", "--archive", str(self.archive),
                "--candidate-id", name, "--source", str(source), "--result", str(result),
                "--parent", parent["candidate_id"], "--proposal-id", proposal["proposal_id"],
                "--prediction-status", "supported", "--route", "learning",
                "--mechanism", name, "--status", "runner_up",
                "--feedback", "Observed the executed local result for " + name, "--learning", str(lesson)]))
        return names

    def selected(self, number: int) -> list[str]:
        return [row["candidate_id"] for row in
                self.turn_context(number)["development_brief"]["scoped_learning"]["selection"]]

    def test_current_learning_rotates_across_successful_checkpoints_and_resume(self) -> None:
        names = self.seed_learning()
        prefix = self.archive.read_bytes()
        run = self.start("--max-turns", "2", "--session-checkpoints", "0")
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        run = self.call("resume", "--campaign", str(self.campaign), "--max-turns", "4")
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual([self.selected(number) for number in range(1, 5)],
                         [["related-best", "old-a"], ["related-best", "old-b"],
                          ["related-best", "old-c"], ["related-best", "old-a"]])
        context = self.turn_context(4)
        key = context["development_brief"]["scoped_learning"]["comparison_key"]
        self.assertEqual(self.state()["learning_exposures"], {key: {
            "related-best": 4, "old-a": 4, "old-b": 2, "old-c": 3}})
        self.assertTrue(self.archive.read_bytes().startswith(prefix))
        status = self.call("status", "--campaign", str(self.campaign))
        self.assertEqual(json.loads(status.stdout)["learning_exposed_heads"], len(names))

    def test_failed_cli_and_invalid_receipt_do_not_consume_learning(self) -> None:
        self.seed_learning()
        self.environment["FAKE_SCENARIO"] = "trial_failures"
        for number in range(1, 4):
            run = self.start("--max-turns", "1") if number == 1 else self.call(
                "resume", "--campaign", str(self.campaign), "--max-turns", str(number))
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            if number < 3:
                self.assertEqual(self.state()["learning_exposures"], {})
        self.assertEqual(self.selected(1), self.selected(2))
        self.assertEqual(self.selected(1), self.selected(3))
        key = self.turn_context(3)["development_brief"]["scoped_learning"]["comparison_key"]
        self.assertEqual(self.state()["learning_exposures"], {key: {"related-best": 3, "old-a": 3}})

    def test_legacy_prepared_request_preserves_context_without_inventing_delivery(self) -> None:
        self.seed_learning()
        driver.new_campaign(driver.parser().parse_args(self.start_args("--max-turns", "1")))
        legacy = self.state()
        legacy.pop("learning_exposures")
        runtime.atomic_json(self.campaign / "state.json", legacy)
        state = driver.read_state(self.campaign)
        self.assertEqual(state["learning_exposures"], {})
        driver.prepare_turn(self.campaign, state)
        self.assertEqual(self.state()["learning_exposures"], {})
        turn = state["inflight"]
        self.assertEqual(turn["learning_exposure"]["candidates"], ["related-best", "old-a"])
        turn.pop("learning_exposure")
        driver.save_state(self.campaign, state)
        directory = driver.materialize_request(self.campaign, turn)
        original = (directory / "context.json").read_bytes()
        (directory / "context.json").unlink()
        driver.materialize_request(self.campaign, driver.read_state(self.campaign)["inflight"])
        self.assertEqual((directory / "context.json").read_bytes(), original)
        run = self.call("resume", "--campaign", str(self.campaign))
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(self.state()["learning_exposures"], {})
        run = self.call("resume", "--campaign", str(self.campaign), "--max-turns", "2")
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(self.selected(1), self.selected(2))
        key = self.turn_context(2)["development_brief"]["scoped_learning"]["comparison_key"]
        self.assertEqual(self.state()["learning_exposures"], {key: {"related-best": 2, "old-a": 2}})


if __name__ == "__main__":
    unittest.main()
