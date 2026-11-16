#!/usr/bin/env python3
"""Estimate sampling uncertainty of a fixed prediction pair using paired bootstrap."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import platform
import random
import sys
from typing import Any, Callable

import evaluate_predictions as evaluator
from compare_prediction_results import ComparisonFailure
from prediction_evidence import EvidenceFailure, load_pair, read_categories


class UncertaintyFailure(Exception):
    pass


def percentile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    fraction = position - left
    return math.fsum([ordered[left] * (1 - fraction), ordered[right] * fraction])


def summarize(replicates: list[dict], confidence: float, minimum_improvement: float) -> dict[str, Any]:
    differences = sorted(row["objective_improvement"] for row in replicates if row["status"] == "success")
    unavailable = None
    if len(differences) < 100 or len(differences) / len(replicates) < 0.9:
        unavailable = "Requires at least 100 valid replicates and at least 90% valid draws"
    interval = None
    preference = "inconclusive"
    fraction = None
    if unavailable is None:
        tail = (1 - confidence) / 2
        lower, upper = percentile(differences, tail), percentile(differences, 1 - tail)
        interval = {"method": "paired_percentile_bootstrap", "confidence_level": confidence,
                    "lower": lower, "upper": upper}
        if lower > minimum_improvement:
            preference = "candidate_supported"
        elif upper < -minimum_improvement:
            preference = "baseline_supported"
        fraction = sum(value > minimum_improvement for value in differences) / len(differences)
    return {
        "status": "available" if unavailable is None else "unavailable",
        "requested_replicates": len(replicates), "valid_replicates": len(differences),
        "invalid_replicates": len(replicates) - len(differences), "unavailable_reason": unavailable,
        "objective_improvement_interval": interval, "minimum_improvement": minimum_improvement,
        "evidence_preference": preference, "fraction_above_minimum": fraction,
    }


def prepare_loss_score(metric: str, labels: list[float], predictions: list[float],
                       epsilon: float) -> Callable[[list[int]], float]:
    """Cache row losses, retaining per-draw scaling for finite-range regression."""
    if metric in {"rmse", "mae"}:
        residuals = [abs(label - value) for label, value in zip(labels, predictions)]

        def score(indexes: list[int]) -> float:
            selected = [residuals[index] for index in indexes]
            scale = max(selected)
            if scale == 0:
                return 0.0
            # A global scale can underflow small residuals when an extreme row is absent.
            return scale * (math.sqrt(math.fsum((value / scale) ** 2 for value in selected) / len(selected))
                            if metric == "rmse" else math.fsum(value / scale for value in selected) / len(selected))

        return score
    clipped = [min(1 - epsilon, max(epsilon, value)) for value in predictions]
    losses = [-math.log(p) if label == 1 else -math.log1p(-p) for label, p in zip(labels, clipped)]
    return lambda indexes: math.fsum(losses[index] for index in indexes) / len(indexes)


def prepare_auc_order(labels: list[float], predictions: list[float]) -> list[tuple[int, bool, bool]]:
    """Sort once; each row carries its class and whether its score tie ends here."""
    order = sorted(range(len(labels)), key=predictions.__getitem__)
    return [(index, labels[index] == 1,
             position + 1 == len(order) or predictions[index] != predictions[order[position + 1]])
            for position, index in enumerate(order)]


def resampled_auc(order: list[tuple[int, bool, bool]], multiplicities: list[int],
                  positive_count: int, negative_count: int) -> float:
    """Compute the original pooled AUC using integer row multiplicities."""
    positives = negatives = negatives_before = twice_favorable = 0
    for index, positive, tie_end in order:
        if positive:
            positives += multiplicities[index]
        else:
            negatives += multiplicities[index]
        if tie_end:
            twice_favorable += positives * (2 * negatives_before + negatives)
            negatives_before += negatives
            positives = negatives = 0
    return twice_favorable / (2 * positive_count * negative_count)


def bootstrap(metric: str, labels: list[float], before: list[float], after: list[float], units: list[list[int]],
              repetitions: int, seed: int, epsilon: float, max_row_draws: int) -> tuple[list[dict], int]:
    if len(units) < 2 or any(not unit for unit in units):
        raise UncertaintyFailure("At least two non-empty independent sampling units are required")
    if sorted(index for unit in units for index in unit) != list(range(len(labels))):
        raise UncertaintyFailure("Sampling units must partition the evaluated rows exactly once")
    if repetitions < 100 or repetitions > 10000 or max_row_draws < 1:
        raise UncertaintyFailure("Bootstrap samples must be 100-10000 and max-row-draws positive")
    if len(labels) * repetitions > max_row_draws:
        raise UncertaintyFailure("Expected bootstrap work exceeds --max-row-draws; budget more compute or fewer replicates")
    # Check immutable inputs once, before sampling; each draw only changes multiplicity.
    for predictions in [before, after]:
        evaluator.calculate_metric(metric, labels, predictions, epsilon)
    if metric == "roc_auc":
        orders = [prepare_auc_order(labels, predictions) for predictions in [before, after]]
    else:
        scorers = [prepare_loss_score(metric, labels, predictions, epsilon) for predictions in [before, after]]
    rng = random.Random(seed)
    rows, row_draws = [], 0
    for iteration in range(repetitions):
        sampled_units = [units[rng.randrange(len(units))] for _ in units]
        count = sum(len(unit) for unit in sampled_units)
        if row_draws + count > max_row_draws:
            raise UncertaintyFailure("Bootstrap exceeded --max-row-draws; reduce replicates or explicitly budget more compute")
        row_draws += count
        indexes = [index for unit in sampled_units for index in unit]
        if metric == "roc_auc":
            multiplicities = [0] * len(labels)
            positive_count = 0
            for index in indexes:
                multiplicities[index] += 1
                positive_count += labels[index] == 1
            negative_count = count - positive_count
            if not positive_count or not negative_count:
                rows.append({"replicate": iteration + 1, "case_count": count, "status": "unavailable",
                             "baseline_score": None, "candidate_score": None, "objective_improvement": None,
                             "unavailable_reason": "roc_auc_requires_both_classes"})
                continue
            baseline_score, candidate_score = [resampled_auc(order, multiplicities, positive_count, negative_count)
                                                for order in orders]
        else:
            baseline_score, candidate_score = [score(indexes) for score in scorers]
        improvement = (candidate_score - baseline_score if evaluator.METRIC_DIRECTIONS[metric] == "maximize"
                       else baseline_score - candidate_score)
        rows.append({"replicate": iteration + 1, "case_count": count, "status": "success",
                     "baseline_score": baseline_score, "candidate_score": candidate_score,
                     "objective_improvement": improvement, "unavailable_reason": None})
    return rows, row_draws


def assess(args: argparse.Namespace, output_dir: pathlib.Path) -> dict[str, Any]:
    if (not math.isfinite(args.confidence_level) or not 0 < args.confidence_level < 1
            or not math.isfinite(args.minimum_improvement) or args.minimum_improvement < 0):
        raise UncertaintyFailure("Confidence must be between 0 and 1; minimum improvement finite and non-negative")
    if args.resampling_unit == "row" and (args.groups is not None or args.group_column is not None):
        raise UncertaintyFailure("Group arguments are only valid for --resampling-unit group")
    if args.resampling_unit == "group" and (args.groups is None or not args.group_column or not args.group_column.strip()):
        raise UncertaintyFailure("Group resampling requires --groups and a non-empty --group-column")
    pair = load_pair(args.baseline, args.candidate, args.truth)
    group_raw = None
    groups: dict[str, list[int]] = {}
    if args.resampling_unit == "group":
        if args.group_column == pair.configuration["id_column"]:
            raise UncertaintyFailure("Group and ID columns must differ")
        group_raw = args.groups.expanduser().resolve(strict=True).read_bytes()
        categories = read_categories(group_raw, pair.configuration["id_column"], [args.group_column], set(pair.sample_ids))
        for index, sample_id in enumerate(pair.sample_ids):
            groups.setdefault(categories[sample_id][args.group_column], []).append(index)
        units = [groups[name] for name in sorted(groups)]
    else:
        units = [[index] for index in range(len(pair.sample_ids))]
    replicates, row_draws = bootstrap(pair.metric, pair.labels, pair.baseline, pair.candidate, units,
                                    args.bootstrap_samples, args.seed, pair.epsilon, args.max_row_draws)
    uncertainty = summarize(replicates, args.confidence_level, args.minimum_improvement)
    for name, raw in zip(["baseline.csv", "candidate.csv"], pair.prediction_bytes):
        with (output_dir / name).open("xb") as stream:
            stream.write(raw)
    if group_raw is not None:
        with (output_dir / "groups.csv").open("xb") as stream:
            stream.write(group_raw)
    with (output_dir / "bootstrap.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(replicates[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(replicates)
    configuration = {
        "resampling_unit": args.resampling_unit, "bootstrap_samples": args.bootstrap_samples, "seed": args.seed,
        "confidence_level": args.confidence_level, "minimum_improvement": args.minimum_improvement,
        "max_row_draws": args.max_row_draws, "group_column": args.group_column,
        "group_hash": evaluator.byte_hash(group_raw) if group_raw is not None else None,
        "python": platform.python_version(),
    }
    return {
        "schema_version": 1, "adapter": "prediction_sampling_uncertainty", "status": "success",
        "selection_scope": "fixed_predictions_conditional_on_sampling_assumptions",
        "aggregate_comparison": pair.comparison, "uncertainty": uncertainty,
        "sampling_unit_count": len(units), "case_count": len(pair.sample_ids), "row_draws": row_draws,
        "configuration": configuration, "config_hash": evaluator.object_hash(configuration),
        "estimator_hash": evaluator.object_hash({name: evaluator.byte_hash(pathlib.Path(__file__).with_name(name).read_bytes())
                                                 for name in ["compare_prediction_uncertainty.py", "prediction_evidence.py",
                                                              "evaluate_predictions.py", "compare_prediction_results.py"]}),
        "inputs": {key: str(path) for key, path in pair.paths.items()}, "input_hashes": pair.input_hashes,
        "unchecked_rules": sorted(set(pair.comparison["unchecked_rules"]) | {
            "sampling_unit_independence", "distribution_shift", "training_variation", "multiple_comparisons"}),
        "artifacts": [str(output_dir / name) for name in
                      ["baseline.csv", "candidate.csv", "bootstrap.csv", *(["groups.csv"] if group_raw else [])]],
        "note": "The interval estimates sampling variation conditional on fixed predictions and exchangeable units. "
                "The bootstrap fraction is not a p-value or probability of winning. It does not establish leaderboard gain.",
        "error": None,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["baseline", "candidate", "truth", "output-dir"]:
        parser.add_argument(f"--{name}", required=True, type=pathlib.Path)
    parser.add_argument("--resampling-unit", required=True, choices=["row", "group"])
    parser.add_argument("--groups", type=pathlib.Path, help="full-split ID/group metadata for cluster resampling")
    parser.add_argument("--group-column", help="column identifying independent clusters")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--minimum-improvement", type=float, default=0,
                        help="practical threshold in the declared metric's units, chosen before comparison")
    parser.add_argument("--max-row-draws", type=int, default=2000000,
                        help="total resampled row occurrences allowed across all replicates")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    created = False
    try:
        output_dir.mkdir(exist_ok=False)
        created = True
        result = assess(args, output_dir)
    except (OSError, UncertaintyFailure, EvidenceFailure, ComparisonFailure, evaluator.PredictionFailure,
            ValueError, TypeError, KeyError, OverflowError) as exc:
        result = {"schema_version": 1, "adapter": "prediction_sampling_uncertainty", "status": "failed",
                  "error": {"type": "uncertainty_invalid", "message": str(exc)}}
    if created:
        try:
            with (output_dir / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": {"type": "output_failure", "message": str(exc)}},
                             ensure_ascii=False), file=sys.stderr)
            return 2
    print(json.dumps({"status": result["status"], "report": str(output_dir / "report.json") if created else None,
                      "uncertainty": result.get("uncertainty"), "error": result["error"]}, ensure_ascii=False),
          file=sys.stdout if result["status"] == "success" else sys.stderr)
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
