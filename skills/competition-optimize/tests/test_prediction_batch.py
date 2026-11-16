from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
batch = importlib.import_module("evaluate_prediction_batch")
evaluator = importlib.import_module("evaluate_predictions")
comparator = importlib.import_module("compare_prediction_results")
evidence = importlib.import_module("prediction_evidence")


class PredictionBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\n001,0\n1,1\na,0\nb,1\n", encoding="utf-8")
        self.baseline, self.candidate = self.root / "baseline.csv", self.root / "candidate.csv"
        self.baseline.write_text("id,prediction\n001,0.5\n1,0.5\na,0.5\nb,0.5\n", encoding="utf-8")
        self.candidate.write_text("id,prediction\nb,0.9\na,0.1\n1,0.8\n001,0.2\n", encoding="utf-8")
        self.sequence = 0

    def arguments(self, output: Path, *extra: str) -> list[str]:
        return ["--truth", str(self.truth), "--candidate", "candidate", str(self.candidate),
                "--candidate", "baseline", str(self.baseline), "--baseline", "baseline",
                "--metric", "rmse", "--stage", "development", "--split-id", "dev",
                "--output-dir", str(output), *extra]

    def run_batch(self, *extra: str) -> tuple[dict, Path]:
        self.sequence += 1
        output = self.root / f"batch-{self.sequence}"
        args = batch.make_parser().parse_args(self.arguments(output, *extra))
        candidates = batch.validate_candidates(args.candidate, args.baseline)
        output.mkdir()
        return batch.run_batch(args, output, candidates), output

    def test_batch_matches_individual_scores_hashes_contracts_and_comparisons_for_all_metrics(self) -> None:
        for metric in evaluator.METRIC_DIRECTIONS:
            with self.subTest(metric=metric):
                report, output = self.run_batch("--metric", metric)
                self.assertEqual(report["status"], "success")
                singles = {}
                for name, source in [("baseline", self.baseline), ("candidate", self.candidate)]:
                    directory = self.root / f"single-{metric}-{name}"
                    directory.mkdir()
                    args = evaluator.make_parser().parse_args([
                        "--truth", str(self.truth), "--predictions", str(source), "--metric", metric,
                        "--stage", "development", "--split-id", "dev", "--output-dir", str(directory),
                    ])
                    single = evaluator.evaluate(args, directory)
                    write = directory / "result.json"
                    batch.write_json(write, single)
                    singles[name] = comparator.load_result(write)
                    saved = comparator.load_result(output / "evaluations" / name / "result.json")
                    for key in ["score", "candidate_hash", "evaluator_hash", "score_model_hash", "evaluation",
                                "checks", "validity_scope", "unchecked_rules"]:
                        self.assertEqual(saved[key], single[key])
                    self.assertEqual((directory / "predictions.csv").read_bytes(),
                                     (output / "evaluations" / name / "predictions.csv").read_bytes())
                expected = comparator.compare(singles["baseline"], singles["candidate"], 1e-12)
                actual = json.loads((output / "comparisons/candidate.json").read_text(encoding="utf-8"))
                for key in expected:
                    if key not in {"baseline", "candidate"}:
                        self.assertEqual(actual[key], expected[key])
                pair = evidence.load_pair(output / "evaluations/baseline/result.json",
                                          output / "evaluations/candidate/result.json", output / "truth.csv")
                self.assertEqual(pair.sample_ids, ["001", "1", "a", "b"])

    def test_failed_candidate_does_not_block_valid_candidates_or_comparisons(self) -> None:
        bad = self.root / "bad.csv"
        bad.write_text("id,prediction\n001,nan\n", encoding="utf-8")
        report, output = self.run_batch("--candidate", "bad", str(bad),
                                        "--candidate", "missing", str(self.root / "missing.csv"))
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual((report["successful_candidates"], report["failed_candidates"]), (2, 2))
        self.assertTrue((output / "comparisons/candidate.json").exists())
        for name in ["bad", "missing"]:
            result = json.loads((output / "evaluations" / name / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(result["valid"])
            self.assertIsNone(result["score"]["value"])
            self.assertFalse((output / "comparisons" / f"{name}.json").exists())

    def test_failed_baseline_never_produces_a_comparison(self) -> None:
        self.baseline.write_text("bad input", encoding="utf-8")
        report, output = self.run_batch()
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual(list((output / "comparisons").iterdir()), [])
        self.assertTrue(all(record["comparison"] is None for record in report["candidates"]))

    def test_single_candidate_without_baseline_supports_success_and_complete_failure(self) -> None:
        for name, source in [("valid", self.candidate), ("missing", self.root / "missing.csv")]:
            output = self.root / f"without-baseline-{name}"
            args = batch.make_parser().parse_args([
                "--truth", str(self.truth), "--candidate", name, str(source), "--metric", "rmse",
                "--stage", "development", "--split-id", "dev", "--output-dir", str(output),
            ])
            output.mkdir()
            report = batch.run_batch(args, output, batch.validate_candidates(args.candidate, args.baseline))
            self.assertEqual(report["status"], "success" if name == "valid" else "failed")
            self.assertIsNone(report["baseline"])
            self.assertFalse((output / "comparisons").exists())
            self.assertIsNone(report["candidates"][0]["comparison"])

    def test_custom_columns_clipping_confirmation_stage_and_score_kind_are_preserved(self) -> None:
        self.truth.write_text("key,y\n001,0\n1,1\n", encoding="utf-8")
        self.baseline.write_text("key,prob\n001,1\n1,0\n", encoding="utf-8")
        self.candidate.write_text("key,prob\n1,1\n001,0\n", encoding="utf-8")
        report, output = self.run_batch("--id-column", "key", "--target-column", "y", "--prediction-column", "prob",
                                        "--metric", "binary_log_loss", "--log-loss-epsilon", "0.01",
                                        "--stage", "confirmation", "--score-kind", "official_metric")
        self.assertEqual(report["status"], "success")
        result = comparator.load_result(output / "evaluations/candidate/result.json")
        self.assertEqual(result["score"]["parameters"], {"epsilon": 0.01})
        self.assertEqual(result["score"]["kind"], "official_metric")
        self.assertEqual(result["evaluation"]["stage"], "confirmation")

    def test_shared_truth_snapshot_stays_fixed_when_original_source_changes(self) -> None:
        original = self.truth.read_bytes()
        evaluate = evaluator.evaluate
        def mutate_source(args, directory):
            result = evaluate(args, directory)
            self.truth.write_text("id,target\n001,999\n1,999\na,999\nb,999\n", encoding="utf-8")
            return result
        with patch.object(evaluator, "evaluate", side_effect=mutate_source):
            report, output = self.run_batch()
        self.assertEqual(report["status"], "success")
        self.assertEqual((output / "truth.csv").read_bytes(), original)
        self.assertEqual(report["truth"]["hash"], evaluator.byte_hash(original))
        self.assertEqual(comparator.load_result(output / "evaluations/baseline/result.json")["score"]["value"], 0.5)

    def test_names_baseline_and_candidate_limit_are_validated_before_output_creation(self) -> None:
        for name in ["../escape", "A.", "CON", "nul.csv", "a/b", "模型"]:
            with self.subTest(name=name), self.assertRaises(batch.BatchFailure):
                batch.validate_candidates([[name, str(self.candidate)]], None)
        for members, baseline in [([], None), ([["a", "x"]] * 65, None),
                                  ([["a", "x"], ["A", "y"]], None), ([["a", "x"]], "A")]:
            with self.subTest(members=members, baseline=baseline), self.assertRaises(batch.BatchFailure):
                batch.validate_candidates(members, baseline)

    def test_truth_cannot_also_be_used_as_a_prediction_candidate(self) -> None:
        self.truth.write_text("id,target,prediction\n001,0,0\n1,1,1\n", encoding="utf-8")
        self.candidate.write_bytes(self.truth.read_bytes())
        report, output = self.run_batch("--candidate", "leak", str(self.truth))
        leak = next(record for record in report["candidates"] if record["name"] == "leak")
        self.assertFalse(leak["valid"])
        self.assertEqual(leak["error"]["type"], "invalid_input")

    def test_cli_preserves_completed_output_and_returns_failure_for_partial_or_invalid_batches(self) -> None:
        output = self.root / "中文输出"
        prefix = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "evaluate_prediction_batch.py")]
        command = [*prefix, *self.arguments(output)]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        originals = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
        repeated = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(repeated.returncode, 2)
        self.assertTrue(all(path.read_bytes() == raw for path, raw in originals.items()))
        partial = subprocess.run([*prefix, *self.arguments(self.root / "partial", "--candidate", "bad", "missing.csv")],
                                 capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(partial.returncode, 2)
        self.assertEqual(json.loads(partial.stderr)["status"], "partial_failure")
        invalid_output = self.root / "invalid"
        invalid = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT_DIR / "evaluate_prediction_batch.py"),
                                  *self.arguments(invalid_output, "--tie-epsilon", "nan")],
                                 capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(invalid_output.exists())


if __name__ == "__main__":
    unittest.main()
