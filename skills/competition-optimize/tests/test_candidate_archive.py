from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
archive = importlib.import_module("candidate_archive")


class CandidateArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "solution.cpp"
        self.source.write_text("int solve() { return 1; }\n", encoding="utf-8")
        self.archive = self.root / "candidate-archive.jsonl"

    def record(self, candidate_id: str, route: str, value: float, status: str = "runner_up",
               source: Path | None = None, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "record",
                   "--archive", str(self.archive), "--candidate-id", candidate_id,
                   "--source", str(source or self.source), "--route", route,
                   "--mechanism", f"mechanism-{candidate_id}", "--status", status,
                   "--valid", "--objective-value", str(value), "--objective-direction", "maximize",
                   "--objective-kind", "proxy", "--objective-name", "test-score", "--stage", "full",
                   "--evaluator-hash", "e" * 64, "--workload-hash", "a" * 64, "--score-model-hash", "d" * 64]
        if extra:
            command.extend(extra)
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_records_identity_and_rejects_exact_duplicate(self) -> None:
        first = self.record("baseline", "route-a", 1.0, "incumbent")
        self.assertEqual(first.returncode, 0, first.stderr)
        duplicate = self.record("renamed", "route-a", 1.1)
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual(json.loads(duplicate.stderr)["error"]["type"], "duplicate_fingerprint")
        rows = [json.loads(line) for line in self.archive.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["candidate_id"], "baseline")
        self.assertEqual(len(rows[0]["fingerprint"]), 64)

    def test_changed_source_is_new_candidate_but_same_id_is_rejected(self) -> None:
        self.assertEqual(self.record("c1", "route-a", 1.0).returncode, 0)
        self.source.write_text("int solve() { return 2; }\n", encoding="utf-8")
        self.assertEqual(self.record("c2", "route-a", 1.1).returncode, 0)
        same_id = self.record("c2", "route-a", 1.2)
        self.assertEqual(same_id.returncode, 2)
        self.assertEqual(json.loads(same_id.stderr)["error"]["type"], "duplicate_candidate_id")

    def test_result_metadata_preserves_invalid_feedback(self) -> None:
        result = self.root / "result.json"
        result.write_text(json.dumps({"candidate_hash": "a" * 64, "evaluator_hash": "e" * 64,
                                      "valid": False, "score": {"direction": "minimize", "value": 8.0}}),
                          encoding="utf-8")
        command = [sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "record",
                   "--archive", str(self.archive), "--candidate-id", "bad", "--result", str(result),
                   "--route", "route-a", "--mechanism", "failed-rule", "--status", "rejected",
                   "--failure", "timeout at workload 3"]
        run = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        record = json.loads(self.archive.read_text(encoding="utf-8").strip())
        self.assertFalse(record["valid"])
        self.assertEqual(record["objective"]["direction"], "minimize")
        self.assertEqual(record["failure_mechanism"], "timeout at workload 3")

    def test_route_decision_switches_after_comparable_stagnation(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0, "incumbent").returncode, 0)
        self.source.write_text("int solve() { return 2; }\n", encoding="utf-8")
        self.assertEqual(self.record("a1", "route-a", 0.9, "rejected").returncode, 0)
        self.source.write_text("int solve() { return 3; }\n", encoding="utf-8")
        self.assertEqual(self.record("a2", "route-a", 0.8, "rejected").returncode, 0)
        decision = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "decide",
                                  "--archive", str(self.archive), "--current-route", "route-a",
                                  "--min-stagnant", "2"], capture_output=True, text=True, check=False)
        self.assertEqual(decision.returncode, 0, decision.stderr)
        value = json.loads(decision.stdout)
        self.assertEqual(value["action"], "explore")
        self.assertEqual(value["current_route"], "route-a")
        self.assertIn("no new historical best", value["reason"])

    def test_unresolved_mechanism_keeps_route_in_exploit_mode(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0, "incumbent").returncode, 0)
        self.source.write_text("int solve() { return 2; }\n", encoding="utf-8")
        self.assertEqual(self.record("p", "route-a", 0.99, "promising", extra=["--feedback", "missing decoder step"])
                         .returncode, 0)
        decision = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "decide",
                                  "--archive", str(self.archive), "--current-route", "route-a"],
                                  capture_output=True, text=True, check=False)
        self.assertEqual(decision.returncode, 0, decision.stderr)
        self.assertEqual(json.loads(decision.stdout)["action"], "exploit")

    def test_archive_parser_rejects_malformed_json(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        with self.archive.open("ab") as stream:
            stream.write(b'{"event":\n')
        result = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "summary",
                                 "--archive", str(self.archive)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "invalid_json")

    def decide(self, *extra: str) -> dict:
        run = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "decide",
                              "--archive", str(self.archive), *extra], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def mutate_and_record(self, name: str, score: float, *extra: str) -> None:
        self.source.write_text(f"int solve() {{ return {name!r}; }}\n", encoding="utf-8")
        run = self.record(name, "route-a", score, "rejected", extra=list(extra))
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_rebound_below_history_best_is_not_route_progress(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        self.mutate_and_record("weaker", 0.7)
        self.mutate_and_record("rebound", 0.9)
        decision = self.decide()
        self.assertEqual(decision["action"], "explore")
        self.assertEqual(decision["progress_candidates"], [])

    def test_new_historical_best_is_progress_and_minimize_is_respected(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--objective-direction", "minimize"]).returncode, 0)
        self.mutate_and_record("better", 0.8, "--objective-direction", "minimize")
        decision = self.decide()
        self.assertEqual(decision["action"], "exploit")
        self.assertEqual(decision["progress_candidates"], ["better"])

    def test_changed_evaluator_workload_score_model_stage_or_kind_are_not_comparable(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        for index, flags in enumerate([["--evaluator-hash", "b" * 64], ["--workload-hash", "b" * 64],
                                       ["--score-model-hash", "b" * 64], ["--stage", "short"],
                                       ["--objective-kind", "official_metric"]]):
            self.mutate_and_record(f"changed-{index}", 0.5, *flags)
            with self.subTest(flags=flags):
                decision = self.decide()
                self.assertEqual(decision["action"], "diagnose")
                self.assertEqual(decision["recent_valid_candidates"], 1)

    def test_confirmation_is_archived_without_guiding_next_route(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        self.mutate_and_record("weak", 0.5)
        before = self.decide()
        self.mutate_and_record("confirmed", 9.0, "--role", "confirmation")
        self.assertEqual(self.decide(), before)

    def test_confirmation_does_not_reorder_alternative_routes(self) -> None:
        for route in ["route-a", "route-b", "route-c"]:
            self.source.write_text(route, encoding="utf-8")
            self.assertEqual(self.record(route, route, 1.0).returncode, 0)
        before = self.decide("--current-route", "route-a")
        self.source.write_text("confirmation for b", encoding="utf-8")
        self.assertEqual(self.record("confirm-b", "route-b", 10.0, extra=["--role", "confirmation"]).returncode, 0)
        self.assertEqual(self.decide("--current-route", "route-a"), before)

    def test_missing_score_identity_does_not_invent_a_decision(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--objective-kind", "unknown"]).returncode, 0)
        self.mutate_and_record("unknown", 2.0, "--objective-kind", "unknown")
        self.assertEqual(self.decide()["action"], "diagnose")

    def test_preflight_blocks_duplicates_and_allows_explained_verification(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        command = [sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "check",
                   "--archive", str(self.archive), "--source", str(self.source)]
        blocked = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(blocked.returncode, 2)
        verified = subprocess.run(command + ["--reuse-reason", "matched repetition for timing noise"],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["matches"], ["b"])
        repeated = self.record("repeated", "route-a", 1.0, extra=["--reuse-reason", "timing repetition"])
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)

    def test_result_bytes_source_binding_overrides_and_partial_evidence(self) -> None:
        result = self.root / "result.json"
        base = {"status": "success", "valid": True, "candidate_hash": archive.hash_path(self.source),
                "evaluator_hash": "e" * 64, "score_model_hash": "d" * 64,
                "score": {"kind": "proxy", "metric": "test-score", "direction": "maximize", "value": 1.0},
                "evaluation": {"stage": "full", "split_hash": "a" * 64,
                               "expected_cases": 3, "completed_cases": 3}}
        result.write_text(json.dumps(base), encoding="utf-8")
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--result", str(result)]).returncode, 0)
        self.source.write_text("changed source", encoding="utf-8")
        stale = self.record("stale", "route-a", 1.0, extra=["--result", str(result)])
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(json.loads(stale.stderr)["error"]["type"], "source_result_mismatch")
        base["candidate_hash"] = archive.hash_path(self.source)
        base["evaluation"]["completed_cases"] = 2
        result.write_text(json.dumps(base), encoding="utf-8")
        partial = self.record("partial", "route-a", 1.0, extra=["--result", str(result)])
        self.assertEqual(partial.returncode, 2)
        self.assertEqual(json.loads(partial.stderr)["error"]["type"], "result_override")

    def test_unknown_parent_incomplete_append_nonfinite_config_and_existing_output(self) -> None:
        unknown = self.record("child", "route-a", 1.0, extra=["--parent", "missing"])
        self.assertEqual(unknown.returncode, 2)
        self.assertFalse(self.archive.exists())
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        output = self.root / "decision.json"
        self.decide("--output", str(output))
        command = [sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "decide",
                   "--archive", str(self.archive)]
        for flags in [["--tie-epsilon", "nan"], ["--recent", "1"], ["--output", str(output)]]:
            with self.subTest(flags=flags):
                result = subprocess.run(command + flags, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 2)
        original = self.archive.read_bytes()
        self.archive.write_bytes(original + b'{"event":"candidate"}')
        broken = self.record("next", "route-a", 1.1)
        self.assertEqual(broken.returncode, 2)
        self.assertEqual(json.loads(broken.stderr)["error"]["type"], "incomplete_event")
        self.assertEqual(self.archive.read_bytes(), original + b'{"event":"candidate"}')

    def test_changed_historical_best_result_blocks_feedback(self) -> None:
        result = self.root / "result.json"
        result.write_text(json.dumps({"status": "success", "valid": True,
                                      "candidate_hash": archive.hash_path(self.source)}), encoding="utf-8")
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--result", str(result)]).returncode, 0)
        for index in range(5):
            self.mutate_and_record(f"weak-{index}", 0.5)
        result.write_text(result.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "decide",
                              "--archive", str(self.archive)], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(json.loads(run.stderr)["error"]["type"], "result_changed")

    def test_single_feedback_supported_candidate_can_be_deepened(self) -> None:
        run = self.record("p", "route-a", 1.0, "promising", extra=["--feedback", "decoder has an unimplemented feasibility repair"])
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.decide()["action"], "exploit")

    def test_decision_append_can_be_read_and_source_records_remain_unchanged(self) -> None:
        self.assertEqual(self.record("b", "route-a", 1.0).returncode, 0)
        prefix = self.archive.read_bytes()
        self.decide("--append")
        raw = self.archive.read_bytes()
        self.assertTrue(raw.startswith(prefix))
        entries = archive.read_records(self.archive)
        self.assertEqual(entries[-1]["event"], "decision")
        self.assertEqual(entries[-1]["action"], "diagnose")

    def test_snapshot_directories_are_path_independent_but_track_member_names_and_bytes(self) -> None:
        left, right = self.root / "left", self.root / "right"
        left.mkdir()
        right.mkdir()
        for folder in [left, right]:
            (folder / "a.cpp").write_bytes(b"contents")
        self.assertEqual(archive.hash_path(left), archive.hash_path(right))
        (right / "a.cpp").rename(right / "b.cpp")
        self.assertNotEqual(archive.hash_path(left), archive.hash_path(right))

    def test_structurally_corrupt_records_fail_without_a_traceback(self) -> None:
        for value in [{"schema_version": True, "event": "candidate"},
                      {"schema_version": 1, "event": "candidate"},
                      {"schema_version": 1, "event": "decision", "action": "promote"}]:
            with self.subTest(value=value):
                self.archive.write_text(json.dumps(value) + "\n", encoding="utf-8")
                run = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "summary",
                                      "--archive", str(self.archive)], capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stderr)["status"], "blocked")

    def test_nonfinite_or_overflowing_objectives_are_rejected(self) -> None:
        for value in [True, float("nan"), float("inf"), 10 ** 400]:
            with self.subTest(value=value), self.assertRaises(archive.ArchiveFailure):
                archive.finite_number(value, "score")

    def test_training_snapshot_preflight_works_before_predictions_exist(self) -> None:
        pipeline = self.root / "pipeline"
        pipeline.mkdir()
        code = pipeline / "train.py"
        code.write_text("fit_linear_model()", encoding="utf-8")
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--configuration", str(pipeline)]).returncode, 0)
        command = [sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "check",
                   "--archive", str(self.archive), "--configuration", str(pipeline)]
        old = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(old.returncode, 2)
        self.assertEqual(json.loads(old.stderr)["error"]["type"], "duplicate_fingerprint")
        code.write_text("fit_tree_model()", encoding="utf-8")
        new = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(new.returncode, 0, new.stderr)
        self.assertEqual(json.loads(new.stdout)["matches"], [])

    def test_complete_preflight_keeps_different_pipeline_with_same_outputs(self) -> None:
        configuration = self.root / "configuration.json"
        configuration.write_text('{"model":"linear"}', encoding="utf-8")
        self.assertEqual(self.record("b", "route-a", 1.0, extra=["--configuration", str(configuration)]).returncode, 0)
        configuration.write_text('{"model":"tree"}', encoding="utf-8")
        check = subprocess.run([sys.executable, str(SCRIPT_DIR / "candidate_archive.py"), "check",
                                "--archive", str(self.archive), "--source", str(self.source),
                                "--configuration", str(configuration)], capture_output=True, text=True, timeout=15)
        self.assertEqual(check.returncode, 0, check.stderr)


if __name__ == "__main__":
    unittest.main()
