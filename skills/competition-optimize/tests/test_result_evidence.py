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
from candidate_evidence import ArchiveFailure, implementation_identity, observed_snapshot
from result_evidence import ObservationClaims, ResultEvidence


class ResultEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def read(self, result: dict) -> ResultEvidence:
        path = self.root / "result.json"
        path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        return ResultEvidence.read(path)

    def test_prediction_contract_preserves_development_and_confirmation_semantics(self) -> None:
        for stage in ("development", "confirmation"):
            with self.subTest(stage=stage):
                result = self.read({
                    "schema_version": 1, "status": "success", "valid": True,
                    "candidate_scope": "prediction_csv", "candidate_hash": "a" * 64,
                    "evaluator_hash": "e" * 64, "score_model_hash": "m" * 64,
                    "validity_scope": "prediction_artifact_and_metric_inputs",
                    "unchecked_rules": ["training_provenance"],
                    "score": {"kind": "official_metric", "metric": "rmse", "direction": "minimize", "value": 0.3},
                    "evaluation": {"stage": stage, "config_hash": "c" * 64, "split_hash": "s" * 64}})
                observation = result.resolve(ObservationClaims())
                self.assertEqual(observation.role, stage)
                self.assertEqual(observation.purpose, stage)
                self.assertIsNone(observation.fidelity)
                self.assertEqual(observation.operation, "evaluate")
                self.assertEqual(observation.objective, {"value": 0.3, "direction": "minimize", "kind": "official_metric", "name": "rmse", "components": {}})
                self.assertEqual(observation.comparison["workload_hash"], "s" * 64)
                self.assertEqual(result.metadata["unchecked_rules"], ["training_provenance"])
                self.assertEqual(result.source_kind, "adapter_result")
                if stage == "confirmation":
                    with self.assertRaises(ArchiveFailure) as error:
                        result.resolve(ObservationClaims(role="development"))
                    self.assertEqual(error.exception.kind, "result_override")

    def test_timeslot_fidelity_does_not_override_explicit_confirmation_role(self) -> None:
        result = self.read({
            "schema_version": 2, "status": "success", "correct": True, "stage": "full",
            "candidate_hash": "a" * 64, "evaluator_hash": "e" * 64,
            "workload_hash": "w" * 64, "score_model_hash": "m" * 64,
            "runtime_environment": {"compiler": "fixture"},
            "score": {"kind": "proxy", "aggregation": "mean_quality", "direction": "maximize", "value": 2.0},
            "metrics": {"summary": {"quality": 2.0}, "partial": False}})
        observation = result.resolve(ObservationClaims(role="confirmation"))
        self.assertTrue(observation.valid)
        self.assertEqual(observation.purpose, "confirmation")
        self.assertEqual(observation.fidelity, "full")
        self.assertEqual(observation.comparison["stage"], "full")
        self.assertEqual(observation.objective["name"], "mean_quality")
        self.assertEqual(result.metadata["metric_summary"], {"quality": 2.0})

    def test_unknown_score_and_package_operation_remain_distinct(self) -> None:
        result = self.read({"schema_version": 2, "status": "success", "correct": True,
                            "stage": "package", "score": {"kind": "unknown", "components": {"quality": 2}}})
        observation = result.resolve(ObservationClaims(role="confirmation"))
        self.assertNotIn("value", observation.objective)
        self.assertEqual(observation.objective["kind"], "unknown")
        self.assertEqual(observation.operation, "package")
        self.assertIsNone(observation.fidelity)
        self.assertEqual(observation.purpose, "confirmation")
        result.metadata["stage"] = "task_specific_fidelity"
        self.assertIsNone(result.resolve(ObservationClaims()).fidelity)

    def test_failed_and_partial_results_cannot_be_overridden_valid(self) -> None:
        for changes in ({"status": "failed"}, {"metrics": {"partial": True}},
                        {"evaluation": {"expected_cases": 4, "completed_cases": 3}}):
            with self.subTest(changes=changes):
                result = self.read({"status": "success", "correct": True, **changes})
                self.assertFalse(result.resolve(ObservationClaims()).valid)
                with self.assertRaises(ArchiveFailure) as error:
                    result.resolve(ObservationClaims(valid=True))
                self.assertEqual(error.exception.kind, "result_override")

    def test_package_and_static_checks_do_not_imply_complete_validity(self) -> None:
        for scope, stage in (("package_bytes", "package"), ("static_rule_subset", "rules")):
            with self.subTest(scope=scope):
                result = self.read({"schema_version": 3, "status": "success", "correct": None,
                                    "stage": stage, "validity_scope": scope, "candidate_hash": "a" * 64,
                                    "unchecked_rules": ["runtime_correctness"],
                                    "score": {"kind": "unknown"}})
                self.assertIsNone(result.metadata["valid"])
                with self.assertRaises(ArchiveFailure) as error:
                    result.resolve(ObservationClaims())
                self.assertEqual(error.exception.kind, "invalid_candidate")
                observation = result.resolve(ObservationClaims(valid=False, role="confirmation"))
                self.assertFalse(observation.valid)
                self.assertNotIn("value", observation.objective)
                self.assertEqual(result.metadata["validity_scope"], scope)
                self.assertEqual(observation.operation, stage)
                ledger = self.root / (stage + ".jsonl")
                command = [sys.executable, "-B", str(SCRIPTS / "candidate_archive.py"), "record", "--archive", str(ledger),
                           "--result", str(self.root / "result.json"), "--candidate-id", stage, "--route", "checks",
                           "--mechanism", "Artifact-only check", "--status", "unresolved", "--role", "confirmation"]
                rejected = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual(rejected.returncode, 2)
                self.assertFalse(ledger.exists())
                accepted = subprocess.run(command + ["--invalid"], capture_output=True, text=True, timeout=15)
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                record = json.loads(ledger.read_text())
                self.assertFalse(record["valid"])
                self.assertEqual(record["result"]["validity_scope"], scope)
                self.assertNotIn("value", record["objective"])
                self.assertFalse(observed_snapshot(record, implementation_identity(record)))

    def test_manual_scores_do_not_create_adapter_or_execution_provenance(self) -> None:
        result = ResultEvidence.read(None)
        observation = result.resolve(ObservationClaims(
            valid=True, objective_value=9, objective_direction="maximize", objective_kind="official_metric",
            objective_name="quality", evaluator_hash="e", workload_hash="w", score_model_hash="m", stage="full"))
        self.assertEqual(result.source_kind, "manual_claim")
        self.assertEqual(result.metadata, {})
        entry = {"role": observation.role, "valid": observation.valid, "objective": observation.objective,
                 "comparison": observation.comparison, "result": result.metadata,
                 "artifacts": {"source": "a" * 64}, "artifact_paths": {"source": "/not-an-execution.py"}}
        self.assertFalse(observed_snapshot(entry, implementation_identity(entry)))

    def test_legacy_facade_preserves_metadata_and_override_errors(self) -> None:
        archive = importlib.import_module("candidate_archive")
        result = self.read({"status": "success", "valid": True, "evaluator_hash": "e",
                            "score": {"kind": "official_metric", "metric": "quality", "direction": "maximize", "value": 4}})
        self.assertEqual(archive.result_metadata(self.root / "result.json"), result.metadata)
        for claims in (ObservationClaims(objective_value=5), ObservationClaims(evaluator_hash="other")):
            with self.subTest(claims=claims), self.assertRaises(ArchiveFailure) as error:
                result.resolve(claims)
            self.assertEqual(error.exception.kind, "result_override")
        self.assertEqual(archive.result_metadata(None), {})

    def test_result_interface_has_no_archive_or_campaign_import_dependency(self) -> None:
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from result_evidence import ResultEvidence, ObservationClaims; "
                "e = ResultEvidence.read(None); assert e.resolve(ObservationClaims(valid=True)).valid; "
                "assert 'candidate_archive' not in sys.modules; assert 'campaign_search' not in sys.modules")
        run = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS)], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
