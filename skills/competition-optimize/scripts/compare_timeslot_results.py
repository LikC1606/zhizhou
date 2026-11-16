#!/usr/bin/env python3
"""Compare two successful, paired fixed-timeslot evaluations."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
from typing import Any

import timeslot_workloads


QUALITY_TIE_EPSILON = 1e-12
METRIC_FIELDS = ["uniformity", "stability", "operation_ms", "init_ms"]


class ComparisonFailure(Exception):
    pass


def load_result(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonFailure(f"Cannot read result JSON {path}: {exc}") from exc
    keyed_rows(value, path)
    return value


def validate_header(value: dict[str, Any], path: pathlib.Path) -> None:
    if not isinstance(value, dict):
        raise ComparisonFailure(f"Result must be a JSON object: {path}")
    if type(value.get("schema_version")) is not int or value.get("schema_version") not in {2, 3}:
        raise ComparisonFailure(f"Unsupported result schema version: {path}")
    if value.get("status") != "success" or value.get("correct") is not True:
        raise ComparisonFailure(f"Result is not a successful correct evaluation: {path}")
    if value.get("stage") not in {"short", "full"}:
        raise ComparisonFailure(f"Only short/full results can be compared: {path}")
    environment = value.get("runtime_environment")
    if (not isinstance(environment, dict) or
            any(not isinstance(environment.get(key), str) for key in ["system", "release", "machine", "processor"])):
        raise ComparisonFailure(f"Result lacks runtime environment metadata: {path}")
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or metrics.get("partial"):
        raise ComparisonFailure(f"Result lacks complete metrics: {path}")
    rows = metrics.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ComparisonFailure(f"Result has no workload rows: {path}")


def keyed_rows(result: dict[str, Any], path: pathlib.Path) -> dict[tuple[int, int, int, str], dict[str, float]]:
    validate_header(result, path)
    keyed: dict[tuple[int, int, int, str], dict[str, float]] = {}
    for index, row in enumerate(result["metrics"]["rows"]):
        if not isinstance(row, dict):
            raise ComparisonFailure(f"Invalid row {index} in {path}")
        try:
            n, q, seed = row["N"], row["Q"], row["seed"]
            scenario = row["scenario"]
            if any(not isinstance(value, int) or isinstance(value, bool) for value in [n, q, seed]):
                raise ValueError("N, Q, and seed must be integers")
            if not isinstance(scenario, str) or not scenario:
                raise ValueError("scenario must be a non-empty string")
            key = (n, q, seed, scenario)
            raw_values = {field: row[field] for field in METRIC_FIELDS}
            if any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   for value in raw_values.values()):
                raise ValueError("metrics must be JSON numbers")
            values = {field: float(value) for field, value in raw_values.items()}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ComparisonFailure(f"Invalid row {index} in {path}: {exc}") from exc
        if key in keyed:
            raise ComparisonFailure(f"Duplicate workload key {key} in {path}")
        if any(not math.isfinite(value) for value in values.values()):
            raise ComparisonFailure(f"Non-finite metric in row {index} of {path}")
        if not 0.0 <= values["uniformity"] <= 1.0 or not 0.0 <= values["stability"] <= 1.0:
            raise ComparisonFailure(f"Quality metric outside [0, 1] in row {index} of {path}")
        if values["operation_ms"] < 0 or values["init_ms"] < 0:
            raise ComparisonFailure(f"Negative time metric in row {index} of {path}")
        keyed[key] = values
    try:
        timeslot_workloads.validate_result(result, keyed)
    except timeslot_workloads.WorkloadFailure as exc:
        raise ComparisonFailure(f"{exc}: {path}") from exc
    return keyed


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize_deltas(deltas: list[float], epsilon: float = 0.0) -> dict[str, Any]:
    return {
        "mean": mean(deltas),
        "median": statistics.median(deltas) if deltas else None,
        "min": min(deltas) if deltas else None,
        "max": max(deltas) if deltas else None,
        "improved": sum(value > epsilon for value in deltas),
        "regressed": sum(value < -epsilon for value in deltas),
        "tied": sum(abs(value) <= epsilon for value in deltas),
    }


def compare(baseline: dict[str, Any], baseline_path: pathlib.Path,
            candidate: dict[str, Any], candidate_path: pathlib.Path) -> dict[str, Any]:
    for field in ["stage", "evaluator_hash"]:
        if baseline.get(field) != candidate.get(field):
            raise ComparisonFailure(f"Cannot compare results with different {field}")
    if baseline.get("runtime_environment") != candidate.get("runtime_environment"):
        raise ComparisonFailure("Cannot compare timing results from different runtime environments")
    for name, result in [("baseline", baseline), ("candidate", candidate)]:
        for field in ["candidate_hash", "evaluator_hash"]:
            value = result.get(field)
            if not isinstance(value, str) or not value:
                raise ComparisonFailure(f"Missing {field} in {name} result")

    base_rows = keyed_rows(baseline, baseline_path)
    candidate_rows = keyed_rows(candidate, candidate_path)

    paired = []
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    quality_deltas = []
    operation_speedups = []
    init_speedups = []
    for key in sorted(base_rows):
        base = base_rows[key]
        trial = candidate_rows[key]
        uniformity_delta = trial["uniformity"] - base["uniformity"]
        stability_delta = trial["stability"] - base["stability"]
        quality_delta = 0.55 * uniformity_delta + 0.35 * stability_delta
        operation_speedup = (
            (base["operation_ms"] - trial["operation_ms"]) / base["operation_ms"] * 100.0
            if base["operation_ms"] > 0 else None
        )
        init_speedup = (
            (base["init_ms"] - trial["init_ms"]) / base["init_ms"] * 100.0
            if base["init_ms"] > 0 else None
        )
        quality_deltas.append(quality_delta)
        if operation_speedup is not None:
            operation_speedups.append(operation_speedup)
        if init_speedup is not None:
            init_speedups.append(init_speedup)
        n, q, seed, scenario = key
        record = {
            "N": n, "Q": q, "seed": seed, "scenario": scenario,
            "uniformity_delta": uniformity_delta,
            "stability_delta": stability_delta,
            "quality_proxy_delta": quality_delta,
            "operation_ms_delta": trial["operation_ms"] - base["operation_ms"],
            "operation_speedup_percent": operation_speedup,
            "init_ms_delta": trial["init_ms"] - base["init_ms"],
            "init_speedup_percent": init_speedup,
        }
        paired.append(record)
        groups.setdefault((n, q), []).append(record)

    by_workload_config = []
    for (n, q), records in sorted(groups.items()):
        by_workload_config.append({
            "N": n,
            "Q": q,
            "cases": len(records),
            "quality_proxy_delta": summarize_deltas(
                [row["quality_proxy_delta"] for row in records], QUALITY_TIE_EPSILON,
            ),
            "operation_speedup_percent": summarize_deltas(
                [row["operation_speedup_percent"] for row in records
                 if row["operation_speedup_percent"] is not None],
            ),
            "init_speedup_percent": summarize_deltas(
                [row["init_speedup_percent"] for row in records
                 if row["init_speedup_percent"] is not None],
            ),
        })

    return {
        "schema_version": 1,
        "status": "success",
        "stage": baseline["stage"],
        "evaluator_hash": baseline["evaluator_hash"],
        "runtime_environment": baseline["runtime_environment"],
        "baseline": {"result": str(baseline_path.resolve()), "candidate_hash": baseline["candidate_hash"]},
        "candidate": {"result": str(candidate_path.resolve()), "candidate_hash": candidate["candidate_hash"]},
        "workload_count": len(paired),
        "workload_hash": timeslot_workloads.seal(baseline["stage"])["workload_hash"],
        "workload_protocol": timeslot_workloads.PROTOCOL,
        "quality_proxy_definition": "0.55 * uniformity + 0.35 * stability; local proxy, not official total score",
        "timing_note": "One execution per candidate/workload; timing deltas are descriptive and should be repeated before promotion.",
        "summary": {
            "quality_proxy_delta": summarize_deltas(quality_deltas, QUALITY_TIE_EPSILON),
            "operation_speedup_percent": summarize_deltas(operation_speedups),
            "init_speedup_percent": summarize_deltas(init_speedups),
        },
        "by_workload_config": by_workload_config,
        "workloads": paired,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=pathlib.Path)
    parser.add_argument("--candidate", required=True, type=pathlib.Path,
                        help="candidate result.json, not source code")
    parser.add_argument("--output", type=pathlib.Path,
                        help="optional new JSON output path; existing files are never overwritten")
    args = parser.parse_args()
    try:
        baseline_path = args.baseline.expanduser().resolve(strict=True)
        candidate_path = args.candidate.expanduser().resolve(strict=True)
        baseline = load_result(baseline_path)
        candidate = load_result(candidate_path)
        result = compare(baseline, baseline_path, candidate, candidate_path)
        if args.output is not None:
            output = args.output.expanduser().resolve()
            if output.exists():
                raise ComparisonFailure(f"Refusing to overwrite comparison output: {output}")
            if not output.parent.is_dir():
                raise ComparisonFailure(f"Output parent directory does not exist: {output.parent}")
            result["output_file"] = str(output)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ComparisonFailure) as exc:
        print(json.dumps({"status": "failed", "error": {"type": "comparison_invalid", "message": str(exc)}},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    console_result = {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "stage": result["stage"],
        "evaluator_hash": result["evaluator_hash"],
        "baseline_candidate_hash": result["baseline"]["candidate_hash"],
        "candidate_hash": result["candidate"]["candidate_hash"],
        "workload_count": result["workload_count"],
        "summary": result["summary"],
        "by_workload_config": result["by_workload_config"],
        "timing_note": result["timing_note"],
        "output_file": result.get("output_file"),
    }
    print(json.dumps(console_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
