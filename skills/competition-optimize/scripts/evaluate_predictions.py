#!/usr/bin/env python3
"""Evaluate unweighted scalar CSV predictions on a declared local split."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import platform
import sys
from typing import Any


from dataclasses import dataclass, fields

from prediction_core import (
    METRIC_DIRECTIONS, UNCHECKED_RULES, PredictionFailure,
    byte_hash, object_hash, read_values, calculate_metric,
)


@dataclass(frozen=True)
class EvaluationSpec:
    truth: pathlib.Path
    predictions: pathlib.Path
    metric: str
    stage: str
    split_id: str
    id_column: str = "id"
    target_column: str = "target"
    prediction_column: str = "prediction"
    score_kind: str = "proxy"
    log_loss_epsilon: float = 1e-15
    case_profile: bool = False

    @classmethod
    def from_namespace(cls, value: argparse.Namespace) -> "EvaluationSpec":
        return cls(**{field.name: getattr(value, field.name)
                      for field in fields(cls) if hasattr(value, field.name)})


def evaluator_fingerprint() -> str:
    """Bind the executed scorer, including its extracted implementation."""
    return object_hash({name: byte_hash(pathlib.Path(__file__).with_name(name).read_bytes())
                        for name in ["evaluate_predictions.py", "prediction_core.py"]})


def evaluate(args: EvaluationSpec | argparse.Namespace, output_dir: pathlib.Path) -> dict[str, Any]:
    args = args if isinstance(args, EvaluationSpec) else EvaluationSpec.from_namespace(args)
    if (not args.split_id.strip() or not args.id_column.strip()
            or not args.target_column.strip() or not args.prediction_column.strip()):
        raise PredictionFailure("invalid_config", "Split ID and column names must be non-empty")
    if args.id_column in {args.target_column, args.prediction_column}:
        raise PredictionFailure("invalid_config", "ID and numeric value columns must differ")
    include_case_profile = getattr(args, "case_profile", False)
    if include_case_profile and args.metric == "roc_auc":
        raise PredictionFailure("invalid_input", "ROC-AUC does not decompose into per-sample losses")
    truth_path = args.truth.expanduser().resolve(strict=True)
    prediction_path = args.predictions.expanduser().resolve(strict=True)
    if truth_path == prediction_path:
        raise PredictionFailure("invalid_input", "Truth and prediction artifacts must be separate files")
    truth_raw, prediction_raw = truth_path.read_bytes(), prediction_path.read_bytes()
    labels = read_values(truth_raw, args.id_column, args.target_column, "truth")
    predictions = read_values(prediction_raw, args.id_column, args.prediction_column, "predictions")
    if labels.keys() != predictions.keys():
        missing = len(labels.keys() - predictions.keys())
        extra = len(predictions.keys() - labels.keys())
        raise PredictionFailure("id_mismatch", f"Prediction IDs differ from truth: missing={missing}, extra={extra}")
    sample_ids = sorted(labels)
    score = calculate_metric(args.metric, [labels[key] for key in sample_ids],
                             [predictions[key] for key in sample_ids], args.log_loss_epsilon)
    parameters = {"epsilon": args.log_loss_epsilon} if args.metric == "binary_log_loss" else {}
    score_model = {
        "metric": args.metric,
        "direction": METRIC_DIRECTIONS[args.metric],
        "kind": args.score_kind,
        "aggregation": "unweighted over all aligned rows",
        "parameters": parameters,
    }
    config = {
        "stage": args.stage, "split_id": args.split_id,
        "truth_hash": byte_hash(truth_raw), "id_column": args.id_column,
        "target_column": args.target_column, "prediction_column": args.prediction_column,
        "score_model": score_model,
    }
    case_profile = None
    if include_case_profile:
        losses = {}
        for key in sample_ids:
            label, prediction = labels[key], predictions[key]
            if args.metric == "rmse":
                residual = label - prediction
                loss = residual * residual
            elif args.metric == "mae":
                loss = abs(label - prediction)
            else:
                clipped = min(1 - args.log_loss_epsilon, max(args.log_loss_epsilon, prediction))
                loss = -math.log(clipped) if label == 1 else -math.log1p(-clipped)
            if not math.isfinite(loss):
                raise PredictionFailure("invalid_score", "Case loss exceeds finite floating-point range")
            losses[key] = loss
        case_profile = {
            "metric": {"rmse": "squared_error", "mae": "absolute_error",
                       "binary_log_loss": "binary_log_loss"}[args.metric],
            "direction": "minimize", "cases": losses,
        }
    snapshot = output_dir / "predictions.csv"
    with snapshot.open("xb") as stream:
        stream.write(prediction_raw)
    result = {
        "schema_version": 1,
        "adapter": "prediction_csv",
        "status": "success", "valid": True,
        "validity_scope": "prediction_artifact_and_metric_inputs",
        "checks": {"csv_schema": "passed", "unique_ids": "passed", "id_coverage": "passed",
                   "finite_values": "passed", "metric_domain": "passed"},
        "unchecked_rules": UNCHECKED_RULES,
        "candidate_hash": byte_hash(prediction_raw), "candidate_scope": "prediction_csv",
        "evaluator_hash": evaluator_fingerprint(),
        "score_model_hash": object_hash(score_model),
        "score": {**score_model, "origin": "local", "value": score, "components": {}},
        "evaluation": {
            "stage": args.stage, "split_id": args.split_id, "split_hash": config["truth_hash"],
            "config_hash": object_hash(config), "configuration": config,
            "expected_cases": len(labels), "completed_cases": len(predictions),
            "seeds": [], "repetitions": 1,
            "runtime_environment": {"python": platform.python_version(), "system": platform.system()},
        },
        "inputs": {"truth": str(truth_path), "predictions": str(prediction_path)},
        "artifacts": [str(snapshot)], "error": None,
    }
    if case_profile is not None:
        result["case_profile"] = case_profile
    return result


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True, type=pathlib.Path)
    parser.add_argument("--predictions", required=True, type=pathlib.Path)
    parser.add_argument("--metric", required=True, choices=list(METRIC_DIRECTIONS))
    parser.add_argument("--stage", required=True, choices=["development", "confirmation"])
    parser.add_argument("--split-id", required=True, help="name of the frozen local validation split")
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--target-column", default="target")
    parser.add_argument("--prediction-column", default="prediction")
    parser.add_argument("--score-kind", choices=["proxy", "official_metric"], default="proxy",
                        help="official_metric only after verifying this exact formula against the contest scorer")
    parser.add_argument("--log-loss-epsilon", type=float, default=1e-15)
    parser.add_argument("--case-profile", action="store_true",
                        help="include per-sample losses (RMSE uses squared error; unavailable for ROC-AUC)")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path,
                        help="new directory under an existing parent; never overwrite prior runs")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    created = False
    try:
        output_dir.mkdir(exist_ok=False)
        created = True
        result = evaluate(args, output_dir)
    except (OSError, PredictionFailure, OverflowError, ValueError) as exc:
        result = {
            "schema_version": 1, "adapter": "prediction_csv", "status": "failed", "valid": False,
            "score": {"value": None},
            "error": {"type": exc.kind if isinstance(exc, PredictionFailure) else "invalid_input",
                      "message": str(exc)},
        }
    if created:
        try:
            with (output_dir / "result.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": {"type": "output_failure", "message": str(exc)}},
                             ensure_ascii=False), file=sys.stderr)
            return 2
    summary = {key: result[key] for key in ["schema_version", "status", "valid", "score", "error"]}
    summary["result_file"] = str(output_dir / "result.json") if created else None
    if result["status"] == "success":
        summary["validity_scope"] = result["validity_scope"]
        summary["unchecked_rules"] = result["unchecked_rules"]
        summary["case_count"] = result["evaluation"]["completed_cases"]
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2),
          file=sys.stdout if result["status"] == "success" else sys.stderr)
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
