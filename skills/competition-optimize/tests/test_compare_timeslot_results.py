from __future__ import annotations

import copy
import importlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
compare_results = importlib.import_module("compare_timeslot_results")
workloads = importlib.import_module("timeslot_workloads")


ENVIRONMENT = {
    "system": "TestOS",
    "release": "1",
    "machine": "test-machine",
    "processor": "test-cpu",
}


def row(n: int, q: int, seed: int, scenario: str, uniformity: float,
        stability: float, operation_ms: float, init_ms: float) -> dict:
    return {
        "N": n,
        "Q": q,
        "seed": seed,
        "scenario": scenario,
        "uniformity": uniformity,
        "stability": stability,
        "operation_ms": operation_ms,
        "init_ms": init_ms,
    }


def complete_rows(stage: str = "full") -> list[dict]:
    sizes = [400, 10000] if stage == "full" else [100, 400, 10000]
    lengths = [1000] if stage == "full" else [1, 10, 100]
    return [row(n, q, seed, scenario, 0.5, 0.5, 10, 5)
            for n in sizes for q in lengths for seed in [1, 7, 17, 31, 101]
            for scenario in ["mixed", "sparse", "dense", "single", "bulk", "many-types",
                             "dominant", "uneven", "fresh-id"]]


def result(rows: list[dict] | None = None, stage: str = "full") -> dict:
    return {
        "schema_version": 2,
        "status": "success",
        "correct": True,
        "stage": stage,
        "candidate_hash": "a" * 64,
        "evaluator_hash": "e" * 64,
        "runtime_environment": copy.deepcopy(ENVIRONMENT),
        "metrics": {
            "rows": complete_rows(stage) if rows is None else rows,
        },
    }


class CompareTimeslotResultsTests(unittest.TestCase):
    def compare(self, baseline: dict, candidate: dict) -> dict:
        return compare_results.compare(
            baseline, Path("baseline.json"), candidate, Path("candidate.json"),
        )

    def test_compares_paired_rows_and_summarizes_by_n_and_q(self) -> None:
        baseline = result()
        baseline["metrics"]["rows"][0].update(uniformity=0.5, stability=0.4)
        baseline["metrics"]["rows"][1].update(uniformity=0.4, stability=0.6, operation_ms=0, init_ms=0)
        baseline["metrics"]["rows"][45].update(uniformity=0.8, stability=0.8, operation_ms=30, init_ms=10)
        candidate = copy.deepcopy(baseline)
        candidate["metrics"]["rows"][0].update(uniformity=0.6, stability=0.5, operation_ms=8, init_ms=4)
        candidate["metrics"]["rows"][1].update(uniformity=0.3, stability=0.7)
        candidate["metrics"]["rows"][45].update(operation_ms=33, init_ms=12)
        candidate["metrics"]["rows"].reverse()

        compared = self.compare(baseline, candidate)

        self.assertEqual(compared["workload_count"], 90)
        self.assertEqual([group["N"] for group in compared["by_workload_config"]], [400, 10000])
        self.assertEqual(compared["by_workload_config"][0]["cases"], 45)
        paired = {(item["N"], item["seed"], item["scenario"]): item for item in compared["workloads"]}
        self.assertAlmostEqual(paired[400, 1, "mixed"]["quality_proxy_delta"], 0.09)
        self.assertAlmostEqual(paired[400, 1, "mixed"]["operation_speedup_percent"], 20.0)
        self.assertIsNone(paired[400, 1, "sparse"]["operation_speedup_percent"])
        self.assertAlmostEqual(compared["summary"]["quality_proxy_delta"]["mean"], 0.07 / 90)

    def test_rejects_different_evaluator_environment_and_stage(self) -> None:
        mutations = [
            ("evaluator_hash", "different"),
            ("stage", "short"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                candidate = result()
                candidate[field] = value
                with self.assertRaises(compare_results.ComparisonFailure):
                    self.compare(result(), candidate)

        candidate = result()
        candidate["runtime_environment"]["machine"] = "other-machine"
        with self.assertRaisesRegex(compare_results.ComparisonFailure, "runtime environments"):
            self.compare(result(), candidate)

    def test_rejects_unpaired_or_duplicate_workloads(self) -> None:
        baseline = result()
        candidate = result(complete_rows()[:-1])
        with self.assertRaisesRegex(compare_results.ComparisonFailure, "[Ww]orkload"):
            self.compare(baseline, candidate)

        duplicate = row(100, 1, 1, "steady", 0.5, 0.5, 10, 5)
        with self.assertRaisesRegex(compare_results.ComparisonFailure, "Duplicate workload key"):
            self.compare(result([duplicate, copy.deepcopy(duplicate)]), result([duplicate]))

    def test_rejects_both_results_omitting_the_same_case(self) -> None:
        partial = result(complete_rows()[:-1])
        with self.assertRaisesRegex(compare_results.ComparisonFailure, "missing"):
            self.compare(partial, copy.deepcopy(partial))

    def test_rejects_shared_extra_unknown_or_wrong_stage_cases(self) -> None:
        extra = complete_rows()
        extra.append(row(400, 1000, 999, "mixed", 0.5, 0.5, 10, 5))
        unknown = complete_rows()
        unknown[0]["scenario"] = "steady"
        for rows in [extra, unknown, complete_rows("short")]:
            with self.subTest(count=len(rows)), self.assertRaises(compare_results.ComparisonFailure):
                self.compare(result(rows), result(copy.deepcopy(rows)))

    def test_load_accepts_complete_legacy_short_and_full_but_rejects_missing_cases(self) -> None:
        for stage, count in [("short", 405), ("full", 90)]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "result.json"
                value = result(stage=stage)
                path.write_text(json.dumps(value), encoding="utf-8")
                loaded = compare_results.load_result(path)
                self.assertEqual(self.compare(loaded, loaded)["workload_count"], count)
                value["metrics"]["rows"].pop()
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(compare_results.ComparisonFailure, "missing"):
                    compare_results.load_result(path)

    def test_schema3_requires_the_fixed_seal_and_complete_counts(self) -> None:
        valid = result()
        valid["schema_version"] = 3
        seal = workloads.seal("full")
        valid["workload_hash"] = seal["workload_hash"]
        valid["evaluation"] = {"workload_protocol": seal["workload_protocol"],
                               "expected_cases": 90, "completed_cases": 90}
        self.assertEqual(self.compare(result(), valid)["workload_count"], 90)
        for field, value in [("workload_protocol", "self-declared"), ("expected_cases", 89),
                             ("completed_cases", 89), ("completed_cases", True)]:
            changed = copy.deepcopy(valid)
            changed["evaluation"][field] = value
            with self.subTest(field=field), self.assertRaises(compare_results.ComparisonFailure):
                self.compare(changed, copy.deepcopy(changed))
        for field in ["workload_hash", "evaluation"]:
            changed = copy.deepcopy(valid)
            del changed[field]
            with self.subTest(field=field), self.assertRaises(compare_results.ComparisonFailure):
                self.compare(changed, copy.deepcopy(changed))
        changed = copy.deepcopy(valid)
        changed["workload_hash"] = workloads.seal("short")["workload_hash"]
        with self.assertRaises(compare_results.ComparisonFailure):
            self.compare(changed, copy.deepcopy(changed))

    def test_rejects_boolean_string_and_non_finite_metrics(self) -> None:
        invalid_values = [True, "0.5", math.inf, math.nan]
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                invalid_row = row(100, 1, 1, "steady", 0.5, 0.5, 10, 5)
                invalid_row["uniformity"] = value
                with self.assertRaises(compare_results.ComparisonFailure):
                    self.compare(result([invalid_row]), result())

    def test_rejects_quality_outside_unit_interval_and_negative_time(self) -> None:
        for field, value in [("uniformity", 1.01), ("stability", -0.01), ("operation_ms", -1)]:
            with self.subTest(field=field):
                invalid_row = row(100, 1, 1, "steady", 0.5, 0.5, 10, 5)
                invalid_row[field] = value
                with self.assertRaises(compare_results.ComparisonFailure):
                    self.compare(result([invalid_row]), result())

    def test_load_result_rejects_failed_and_partial_results(self) -> None:
        for changes in [{"status": "failed"}, {"metrics": {"rows": [], "partial": True}}]:
            value = result()
            value.update(changes)
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "result.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(compare_results.ComparisonFailure):
                    compare_results.load_result(path)


if __name__ == "__main__":
    unittest.main()
