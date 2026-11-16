#!/usr/bin/env python3
"""Fit numeric tabular candidates, preserve OOF lineage, and deliver frozen models.

Candidates supply build_model(seed, task), returning a sklearn-compatible estimator.
Candidate code and model files are trusted local code, not sandboxed inputs.
"""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import platform
import sys
import time

from audit_data_split import number, timestamp
from evaluate_predictions import EvaluationSpec, evaluate
from prediction_core import byte_hash, object_hash


class TrainingFailure(ValueError):
    pass


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path, columns: list[str], *, raw: bytes | None = None) -> tuple[list[str], dict[str, dict]]:
    text = (path.read_bytes() if raw is None else raw).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    header = reader.fieldnames
    if (not header or any(not name.strip() for name in header)
            or len(set(header)) != len(header) or not set(columns) <= set(header)):
        raise TrainingFailure("CSV requires distinct named columns: " + ", ".join(columns))
    rows = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise TrainingFailure("Malformed CSV row")
        key = row[columns[0]]
        if not key.strip() or key in rows:
            raise TrainingFailure("CSV IDs must be nonempty and unique")
        rows[key] = row
    if not rows:
        raise TrainingFailure("CSV is empty")
    return header, rows


def save_csv(path: Path, header: list[str], rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def environment() -> dict:
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in
                         ["numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl"]}}


def runtime():
    try:
        import numpy as np
        import joblib
        from threadpoolctl import threadpool_limits
    except ImportError as exc:
        raise TrainingFailure("Install the optional scripts/requirements-tabular.txt in an isolated environment") from exc
    return np, joblib, threadpool_limits


def unique_ids(value, label: str) -> list[str]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise TrainingFailure(label + " must contain unique nonempty string IDs")
    return value


def validate_spec(spec: dict) -> None:
    if spec.get("schema_version") != 1 or not spec.get("task_id"):
        raise TrainingFailure("Expected schema_version=1 and task_id")
    if spec.get("task") not in {"regression", "binary"}:
        raise TrainingFailure("Only scalar regression and binary tasks are supported")
    allowed = {"rmse", "mae"} if spec["task"] == "regression" else {"binary_log_loss", "roc_auc"}
    if spec.get("metric") not in allowed:
        raise TrainingFailure("Metric does not match the declared task")
    features = unique_ids(spec.get("features"), "features")
    names = [spec.get(name, default) for name, default in
             [("id_column", "id"), ("target_column", "target"), ("prediction_column", "prediction")]]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != 3:
        raise TrainingFailure("ID, target and prediction columns must be distinct")
    if set(features) & set(names):
        raise TrainingFailure("Features cannot include ID, target or prediction columns")
    split = spec.get("split", {})
    if split.get("kind") not in {"iid", "group", "time", "group_time"}:
        raise TrainingFailure("Declare split.kind as iid, group, time or group_time")
    if "group" in split["kind"] and not split.get("group_column"):
        raise TrainingFailure("Group splitting requires group_column")
    if "time" in split["kind"]:
        if not split.get("time_column") or split.get("time_format") not in {"number", "iso8601"}:
            raise TrainingFailure("Time splitting requires time_column and time_format")
        if number(str(split.get("minimum_time_gap", "0"))) < 0:
            raise TrainingFailure("minimum_time_gap must be nonnegative")
    if spec.get("score_kind", "proxy") not in {"proxy", "official_metric"}:
        raise TrainingFailure("Unknown score_kind")
    unique_ids(spec.get("expected_oof_ids"), "expected_oof_ids")
    if not isinstance(spec.get("folds"), list) or not spec["folds"]:
        raise TrainingFailure("Declare at least one fold")


def metadata_columns(spec: dict, *, training: bool = True) -> list[str]:
    split = spec["split"]
    names = ["group_column", "time_column"] + (["available_time_column"] if training else [])
    return [split[name] for name in names
            if split.get(name)]


def check_boundary(spec: dict, left: dict, right: dict) -> None:
    if set(left) & set(right):
        raise TrainingFailure("Training and evaluation IDs overlap")
    split = spec["split"]
    if "group" in split["kind"]:
        column = split["group_column"]
        groups = [{row[column] for row in rows.values()} for rows in [left, right]]
        if "" in groups[0] | groups[1] or groups[0] & groups[1]:
            raise TrainingFailure("Training and evaluation groups overlap or are empty")
    if "time" in split["kind"]:
        column, form = split["time_column"], split["time_format"]
        available = split.get("available_time_column", column)
        latest = max(max(timestamp(row[column], form), timestamp(row[available], form))
                     for row in left.values())
        earliest = min(timestamp(row[column], form) for row in right.values())
        gap = number(str(split.get("minimum_time_gap", "0")))
        if earliest <= latest or earliest - latest < gap:
            raise TrainingFailure("Evaluation precedes training event/label availability or required time gap")


def matrix(np, rows: dict, ids: list[str], features: list[str]):
    values = np.array([[float(rows[key][feature]) for feature in features] for key in ids], dtype=float)
    if not np.isfinite(values).all():
        raise TrainingFailure("Features must be finite numeric values")
    return values


def predictions(np, model, values, task: str):
    if task == "binary":
        classes = list(model.classes_)
        if set(classes) != {0, 1}:
            raise TrainingFailure("Binary estimator must learn classes 0 and 1")
        result = np.asarray(model.predict_proba(values))[:, classes.index(1)]
    else:
        result = np.asarray(model.predict(values))
    if result.shape != (len(values),) or not np.isfinite(result).all():
        raise TrainingFailure("Estimator must produce one finite scalar per row")
    if task == "binary" and ((result < 0).any() or (result > 1).any()):
        raise TrainingFailure("Binary predictions must be probabilities")
    return result


def artifact_hashes(root: Path) -> dict:
    return {str(path.relative_to(root)): byte_hash(path.read_bytes()) for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "manifest.json" and "__pycache__" not in path.parts}


def verified_manifest(root: Path, kind: str) -> dict:
    manifest = read_json(root / "manifest.json")
    if manifest.get("kind") != kind or manifest.get("seal") != object_hash({
            key: value for key, value in manifest.items() if key != "seal"}):
        raise TrainingFailure("Invalid manifest or seal")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or byte_hash(path.read_bytes()) != expected:
            raise TrainingFailure("Artifact changed: " + name)
    return manifest


def seal(root: Path, fields: dict) -> dict:
    manifest = {"schema_version": 1, **fields, "files": artifact_hashes(root)}
    manifest["seal"] = object_hash(manifest)
    write_json(root / "manifest.json", manifest)
    return manifest


def score(spec: dict, truth: Path, predicted: Path, stage: str, root: Path, split_hash: str) -> dict:
    root.mkdir()
    result = evaluate(EvaluationSpec(truth=truth, predictions=predicted, metric=spec["metric"],
                      stage=stage, split_id=spec["task_id"] + ":" + split_hash,
                      id_column=spec.get("id_column", "id"), target_column=spec.get("target_column", "target"),
                      prediction_column=spec.get("prediction_column", "prediction"),
                      score_kind=spec.get("score_kind", "proxy"), case_profile=spec["metric"] != "roc_auc"), root)
    write_json(root / "result.json", result)
    return result


def train(data: Path, protocol: Path, candidate: Path, output: Path) -> dict:
    np, joblib, limits = runtime()
    inputs = {"training.csv": data.read_bytes(), "protocol.json": protocol.read_bytes(),
              "candidate.py": candidate.read_bytes()}
    spec = json.loads(inputs["protocol.json"])
    validate_spec(spec)
    identifier, target = spec.get("id_column", "id"), spec.get("target_column", "target")
    _, rows = csv_rows(data, [identifier, target, *spec["features"], *metadata_columns(spec)], raw=inputs["training.csv"])
    used, evaluated, fold_ids = set(), set(), set()
    for fold in spec["folds"]:
        if not isinstance(fold.get("id"), str) or not fold["id"] or fold["id"] in fold_ids:
            raise TrainingFailure("Fold IDs must be nonempty and unique")
        if type(fold.get("seed")) is not int:
            raise TrainingFailure("Each fold requires an integer seed")
        fold_ids.add(fold["id"])
        training = unique_ids(fold.get("train_ids"), "train_ids")
        validation = unique_ids(fold.get("validation_ids"), "validation_ids")
        if not set(training + validation) <= rows.keys() or evaluated & set(validation):
            raise TrainingFailure("Fold references unknown IDs or duplicates OOF coverage")
        check_boundary(spec, {key: rows[key] for key in training}, {key: rows[key] for key in validation})
        used.update(training + validation)
        evaluated.update(validation)
    if used != rows.keys() or evaluated != set(spec["expected_oof_ids"]):
        raise TrainingFailure("Dataset or declared OOF coverage is incomplete")
    if spec["split"]["kind"] in {"iid", "group"} and evaluated != rows.keys():
        raise TrainingFailure("Non-temporal OOF must cover every training data row exactly once")
    # All learned preprocessing is fitted within the estimator's fit call on these rows.
    output.mkdir()
    for name, raw in inputs.items():
        (output / name).write_bytes(raw)
    execution_environment = environment()
    # Stable archive implementation identity: source/data/features/dependencies,
    # without output bytes, timing or fold measurement seeds.
    write_json(output / "recipe.json", {"schema_version": 1, "task": spec["task"],
               "features": spec["features"], "id_column": identifier, "target_column": target,
               "candidate_source": inputs["candidate.py"].decode("utf-8-sig"),
               "training_data_sha256": byte_hash(inputs["training.csv"]),
               "environment": execution_environment, "adapter_hash": byte_hash(Path(__file__).read_bytes())})
    module_spec = importlib.util.spec_from_file_location("competition_candidate", output / "candidate.py")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    oof, receipts = {}, []
    (output / "models").mkdir()
    with limits(limits=1):
        for index, fold in enumerate(spec["folds"]):
            train_ids, valid_ids = fold["train_ids"], fold["validation_ids"]
            features = matrix(np, rows, train_ids, spec["features"])
            labels = np.array([float(rows[key][target]) for key in train_ids])
            if not np.isfinite(labels).all() or (spec["task"] == "binary" and set(labels) != {0, 1}):
                raise TrainingFailure("Training labels must be finite; binary folds require both 0 and 1")
            model = module.build_model(fold["seed"], spec["task"])
            started = time.perf_counter()
            model.fit(features, labels)
            fitting = time.perf_counter() - started
            started = time.perf_counter()
            values = predictions(np, model, matrix(np, rows, valid_ids, spec["features"]), spec["task"])
            inference = time.perf_counter() - started
            oof.update(zip(valid_ids, map(float, values)))
            model_name = f"models/fold-{index}.joblib"
            joblib.dump(model, output / model_name)
            receipts.append({"fold_id": fold["id"], "seed": fold["seed"], "train_ids": train_ids,
                             "validation_ids": valid_ids, "train_id_hash": object_hash(train_ids),
                             "validation_id_hash": object_hash(valid_ids), "model": model_name,
                             "fit_seconds": fitting, "prediction_seconds": inference,
                             "model_bytes": (output / model_name).stat().st_size})
    ordered = spec["expected_oof_ids"]
    save_csv(output / "oof.csv", [identifier, spec.get("prediction_column", "prediction")],
             [(key, repr(oof[key])) for key in ordered])
    save_csv(output / "truth.csv", [identifier, target], [(key, rows[key][target]) for key in ordered])
    result = score(spec, output / "truth.csv", output / "oof.csv", "development", output / "evaluation",
                   object_hash(spec))
    write_json(output / "fit.json", {"folds": receipts, "environment": execution_environment,
               "adapter_hash": byte_hash(Path(__file__).read_bytes()), "preprocessing_scope": "estimator.fit(training_rows)",
               "oof_aggregation": "one prediction per declared row; pooled unweighted metric",
               "inference_recipe": "arithmetic mean of all fitted fold model predictions",
               "unchecked": ["arbitrary_candidate_code_access", "upstream_feature_leakage", "competition_rules",
                             "prior_confirmation_exposure", "resource_limits"]})
    manifest = seal(output, {"kind": "tabular_training", "task_id": spec["task_id"],
                            "score": result["score"], "protocol_hash": object_hash(spec)})
    return {"status": "success", "manifest": str(output / "manifest.json"), "seal": manifest["seal"],
            "result": str(output / "evaluation/result.json"), "score": result["score"]}


def freeze(run: Path, output: Path, decision_rule: str) -> dict:
    manifest = verified_manifest(run, "tabular_training")
    if not decision_rule.strip():
        raise TrainingFailure("Freeze a delivery decision rule before confirmation")
    output.mkdir()
    for name, expected in manifest["files"].items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = (run / name).read_bytes()
        if byte_hash(raw) != expected:
            raise TrainingFailure("Training artifact changed while freezing: " + name)
        destination.write_bytes(raw)
    frozen = seal(output, {"kind": "tabular_frozen", "training_seal": manifest["seal"],
                          "decision_rule": decision_rule, "protocol_hash": manifest["protocol_hash"]})
    return {"status": "frozen", "manifest": str(output / "manifest.json"), "seal": frozen["seal"]}


def deliver(frozen: Path, data: Path, output: Path, *, truth: Path | None = None,
            sample_submission: Path | None = None) -> dict:
    if output.exists():
        raise FileExistsError("Delivery output already exists: " + str(output))
    np, joblib, limits = runtime()
    manifest = verified_manifest(frozen, "tabular_frozen")
    spec = read_json(frozen / "protocol.json")
    identifier, column = spec.get("id_column", "id"), spec.get("prediction_column", "prediction")
    receipt = read_json(frozen / "fit.json")
    if environment() != receipt["environment"]:
        raise TrainingFailure("Frozen models require the recorded Python/platform/package environment")
    _, training = csv_rows(frozen / "training.csv", [identifier, *metadata_columns(spec)])
    _, rows = csv_rows(data, [identifier, *spec["features"], *metadata_columns(spec, training=False)])
    check_boundary(spec, training, rows)
    ids = list(rows)
    if sample_submission is not None:
        header, sample = csv_rows(sample_submission, [identifier, column])
        if header != [identifier, column] or sample.keys() != rows.keys():
            raise TrainingFailure("Sample submission must have exact ID/prediction columns and matching IDs")
        ids = list(sample)
    # Import only the sealed candidate, so models with candidate-defined classes can unpickle.
    module_spec = importlib.util.spec_from_file_location("competition_candidate", frozen / "candidate.py")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    started = time.perf_counter()
    with limits(limits=1):
        features = matrix(np, rows, ids, spec["features"])
        values = np.zeros(len(ids))
        for fold in receipt["folds"]:
            model = joblib.load(frozen / fold["model"])
            values += predictions(np, model, features, spec["task"]) / len(receipt["folds"])
    output.mkdir()
    prediction_path = output / ("submission.csv" if sample_submission is not None else "predictions.csv")
    save_csv(prediction_path, [identifier, column], [(key, repr(float(value))) for key, value in zip(ids, values)])
    report = {"status": "success", "frozen_seal": manifest["seal"], "decision_rule": manifest["decision_rule"],
              "data_hash": byte_hash(data.read_bytes()), "prediction_hash": byte_hash(prediction_path.read_bytes()),
              "prediction_seconds": time.perf_counter() - started, "row_count": len(ids),
              "sample_submission_hash": byte_hash(sample_submission.read_bytes()) if sample_submission else None}
    if truth is not None:
        # Confirmation is first read here, after frozen model selection and inference.
        result = score(spec, truth, prediction_path, "confirmation", output / "evaluation",
                       manifest["protocol_hash"] + ":confirmation")
        report["score"] = result["score"]
    write_json(output / "delivery.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    fit = commands.add_parser("train")
    for name in ["data", "protocol", "candidate"]:
        fit.add_argument("--" + name, type=Path, required=True)
    frozen = commands.add_parser("freeze")
    frozen.add_argument("--run", type=Path, required=True)
    frozen.add_argument("--decision-rule", required=True)
    for command in ["confirm", "predict"]:
        p = commands.add_parser(command)
        p.add_argument("--frozen", type=Path, required=True)
        p.add_argument("--data", type=Path, required=True)
        p.add_argument("--truth" if command == "confirm" else "--sample-submission", type=Path, required=True)
    for p in [fit, frozen, *[commands.choices[name] for name in ["confirm", "predict"]]]:
        p.add_argument("--output-dir", type=Path, required=True, help="New directory; parent must exist")
    args = parser.parse_args()
    try:
        if args.operation == "train":
            report = train(args.data, args.protocol, args.candidate, args.output_dir)
        elif args.operation == "freeze":
            report = freeze(args.run, args.output_dir, args.decision_rule)
        else:
            report = deliver(args.frozen, args.data, args.output_dir,
                             truth=getattr(args, "truth", None), sample_submission=getattr(args, "sample_submission", None))
        print(json.dumps(report, allow_nan=False, indent=2))
        return 0
    except Exception as exc:
        # Estimator errors are failures too; never emit a successful fit receipt for them.
        print(json.dumps({"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
