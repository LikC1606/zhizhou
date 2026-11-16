from __future__ import annotations

import csv
import importlib
import itertools
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
estimator = importlib.import_module("compare_prediction_uncertainty")
evaluator = importlib.import_module("evaluate_predictions")


class BootstrapTests(unittest.TestCase):
    def assert_matches_resampled_metric(self, metric: str, labels: list[float], baseline: list[float],
                                       candidate: list[float], units: list[list[int]], seed: int = 8301) -> None:
        rows, draws = estimator.bootstrap(metric, labels, baseline, candidate, units, 200, seed, 1e-15, 10000)
        rng, expected_draws = random.Random(seed), 0
        for row in rows:
            indexes = [index for _ in units for index in units[rng.randrange(len(units))]]
            expected_draws += len(indexes)
            truth = [labels[index] for index in indexes]
            if metric == "roc_auc" and len(set(truth)) < 2:
                self.assertEqual(row["status"], "unavailable")
                continue
            expected = [evaluator.calculate_metric(metric, truth, [values[index] for index in indexes])
                        for values in [baseline, candidate]]
            self.assertEqual(row["case_count"], len(indexes))
            self.assertEqual(row["baseline_score"], expected[0])
            self.assertEqual(row["candidate_score"], expected[1])
            improvement = (expected[1] - expected[0] if metric == "roc_auc" else expected[0] - expected[1])
            self.assertEqual(row["objective_improvement"], improvement)
        self.assertEqual(draws, expected_draws)

    def test_cached_metrics_match_full_resampling_for_all_metrics_and_unequal_groups(self) -> None:
        labels = [0, 1, 1, 0, 1, 0, 0]
        baseline, candidate = [0, 1, 0.5, 0.5, 0, 1, 0.25], [0.7, 0.7, 0.5, 0.2, 1, 0, 0.7]
        for metric in evaluator.METRIC_DIRECTIONS:
            for units in [[[index] for index in range(7)], [[0], [1, 2, 3, 4], [5, 6]]]:
                with self.subTest(metric=metric, units=units):
                    self.assert_matches_resampled_metric(metric, labels, baseline, candidate, units)

    def test_regression_rescales_each_draw_when_extreme_rows_are_absent(self) -> None:
        labels, baseline, candidate = [0] * 4, [1e308, 1e-300, 2e-300, 3e-300], [5e307, 0, 1e-300, 2e-300]
        for metric in ["rmse", "mae"]:
            with self.subTest(metric=metric):
                self.assert_matches_resampled_metric(metric, labels, baseline, candidate, [[i] for i in range(4)])
                rows, _ = estimator.bootstrap(metric, labels, baseline, candidate, [[i] for i in range(4)],
                                              200, 8301, 1e-15, 10000)
                self.assertTrue(any(0 < row["baseline_score"] < 1e-299 for row in rows))

    def test_cached_auc_handles_signed_zero_extreme_ranks_and_unselected_tie_end_rows(self) -> None:
        labels = [0, 1, 1, 0, 0, 1]
        baseline, candidate = [-1e308, -0.0, 0.0, 1e308, 0.0, 1e308], [1e308, 0, 0, -1e308, 0, 0]
        self.assert_matches_resampled_metric("roc_auc", labels, baseline, candidate, [[0, 1], [2], [3, 4, 5]])

    def test_invalid_full_inputs_are_rejected_before_cached_sampling(self) -> None:
        cases = [("rmse", [0, 0], [1]), ("mae", [0, 0], [0, math.nan]),
                 ("rmse", [1e308, 0], [-1e308, 0]), ("binary_log_loss", [0, 1], [0, 2]),
                 ("roc_auc", [0, 0.5], [0, 1]), ("unknown", [0, 1], [0, 1])]
        for metric, labels, values in cases:
            with self.subTest(metric=metric, values=values), self.assertRaises(evaluator.PredictionFailure):
                estimator.bootstrap(metric, labels, values, values, [[0], [1]], 100, 0, 1e-15, 1000)

    def test_identical_predictions_have_exactly_zero_difference_in_every_paired_draw(self) -> None:
        labels = [1, 2, 3, 4]
        predictions = [1.2, 1.5, 3.7, 3]
        rows, draws = estimator.bootstrap("rmse", labels, predictions, predictions, [[i] for i in range(4)],
                                          100, 27, 1e-15, 1000)
        self.assertEqual(draws, 400)
        self.assertTrue(all(row["objective_improvement"] == 0 for row in rows))
        summary = estimator.summarize(rows, 0.95, 0)
        self.assertEqual(summary["objective_improvement_interval"]["lower"], 0)
        self.assertEqual(summary["objective_improvement_interval"]["upper"], 0)
        self.assertEqual(summary["evidence_preference"], "inconclusive")

    def test_group_draws_match_exhaustive_whole_cluster_oracle_with_unequal_sizes(self) -> None:
        units = [[0, 1], [2]]
        rows, _ = estimator.bootstrap("mae", [0, 0, 0], [1, 1, 9], [0, 0, 0], units, 100, 2, 1e-15, 1000)
        possible = set()
        for choices in itertools.product(range(2), repeat=2):
            indexes = [index for choice in choices for index in units[choice]]
            score = sum([1, 1, 9][index] for index in indexes) / len(indexes)
            possible.add((len(indexes), score))
        observed_counts = {row["case_count"] for row in rows}
        self.assertEqual(observed_counts, {count for count, score in possible})
        for row in rows:
            expected = next(score for count, score in possible if count == row["case_count"])
            self.assertAlmostEqual(row["objective_improvement"], expected)
        self.assertEqual(possible, {(4, 1), (3, 11 / 3), (2, 9)})

    def test_row_draws_match_independent_known_mae_difference_oracle(self) -> None:
        labels, baseline, candidate = [0, 0, 0], [1, 4, 3], [2, 0, 2]
        rows, _ = estimator.bootstrap("mae", labels, baseline, candidate, [[0], [1], [2]], 100, 5, 1e-15, 1000)
        rng = random.Random(5)
        for row in rows:
            indexes = [rng.randrange(3) for _ in range(3)]
            expected = sum([baseline[i] - candidate[i] for i in indexes]) / 3
            self.assertAlmostEqual(row["objective_improvement"], expected)

    def test_auc_direction_and_ties_are_preserved_with_missing_classes_recorded(self) -> None:
        labels = [0, 0, 1, 1]
        rows, _ = estimator.bootstrap("roc_auc", labels, [0.5] * 4, [0, 0, 1, 1], [[i] for i in range(4)],
                                      100, 3, 1e-15, 1000)
        self.assertTrue(any(row["status"] == "unavailable" for row in rows))
        for row in rows:
            if row["status"] == "success":
                self.assertEqual(row["objective_improvement"], 0.5)
            else:
                self.assertIsNone(row["candidate_score"])
                self.assertEqual(row["unavailable_reason"], "roc_auc_requires_both_classes")

    def test_auc_bootstrap_matches_independent_pairwise_ranking_oracle(self) -> None:
        labels, baseline, candidate = [0, 1, 0, 1], [0, 0, 1, 1], [0.2, 0.7, 0.1, 0.6]
        rows, _ = estimator.bootstrap("roc_auc", labels, baseline, candidate, [[i] for i in range(4)],
                                      100, 73, 1e-15, 1000)
        rng = random.Random(73)
        for row in rows:
            indexes = [rng.randrange(4) for _ in range(4)]
            positives = [index for index in indexes if labels[index] == 1]
            negatives = [index for index in indexes if labels[index] == 0]
            if not positives or not negatives:
                self.assertEqual(row["status"], "unavailable")
                continue
            def auc(predictions: list[float]) -> float:
                return sum(1 if predictions[pos] > predictions[neg] else
                           0.5 if predictions[pos] == predictions[neg] else 0
                           for pos in positives for neg in negatives) / (len(positives) * len(negatives))
            self.assertEqual(row["objective_improvement"], auc(candidate) - auc(baseline))

    def test_insufficient_valid_auc_draws_do_not_produce_a_confidence_interval(self) -> None:
        rows, _ = estimator.bootstrap("roc_auc", [0, 1], [0.5, 0.5], [0, 1], [[0], [1]], 200, 1, 1e-15, 1000)
        summary = estimator.summarize(rows, 0.95, 0)
        self.assertEqual(summary["status"], "unavailable")
        self.assertGreater(summary["invalid_replicates"], 20)
        self.assertIsNone(summary["objective_improvement_interval"])
        self.assertEqual(summary["evidence_preference"], "inconclusive")

    def test_reproducible_seed_and_quantile_interpolation(self) -> None:
        args = ("mae", [0, 0, 0], [1, 2, 9], [0, 0, 0], [[0], [1], [2]])
        first, _ = estimator.bootstrap(*args, 100, 9, 1e-15, 1000)
        second, _ = estimator.bootstrap(*args, 100, 9, 1e-15, 1000)
        third, _ = estimator.bootstrap(*args, 100, 10, 1e-15, 1000)
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertEqual(estimator.percentile([0, 10], 0.25), 2.5)
        self.assertEqual(estimator.percentile([-1e308, 1e308], 0.5), 0)

    def test_practical_threshold_keeps_small_consistent_gain_inconclusive(self) -> None:
        rows, _ = estimator.bootstrap("mae", [0, 0], [0.1, 0.1], [0, 0], [[0], [1]], 100, 0, 1e-15, 1000)
        self.assertEqual(estimator.summarize(rows, 0.95, 0)["evidence_preference"], "candidate_supported")
        self.assertEqual(estimator.summarize(rows, 0.95, 0.1)["evidence_preference"], "inconclusive")
        reverse, _ = estimator.bootstrap("mae", [0, 0], [0, 0], [0.1, 0.1], [[0], [1]], 100, 0, 1e-15, 1000)
        self.assertEqual(estimator.summarize(reverse, 0.95, 0)["evidence_preference"], "baseline_supported")

    def test_positive_observed_gain_can_have_an_interval_crossing_zero(self) -> None:
        rows, _ = estimator.bootstrap("mae", [0, 0], [0, 10], [5, 0], [[0], [1]], 500, 17, 1e-15, 2000)
        summary = estimator.summarize(rows, 0.95, 0)
        interval = summary["objective_improvement_interval"]
        self.assertLess(interval["lower"], 0)
        self.assertGreater(interval["upper"], 0)
        self.assertEqual(summary["evidence_preference"], "inconclusive")

    def test_sampling_units_and_compute_bounds_are_enforced(self) -> None:
        for units in [[[0, 1]], [[0], []], [[0], [0, 1]], [[0], [2]]]:
            with self.subTest(units=units), self.assertRaises(estimator.UncertaintyFailure):
                estimator.bootstrap("mae", [0, 0], [1, 1], [0, 0], units, 100, 0, 1e-15, 1000)
        for samples, budget in [(99, 1000), (10001, 1000), (100, 0), (100, 199)]:
            with self.subTest(samples=samples, budget=budget), self.assertRaises(estimator.UncertaintyFailure):
                estimator.bootstrap("mae", [0, 0], [1, 1], [0, 0], [[0], [1]], samples, 0, 1e-15, budget)

    def test_unequal_group_draws_cannot_exceed_budget_even_when_expected_work_fits(self) -> None:
        # Expected 300 row draws; this seed draws 310 from two unequal groups.
        with self.assertRaisesRegex(estimator.UncertaintyFailure, "Bootstrap exceeded"):
            estimator.bootstrap("mae", [0, 0, 0], [1, 1, 1], [0, 0, 0], [[0], [1, 2]],
                                100, 3, 1e-15, 300)


class UncertaintyWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\n001,0\n1,0\na,0\nb,0\n", encoding="utf-8")
        self.groups = self.root / "groups.csv"
        self.groups.write_text("id,patient\nb,p2\na,p2\n1,p1\n001,p1\n", encoding="utf-8")
        self.sequence = 0
        self.baseline = self.evaluate("id,prediction\n001,2\n1,2\na,2\nb,2\n")
        self.candidate = self.evaluate("id,prediction\nb,1\na,1\n1,1\n001,1\n")

    def evaluate(self, csv_text: str, *extra: str) -> Path:
        self.sequence += 1
        source = self.root / f"prediction-{self.sequence}.csv"
        source.write_text(csv_text, encoding="utf-8")
        output = self.root / f"evaluation-{self.sequence}"
        output.mkdir()
        args = evaluator.make_parser().parse_args([
            "--truth", str(self.truth), "--predictions", str(source), "--metric", "rmse",
            "--stage", "development", "--split-id", "dev", "--output-dir", str(output), *extra,
        ])
        result = evaluator.evaluate(args, output)
        path = output / "result.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return path

    def arguments(self, output: Path, *extra: str) -> list[str]:
        return ["--baseline", str(self.baseline), "--candidate", str(self.candidate), "--truth", str(self.truth),
                "--resampling-unit", "row", "--bootstrap-samples", "100", "--output-dir", str(output), *extra]

    def assess(self, *extra: str) -> tuple[dict, Path]:
        self.sequence += 1
        output = self.root / f"uncertainty-{self.sequence}"
        output.mkdir()
        args = estimator.make_parser().parse_args(self.arguments(output, *extra))
        return estimator.assess(args, output), output

    def test_group_workflow_preserves_metadata_and_replicates_with_exact_id_alignment(self) -> None:
        report, output = self.assess("--resampling-unit", "group", "--groups", str(self.groups), "--group-column", "patient")
        self.assertEqual(report["sampling_unit_count"], 2)
        self.assertEqual(report["uncertainty"]["evidence_preference"], "candidate_supported")
        self.assertEqual(report["aggregate_comparison"]["objective_improvement"], 1)
        self.assertEqual(report["row_draws"], 400)
        self.assertEqual((output / "groups.csv").read_bytes(), self.groups.read_bytes())
        self.assertEqual((output / "candidate.csv").read_bytes(), (self.candidate.parent / "predictions.csv").read_bytes())
        with (output / "bootstrap.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 100)
        self.assertTrue(all(float(row["objective_improvement"]) == 1 for row in rows))

    def test_frozen_confirmation_comparison_is_supported_without_error_diagnostics(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,2\n1,2\na,2\nb,2\n", "--stage", "confirmation")
        self.candidate = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--stage", "confirmation")
        report, _ = self.assess()
        self.assertEqual(report["aggregate_comparison"]["stage"], "confirmation")
        self.assertEqual(report["uncertainty"]["evidence_preference"], "candidate_supported")

    def test_log_loss_and_auc_use_original_score_formula_and_direction(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,1\na,0\nb,1\n", encoding="utf-8")
        for metric in ["binary_log_loss", "roc_auc"]:
            self.baseline = self.evaluate("id,prediction\n001,0.5\n1,0.5\na,0.5\nb,0.5\n", "--metric", metric)
            self.candidate = self.evaluate("id,prediction\n001,0\n1,1\na,0\nb,1\n", "--metric", metric)
            report, _ = self.assess("--resampling-unit", "group", "--groups", str(self.groups),
                                    "--group-column", "patient", "--bootstrap-samples", "1000", "--seed", "5")
            self.assertGreater(report["aggregate_comparison"]["objective_improvement"], 0)
            self.assertEqual(report["uncertainty"]["evidence_preference"], "candidate_supported")

    def test_group_mode_requires_complete_non_empty_metadata_and_two_clusters(self) -> None:
        for content in ["id,patient\n001,p1\n1,p1\na,p1\nb,p1\n", "id,patient\n001,p1\n1,p1\na,p2\n",
                        "id,patient\n001,p1\n1,p1\na, \nb,p2\n", "id,patient\n001,p1\n001,p1\na,p2\nb,p2\n"]:
            self.groups.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises((estimator.UncertaintyFailure, estimator.EvidenceFailure)):
                self.assess("--resampling-unit", "group", "--groups", str(self.groups), "--group-column", "patient")

    def test_invalid_options_and_mismatched_evaluations_are_rejected(self) -> None:
        options = [
            ("--confidence-level", "nan"), ("--confidence-level", "0"), ("--confidence-level", "1"),
            ("--minimum-improvement", "-1"), ("--minimum-improvement", "inf"), ("--groups", str(self.groups)),
            ("--group-column", "patient"), ("--resampling-unit", "group"),
            ("--resampling-unit", "group", "--groups", str(self.groups), "--group-column", "id"),
        ]
        for extra in options:
            with self.subTest(extra=extra), self.assertRaises(estimator.UncertaintyFailure):
                self.assess(*extra)
        self.candidate = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--metric", "mae")
        with self.assertRaises(estimator.ComparisonFailure):
            self.assess()

    def test_corrupt_score_record_and_changed_truth_are_rejected(self) -> None:
        result = json.loads(self.candidate.read_text(encoding="utf-8"))
        result["score"]["value"] = 0.2
        self.candidate.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(estimator.EvidenceFailure, "Recomputed score differs"):
            self.assess()
        self.truth.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(estimator.EvidenceFailure, "Truth bytes differ"):
            self.assess()

    def test_cli_reproduces_bootstrap_and_refuses_overwrite(self) -> None:
        output = self.root / "cli-uncertainty"
        command = [sys.executable, str(SCRIPT_DIR / "compare_prediction_uncertainty.py"), *self.arguments(output)]
        first = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["uncertainty"]["evidence_preference"], "candidate_supported")
        before = (output / "report.json").read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 2)
        self.assertEqual((output / "report.json").read_bytes(), before)
        repeated = self.root / "cli-repeated"
        third = subprocess.run([sys.executable, str(SCRIPT_DIR / "compare_prediction_uncertainty.py"),
                                *self.arguments(repeated)], capture_output=True, text=True, timeout=15)
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual((output / "bootstrap.csv").read_bytes(), (repeated / "bootstrap.csv").read_bytes())

    def test_cli_budget_failure_records_reason_and_no_success_artifacts(self) -> None:
        output = self.root / "budget-failure"
        completed = subprocess.run([sys.executable, str(SCRIPT_DIR / "compare_prediction_uncertainty.py"),
                                    *self.arguments(output, "--max-row-draws", "10")],
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 2)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertIn("max-row-draws", report["error"]["message"])
        self.assertFalse((output / "bootstrap.csv").exists())


if __name__ == "__main__":
    unittest.main()
