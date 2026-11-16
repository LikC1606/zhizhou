from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
evaluator = importlib.import_module("evaluate_predictions")
core = importlib.import_module("prediction_core")
batch = importlib.import_module("evaluate_prediction_batch")


class PredictionCoreTests(unittest.TestCase):
    def test_core_and_evidence_import_without_loading_comparison_cli(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "import prediction_core, prediction_evidence; "
                "assert 'compare_prediction_results' not in sys.modules")
        process = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS)],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_extracted_scorer_changes_invalidate_installed_evidence(self):
        original = Path.read_bytes
        before = evaluator.evaluator_fingerprint()

        def changed(path):
            data = original(path)
            return data + b"\n# changed scorer\n" if path.name == "prediction_core.py" else data

        with patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(before, evaluator.evaluator_fingerprint())

    def test_typed_evaluation_and_batch_keep_identical_case_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            truth, prediction = root / "truth.csv", root / "prediction.csv"
            truth.write_text("id,target\na,1\nb,3\n")
            prediction.write_text("id,prediction\nb,4\na,1\n")
            single, group = root / "single", root / "batch"
            single.mkdir()
            group.mkdir()
            spec = evaluator.EvaluationSpec(truth, prediction, "rmse", "development",
                                            "same-split", case_profile=True)
            result = evaluator.evaluate(spec, single)
            (single / "result.json").write_text(json.dumps(result))
            loaded = core.load_result(single / "result.json")
            args = batch.make_parser().parse_args([
                "--truth", str(truth), "--candidate", "one", str(prediction),
                "--metric", "rmse", "--stage", "development", "--split-id", "same-split",
                "--case-profile", "--output-dir", str(group)])
            report = batch.run_batch(args, group, batch.validate_candidates(args.candidate, None))
            combined = core.load_result(Path(report["candidates"][0]["result"]))
            self.assertEqual(loaded["case_profile"], combined["case_profile"])
            self.assertEqual(core.compare(loaded, combined, 0)["metric_preference"], "tie")


if __name__ == "__main__":
    unittest.main()
