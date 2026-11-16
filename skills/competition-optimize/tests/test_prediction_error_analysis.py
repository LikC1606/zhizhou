from __future__ import annotations

import copy
import csv
import importlib
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
analyzer = importlib.import_module("analyze_prediction_errors")
evaluator = importlib.import_module("evaluate_predictions")


class PredictionErrorAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\n001,0\n1,0\na,0\nb,0\n", encoding="utf-8")
        self.slices = self.root / "slices.csv"
        self.slices.write_text("id,regime,device\nb,easy,B\na,easy,A\n1,hard,B\n001,hard,A\n", encoding="utf-8")
        self.sequence = 0
        self.baseline = self.evaluate("id,prediction\nb,1\na,1\n1,4\n001,4\n")
        self.candidate = self.evaluate("id,prediction\n1,0\n001,0\na,2\nb,2\n")

    def evaluate(self, predictions: str, *extra: str) -> Path:
        self.sequence += 1
        source = self.root / f"prediction-{self.sequence}.csv"
        source.write_text(predictions, encoding="utf-8")
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
                "--output-dir", str(output), *extra]

    def analyze(self, *extra: str) -> tuple[dict, Path]:
        self.sequence += 1
        output = self.root / f"analysis-{self.sequence}"
        output.mkdir()
        args = analyzer.make_parser().parse_args(self.arguments(output, *extra))
        return analyzer.analyze(args, output), output

    def test_total_gain_with_slice_regression_is_visible_and_matches_hand_calculations(self) -> None:
        report, output = self.analyze("--slices", str(self.slices), "--slice-column", "regime",
                                      "--slice-column", "device", "--top-k", "1")
        comparison = report["aggregate_comparison"]
        self.assertAlmostEqual(comparison["baseline"]["score"], math.sqrt(8.5))
        self.assertAlmostEqual(comparison["candidate"]["score"], math.sqrt(2))
        self.assertEqual(comparison["metric_preference"], "candidate")
        self.assertEqual(report["case_preference_counts"], {"candidate": 2, "baseline": 2, "tie": 0})
        regimes = {row["value"]: row for row in report["slices"] if row["column"] == "regime"}
        self.assertEqual(regimes["hard"]["objective_improvement"], 4)
        self.assertEqual(regimes["easy"]["objective_improvement"], -1)
        self.assertAlmostEqual(regimes["easy"]["baseline_error_share"], 1 / 17)
        self.assertEqual(regimes["easy"]["candidate_error_share"], 1)
        self.assertEqual(report["error_share_kind"], "squared_error")
        self.assertEqual(report["largest_regressions"][0]["id"], "a")
        self.assertEqual(report["largest_candidate_errors"][0]["id"], "a")
        with (output / "cases.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["id"] for row in rows], ["001", "1", "a", "b"])
        self.assertEqual(rows[0]["slice:regime"], "hard")
        self.assertEqual((output / "baseline.csv").read_bytes(), (self.baseline.parent / "predictions.csv").read_bytes())
        self.assertEqual((output / "slices.csv").read_bytes(), self.slices.read_bytes())

    def test_mae_shares_use_absolute_loss_and_zero_errors_have_zero_shares(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,4\n1,4\na,1\nb,1\n", "--metric", "mae")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n", "--metric", "mae")
        report, _ = self.analyze("--slices", str(self.slices), "--slice-column", "regime")
        regimes = {row["value"]: row for row in report["slices"]}
        self.assertEqual(report["error_share_kind"], "absolute_error")
        self.assertAlmostEqual(regimes["hard"]["baseline_error_share"], 0.8)
        self.assertEqual(regimes["hard"]["candidate_error_share"], 0)
        self.assertEqual(report["aggregate_comparison"]["candidate"]["score"], 0)

    def test_binary_log_loss_uses_evaluation_clipping_and_case_improvements(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,1\na,0\nb,1\n", encoding="utf-8")
        self.baseline = self.evaluate("id,prediction\n001,0.5\n1,0.5\na,0.5\nb,0.5\n",
                                      "--metric", "binary_log_loss", "--log-loss-epsilon", "0.01")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,1\na,1\nb,0\n",
                                       "--metric", "binary_log_loss", "--log-loss-epsilon", "0.01")
        report, _ = self.analyze("--slices", str(self.slices), "--slice-column", "regime")
        regimes = {row["value"]: row for row in report["slices"]}
        self.assertAlmostEqual(regimes["hard"]["candidate_score"], -math.log(0.99))
        self.assertAlmostEqual(regimes["easy"]["candidate_score"], -math.log(0.01))
        self.assertEqual(report["per_case_error_kind"], "clipped_log_loss")
        self.assertEqual(report["case_preference_counts"], {"baseline": 2, "candidate": 2, "tie": 0})
        self.assertAlmostEqual(report["largest_regressions"][0]["candidate_error"], -math.log(0.01))

    def test_auc_reports_group_metrics_without_inventing_per_row_losses(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,0\na,1\nb,1\n", encoding="utf-8")
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--metric", "roc_auc")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,1\nb,1\n", "--metric", "roc_auc")
        report, output = self.analyze("--slices", str(self.slices), "--slice-column", "regime",
                                      "--slice-column", "device")
        self.assertEqual(report["aggregate_comparison"]["objective_improvement"], 0.5)
        self.assertIsNone(report["case_preference_counts"])
        self.assertIsNone(report["per_case_error_kind"])
        self.assertEqual(report["largest_regressions"], [])
        regimes = [row for row in report["slices"] if row["column"] == "regime"]
        devices = [row for row in report["slices"] if row["column"] == "device"]
        for row in regimes:
            self.assertIsNone(row["candidate_score"])
            self.assertEqual(row["unavailable_reason"], "roc_auc_requires_both_classes")
        for row in devices:
            self.assertEqual(row["candidate_score"], 1)
            self.assertEqual(row["baseline_score"], 0.5)
            self.assertIsNone(row["candidate_error_share"])
        with (output / "cases.csv").open(encoding="utf-8", newline="") as stream:
            self.assertTrue(all(row["candidate_error"] == "" for row in csv.DictReader(stream)))

    def test_large_residuals_can_be_diagnosed_without_squaring_overflow(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1e308\n1,1e308\na,0\nb,0\n")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,1e308\nb,1e308\n")
        report, _ = self.analyze("--slices", str(self.slices), "--slice-column", "regime")
        regimes = {row["value"]: row for row in report["slices"]}
        self.assertEqual(regimes["hard"]["baseline_error_share"], 1)
        self.assertEqual(regimes["easy"]["candidate_error_share"], 1)
        self.assertEqual(regimes["hard"]["objective_improvement"], 1e308)
        json.dumps(report, allow_nan=False)

    def test_rmse_regressions_rank_squared_loss_increase_rather_than_absolute_increase(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,100\n1,0\na,0\nb,0\n")
        self.candidate = self.evaluate("id,prediction\n001,101\n1,2\na,0\nb,0\n")
        report, _ = self.analyze("--top-k", "2")
        self.assertEqual([row["id"] for row in report["largest_regressions"]], ["001", "1"])
        self.assertEqual(report["squared_error_scale"], 101)
        first, second = report["largest_regressions"]
        self.assertEqual(first["error_improvement"], -1)
        self.assertEqual(second["error_improvement"], -2)
        self.assertAlmostEqual(first["scaled_squared_error_improvement"], -201 / 101 ** 2)
        self.assertAlmostEqual(second["scaled_squared_error_improvement"], -4 / 101 ** 2)

    def test_error_tolerance_changes_diagnostic_counts_only(self) -> None:
        report, _ = self.analyze("--error-tie-epsilon", "10")
        self.assertEqual(report["case_preference_counts"]["tie"], 4)
        self.assertEqual(report["largest_regressions"], [])
        self.assertEqual(report["aggregate_comparison"]["metric_preference"], "candidate")

    def test_exploratory_diagnostics_reject_confirmation_results(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--stage", "confirmation")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n", "--stage", "confirmation")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "development evaluations"):
            self.analyze()

    def test_truth_changes_and_prediction_corruption_fail(self) -> None:
        original_truth = self.truth.read_bytes()
        self.truth.write_bytes(original_truth + b"\n")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "Truth bytes differ"):
            self.analyze()
        self.truth.write_bytes(original_truth)
        (self.candidate.parent / "predictions.csv").write_text("id,prediction\nx,0\n", encoding="utf-8")
        with self.assertRaisesRegex(analyzer.ComparisonFailure, "snapshot differs"):
            self.analyze()

    def test_changed_evaluator_or_score_records_require_reevaluation(self) -> None:
        original_before = json.loads(self.baseline.read_text(encoding="utf-8"))
        original_after = json.loads(self.candidate.read_text(encoding="utf-8"))
        before, after = copy.deepcopy(original_before), copy.deepcopy(original_after)
        before["evaluator_hash"] = after["evaluator_hash"] = "0" * 64
        self.baseline.write_text(json.dumps(before), encoding="utf-8")
        self.candidate.write_text(json.dumps(after), encoding="utf-8")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "installed prediction evaluator"):
            self.analyze()
        self.baseline.write_text(json.dumps(original_before), encoding="utf-8")
        original_after["score"]["value"] = 0.25
        self.candidate.write_text(json.dumps(original_after), encoding="utf-8")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "Recomputed score differs"):
            self.analyze()

    def test_mismatched_metric_split_and_stage_are_rejected(self) -> None:
        for extra in [("--metric", "mae"), ("--split-id", "other"), ("--stage", "confirmation")]:
            self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n", *extra)
            with self.subTest(extra=extra), self.assertRaises(analyzer.ComparisonFailure):
                self.analyze()

    def test_malformed_or_incomplete_slice_inputs_fail(self) -> None:
        cases = [
            "id,regime\n001,hard\n1,hard\na,easy\n",
            "id,regime\n001,hard\n1,hard\na,easy\nb,easy\nx,easy\n",
            "id,regime\n001,hard\n001,hard\na,easy\nb,easy\n",
            "id,regime\n001,hard\n1, \na,easy\nb,easy\n",
            "id,regime,regime\n001,hard,hard\n",
            "id,regime\n001,hard,extra\n",
            "id,regime\n001\n",
        ]
        for text in cases:
            self.slices.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(analyzer.AnalysisFailure):
                self.analyze("--slices", str(self.slices), "--slice-column", "regime")

    def test_invalid_configuration_and_high_cardinality_slices_fail(self) -> None:
        cases = [
            ("--top-k", "0"), ("--top-k", "101"), ("--max-groups", "0"),
            ("--error-tie-epsilon", "nan"), ("--error-tie-epsilon", "-1"),
            ("--slices", str(self.slices)), ("--slice-column", "regime"),
            ("--slices", str(self.slices), "--slice-column", "regime", "--slice-column", "regime"),
            ("--slices", str(self.slices), "--slice-column", "id"),
            ("--slices", str(self.slices), "--slice-column", "missing"),
            ("--slices", str(self.slices), "--slice-column", "regime", "--max-groups", "1"),
        ]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(analyzer.AnalysisFailure):
                self.analyze(*extra)

    def test_custom_columns_and_utf8_bom_slice_metadata_work(self) -> None:
        self.truth.write_text("sample,label\n001,0\n1,0\n", encoding="utf-8")
        columns = ["--id-column", "sample", "--target-column", "label", "--prediction-column", "estimate"]
        self.baseline = self.evaluate("sample,estimate\n001,2\n1,2\n", *columns)
        self.candidate = self.evaluate("sample,estimate\n1,0\n001,0\n", *columns)
        self.slices.write_bytes(b"\xef\xbb\xbfsample,regime\n1,small\n001,large\n")
        report, _ = self.analyze("--slices", str(self.slices), "--slice-column", "regime")
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(len(report["slices"]), 2)

    def test_cli_writes_full_report_and_refuses_overwrite(self) -> None:
        output = self.root / "cli-analysis"
        command = [sys.executable, str(SCRIPT_DIR / "analyze_prediction_errors.py"),
                   *self.arguments(output, "--slices", str(self.slices), "--slice-column", "regime")]
        first = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["selection_scope"], "development_diagnostics_only")
        self.assertEqual(report["aggregate_comparison"]["metric_preference"], "candidate")
        before = (output / "report.json").read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 2)
        self.assertEqual((output / "report.json").read_bytes(), before)

    def test_cli_failure_records_reason_without_success_artifacts(self) -> None:
        self.truth.write_text("changed", encoding="utf-8")
        output = self.root / "failed-analysis"
        completed = subprocess.run([sys.executable, str(SCRIPT_DIR / "analyze_prediction_errors.py"),
                                    *self.arguments(output)], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 2)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed")
        self.assertIn("Truth bytes differ", report["error"]["message"])
        self.assertFalse((output / "cases.csv").exists())

    def test_summary_matches_full_diagnostics_for_all_metrics_and_references_slice_evidence(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,1\na,0\nb,1\n", encoding="utf-8")
        for metric in evaluator.METRIC_DIRECTIONS:
            with self.subTest(metric=metric):
                self.baseline = self.evaluate("id,prediction\n001,0.5\n1,0.5\na,0.5\nb,0.5\n", "--metric", metric)
                self.candidate = self.evaluate("id,prediction\nb,0.1\na,0.9\n1,0.9\n001,0.1\n", "--metric", metric)
                options = ("--slices", str(self.slices), "--slice-column", "regime",
                           "--slice-column", "device", "--top-k", "2")
                full, _ = self.analyze(*options)
                summary, output = self.analyze(*options, "--summary-only")
                for key in ["aggregate_comparison", "case_count", "case_preference_counts", "squared_error_scale",
                            "per_case_error_kind", "error_share_kind", "largest_candidate_errors",
                            "largest_regressions", "slices", "selection_scope", "error"]:
                    self.assertEqual(summary[key], full[key], key)
                self.assertEqual(summary["configuration"], {**full["configuration"], "output_mode": "summary"})
                self.assertNotEqual(summary["config_hash"], full["config_hash"])
                self.assertEqual(summary["inputs"]["slices"], str(self.slices.resolve()))
                self.assertEqual(summary["input_hashes"]["slices"], evaluator.byte_hash(self.slices.read_bytes()))
                for key, value in full["input_hashes"].items():
                    self.assertEqual(summary["input_hashes"][key], value)
                self.assertEqual(summary["artifacts"], [])
                self.assertEqual(list(output.iterdir()), [])

    def test_streaming_top_cases_keep_id_tie_order_with_more_cases_than_top_k(self) -> None:
        ids = [f"{index:03d}" for index in range(20)]
        self.truth.write_text("id,target\n" + "".join(f"{key},0\n" for key in reversed(ids)), encoding="utf-8")
        self.baseline = self.evaluate("id,prediction\n" + "".join(f"{key},1\n" for key in ids))
        self.candidate = self.evaluate("id,prediction\n" + "".join(f"{key},2\n" for key in reversed(ids)))
        for options in [(), ("--summary-only",)]:
            with self.subTest(options=options):
                report, _ = self.analyze("--top-k", "3", *options)
                self.assertEqual([row["id"] for row in report["largest_candidate_errors"]], ids[:3])
                self.assertEqual([row["id"] for row in report["largest_regressions"]], ids[:3])
                self.assertEqual(report["case_preference_counts"], {"baseline": 20, "candidate": 0, "tie": 0})

    def test_summary_keeps_confirmation_and_corrupt_evidence_rejections(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--stage", "confirmation")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n", "--stage", "confirmation")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "development evaluations"):
            self.analyze("--summary-only")
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n")
        result = json.loads(self.candidate.read_text())
        result["score"]["value"] = 10
        self.candidate.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "Recomputed score differs"):
            self.analyze("--summary-only")
        (self.candidate.parent / "predictions.csv").write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(analyzer.ComparisonFailure, "snapshot differs"):
            self.analyze("--summary-only")

    def test_summary_without_slices_retains_zero_loss_and_large_residual_behavior(self) -> None:
        for predictions in ["id,prediction\n001,0\n1,0\na,0\nb,0\n",
                            "id,prediction\n001,1e308\n1,1e308\na,0\nb,0\n"]:
            with self.subTest(predictions=predictions):
                self.baseline = self.evaluate(predictions)
                self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n")
                full, _ = self.analyze()
                summary, _ = self.analyze("--summary-only")
                for key in ["largest_candidate_errors", "largest_regressions", "case_preference_counts",
                            "aggregate_comparison", "squared_error_scale"]:
                    self.assertEqual(summary[key], full[key])
                self.assertNotIn("slices", summary["inputs"])
                json.dumps(summary, allow_nan=False)

    def test_summary_cli_saves_only_report_and_refuses_overwrite(self) -> None:
        output = self.root / "cli-summary"
        command = [sys.executable, str(SCRIPT_DIR / "analyze_prediction_errors.py"),
                   *self.arguments(output, "--summary-only", "--check-blend-direction")]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.name for path in output.iterdir()}, {"report.json"})
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["configuration"]["output_mode"], "summary")
        self.assertEqual(report["case_count"], 4)
        self.assertEqual(report["blend_direction"]["status"], "available")
        original = (output / "report.json").read_bytes()
        self.assertEqual(subprocess.run(command, capture_output=True, timeout=15).returncode, 2)
        self.assertEqual((output / "report.json").read_bytes(), original)


    def test_complementary_case_wins_can_have_no_beneficial_rmse_blend(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1\n1,2\na,1\nb,2\n")
        self.candidate = self.evaluate("id,prediction\n001,4\n1,1\na,4\nb,1\n")
        report, _ = self.analyze("--check-blend-direction", "--summary-only")
        self.assertEqual(report["case_preference_counts"], {"baseline": 2, "candidate": 2, "tie": 0})
        direction = report["blend_direction"]
        self.assertFalse(direction["strict_gain_over_best_parent_possible"])
        self.assertEqual(direction["minimizing_endpoints"], ["baseline"])
        self.assertEqual(direction["endpoint_inward_loss_derivative_sign"],
                         {"baseline": "positive", "candidate": "negative"})
        self.assertFalse(direction["recipe_evaluated"])

    def test_worse_parent_without_case_wins_can_still_help_but_equal_blend_can_fail(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n")
        self.candidate = self.evaluate("id,prediction\n001,-2\n1,2\na,-2\nb,2\n")
        report, _ = self.analyze("--check-blend-direction")
        self.assertEqual(report["case_preference_counts"], {"baseline": 4, "candidate": 0, "tie": 0})
        direction = report["blend_direction"]
        self.assertTrue(direction["strict_gain_over_best_parent_possible"])
        self.assertEqual(direction["minimizing_endpoints"], [])
        self.assertEqual(direction["endpoint_inward_loss_derivative_sign"],
                         {"baseline": "negative", "candidate": "negative"})
        self.assertGreater(math.sqrt((0.5 ** 2 + 1.5 ** 2) / 2), 1)  # Equal weights fail.
        self.assertLess(math.sqrt((0.4 ** 2 + 1.2 ** 2) / 2), 1)  # An interior weight helps.

    def test_descent_from_one_parent_does_not_establish_gain_over_the_best_parent(self) -> None:
        direction = analyzer.blend_directions("rmse", [0.0], [2.0], [1.0])
        self.assertFalse(direction["strict_gain_over_best_parent_possible"])
        self.assertEqual(direction["minimizing_endpoints"], ["candidate"])
        self.assertEqual(direction["endpoint_inward_loss_derivative_sign"],
                         {"baseline": "negative", "candidate": "positive"})

    def test_mae_zero_residual_kinks_and_flat_segment_have_no_strict_gain(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,0\n", encoding="utf-8")
        self.baseline = self.evaluate("id,prediction\n001,0\n1,2\n", "--metric", "mae")
        self.candidate = self.evaluate("id,prediction\n001,1\n1,1\n", "--metric", "mae")
        report, _ = self.analyze("--check-blend-direction")
        direction = report["blend_direction"]
        self.assertEqual(direction["convex_loss"], "mean_absolute_error")
        self.assertEqual(direction["endpoint_inward_loss_derivative_sign"],
                         {"baseline": "zero", "candidate": "zero"})
        self.assertEqual(direction["minimizing_endpoints"], ["baseline", "candidate"])
        self.assertFalse(direction["strict_gain_over_best_parent_possible"])

    def test_identical_and_perfect_parents_cannot_be_strictly_improved(self) -> None:
        for metric in ["rmse", "mae"]:
            for labels, before, after in [([0.0], [2.0], [2.0]), ([1.0], [1.0], [-2.0]),
                                          ([1.0], [1.0], [1.0])]:
                with self.subTest(metric=metric, before=before, after=after):
                    direction = analyzer.blend_directions(metric, labels, before, after)
                    self.assertFalse(direction["strict_gain_over_best_parent_possible"])
                    self.assertIn("baseline", direction["minimizing_endpoints"])

    def test_exact_signs_handle_overflow_underflow_and_near_cancellation(self) -> None:
        for metric in ["rmse", "mae"]:
            for residual in [1e308, 5e-324]:
                with self.subTest(metric=metric, residual=residual):
                    direction = analyzer.blend_directions(metric, [0.0], [residual], [-residual])
                    self.assertTrue(direction["strict_gain_over_best_parent_possible"])
                    json.dumps(direction, allow_nan=False)
        direction = analyzer.blend_directions("rmse", [0.0, 0.0], [1.0, 1.0], [0.0, 2 + 2 ** -51])
        self.assertEqual(direction["endpoint_inward_loss_derivative_sign"]["baseline"], "positive")
        self.assertFalse(direction["strict_gain_over_best_parent_possible"])
        self.baseline = self.evaluate("id,prediction\n001,1e308\n1,-1e308\na,1e308\nb,-1e308\n")
        self.candidate = self.evaluate("id,prediction\n001,-1e308\n1,1e308\na,-1e308\nb,1e308\n")
        report, _ = self.analyze("--summary-only", "--check-blend-direction")
        self.assertTrue(report["blend_direction"]["strict_gain_over_best_parent_possible"])
        json.dumps(report, allow_nan=False)

    def test_direction_matches_independent_exact_minima_and_parent_reversal(self) -> None:
        rng = random.Random(7)
        for metric in ["rmse", "mae"]:
            for _ in range(100):
                labels, before, after = [[Fraction(rng.randrange(-3, 4)) for _ in range(3)] for _ in range(3)]
                residual = [b - y for b, y in zip(before, labels)]
                delta = [c - b for b, c in zip(before, after)]

                def loss(weight: Fraction) -> Fraction:
                    errors = [r + weight * d for r, d in zip(residual, delta)]
                    return sum(e * e if metric == "rmse" else abs(e) for e in errors)

                weights = [Fraction(0), Fraction(1)]
                if metric == "rmse":
                    curvature = sum(d * d for d in delta)
                    if curvature:
                        weights.append(max(Fraction(0), min(Fraction(1),
                                           -sum(r * d for r, d in zip(residual, delta)) / curvature)))
                else:
                    weights.extend(-r / d for r, d in zip(residual, delta) if d and 0 < -r / d < 1)
                expected = min(map(loss, weights)) < min(loss(Fraction(0)), loss(Fraction(1)))
                direction = analyzer.blend_directions(metric, labels, before, after)
                reverse = analyzer.blend_directions(metric, labels, after, before)
                self.assertEqual(direction["strict_gain_over_best_parent_possible"], expected)
                self.assertEqual(reverse["strict_gain_over_best_parent_possible"], expected)
                signs = direction["endpoint_inward_loss_derivative_sign"]
                self.assertEqual(reverse["endpoint_inward_loss_derivative_sign"],
                                 {"baseline": signs["candidate"], "candidate": signs["baseline"]})

    def test_direction_is_opt_in_mode_independent_and_not_controlled_by_case_tolerance(self) -> None:
        default, _ = self.analyze()
        full, _ = self.analyze("--check-blend-direction")
        summary, _ = self.analyze("--check-blend-direction", "--summary-only", "--error-tie-epsilon", "100")
        self.assertNotIn("blend_direction", default)
        self.assertNotIn("check_blend_direction", default["configuration"])
        self.assertTrue(full["configuration"]["check_blend_direction"])
        self.assertEqual(full["blend_direction"], summary["blend_direction"])
        self.assertEqual(full["aggregate_comparison"], default["aggregate_comparison"])
        self.assertNotEqual(full["config_hash"], default["config_hash"])
        self.assertEqual(summary["case_preference_counts"]["tie"], 4)

    def test_binary_metrics_report_unavailable_instead_of_assuming_convexity(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,1\na,0\nb,1\n", encoding="utf-8")
        for metric in ["binary_log_loss", "roc_auc"]:
            with self.subTest(metric=metric):
                self.baseline = self.evaluate("id,prediction\n001,0.5\n1,0.5\na,0.5\nb,0.5\n", "--metric", metric)
                self.candidate = self.evaluate("id,prediction\n001,0\n1,1\na,1\nb,0\n", "--metric", metric)
                report, _ = self.analyze("--check-blend-direction")
                self.assertEqual(report["status"], "success")
                self.assertEqual(report["blend_direction"],
                                 {"status": "unavailable", "reason": "unsupported_metric",
                                  "metric": metric, "recipe_evaluated": False})

    def test_direction_option_preserves_development_and_evidence_requirements(self) -> None:
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n", "--stage", "confirmation")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n", "--stage", "confirmation")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "development evaluations"):
            self.analyze("--check-blend-direction")
        self.baseline = self.evaluate("id,prediction\n001,1\n1,1\na,1\nb,1\n")
        self.candidate = self.evaluate("id,prediction\n001,0\n1,0\na,0\nb,0\n")
        self.truth.write_bytes(self.truth.read_bytes() + b"\n")
        with self.assertRaisesRegex(analyzer.AnalysisFailure, "Truth bytes differ"):
            self.analyze("--check-blend-direction")


if __name__ == "__main__":
    unittest.main()
