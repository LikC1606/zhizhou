from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")
evaluator = importlib.import_module("evaluate_predictions")


class IterationTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "candidate-archive.jsonl"
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\na,1\nb,4\nc,9\n", encoding="utf-8")
        self.baseline = self.candidate("baseline", [1, 2, 3])
        self.record("baseline", self.baseline, status="incumbent")

    def call(self, *arguments: str, expected: int = 0) -> dict:
        run = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "candidate_archive.py"),
                              *arguments, "--archive", str(self.path)], capture_output=True,
                             encoding="utf-8", timeout=15)
        self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
        return json.loads(run.stdout if expected == 0 else run.stderr)

    def candidate(self, name: str, predictions: list[float], stage: str = "development") -> dict:
        folder = self.root / name
        folder.mkdir()
        source = folder / "predictions.csv"
        source.write_text("id,prediction\n" + "".join(f"{sample},{score}\n" for sample, score in zip("abc", predictions)), encoding="utf-8")
        pipeline = folder / "pipeline"
        pipeline.mkdir()
        (pipeline / "train.py").write_text(f"# immutable pipeline {name}\n", encoding="utf-8")
        output = folder / "evaluation"
        output.mkdir()
        args = evaluator.make_parser().parse_args(["--truth", str(self.truth), "--predictions", str(source),
                                                  "--metric", "rmse", "--stage", stage, "--split-id", "fixed",
                                                  "--output-dir", str(output)])
        result = evaluator.evaluate(args, output)
        result_path = output / "result.json"
        result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        return {"result": result_path, "source": source, "pipeline": pipeline}

    def record(self, name: str, candidate: dict, status: str = "runner_up", *extra: str,
               expected: int = 0) -> dict:
        return self.call("record", "--candidate-id", name, "--source", str(candidate["source"]),
                         "--configuration", str(candidate["pipeline"]), "--result", str(candidate["result"]),
                         "--route", "representation", "--mechanism", name, "--status", status, *extra,
                         expected=expected)

    def propose(self, name: str = "nonlinear", parent: str = "baseline", feedback: str = "baseline",
                target: Path | None = None, expected: int = 0) -> dict:
        proposal = {"proposal_id": name, "parent_ids": [parent], "feedback_from": [feedback],
                    "route": "representation", "code_targets": [str(target or self.baseline["pipeline"] / "train.py")],
                    "basis": "Current linear pipeline leaves systematic nonlinear residuals on matched development rows",
                    "change": "Replace the linear representation with a quadratic basis and refit",
                    "expected_observation": "Curved residuals shrink and RMSE improves over the parent",
                    "validation": "Same truth/split and evaluator; inspect full development RMSE",
                    "stop_condition": "Stop at the round reserve or when the hypothesis is contradicted"}
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        return self.call("propose", "--proposal", str(path), expected=expected)

    def test_two_measured_successors_close_the_actual_feedback_chain(self) -> None:
        self.propose()
        pending = self.call("trace")["iterations"]
        self.assertEqual(pending[0]["state"], "pending")
        child = self.candidate("quadratic", [1.1, 4.2, 8.9])
        self.record("quadratic", child, "incumbent", "--parent", "baseline", "--proposal-id", "nonlinear",
                    "--feedback", "Curvature error dropped; residual scale is now the main limitation",
                    "--prediction-status", "supported")
        self.propose("residual", "quadratic", "quadratic", child["pipeline"] / "train.py")
        final = self.candidate("residual-fit", [1, 4, 9])
        self.record("residual-fit", final, "incumbent", "--parent", "quadratic", "--proposal-id", "residual",
                    "--feedback", "Residual correction removed the remaining error on this fixture",
                    "--prediction-status", "supported")
        trace = self.call("trace")["iterations"]
        self.assertEqual([row["state"] for row in trace], ["evaluated_valid", "evaluated_valid"])
        self.assertEqual(trace[1]["feedback_from"], ["quadratic"])
        self.assertGreater(trace[0]["objective_gain_vs_parents"]["baseline"], 0)
        self.assertGreater(trace[1]["objective_gain_vs_parents"]["quadratic"], 0)
        self.assertEqual(trace[1]["objective"]["value"], 0)
        self.assertEqual(self.call("summary")["proposal_count"], 2)

    def test_a_plan_stays_pending_until_stopped_or_measured(self) -> None:
        self.propose()
        candidate = self.candidate("unlinked", [1, 4, 9])
        self.record("unlinked", candidate)
        self.assertEqual(self.call("trace")["iterations"][0]["state"], "pending")
        self.call("stop", "--proposal-id", "nonlinear", "--reason", "Confirmation reserve reached")
        row = self.call("trace")["iterations"][0]
        self.assertEqual(row["state"], "stopped")
        self.assertIn("reserve", row["reason"])
        self.assertNotIn("objective_gain_vs_parents", row)

    def test_confirmation_cannot_supply_feedback_or_search_parent(self) -> None:
        candidate = self.candidate("confirmation", [1, 4, 9], "confirmation")
        self.record("confirmation", candidate)
        for parent, feedback in [("confirmation", "baseline"), ("baseline", "confirmation")]:
            result = self.propose("confirm-" + parent, parent, feedback,
                                  self.baseline["pipeline"] / "train.py", expected=2)
            self.assertEqual(result["error"]["type"], "confirmation_feedback")

    def test_changed_parent_and_unrelated_target_are_rejected(self) -> None:
        unrelated = self.root / "unrelated.py"
        unrelated.write_text("no parent relationship", encoding="utf-8")
        rejected = self.propose("unrelated", target=unrelated, expected=2)
        self.assertEqual(rejected["error"]["type"], "unbound_code_target")
        code = self.baseline["pipeline"] / "train.py"
        code.write_text("changed after evaluation", encoding="utf-8")
        changed = self.propose("changed", expected=2)
        self.assertEqual(changed["error"]["type"], "parent_artifact_changed")

    def test_unchanged_pipeline_and_manual_claim_do_not_fulfill_a_proposal(self) -> None:
        self.propose()
        child = self.candidate("unchanged", [1, 4, 9])
        child["pipeline"] = self.baseline["pipeline"]
        rejected = self.record("unchanged", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                               "--feedback", "new prediction sample", "--prediction-status", "supported", expected=2)
        self.assertEqual(rejected["error"]["type"], "unchanged_pipeline")
        child["pipeline"] = self.root / "unchanged/pipeline"
        rejected = self.call("record", "--candidate-id", "manual", "--parent", "baseline", "--proposal-id", "nonlinear",
                             "--source", str(child["source"]), "--configuration", str(child["pipeline"]),
                             "--route", "representation", "--mechanism", "manual", "--status", "runner_up", "--valid",
                             "--feedback", "claimed execution", "--prediction-status", "supported", expected=2)
        self.assertEqual(rejected["error"]["type"], "missing_execution_evidence")
        self.assertEqual(self.call("trace")["iterations"][0]["state"], "pending")

    def test_defective_run_is_an_execution_outcome_without_a_valid_gain(self) -> None:
        self.propose()
        child = self.candidate("broken", [1, 4, 9])
        result = json.loads(child["result"].read_text(encoding="utf-8"))
        result.update(status="failed", valid=False, score={"value": None}, error={"type": "runtime_failure"})
        child["result"].write_text(json.dumps(result), encoding="utf-8")
        self.record("broken", child, "rejected", "--parent", "baseline", "--proposal-id", "nonlinear",
                    "--feedback", "Decoder crashed before a complete score", "--prediction-status", "unresolved")
        row = self.call("trace")["iterations"][0]
        self.assertEqual(row["state"], "evaluation_failed_or_invalid")
        self.assertIsNone(row["objective_gain_vs_parents"]["baseline"])

    def test_closed_proposal_cannot_be_reused_or_stopped_twice(self) -> None:
        self.propose()
        self.call("stop", "--proposal-id", "nonlinear", "--reason", "No useful action fits")
        stopped = self.call("stop", "--proposal-id", "nonlinear", "--reason", "Try again", expected=2)
        self.assertEqual(stopped["error"]["type"], "closed_proposal")
        child = self.candidate("late", [1, 4, 9])
        late = self.record("late", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                           "--feedback", "Late result", "--prediction-status", "supported", expected=2)
        self.assertEqual(late["error"]["type"], "closed_proposal")

    def test_missing_feedback_or_prediction_status_cannot_close_the_loop(self) -> None:
        self.propose()
        child = self.candidate("child", [1, 4, 9])
        before = self.path.read_bytes()
        rejected = self.record("child", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                               "--feedback", "Measured better", expected=2)
        self.assertEqual(rejected["error"]["type"], "missing_prediction_status")
        self.assertEqual(self.path.read_bytes(), before)

    def test_trace_refuses_changed_result_and_incomparable_score_is_not_a_gain(self) -> None:
        self.propose()
        child = self.candidate("child", [1, 4, 9])
        result = json.loads(child["result"].read_text(encoding="utf-8"))
        result["evaluation"]["config_hash"] = "b" * 64
        child["result"].write_text(json.dumps(result), encoding="utf-8")
        self.record("child", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                    "--feedback", "Different protocol requires matched evaluation", "--prediction-status", "unresolved")
        row = self.call("trace")["iterations"][0]
        self.assertIsNone(row["objective_gain_vs_parents"]["baseline"])
        child["result"].write_text(child["result"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        rejected = self.call("trace", expected=2)
        self.assertEqual(rejected["error"]["type"], "result_changed")

    def test_compact_trace_keeps_older_pending_ids_visible_without_reloading_all_rows(self) -> None:
        for index in range(3):
            self.propose(f"p-{index}")
        report = self.call("trace", "--recent", "1")
        self.assertEqual(report["total_iterations"], 3)
        self.assertEqual(report["omitted_iterations"], 2)
        self.assertEqual(report["pending_proposals"], ["p-0", "p-1", "p-2"])
        self.assertEqual([row["proposal_id"] for row in report["iterations"]], ["p-2"])
        self.assertEqual(len(self.call("trace", "--all")["iterations"]), 3)

    def test_a_matching_old_result_cannot_complete_a_new_proposal(self) -> None:
        self.propose()
        child = self.candidate("child", [1, 2, 3])
        child["result"] = self.baseline["result"]
        rejected = self.record("child", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                               "--feedback", "Claimed old score", "--prediction-status", "supported", expected=2)
        self.assertEqual(rejected["error"]["type"], "reused_execution_evidence")

    def test_source_only_candidates_do_not_require_a_configuration_artifact(self) -> None:
        # A code candidate without a separate training snapshot still has to
        # change its evaluated source; configuration-specific checks are not universal.
        # Use program evidence, rather than calling prediction CSVs source code.
        candidates = {}
        for name in ("parent-code", "child-code"):
            source = self.root / (name + ".py")
            source.write_text(f"def solve(): return {name!r}\n", encoding="utf-8")
            result = self.root / (name + "-result.json")
            result.write_text(json.dumps({"status": "success", "valid": True,
                                          "candidate_hash": archive.hash_path(source), "candidate_scope": "program_source",
                                          "validity_scope": "program_and_fixture_checks"}) + "\n", encoding="utf-8")
            candidates[name] = {"source": source, "result": result}
        root = self.root / "code-archive.jsonl"
        old = self.path
        self.path = root
        try:
            parent = candidates["parent-code"]
            self.call("record", "--candidate-id", "baseline", "--source", str(parent["source"]),
                      "--result", str(parent["result"]), "--route", "representation", "--mechanism", "code",
                      "--status", "incumbent")
            self.propose(target=parent["source"])
            child = candidates["child-code"]
            self.call("record", "--candidate-id", "child", "--parent", "baseline", "--source", str(child["source"]),
                      "--result", str(child["result"]), "--route", "representation", "--mechanism", "new code",
                      "--status", "runner_up", "--proposal-id", "nonlinear", "--prediction-status", "supported",
                      "--feedback", "Evaluated source changed with the mechanism")
            self.assertEqual(self.call("trace")["iterations"][0]["state"], "evaluated_valid")
        finally:
            self.path = old

    def test_changed_executed_pipeline_invalidates_trace(self) -> None:
        self.propose()
        child = self.candidate("child", [1, 4, 9])
        self.record("child", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                    "--feedback", "Measured better", "--prediction-status", "supported")
        (child["pipeline"] / "train.py").write_text("different code after the trial", encoding="utf-8")
        rejected = self.call("trace", expected=2)
        self.assertEqual(rejected["error"]["type"], "parent_artifact_changed")

    def test_source_only_algorithm_with_unknown_total_score_keeps_raw_evidence(self) -> None:
        self.path = self.root / "algorithm-archive.jsonl"
        paths = {}
        for name, code in [("baseline", "return 1;"), ("child", "return 2;")]:
            source = self.root / (name + ".cpp")
            source.write_text(code, encoding="utf-8")
            result = self.root / (name + "-algorithm-result.json")
            result.write_text(json.dumps({"status": "success", "correct": True, "stage": "full",
                                          "candidate_hash": archive.hash_path(source), "evaluator_hash": "e" * 64,
                                          "metrics": {"partial": False, "summary": {"uniformity": 0.8}},
                                          "elapsed_seconds": 1.2}), encoding="utf-8")
            paths[name] = (source, result)
        self.call("record", "--candidate-id", "baseline", "--source", str(paths["baseline"][0]),
                  "--result", str(paths["baseline"][1]), "--route", "representation", "--mechanism", "baseline",
                  "--status", "incumbent")
        self.propose(target=paths["baseline"][0])
        self.call("record", "--candidate-id", "child", "--parent", "baseline", "--source", str(paths["child"][0]),
                  "--result", str(paths["child"][1]), "--route", "representation", "--mechanism", "child",
                  "--status", "unresolved", "--proposal-id", "nonlinear", "--prediction-status", "unresolved",
                  "--feedback", "Implementation ran; official total score remains unavailable")
        row = self.call("trace")["iterations"][0]
        self.assertEqual(row["state"], "evaluated_valid")
        self.assertEqual(row["objective"]["kind"], "unknown")
        self.assertIsNone(row["objective_gain_vs_parents"]["baseline"])
        self.assertEqual(row["cost"]["evaluation_elapsed_seconds"], 1.2)

    def test_duplicate_and_mismatched_proposals_preserve_pending_evidence(self) -> None:
        self.propose()
        duplicate = self.propose(expected=2)
        self.assertEqual(duplicate["error"]["type"], "duplicate_proposal_id")
        child = self.candidate("child", [1, 4, 9])
        mismatch = self.record("child", child, "runner_up", "--parent", "baseline", "--proposal-id", "nonlinear",
                               "--route", "different-route", "--feedback", "Different mechanism", "--prediction-status", "supported",
                               expected=2)
        self.assertEqual(mismatch["error"]["type"], "proposal_mismatch")
        self.assertEqual(self.call("trace")["iterations"][0]["state"], "pending")


if __name__ == "__main__":
    unittest.main()
