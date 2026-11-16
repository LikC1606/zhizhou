"""Exercise real local fitting and delivery when optional ML dependencies exist."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import tabular_training as adapter
from prediction_core import compare, load_result

ML_AVAILABLE = all(importlib.util.find_spec(name) for name in ["sklearn", "numpy", "joblib", "threadpoolctl"])


class SplitContractTests(unittest.TestCase):
    def test_group_overlap_rejected(self):
        with self.assertRaisesRegex(adapter.TrainingFailure, "groups overlap"):
            adapter.check_boundary({"split": {"kind": "group", "group_column": "group"}},
                                   {"a": {"group": "same"}}, {"b": {"group": "same"}})

    def test_time_availability_and_gap(self):
        spec = {"split": {"kind": "time", "time_column": "time", "time_format": "number",
                          "available_time_column": "available", "minimum_time_gap": "2"}}
        earlier = {"a": {"time": "1", "available": "5"}}
        for next_time in ["4", "5", "6"]:
            with self.subTest(next_time=next_time), self.assertRaises(adapter.TrainingFailure):
                adapter.check_boundary(spec, earlier, {"b": {"time": next_time}})
        adapter.check_boundary(spec, earlier, {"b": {"time": "7"}})


@unittest.skipUnless(ML_AVAILABLE, "Optional dependencies: scripts/requirements-tabular.txt")
class TabularTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data.csv"
        adapter.save_csv(self.data, ["id", "x", "target", "group", "time"],
                         [(str(i), i, i * 3 + 2, str(i // 2), i) for i in range(12)])
        self.spec = {"schema_version": 1, "task_id": "local-regression", "task": "regression",
                     "metric": "rmse", "features": ["x"], "split": {"kind": "group", "group_column": "group"},
                     "expected_oof_ids": [str(i) for i in range(12)], "folds": [
                         {"id": str(j), "seed": 100 + j,
                          "train_ids": [str(i) for i in range(12) if i // 2 % 3 != j],
                          "validation_ids": [str(i) for i in range(12) if i // 2 % 3 == j]} for j in range(3)]}
        self.protocol = self.root / "protocol.json"
        self.protocol.write_text(json.dumps(self.spec))
        self.candidate = self.root / "candidate.py"
        self.candidate.write_text("from sklearn.pipeline import make_pipeline\n"
                                  "from sklearn.preprocessing import StandardScaler\n"
                                  "from sklearn.linear_model import LinearRegression\n"
                                  "def build_model(seed, task):\n"
                                  "    return make_pipeline(StandardScaler(), LinearRegression())\n")

    def train(self, name="run"):
        output = self.root / name
        adapter.train(self.data, self.protocol, self.candidate, output)
        return output

    def frozen(self):
        run = self.train()
        frozen = self.root / "frozen"
        adapter.freeze(run, frozen, "Deliver only if the frozen candidate passes the independent confirmation rule")
        return frozen

    def holdout(self):
        data, truth = self.root / "confirmation.csv", self.root / "confirmation-truth.csv"
        adapter.save_csv(data, ["id", "x", "group"], [("h2", 15, "new-1"), ("h1", 14, "new-2")])
        adapter.save_csv(truth, ["id", "target"], [("h1", 44), ("h2", 47)])
        return data, truth

    def test_actual_pipeline_fits_only_fold_rows_and_oof_is_recomputed(self):
        import joblib
        run = self.train()
        report = adapter.read_json(run / "fit.json")
        for fold in report["folds"]:
            model = joblib.load(run / fold["model"])
            ids = list(map(int, fold["train_ids"]))
            self.assertEqual(model[0].n_samples_seen_, len(ids))
            self.assertAlmostEqual(model[0].mean_[0], sum(ids) / len(ids))
        values = adapter.read_json(run / "evaluation/result.json")
        self.assertEqual(values["evaluation"]["completed_cases"], 12)
        self.assertLess(values["score"]["value"], 1e-12)
        self.assertEqual(values["evaluation"]["stage"], "development")
        self.assertEqual(len(adapter.csv_rows(run / "oof.csv", ["id", "prediction"])[1]), 12)

    def test_repeated_fit_preserves_recipe_identity(self):
        first = self.train("first")
        second = self.train("repeat")
        self.assertEqual((first / "recipe.json").read_bytes(), (second / "recipe.json").read_bytes())
        receipt = adapter.read_json(first / "recipe.json")
        self.assertIn("candidate_source", receipt)
        self.assertNotIn("fit_seconds", receipt)

    def test_real_changed_model_has_comparable_oof(self):
        first = self.train("baseline")
        self.candidate.write_text("from sklearn.dummy import DummyRegressor\n"
                                  "def build_model(seed, task): return DummyRegressor()\n")
        second = self.train("changed")
        a = load_result(first / "evaluation/result.json")
        b = load_result(second / "evaluation/result.json")
        result = compare(a, b, 0.0)
        self.assertIn("score", result["baseline"])
        self.assertGreater(b["score"]["value"], a["score"]["value"])
        self.assertNotEqual(adapter.read_json(first / "manifest.json")["files"]["candidate.py"],
                            adapter.read_json(second / "manifest.json")["files"]["candidate.py"])

    def test_frozen_copy_survives_source_changes_and_confirmation_scores(self):
        frozen = self.frozen()
        self.candidate.write_text("raise RuntimeError('live source must not load')\n")
        (self.root / "run/models/fold-0.joblib").write_bytes(b"changed live run")
        data, truth = self.holdout()
        report = adapter.deliver(frozen, data, self.root / "confirmed", truth=truth)
        self.assertLess(report["score"]["value"], 1e-12)
        result = adapter.read_json(self.root / "confirmed/evaluation/result.json")
        self.assertEqual(result["evaluation"]["stage"], "confirmation")

    def test_submission_order_schema_and_portable_frozen_model(self):
        import shutil
        frozen = self.frozen()
        moved = self.root / "moved"
        shutil.move(frozen, moved)
        data, _ = self.holdout()
        sample = self.root / "sample.csv"
        adapter.save_csv(sample, ["id", "prediction"], [("h1", 0), ("h2", 0)])
        adapter.deliver(moved, data, self.root / "final", sample_submission=sample)
        header, rows = adapter.csv_rows(self.root / "final/submission.csv", ["id", "prediction"])
        self.assertEqual(header, ["id", "prediction"])
        self.assertEqual(list(rows), ["h1", "h2"])
        self.assertAlmostEqual(float(rows["h1"]["prediction"]), 44)

    def test_model_tamper_rejected_before_loading(self):
        frozen = self.frozen()
        (frozen / "models/fold-0.joblib").write_bytes(b"not trusted")
        data, truth = self.holdout()
        with self.assertRaisesRegex(adapter.TrainingFailure, "Artifact changed"):
            adapter.deliver(frozen, data, self.root / "failed", truth=truth)
        self.assertFalse((self.root / "failed").exists())

    def test_confirmation_cannot_reuse_development_groups(self):
        frozen = self.frozen()
        data, truth = self.holdout()
        data.write_text("id,x,group\nh1,14,0\nh2,15,new\n")
        with self.assertRaisesRegex(adapter.TrainingFailure, "groups overlap"):
            adapter.deliver(frozen, data, self.root / "failed", truth=truth)

    def test_sample_submission_rejects_wrong_ids_or_columns(self):
        frozen = self.frozen()
        data, _ = self.holdout()
        sample = self.root / "sample.csv"
        for text in ["id,prediction\nh1,0\nmissing,0\n", "prediction,id\n0,h1\n0,h2\n"]:
            sample.write_text(text)
            with self.subTest(text=text), self.assertRaisesRegex(adapter.TrainingFailure, "Sample submission"):
                adapter.deliver(frozen, data, self.root / "failed", sample_submission=sample)
        self.assertFalse((self.root / "failed").exists())

    def test_only_completed_training_runs_can_be_frozen(self):
        run = self.train()
        (run / "oof.csv").write_text("id,prediction\nwrong,0\n")
        with self.assertRaisesRegex(adapter.TrainingFailure, "Artifact changed"):
            adapter.freeze(run, self.root / "invalid-freeze", "fixed rule")
        self.assertFalse((self.root / "invalid-freeze").exists())

    def test_missing_oof_rows_and_duplicate_validation_rejected_before_fit(self):
        for mode in ["missing", "duplicate"]:
            spec = copy.deepcopy(self.spec)
            if mode == "missing":
                spec["expected_oof_ids"].pop()
            else:
                spec["folds"].append({**spec["folds"][0], "id": "duplicate"})
            self.protocol.write_text(json.dumps(spec))
            with self.subTest(mode=mode), self.assertRaises(adapter.TrainingFailure):
                self.train(mode)
            self.assertFalse((self.root / mode).exists())

    def test_time_oof_allows_declared_warmup_and_rejects_future_training(self):
        spec = copy.deepcopy(self.spec)
        spec["split"] = {"kind": "time", "time_column": "time", "time_format": "number"}
        spec["folds"] = [{"id": "future", "seed": 1, "train_ids": [str(i) for i in range(8)],
                          "validation_ids": [str(i) for i in range(8, 12)]}]
        spec["expected_oof_ids"] = spec["folds"][0]["validation_ids"]
        self.protocol.write_text(json.dumps(spec))
        run = self.train()
        self.assertEqual(adapter.read_json(run / "evaluation/result.json")["evaluation"]["completed_cases"], 4)
        spec["folds"][0]["train_ids"], spec["folds"][0]["validation_ids"] = (
            spec["folds"][0]["validation_ids"], spec["folds"][0]["train_ids"])
        spec["expected_oof_ids"] = spec["folds"][0]["validation_ids"]
        self.protocol.write_text(json.dumps(spec))
        with self.assertRaisesRegex(adapter.TrainingFailure, "Evaluation precedes"):
            self.train("bad")

    def test_binary_real_fit(self):
        self.data.write_text("id,x,target,group\n" + "".join(
            f"{i},{i},{i % 2},{i // 2}\n" for i in range(12)))
        self.spec.update(task="binary", metric="binary_log_loss")
        self.protocol.write_text(json.dumps(self.spec))
        self.candidate.write_text("from sklearn.linear_model import LogisticRegression\n"
                                  "def build_model(seed, task): return LogisticRegression(random_state=seed)\n")
        run = self.train()
        result = adapter.read_json(run / "evaluation/result.json")
        self.assertTrue(result["valid"])
        self.assertGreater(result["score"]["value"], 0)

    def test_cli_failure_is_nonzero_and_no_success_manifest(self):
        self.candidate.write_text("def build_model(seed, task): raise RuntimeError('broken candidate')\n")
        output = self.root / "failed"
        process = subprocess.run([sys.executable, str(SCRIPTS / "tabular_training.py"), "train", "--data", str(self.data),
                                  "--protocol", str(self.protocol), "--candidate", str(self.candidate),
                                  "--output-dir", str(output)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn("broken candidate", process.stderr)
        self.assertFalse((output / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
