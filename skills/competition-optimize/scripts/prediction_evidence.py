"""Verified paired prediction inputs shared by diagnostic tools."""

from __future__ import annotations

import csv
import io
import pathlib
from dataclasses import dataclass
from typing import Any

import evaluate_predictions as evaluator
from prediction_core import compare, load_result


class EvidenceFailure(Exception):
    pass


@dataclass
class PredictionPair:
    paths: dict[str, pathlib.Path]
    input_hashes: dict[str, str]
    comparison: dict[str, Any]
    configuration: dict[str, Any]
    metric: str
    epsilon: float
    sample_ids: list[str]
    labels: list[float]
    baseline: list[float]
    candidate: list[float]
    prediction_bytes: list[bytes]


def load_pair(baseline: pathlib.Path, candidate: pathlib.Path, truth: pathlib.Path) -> PredictionPair:
    paths = {role: path.expanduser().resolve(strict=True)
             for role, path in [("baseline", baseline), ("candidate", candidate), ("truth", truth)]}
    result_bytes = [paths[role].read_bytes() for role in ["baseline", "candidate"]]
    results = [load_result(paths[role]) for role in ["baseline", "candidate"]]
    comparison = compare(*results, 0)
    if results[0]["evaluator_hash"] != evaluator.evaluator_fingerprint():
        raise EvidenceFailure("Reevaluate both candidates with the installed prediction evaluator before analysis")
    config = results[0]["evaluation"]["configuration"]
    for key in ["id_column", "target_column", "prediction_column"]:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise EvidenceFailure("Evaluation must declare non-empty CSV columns")
    if config["id_column"] in {config["target_column"], config["prediction_column"]}:
        raise EvidenceFailure("ID column must differ from numeric value columns")
    metric = results[0]["score"]["metric"]
    model = config["score_model"]
    parameters = model.get("parameters")
    if (model.get("aggregation") != "unweighted over all aligned rows" or not isinstance(parameters, dict)
            or set(parameters) != ({"epsilon"} if metric == "binary_log_loss" else set())):
        raise EvidenceFailure("Unsupported prediction score formula or parameters")
    epsilon = parameters.get("epsilon", 1e-15)
    if type(epsilon) not in {int, float}:
        raise EvidenceFailure("Log-loss epsilon must be a number")
    truth_raw = paths["truth"].read_bytes()
    if evaluator.byte_hash(truth_raw) != results[0]["evaluation"]["split_hash"]:
        raise EvidenceFailure("Truth bytes differ from the evaluated split")
    prediction_bytes = []
    for role, result, original in zip(["baseline", "candidate"], results, result_bytes):
        if paths[role].read_bytes() != original:
            raise EvidenceFailure("Evaluation record changed while reading evidence")
        raw = (paths[role].parent / "predictions.csv").read_bytes()
        if evaluator.byte_hash(raw) != result["candidate_hash"]:
            raise EvidenceFailure("Prediction snapshot changed while reading evidence")
        prediction_bytes.append(raw)
    labels = evaluator.read_values(truth_raw, config["id_column"], config["target_column"], "truth")
    predictions = [evaluator.read_values(raw, config["id_column"], config["prediction_column"], role)
                   for raw, role in zip(prediction_bytes, ["baseline", "candidate"])]
    if any(values.keys() != labels.keys() for values in predictions):
        raise EvidenceFailure("Prediction IDs differ from the evaluated truth")
    if len(labels) != results[0]["evaluation"]["completed_cases"]:
        raise EvidenceFailure("Prediction row count differs from the evaluation")
    sample_ids = sorted(labels)
    ordered_truth = [labels[key] for key in sample_ids]
    before, after = [[values[key] for key in sample_ids] for values in predictions]
    for result, values in zip(results, [before, after]):
        if evaluator.calculate_metric(metric, ordered_truth, values, epsilon) != result["score"]["value"]:
            raise EvidenceFailure("Recomputed score differs from its evaluation record")
    hashes = {"baseline_result": evaluator.byte_hash(result_bytes[0]),
              "candidate_result": evaluator.byte_hash(result_bytes[1]), "truth": evaluator.byte_hash(truth_raw)}
    return PredictionPair(paths, hashes, comparison, config, metric, epsilon, sample_ids,
                          ordered_truth, before, after, prediction_bytes)


def read_categories(raw: bytes, id_column: str, columns: list[str], sample_ids: set[str]) -> dict[str, dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        fields = reader.fieldnames
        if (not fields or any(not field.strip() for field in fields) or len(set(fields)) != len(fields)
                or any(column not in fields for column in [id_column, *columns])):
            raise EvidenceFailure("Metadata CSV needs unique column names and the requested ID/category columns")
        rows: dict[str, dict[str, str]] = {}
        for row_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise EvidenceFailure(f"Metadata CSV has a wrong field count at row {row_number}")
            sample_id = row[id_column]
            if not sample_id.strip() or sample_id in rows:
                raise EvidenceFailure(f"Metadata CSV has an empty or duplicate ID at row {row_number}")
            if any(not row[column].strip() for column in columns):
                raise EvidenceFailure(f"Category values must be non-empty at row {row_number}")
            rows[sample_id] = {column: row[column] for column in columns}
        if rows.keys() != sample_ids:
            raise EvidenceFailure("Metadata IDs must exactly match the evaluated split")
        return rows
    except (UnicodeDecodeError, csv.Error) as exc:
        raise EvidenceFailure(f"Invalid metadata CSV: {exc}") from exc
