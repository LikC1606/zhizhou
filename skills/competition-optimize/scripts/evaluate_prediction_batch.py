#!/usr/bin/env python3
"""Evaluate existing prediction candidates sequentially under one frozen contract."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
from typing import Any

import evaluate_predictions as evaluator
from compare_prediction_results import ComparisonFailure, compare, load_result


class BatchFailure(Exception):
    pass


def write_json(path: pathlib.Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def validate_candidates(members: list[list[str]], baseline: str | None) -> dict[str, pathlib.Path]:
    if not 1 <= len(members) <= 64:
        raise BatchFailure("Provide 1-64 existing candidates within the task's trial budget")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    candidates, names = {}, set()
    for name, source in members:
        if (not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,62}[A-Za-z0-9_-])?", name)
                or name.split(".", 1)[0].upper() in reserved):
            raise BatchFailure("Candidate names need 1-64 portable ASCII characters; device names are reserved")
        if name.lower() in names:
            raise BatchFailure(f"Duplicate candidate name: {name}")
        names.add(name.lower())
        candidates[name] = pathlib.Path(source).expanduser()
    if baseline is not None and baseline not in candidates:
        raise BatchFailure("--baseline must exactly name one of the batch candidates")
    return candidates


def run_batch(args: argparse.Namespace, output: pathlib.Path,
              candidates: dict[str, pathlib.Path]) -> dict[str, Any]:
    truth_source = args.truth.expanduser().resolve(strict=True)
    truth_raw = truth_source.read_bytes()
    # Freeze a shared truth artifact; individual evaluation contracts use its bytes.
    evaluator.read_values(truth_raw, args.id_column, args.target_column, "truth")
    frozen_truth = output / "truth.csv"
    with frozen_truth.open("xb") as stream:
        stream.write(truth_raw)
    (output / "evaluations").mkdir()
    if args.baseline is not None:
        (output / "comparisons").mkdir()
    records, verified = [], {}
    for name, prediction in candidates.items():
        directory = output / "evaluations" / name
        directory.mkdir()
        try:
            if prediction.resolve(strict=True) == truth_source:
                raise evaluator.PredictionFailure("invalid_input", "Truth and prediction artifacts must be separate files")
            configuration = {key: getattr(args, key) for key in [
                "metric", "stage", "split_id", "id_column", "target_column", "prediction_column",
                "score_kind", "log_loss_epsilon",
            ]}
            spec = evaluator.EvaluationSpec(**configuration, truth=frozen_truth,
                                            predictions=prediction,
                                            case_profile=getattr(args, "case_profile", False))
            result = evaluator.evaluate(spec, directory)
            if result["evaluation"]["split_hash"] != evaluator.byte_hash(truth_raw):
                raise BatchFailure("Frozen truth changed during batch evaluation")
        except (OSError, evaluator.PredictionFailure, BatchFailure, OverflowError, ValueError) as exc:
            result = {"schema_version": 1, "adapter": "prediction_csv", "status": "failed", "valid": False,
                      "score": {"value": None},
                      "error": {"type": exc.kind if isinstance(exc, evaluator.PredictionFailure) else "invalid_input",
                                "message": str(exc)}}
        result_path = directory / "result.json"
        write_json(result_path, result)
        record = {"name": name, "result": str(result_path), "status": result["status"],
                  "valid": result["valid"], "score": result["score"], "error": result["error"],
                  "comparison": None}
        records.append(record)
        if result["status"] == "success" and args.baseline is not None:
            # Verify each saved result/snapshot once, then reuse the baseline in memory.
            verified[name] = load_result(result_path)
    if frozen_truth.read_bytes() != truth_raw:
        raise BatchFailure("Frozen truth changed during batch evaluation")
    if args.baseline in verified:
        baseline = verified[args.baseline]
        for record in records:
            name = record["name"]
            if name == args.baseline or name not in verified:
                continue
            comparison = compare(baseline, verified[name], args.tie_epsilon)
            comparison["baseline"]["result"] = str(output / "evaluations" / args.baseline / "result.json")
            comparison["candidate"]["result"] = record["result"]
            comparison_path = output / "comparisons" / f"{name}.json"
            write_json(comparison_path, comparison)
            record["comparison"] = str(comparison_path)
    succeeded = sum(record["status"] == "success" for record in records)
    return {
        "schema_version": 1, "adapter": "prediction_batch",
        "status": "success" if succeeded == len(records) else "partial_failure" if succeeded else "failed",
        "selection_scope": "existing_candidates_evaluation_only", "baseline": args.baseline,
        "expected_candidates": len(records), "successful_candidates": succeeded,
        "failed_candidates": len(records) - succeeded, "candidates": records,
        "truth": {"source": str(truth_source), "snapshot": str(frozen_truth), "hash": evaluator.byte_hash(truth_raw)},
        "batch_hash": evaluator.byte_hash(pathlib.Path(__file__).read_bytes()),
        "unchecked_rules": evaluator.UNCHECKED_RULES, "error": None,
        "note": "Sequential evaluation only; each tested configuration still consumes its trial budget. "
                "No training, tuning, uncertainty analysis, promotion, or submission.",
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, action="append", nargs=2, metavar=("NAME", "CSV"))
    parser.add_argument("--baseline", help="optional exact candidate name for matched comparisons")
    parser.add_argument("--truth", required=True, type=pathlib.Path)
    parser.add_argument("--metric", required=True, choices=list(evaluator.METRIC_DIRECTIONS))
    parser.add_argument("--stage", required=True, choices=["development", "confirmation"])
    parser.add_argument("--split-id", required=True)
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--target-column", default="target")
    parser.add_argument("--prediction-column", default="prediction")
    parser.add_argument("--score-kind", choices=["proxy", "official_metric"], default="proxy")
    parser.add_argument("--log-loss-epsilon", type=float, default=1e-15)
    parser.add_argument("--case-profile", action="store_true",
                        help="include the same per-sample losses as individual evaluation")
    parser.add_argument("--tie-epsilon", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path, help="new directory under an existing parent")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    output, created = args.output_dir.expanduser().resolve(), False
    try:
        candidates = validate_candidates(args.candidate, args.baseline)
        # Validate the comparison setting even if every comparison is skipped.
        if not math.isfinite(args.tie_epsilon) or args.tie_epsilon < 0:
            raise BatchFailure("Tie epsilon must be finite and non-negative")
        output.mkdir(exist_ok=False)
        created = True
        report = run_batch(args, output, candidates)
    except (OSError, BatchFailure, ComparisonFailure, evaluator.PredictionFailure, OverflowError, ValueError) as exc:
        report = {"schema_version": 1, "adapter": "prediction_batch", "status": "failed",
                  "error": {"type": "batch_invalid", "message": str(exc)}}
    if created:
        try:
            write_json(output / "batch.json", report)
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
            return 2
    print(json.dumps({"status": report["status"], "report": str(output / "batch.json") if created else None,
                      "successful_candidates": report.get("successful_candidates"),
                      "failed_candidates": report.get("failed_candidates"), "error": report["error"]},
                     ensure_ascii=False, allow_nan=False),
          file=sys.stdout if report["status"] == "success" else sys.stderr)
    return 0 if report["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
