from __future__ import annotations

import copy
import importlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
blender = importlib.import_module("blend_predictions")
evaluator = importlib.import_module("evaluate_predictions")
comparator = importlib.import_module("compare_prediction_results")


class PredictionBlendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\n001,2\n1,4\n", encoding="utf-8")
        self.sequence = 0
        self.left = self.evaluation("id,prediction\n001,0\n1,2\n")
        self.right = self.evaluation("id,prediction\n1,6\n001,4\n")

    def evaluation(self, csv_text: str, *extra: str) -> Path:
        self.sequence += 1
        source = self.root / f"source-{self.sequence}.csv"
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

    def create_arguments(self, output: Path, weights: list[str] | None = None) -> list[str]:
        return ["create", "--member", "left", str(self.left), "--member", "right", str(self.right),
                "--weights", *(weights or ["1", "1"]), "--output-dir", str(output)]

    def create(self, weights: list[str] | None = None) -> tuple[Path, dict]:
        self.sequence += 1
        output = self.root / f"blend-{self.sequence}"
        output.mkdir()
        args = blender.make_parser().parse_args(self.create_arguments(output, weights))
        return output, blender.build(args, output)

    def recipe(self) -> dict:
        output, _ = self.create()
        return blender.load_recipe(output / "recipe.json")

    def test_weighted_blend_aligns_exact_ids_and_preserves_parent_snapshots(self) -> None:
        left_snapshot = (self.left.parent / "predictions.csv").read_bytes()
        right_snapshot = (self.right.parent / "predictions.csv").read_bytes()
        output, result = self.create(["1", "3"])
        raw = (output / "predictions.csv").read_bytes()
        self.assertEqual(evaluator.read_values(raw, "id", "prediction", "blend"), {"001": 3, "1": 5})
        recipe = blender.load_recipe(output / "recipe.json")
        self.assertEqual([member["weight"] for member in recipe["members"]], [0.25, 0.75])
        self.assertEqual(result["candidate_hash"], evaluator.byte_hash(raw))
        self.assertIsNone(result["score"]["value"])
        for name in ["left", "right"]:
            self.assertEqual((output / "parents" / f"{name}.csv").read_bytes(),
                             left_snapshot if name == "left" else right_snapshot)
        (self.left.parent / "predictions.csv").write_text("changed", encoding="utf-8")
        self.assertEqual((output / "parents" / "left.csv").read_bytes(), left_snapshot)

    def test_fixed_recipe_applies_to_new_ids_by_member_name_without_labels(self) -> None:
        development, _ = self.create(["3", "1"])
        left, right = self.root / "test-left.csv", self.root / "test-right.csv"
        left.write_text("id,prediction\nb,10\na,20\n", encoding="utf-8")
        right.write_text("id,prediction\na,40\nb,30\n", encoding="utf-8")
        output = self.root / "applied"
        output.mkdir()
        args = blender.make_parser().parse_args([
            "apply", "--recipe", str(development / "recipe.json"),
            "--member", "right", str(right), "--member", "left", str(left), "--output-dir", str(output),
        ])
        result = blender.build(args, output)
        self.assertEqual(evaluator.read_values((output / "predictions.csv").read_bytes(), "id", "prediction", "test"),
                         {"a": 25, "b": 15})
        self.assertEqual((output / "recipe.json").read_bytes(), (development / "recipe.json").read_bytes())
        self.assertIn("member_model_identity", result["unchecked_rules"])

    def test_reapplying_recipe_reproduces_exact_prediction_bytes(self) -> None:
        output, result = self.create(["2", "1"])
        recipe = blender.load_recipe(output / "recipe.json")
        inputs = {name: (output / "parents" / f"{name}.csv").read_bytes() for name in ["right", "left"]}
        raw, count = blender.blend_csv(recipe, inputs)
        self.assertEqual(raw, (output / "predictions.csv").read_bytes())
        self.assertEqual(evaluator.byte_hash(raw), result["candidate_hash"])
        self.assertEqual(count, 2)

    def test_blend_can_improve_metric_when_parent_errors_are_complementary(self) -> None:
        output, _ = self.create()
        blend_result = self.evaluation((output / "predictions.csv").read_text(encoding="utf-8"))
        baseline, candidate = comparator.load_result(self.left), comparator.load_result(blend_result)
        self.assertEqual(baseline["score"]["value"], 2)
        self.assertEqual(candidate["score"]["value"], 0)
        self.assertEqual(comparator.compare(baseline, candidate, 0)["metric_preference"], "candidate")

    def test_confirmation_results_cannot_be_used_to_create_a_recipe(self) -> None:
        self.left = self.evaluation("id,prediction\n001,0\n1,2\n", "--stage", "confirmation")
        self.right = self.evaluation("id,prediction\n001,4\n1,6\n", "--stage", "confirmation")
        with self.assertRaisesRegex(blender.BlendFailure, "development results only"):
            self.create()

    def test_creation_rejects_mismatched_metrics_splits_stages_and_corrupt_snapshots(self) -> None:
        for extra in [("--metric", "mae"), ("--split-id", "other"), ("--stage", "confirmation")]:
            self.right = self.evaluation("id,prediction\n001,4\n1,6\n", *extra)
            with self.subTest(extra=extra), self.assertRaises(comparator.ComparisonFailure):
                self.create()
        self.right = self.evaluation("id,prediction\n001,4\n1,6\n")
        (self.right.parent / "predictions.csv").write_text("id,prediction\n001,1\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(comparator.ComparisonFailure, "snapshot differs"):
            self.create()

    def test_invalid_weights_and_extreme_weight_ranges_fail(self) -> None:
        for weights in [[], [1], [1, 2, 3], [0, 0], [1, -1], [1, math.inf], [1, math.nan],
                        [True, 1], [5e-324, 1e308]]:
            with self.subTest(weights=weights), self.assertRaises(blender.BlendFailure):
                blender.normalize_weights(weights, 2)
        self.assertEqual(blender.normalize_weights([1e308, 1e308], 2), [0.5, 0.5])

    def test_duplicate_invalid_or_single_member_names_fail(self) -> None:
        for names in [["left"], ["left", "left"], ["left", "LEFT"], ["../left", "right"], ["", "right"], ["x" * 65, "right"],
                      ["CON", "right"], ["nul.csv", "right"], ["Com1", "right"]]:
            with self.subTest(names=names), self.assertRaises(blender.BlendFailure):
                blender.named_paths([[name, str(self.left)] for name in names])

    def test_apply_rejects_different_member_sets_id_coverage_and_non_finite_values(self) -> None:
        recipe = self.recipe()
        good = b"id,prediction\nx,1\ny,2\n"
        cases = [
            {"left": good}, {"left": good, "other": good},
            {"left": good, "right": b"id,prediction\nx,1\n"},
            {"left": good, "right": b"id,prediction\nx,nan\ny,2\n"},
            {"left": good, "right": b"id,prediction\nx,1\nx,2\n"},
        ]
        for inputs in cases:
            with self.subTest(inputs=inputs), self.assertRaises((blender.BlendFailure, evaluator.PredictionFailure)):
                blender.blend_csv(recipe, inputs)

    def test_custom_columns_survive_recipe_application(self) -> None:
        self.truth.write_text("sample,label\n001,2\n1,4\n", encoding="utf-8")
        columns = ["--id-column", "sample", "--target-column", "label", "--prediction-column", "estimate"]
        self.left = self.evaluation("sample,estimate\n001,0\n1,2\n", *columns)
        self.right = self.evaluation("sample,estimate\n001,4\n1,6\n", *columns)
        output, _ = self.create()
        self.assertEqual(evaluator.read_values((output / "predictions.csv").read_bytes(), "sample", "estimate", "blend"),
                         {"001": 2, "1": 4})

    def test_probability_blends_remain_valid_for_binary_log_loss(self) -> None:
        self.truth.write_text("id,target\n001,0\n1,1\n", encoding="utf-8")
        self.left = self.evaluation("id,prediction\n001,0\n1,0.6\n", "--metric", "binary_log_loss")
        self.right = self.evaluation("id,prediction\n001,0.4\n1,1\n", "--metric", "binary_log_loss")
        output, _ = self.create()
        result = comparator.load_result(self.evaluation((output / "predictions.csv").read_text(encoding="utf-8"),
                                                       "--metric", "binary_log_loss"))
        self.assertAlmostEqual(result["score"]["value"], -math.log(0.8))

    def test_large_values_cancellation_and_zero_weight_endpoints_are_finite(self) -> None:
        recipe = self.recipe()
        recipe["members"] = [{"name": name, "weight": 1 / 3} for name in ["a", "b", "c"]]
        raw, _ = blender.blend_csv(recipe, {"a": b"id,prediction\nx,1e308\n",
                                          "b": b"id,prediction\nx,-1e308\n",
                                          "c": b"id,prediction\nx,1e-300\n"})
        self.assertAlmostEqual(evaluator.read_values(raw, "id", "prediction", "blend")["x"] / 1e-300, 1 / 3)
        recipe["members"] = [{"name": "left", "weight": 1}, {"name": "right", "weight": 0}]
        raw, _ = blender.blend_csv(recipe, {"left": b"id,prediction\nx,1e-300\n",
                                          "right": b"id,prediction\nx,1e308\n"})
        self.assertEqual(evaluator.read_values(raw, "id", "prediction", "blend")["x"], 1e-300)
        recipe["members"][0]["weight"] = recipe["members"][1]["weight"] = 0.5
        raw, _ = blender.blend_csv(recipe, {"left": b"id,prediction\nx,1.7976931348623157e308\n",
                                          "right": b"id,prediction\nx,1.7976931348623157e308\n"})
        self.assertEqual(evaluator.read_values(raw, "id", "prediction", "blend")["x"], sys.float_info.max)

    def test_modified_recipe_fails_hash_check(self) -> None:
        recipe = self.recipe()
        recipe["members"][0]["weight"] = 0.2
        path = self.root / "edited-recipe.json"
        path.write_text(json.dumps(recipe), encoding="utf-8")
        with self.assertRaisesRegex(blender.BlendFailure, "does not match its hash"):
            blender.load_recipe(path)

    def test_invalid_rehashed_recipe_contents_are_rejected(self) -> None:
        original = self.recipe()
        mutations = [
            lambda r: r.update(schema_version=True), lambda r: r.update(operation="unknown"),
            lambda r: r.update(id_column="prediction"), lambda r: r["selection_contract"].update(stage="confirmation"),
            lambda r: r["members"][0].update(weight=True), lambda r: r["members"][0].update(weight=-1),
            lambda r: r["members"][0].update(weight=0.1), lambda r: r["members"][0].update(name="right"),
            lambda r: r["members"][0].update(development_candidate_hash="missing"),
        ]
        path = self.root / "invalid-recipe.json"
        for mutate in mutations:
            recipe = copy.deepcopy(original)
            mutate(recipe)
            recipe["recipe_hash"] = evaluator.object_hash({key: value for key, value in recipe.items() if key != "recipe_hash"})
            path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.subTest(recipe=recipe), self.assertRaises(blender.BlendFailure):
                blender.load_recipe(path)

    def test_cli_create_apply_and_evaluate_reproduce_a_candidate_and_preserve_outputs(self) -> None:
        output = self.root / "cli-blend"
        command = [sys.executable, str(SCRIPT_DIR / "blend_predictions.py"), *self.create_arguments(output)]
        first = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (output / "manifest.json").read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 2)
        self.assertEqual((output / "manifest.json").read_bytes(), before)
        applied = self.root / "cli-apply"
        application = subprocess.run([
            sys.executable, str(SCRIPT_DIR / "blend_predictions.py"), "apply", "--recipe", str(output / "recipe.json"),
            "--member", "right", str(output / "parents" / "right.csv"),
            "--member", "left", str(output / "parents" / "left.csv"), "--output-dir", str(applied),
        ], capture_output=True, text=True, timeout=15)
        self.assertEqual(application.returncode, 0, application.stderr)
        self.assertEqual((applied / "predictions.csv").read_bytes(), (output / "predictions.csv").read_bytes())
        evaluated = self.root / "cli-evaluated"
        evaluation = subprocess.run([
            sys.executable, str(SCRIPT_DIR / "evaluate_predictions.py"), "--truth", str(self.truth),
            "--predictions", str(applied / "predictions.csv"), "--metric", "rmse", "--stage", "development",
            "--split-id", "dev", "--output-dir", str(evaluated),
        ], capture_output=True, text=True, timeout=15)
        self.assertEqual(evaluation.returncode, 0, evaluation.stderr)
        self.assertEqual(json.loads(evaluation.stdout)["score"]["value"], 0)

    def test_cli_failure_has_no_score_or_constructed_candidate(self) -> None:
        output = self.root / "bad-blend"
        completed = subprocess.run([sys.executable, str(SCRIPT_DIR / "blend_predictions.py"),
                                    *self.create_arguments(output, ["0", "0"])],
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 2)
        result = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["score"]["value"])
        self.assertFalse((output / "predictions.csv").exists())

    def test_frozen_recipe_is_evaluated_on_a_separate_confirmation_split(self) -> None:
        development, _ = self.create()
        left, right = self.root / "confirm-left.csv", self.root / "confirm-right.csv"
        left.write_text("id,prediction\nx,8\ny,18\n", encoding="utf-8")
        right.write_text("id,prediction\ny,22\nx,12\n", encoding="utf-8")
        output = self.root / "confirm-blend"
        output.mkdir()
        args = blender.make_parser().parse_args([
            "apply", "--recipe", str(development / "recipe.json"),
            "--member", "left", str(left), "--member", "right", str(right), "--output-dir", str(output),
        ])
        blender.build(args, output)
        self.truth.write_text("id,target\nx,10\ny,20\n", encoding="utf-8")
        baseline = comparator.load_result(self.evaluation(left.read_text(encoding="utf-8"),
                                                          "--stage", "confirmation", "--split-id", "confirm"))
        candidate = comparator.load_result(self.evaluation((output / "predictions.csv").read_text(encoding="utf-8"),
                                                           "--stage", "confirmation", "--split-id", "confirm"))
        comparison = comparator.compare(baseline, candidate, 0)
        self.assertEqual(comparison["stage"], "confirmation")
        self.assertEqual(comparison["metric_preference"], "candidate")
        self.assertNotEqual(candidate["evaluation"]["split_hash"],
                            blender.load_recipe(development / "recipe.json")["selection_contract"]["split_hash"])
        self.assertEqual((output / "recipe.json").read_bytes(), (development / "recipe.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
