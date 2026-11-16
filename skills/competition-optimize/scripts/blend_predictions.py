#!/usr/bin/env python3
"""Create a convex prediction blend on development results or apply its frozen recipe."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import pathlib
import re
import sys
from typing import Any

from compare_prediction_results import ComparisonFailure, compare, load_result
from evaluate_predictions import UNCHECKED_RULES, PredictionFailure, byte_hash, object_hash, read_values


NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
HASH_PATTERN = r"[0-9a-f]{64}"
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                  *(f"LPT{i}" for i in range(1, 10))}


class BlendFailure(Exception):
    pass


def valid_name(name: Any) -> bool:
    return (isinstance(name, str) and re.fullmatch(NAME_PATTERN, name) is not None
            and name.split(".", 1)[0].upper() not in RESERVED_NAMES)


def normalize_weights(weights: list[float], count: int) -> list[float]:
    if len(weights) != count:
        raise BlendFailure("Provide exactly one weight per named member, in member order")
    if any(type(weight) not in {int, float} or not math.isfinite(weight) or weight < 0 for weight in weights):
        raise BlendFailure("Weights must be finite, non-negative numbers")
    scale = max(weights)
    if scale == 0:
        raise BlendFailure("At least one member must have a positive weight")
    scaled = [weight / scale for weight in weights]
    total = math.fsum(scaled)
    normalized = [weight / total for weight in scaled]
    if any(original > 0 and weight == 0 for original, weight in zip(weights, normalized)):
        raise BlendFailure("Weight range is too large to preserve positive weights")
    return normalized


def named_paths(members: list[list[str]]) -> dict[str, pathlib.Path]:
    paths: dict[str, pathlib.Path] = {}
    seen_names: set[str] = set()
    for name, path in members:
        if not valid_name(name):
            raise BlendFailure("Member names must be 1-64 ASCII letters, digits, dots, underscores, or hyphens;"
                               " Windows device names are reserved")
        if name.lower() in seen_names:
            raise BlendFailure(f"Duplicate member name: {name}")
        seen_names.add(name.lower())
        paths[name] = pathlib.Path(path).expanduser().resolve(strict=True)
    if len(paths) < 2:
        raise BlendFailure("A blend needs at least two named members")
    return paths


def create_recipe(paths: dict[str, pathlib.Path], weights: list[float]) -> tuple[dict, dict, list]:
    normalized = normalize_weights(weights, len(paths))
    results = {name: load_result(path) for name, path in paths.items()}
    reference = next(iter(results.values()))
    if reference["evaluation"]["stage"] != "development":
        raise BlendFailure("Create and select blend recipes using development results only")
    for result in results.values():
        compare(reference, result, 0)
    config = reference["evaluation"]["configuration"]
    for key in ["id_column", "prediction_column"]:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise BlendFailure("Development results must declare valid prediction columns")
    if config["id_column"] == config["prediction_column"]:
        raise BlendFailure("ID and prediction columns must differ")
    inputs: dict[str, bytes] = {}
    lineage = []
    for name, path in paths.items():
        raw = (path.parent / "predictions.csv").read_bytes()
        if byte_hash(raw) != results[name]["candidate_hash"]:
            raise BlendFailure(f"Prediction snapshot changed while reading member {name}")
        inputs[name] = raw
        lineage.append({"name": name, "input": str(path.parent / "predictions.csv"),
                        "candidate_hash": byte_hash(raw), "evaluation": str(path),
                        "evaluation_hash": byte_hash(path.read_bytes())})
    recipe = {
        "schema_version": 1, "kind": "prediction_blend", "operation": "convex_weighted_mean",
        "id_column": config["id_column"], "prediction_column": config["prediction_column"],
        "members": [{"name": name, "weight": weight,
                     "development_candidate_hash": results[name]["candidate_hash"]}
                    for name, weight in zip(paths, normalized)],
        "selection_contract": {
            "stage": "development", "split_hash": reference["evaluation"]["split_hash"],
            "config_hash": reference["evaluation"]["config_hash"],
            "evaluator_hash": reference["evaluator_hash"], "score_model_hash": reference["score_model_hash"],
        },
    }
    recipe["recipe_hash"] = object_hash(recipe)
    return recipe, inputs, lineage


def load_recipe(path: pathlib.Path) -> dict[str, Any]:
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(recipe, dict):
            raise BlendFailure("Recipe must be a JSON object")
        body = {key: value for key, value in recipe.items() if key != "recipe_hash"}
        if object_hash(body) != recipe.get("recipe_hash"):
            raise BlendFailure("Recipe content does not match its hash")
    except (UnicodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise BlendFailure(f"Invalid recipe: {exc}") from exc
    if (type(recipe.get("schema_version")) is not int or recipe["schema_version"] != 1
            or recipe.get("kind") != "prediction_blend" or recipe.get("operation") != "convex_weighted_mean"):
        raise BlendFailure("Unsupported blend recipe")
    for key in ["id_column", "prediction_column"]:
        if not isinstance(recipe.get(key), str) or not recipe[key].strip():
            raise BlendFailure("Recipe columns must be non-empty strings")
    if recipe["id_column"] == recipe["prediction_column"]:
        raise BlendFailure("ID and prediction columns must differ")
    members = recipe.get("members")
    if not isinstance(members, list) or len(members) < 2:
        raise BlendFailure("Recipe requires at least two members")
    names, weights = [], []
    for member in members:
        if not isinstance(member, dict):
            raise BlendFailure("Malformed recipe member")
        name, weight = member.get("name"), member.get("weight")
        if not valid_name(name) or name.lower() in {item.lower() for item in names}:
            raise BlendFailure("Recipe member names must be unique and valid")
        if type(weight) not in {int, float} or not math.isfinite(weight) or not 0 <= weight <= 1:
            raise BlendFailure("Recipe weights must be finite numbers in [0, 1]")
        development_hash = member.get("development_candidate_hash")
        if not isinstance(development_hash, str) or not re.fullmatch(HASH_PATTERN, development_hash):
            raise BlendFailure("Missing development prediction hash")
        names.append(name)
        weights.append(weight)
    if not math.isclose(math.fsum(weights), 1, rel_tol=0, abs_tol=1e-12):
        raise BlendFailure("Recipe weights must sum to one")
    contract = recipe.get("selection_contract")
    if not isinstance(contract, dict) or contract.get("stage") != "development":
        raise BlendFailure("Recipe must record a development selection contract")
    for key in ["split_hash", "config_hash", "evaluator_hash", "score_model_hash"]:
        if not isinstance(contract.get(key), str) or not re.fullmatch(HASH_PATTERN, contract[key]):
            raise BlendFailure(f"Missing or malformed selection {key}")
    return recipe


def blend_csv(recipe: dict, inputs: dict[str, bytes]) -> tuple[bytes, int]:
    expected = {member["name"] for member in recipe["members"]}
    if inputs.keys() != expected:
        raise BlendFailure("Input member names must exactly match the frozen recipe")
    values = {name: read_values(raw, recipe["id_column"], recipe["prediction_column"], name)
              for name, raw in inputs.items()}
    sample_ids = next(iter(values.values())).keys()
    if any(member_values.keys() != sample_ids for member_values in values.values()):
        raise BlendFailure("Member prediction IDs differ; all members must cover the same samples")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([recipe["id_column"], recipe["prediction_column"]])
    active = [member for member in recipe["members"] if member["weight"] > 0]
    for sample_id in sorted(sample_ids):
        predictions = [values[member["name"]][sample_id] for member in active]
        try:
            value = math.fsum(member["weight"] * prediction for member, prediction in zip(active, predictions))
        except OverflowError:
            # Scaling is a fallback for sum overflow, preserving cancellation accuracy normally.
            scale = max(abs(value) for value in predictions)
            scaled = [value / scale for value in predictions]
            mean = math.fsum(member["weight"] * value for member, value in zip(active, scaled))
            value = scale * min(max(scaled), max(min(scaled), mean))
        value = min(max(predictions), max(min(predictions), value))
        if not math.isfinite(value):
            raise BlendFailure("Blended prediction is not finite")
        writer.writerow([sample_id, repr(value)])
    return stream.getvalue().encode("utf-8"), len(sample_ids)


def build(args: argparse.Namespace, output_dir: pathlib.Path) -> dict[str, Any]:
    paths = named_paths(args.member)
    if args.command == "create":
        recipe, inputs, lineage = create_recipe(paths, args.weights)
    else:
        recipe_path = args.recipe.expanduser().resolve(strict=True)
        recipe = load_recipe(recipe_path)
        inputs = {name: path.read_bytes() for name, path in paths.items()}
        lineage = [{"name": name, "input": str(paths[name]), "candidate_hash": byte_hash(raw)}
                   for name, raw in inputs.items()]
    prediction_raw, count = blend_csv(recipe, inputs)
    parent_dir = output_dir / "parents"
    parent_dir.mkdir()
    for name, raw in inputs.items():
        with (parent_dir / f"{name}.csv").open("xb") as stream:
            stream.write(raw)
    with (output_dir / "predictions.csv").open("xb") as stream:
        stream.write(prediction_raw)
    with (output_dir / "recipe.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(recipe, allow_nan=False, indent=2) + "\n")
    return {
        "schema_version": 1, "adapter": "prediction_blend", "status": "success",
        "command": args.command, "recipe_hash": recipe["recipe_hash"],
        "builder_hash": object_hash({name: byte_hash(pathlib.Path(__file__).with_name(name).read_bytes())
                                     for name in ["blend_predictions.py", "evaluate_predictions.py",
                                                  "compare_prediction_results.py"]}),
        "candidate_hash": byte_hash(prediction_raw), "case_count": count,
        "parents": lineage, "score": {"value": None},
        "unchecked_rules": [*UNCHECKED_RULES, "member_model_identity", "ensemble_resource_limits"],
        "artifacts": [str(output_dir / name) for name in ["predictions.csv", "recipe.json", "parents"]],
        "note": "Candidate construction only; evaluate this blend and confirm the frozen recipe separately.",
        "error": None,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ["create", "apply"]:
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--member", required=True, action="append", nargs=2, metavar=("NAME", "PATH"),
                               help="named development result.json for create; named prediction CSV for apply")
        subparser.add_argument("--output-dir", required=True, type=pathlib.Path,
                               help="new directory under an existing parent; never overwrite")
        if command == "create":
            subparser.add_argument("--weights", required=True, nargs="+", type=float,
                                   help="non-negative weights in member order; normalized before saving")
        else:
            subparser.add_argument("--recipe", required=True, type=pathlib.Path)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    created = False
    try:
        output_dir.mkdir(exist_ok=False)
        created = True
        result = build(args, output_dir)
    except (OSError, BlendFailure, ComparisonFailure, PredictionFailure, ValueError, TypeError, OverflowError) as exc:
        result = {"schema_version": 1, "adapter": "prediction_blend", "status": "failed",
                  "score": {"value": None}, "error": {"type": "blend_invalid", "message": str(exc)}}
    if created:
        try:
            with (output_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": {"type": "output_failure", "message": str(exc)}},
                             ensure_ascii=False), file=sys.stderr)
            return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2),
          file=sys.stdout if result["status"] == "success" else sys.stderr)
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
