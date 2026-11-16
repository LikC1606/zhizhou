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
split = importlib.import_module("audit_data_split")


class DataSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.splits = self.root / "splits.json"
        self.metadata = self.root / "rows.csv"
        self.write_splits({"train": ["001", "1"], "development": ["a"], "confirmation": ["b"]})
        self.metadata.write_text("id,patient,duplicate,time,available\n"
                                 "b,p3,d3,30,31\na,p2,d2,20,21\n1,p1,d1,11,12\n001,p1,d1,10,11\n",
                                 encoding="utf-8")

    def write_splits(self, value: dict) -> None:
        self.splits.write_text(json.dumps(value), encoding="utf-8")

    def args(self, *extra: str):
        return split.make_parser().parse_args(["--splits", str(self.splits),
                                              "--output", str(self.root / "receipt.json"), *extra])

    def timed(self, *extra: str):
        return self.args("--metadata", str(self.metadata), "--time-column", "time",
                         "--time-format", "number", "--available-time-column", "available",
                         "--time-order", "train", "development", "confirmation", *extra)

    def test_basic_split_keeps_exact_ids_and_names_unchecked_scope(self) -> None:
        report = split.audit(self.args())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["unique_ids"], 4)
        self.assertEqual(len(report["checks"]), 3)
        self.assertEqual(report["sources"]["splits"]["sha256"], split.digest(self.splits.read_bytes()))
        self.assertIn("actual_fitting_rows", report["unchecked"])
        self.assertIn("prior_holdout_exposure", report["unchecked"])
        self.assertEqual(report["validity_scope"], "declared_partition_metadata_only")

    def test_id_overlap_is_rejected_and_examples_are_bounded(self) -> None:
        self.write_splits({"train": [str(i) for i in range(12)], "test": [str(i) for i in range(8)]})
        report = split.audit(self.args())
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["checks"][0]["overlap_count"], 8)
        self.assertEqual(len(report["checks"][0]["examples"]), 5)

    def test_multiple_group_boundaries_pass_and_patient_leakage_is_rejected(self) -> None:
        args = self.args("--metadata", str(self.metadata), "--group-column", "patient",
                         "--group-column", "duplicate")
        self.assertEqual(split.audit(args)["status"], "passed")
        self.metadata.write_text(self.metadata.read_text().replace("a,p2", "a,p1"), encoding="utf-8")
        report = split.audit(args)
        failures = [check for check in report["checks"] if not check["passed"]]
        self.assertEqual(failures, [{"kind": "group_disjointness", "column": "patient",
                                    "partitions": ["train", "development"], "passed": False,
                                    "overlap_count": 1, "examples": ["p1"]}])

    def test_metadata_coverage_rejects_missing_or_extra_rows(self) -> None:
        for text, missing, extra in [("id\n001\n1\na\n", 1, 0), ("id\n001\n1\na\nb\nunused\n", 0, 1)]:
            with self.subTest(text=text):
                self.metadata.write_text(text, encoding="utf-8")
                report = split.audit(self.args("--metadata", str(self.metadata)))
                self.assertEqual(report["status"], "rejected")
                self.assertEqual(report["checks"][-1]["missing_count"], missing)
                self.assertEqual(report["checks"][-1]["extra_count"], extra)

    def test_time_boundaries_use_label_availability_and_exact_minimum_gap(self) -> None:
        self.assertEqual(split.audit(self.timed("--minimum-time-gap", "8"))["status"], "passed")
        self.assertEqual(split.audit(self.timed("--minimum-time-gap", "8.000000000000000001"))["status"],
                         "rejected")
        # Event timestamps remain ordered, but this training label is known too late.
        self.metadata.write_text(self.metadata.read_text().replace("1,p1,d1,11,12", "1,p1,d1,11,20"),
                                 encoding="utf-8")
        report = split.audit(self.timed())
        self.assertEqual(report["status"], "rejected")
        boundary = [item for item in report["checks"] if item["kind"] == "forward_time_boundary"][0]
        self.assertEqual(boundary["gap"], "0")
        self.assertFalse(boundary["passed"])

    def test_reversed_event_time_and_tied_boundaries_are_rejected_without_available_column(self) -> None:
        for time in ["20", "25"]:
            with self.subTest(time=time):
                self.metadata.write_text(f"id,time\n001,10\n1,{time}\na,20\nb,30\n", encoding="utf-8")
                args = self.args("--metadata", str(self.metadata), "--time-column", "time",
                                 "--time-format", "number", "--time-order", "train", "development", "confirmation")
                self.assertEqual(split.audit(args)["status"], "rejected")

    def test_iso_timezones_are_compared_as_instants_with_second_gap(self) -> None:
        self.write_splits({"train": ["1"], "development": ["a"], "confirmation": ["b"]})
        self.metadata.write_text("id,time,available\n1,2026-10-10T09:00:00+08:00,2026-10-10T01:00:01Z\n"
                                 "a,2026-10-10T01:00:02Z,2026-10-10T01:00:03+00:00\n"
                                 "b,2026-10-10T02:00:04+01:00,2026-10-10T01:00:05Z\n", encoding="utf-8")
        report = split.audit(self.timed("--time-format", "iso8601", "--minimum-time-gap", "1"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["configuration"]["time_unit"], "seconds")
        self.assertEqual(split.audit(self.timed("--time-format", "iso8601", "--minimum-time-gap", "1.01"))
                         ["status"], "rejected")

    def test_invalid_split_records_are_rejected(self) -> None:
        for raw in [b'{"train":["x"],"train":["y"]}', b'{"train":[1],"test":["a"]}',
                    b'{"train":["x","x"],"test":["a"]}', b'{"train":[],"test":["a"]}',
                    b'{"train":[" "],"test":["a"]}', b'[]', b'{"train":["x"]}', b'\xff']:
            with self.subTest(raw=raw):
                self.splits.write_bytes(raw)
                with self.assertRaises(split.SplitFailure):
                    split.audit(self.args())

    def test_bad_metadata_and_missing_columns_are_rejected(self) -> None:
        for raw in ["id,patient\n001,p1\n001,p2\n", "id,id,patient\nx,x,p1\n", "id,patient\nx,\n",
                    "id,patient\nx,p1,extra\n", "id,patient\nx\n", "id\nx\n", "id,patient\n"]:
            with self.subTest(raw=raw):
                self.metadata.write_text(raw, encoding="utf-8")
                with self.assertRaises(split.SplitFailure):
                    split.audit(self.args("--metadata", str(self.metadata), "--group-column", "patient"))

    def test_partial_or_ambiguous_time_configuration_is_rejected(self) -> None:
        for options in [("--group-column", "patient"), ("--time-order", "train", "development", "confirmation"),
                        ("--metadata", str(self.metadata), "--time-column", "time"),
                        ("--minimum-time-gap", "1"), ("--minimum-time-gap", "-1"),
                        ("--available-time-column", "available"), ("--time-format", "number")]:
            with self.subTest(options=options), self.assertRaises(split.SplitFailure):
                split.audit(self.args(*options))
        for order in [("train", "development"), ("train", "development", "development"),
                      ("train", "development", "unknown")]:
            with self.subTest(order=order), self.assertRaises(split.SplitFailure):
                split.audit(self.timed("--time-order", *order))

    def test_invalid_numbers_and_naive_dates_never_pass(self) -> None:
        for bad, fmt in [("nan", "number"), ("Infinity", "number"), ("1e1001", "number"),
                         ("2026-10-10T01:00:00", "iso8601"), ("bad-date", "iso8601"),
                         ("2026-10-10T01:00:00.0000001Z", "iso8601"),
                         ("2026-10-10T01:00.5Z", "iso8601"),
                         ("2026-10-10T01:00:00+00:00:00.1", "iso8601")]:
            with self.subTest(bad=bad):
                self.metadata.write_text(f"id,time,available\n001,{bad},{bad}\n1,1,1\na,2,2\nb,3,3\n",
                                         encoding="utf-8")
                with self.assertRaises(split.SplitFailure):
                    split.audit(self.timed("--time-format", fmt))

    def test_sources_changed_during_audit_are_rejected(self) -> None:
        read = Path.read_bytes
        calls = 0
        def changed(path):
            nonlocal calls
            raw = read(path)
            if path == self.splits:
                calls += 1
                return raw if calls == 1 else raw + b" "
            return raw
        with patch.object(Path, "read_bytes", changed), self.assertRaises(split.SplitFailure) as caught:
            split.audit(self.args())
        self.assertEqual(caught.exception.kind, "source_changed")

    def test_cli_records_rejections_and_never_overwrites_receipts(self) -> None:
        script = SCRIPT_DIR / "audit_data_split.py"
        output = self.root / "receipt.json"
        command = [sys.executable, str(script), "--splits", str(self.splits), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        old = output.read_bytes()
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
        self.assertEqual(output.read_bytes(), old)
        self.write_splits({"train": ["x"], "development": ["x"]})
        command[-1] = str(self.root / "rejected.json")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "rejected")
        self.assertEqual(json.loads(Path(command[-1]).read_text())["status"], "rejected")
        self.splits.write_text("broken", encoding="utf-8")
        command[-1] = str(self.root / "invalid.json")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["type"], "invalid_splits")
        self.assertFalse(Path(command[-1]).exists())


if __name__ == "__main__":
    unittest.main()
