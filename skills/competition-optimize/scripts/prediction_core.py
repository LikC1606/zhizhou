"""Prediction metrics, CSV validation and comparable saved-result evidence.

No command-line module is imported here. The evaluator, paired diagnostics and
comparison CLI share this interface; saved schemas remain version 1.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pathlib
import re
from typing import Any


METRIC_DIRECTIONS = {
    "rmse": "minimize",
    "mae": "minimize",
    "binary_log_loss": "minimize",
    "roc_auc": "maximize",
}
UNCHECKED_RULES = ["training_leakage", "training_provenance", "resource_limits", "competition_rules"]


class PredictionFailure(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def byte_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_hash(value: Any) -> str:
    return byte_hash(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True, allow_nan=False).encode("utf-8"))


def read_values(raw: bytes, id_column: str, value_column: str, source: str) -> dict[str, float]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        columns = reader.fieldnames
        if (not columns or any(not column.strip() for column in columns)
                or len(set(columns)) != len(columns)):
            raise PredictionFailure("invalid_csv", f"{source}: missing, empty, or duplicate column names")
        if id_column not in columns or value_column not in columns:
            raise PredictionFailure("invalid_csv", f"{source}: requires {id_column!r} and {value_column!r}")
        values: dict[str, float] = {}
        for row_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise PredictionFailure("invalid_csv", f"{source}: wrong field count at row {row_number}")
            sample_id = row[id_column]
            if not sample_id.strip():
                raise PredictionFailure("invalid_id", f"{source}: empty ID at row {row_number}")
            if sample_id in values:
                raise PredictionFailure("invalid_id", f"{source}: duplicate ID at row {row_number}")
            try:
                value = float(row[value_column])
            except ValueError as exc:
                raise PredictionFailure("invalid_value", f"{source}: non-numeric value at row {row_number}") from exc
            if not math.isfinite(value):
                raise PredictionFailure("invalid_value", f"{source}: non-finite value at row {row_number}")
            values[sample_id] = value
        if not values:
            raise PredictionFailure("invalid_csv", f"{source}: contains no data rows")
        return values
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PredictionFailure("invalid_csv", f"{source}: {exc}") from exc


def calculate_metric(metric: str, labels: list[float], predictions: list[float],
                     epsilon: float = 1e-15) -> float:
    if metric not in METRIC_DIRECTIONS:
        raise PredictionFailure("invalid_metric", f"Unsupported metric: {metric}")
    if not labels or len(labels) != len(predictions):
        raise PredictionFailure("invalid_score", "Labels and predictions must be non-empty and paired")
    if any(not math.isfinite(value) for value in labels + predictions):
        raise PredictionFailure("invalid_score", "Metric inputs must be finite")
    if not math.isfinite(epsilon) or not 0 < epsilon < 0.5:
        raise PredictionFailure("invalid_config", "Log-loss epsilon must be finite and between 0 and 0.5")
    count = len(labels)
    if metric in {"rmse", "mae"}:
        residuals = [abs(label - prediction) for label, prediction in zip(labels, predictions)]
        if any(not math.isfinite(value) for value in residuals):
            raise PredictionFailure("invalid_score", "Residual exceeds finite floating-point range")
        scale = max(residuals)
        # Scaling avoids overflowing when finite residuals are squared or summed.
        score = 0.0 if scale == 0 else scale * (
            math.sqrt(math.fsum((value / scale) ** 2 for value in residuals) / count)
            if metric == "rmse" else math.fsum(value / scale for value in residuals) / count
        )
    else:
        if any(label not in (0.0, 1.0) for label in labels):
            raise PredictionFailure("invalid_domain", "Binary metrics require labels encoded as 0 or 1")
        if metric == "binary_log_loss":
            if any(not 0 <= value <= 1 for value in predictions):
                raise PredictionFailure("invalid_domain", "Binary log loss requires probabilities in [0, 1]")
            clipped = [min(1 - epsilon, max(epsilon, value)) for value in predictions]
            if any(not 0 < value < 1 for value in clipped):
                raise PredictionFailure("invalid_config", "Epsilon is too small for finite log-loss clipping")
            score = math.fsum(-math.log(p) if label == 1 else -math.log1p(-p)
                              for label, p in zip(labels, clipped)) / count
        else:
            positive_count = sum(label == 1 for label in labels)
            negative_count = count - positive_count
            if not positive_count or not negative_count:
                raise PredictionFailure("invalid_domain", "ROC-AUC requires both positive and negative labels")
            ordered = sorted(zip(predictions, labels))
            negatives_before = 0
            twice_favorable = 0
            start = 0
            while start < count:
                end = start + 1
                while end < count and ordered[end][0] == ordered[start][0]:
                    end += 1
                positives = sum(label == 1 for _, label in ordered[start:end])
                negatives = end - start - positives
                twice_favorable += positives * (2 * negatives_before + negatives)
                negatives_before += negatives
                start = end
            score = twice_favorable / (2 * positive_count * negative_count)
    if not math.isfinite(score):
        raise PredictionFailure("invalid_score", "Computed score is not finite")
    return score


class ComparisonFailure(Exception):
    pass


def metric_preference(improvement: float, epsilon: float) -> str:
    return "tie" if abs(improvement) <= epsilon else "candidate" if improvement > 0 else "baseline"


def load_result(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonFailure(f"Cannot read result {path}: {exc}") from exc
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ComparisonFailure("Unsupported prediction result schema")
    if value.get("adapter") != "prediction_csv" or value.get("status") != "success" or value.get("valid") is not True:
        raise ComparisonFailure("Result is not a successful prediction evaluation")
    if value.get("validity_scope") != "prediction_artifact_and_metric_inputs":
        raise ComparisonFailure("Unexpected validity scope")
    checks = value.get("checks")
    if not isinstance(checks, dict) or any(checks.get(key) != "passed" for key in
            ["csv_schema", "unique_ids", "id_coverage", "finite_values", "metric_domain"]):
        raise ComparisonFailure("Required prediction checks did not pass")
    unchecked = value.get("unchecked_rules")
    if not isinstance(unchecked, list) or any(not isinstance(rule, str) for rule in unchecked):
        raise ComparisonFailure("Malformed unchecked-rule metadata")
    for key in ["candidate_hash", "evaluator_hash", "score_model_hash"]:
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise ComparisonFailure(f"Missing or malformed {key}")
    score, evaluation = value.get("score"), value.get("evaluation")
    if not isinstance(score, dict) or not isinstance(evaluation, dict):
        raise ComparisonFailure("Missing score or evaluation metadata")
    metric = score.get("metric")
    if not isinstance(metric, str) or metric not in METRIC_DIRECTIONS:
        raise ComparisonFailure("Unknown metric")
    if score.get("direction") != METRIC_DIRECTIONS[metric] or score.get("origin") != "local":
        raise ComparisonFailure("Metric direction or score origin is inconsistent")
    if score.get("kind") not in {"proxy", "official_metric"}:
        raise ComparisonFailure("Unsupported score kind")
    number = score.get("value")
    if type(number) not in {int, float} or not math.isfinite(number):
        raise ComparisonFailure("Score must be a finite JSON number")
    if number < 0 or (metric == "roc_auc" and number > 1):
        raise ComparisonFailure("Score is outside the metric domain")
    expected, completed = evaluation.get("expected_cases"), evaluation.get("completed_cases")
    if type(expected) is not int or type(completed) is not int or expected < 1 or completed != expected:
        raise ComparisonFailure("Evaluation does not cover the complete split")
    if evaluation.get("stage") not in {"development", "confirmation"}:
        raise ComparisonFailure("Unexpected evaluation stage")
    config = evaluation.get("configuration")
    if not isinstance(config, dict):
        raise ComparisonFailure("Missing evaluation configuration")
    model = config.get("score_model")
    if not isinstance(model, dict) or object_hash(model) != value["score_model_hash"]:
        raise ComparisonFailure("Score model metadata does not match its hash")
    if any(score.get(key) != model.get(key) for key in ["metric", "direction", "kind", "aggregation", "parameters"]):
        raise ComparisonFailure("Score metadata differs from the score model")
    if object_hash(config) != evaluation.get("config_hash"):
        raise ComparisonFailure("Evaluation configuration does not match its hash")
    if any(evaluation.get(key) != config.get(key) for key in ["stage", "split_id"]):
        raise ComparisonFailure("Evaluation stage or split differs from its configuration")
    if evaluation.get("split_hash") != config.get("truth_hash"):
        raise ComparisonFailure("Split hash differs from the truth hash")
    if not isinstance(evaluation.get("split_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", evaluation["split_hash"]):
        raise ComparisonFailure("Missing or malformed split hash")
    try:
        snapshot = (path.parent / "predictions.csv").read_bytes()
    except OSError as exc:
        raise ComparisonFailure(f"Cannot read the saved prediction snapshot: {exc}") from exc
    if byte_hash(snapshot) != value["candidate_hash"]:
        raise ComparisonFailure("Saved prediction snapshot differs from the evaluated candidate")
    return value


def compare(baseline: dict[str, Any], candidate: dict[str, Any], epsilon: float) -> dict[str, Any]:
    if not math.isfinite(epsilon) or epsilon < 0:
        raise ComparisonFailure("Tie epsilon must be finite and non-negative")
    for key in ["evaluator_hash", "score_model_hash"]:
        if baseline[key] != candidate[key]:
            raise ComparisonFailure(f"Cannot compare different {key}")
    for key in ["stage", "split_id", "split_hash", "config_hash", "expected_cases", "completed_cases"]:
        if baseline["evaluation"][key] != candidate["evaluation"][key]:
            raise ComparisonFailure(f"Cannot compare different {key}")
    score = baseline["score"]
    delta = candidate["score"]["value"] - score["value"]
    improvement = delta if score["direction"] == "maximize" else -delta
    if not math.isfinite(improvement):
        raise ComparisonFailure("Score difference is not finite")
    return {
        "schema_version": 1, "status": "success",
        "selection_scope": "local_metric_only_pending_other_rule_checks",
        "metric": score["metric"], "direction": score["direction"], "score_kind": score["kind"],
        "stage": baseline["evaluation"]["stage"], "split_hash": baseline["evaluation"]["split_hash"],
        "evaluator_hash": baseline["evaluator_hash"], "score_model_hash": baseline["score_model_hash"],
        "baseline": {"candidate_hash": baseline["candidate_hash"], "score": score["value"]},
        "candidate": {"candidate_hash": candidate["candidate_hash"], "score": candidate["score"]["value"]},
        "raw_score_delta": delta, "objective_improvement": improvement,
        "metric_preference": metric_preference(improvement, epsilon), "tie_epsilon": epsilon,
        "unchecked_rules": sorted(set(UNCHECKED_RULES) | set(baseline.get("unchecked_rules", []))
                                  | set(candidate.get("unchecked_rules", []))),
        "note": "This compares deterministic local scores; it does not establish training repeatability or final-test gain.",
    }
