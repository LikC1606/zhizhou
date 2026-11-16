#!/usr/bin/env python3
"""Compare fixed-budget plurality with irreversible-lead stopping on cached development answers."""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys
import json
from collections import Counter
from typing import Any

import candidate_evidence as evidence


class ReplayFailure(Exception):
    pass


def exact_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayFailure(f"{field} must be a non-empty string")
    return value


def read_trace(raw: bytes) -> dict[str, Any]:
    trace = evidence.load_json(raw, "inference trace")
    if (not isinstance(trace, dict) or type(trace.get("schema_version")) is not int
            or trace["schema_version"] != 1):
        raise ReplayFailure("Expected inference trace schema_version 1")
    if trace.get("stage") != "development":
        raise ReplayFailure("Exploratory replay requires development evidence")
    generation = trace.get("generation")
    if not isinstance(generation, dict):
        raise ReplayFailure("Missing generation identities")
    for field in ["recipe_sha256", "workload_sha256", "answer_parser_sha256"]:
        value = generation.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ReplayFailure(f"generation.{field} must be a lowercase SHA-256")
    cases = trace.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ReplayFailure("Need a non-empty cases list")
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ReplayFailure("Each case must be an object")
        case_id = exact_text(case.get("id"), "case.id")
        if case_id in case_ids:
            raise ReplayFailure(f"Duplicate case ID: {case_id}")
        case_ids.add(case_id)
        exact_text(case.get("target"), f"{case_id}.target")
        samples = case.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ReplayFailure(f"{case_id} needs ordered samples")
        sample_ids: set[str] = set()
        for sample in samples:
            if not isinstance(sample, dict):
                raise ReplayFailure("Each sample must be an object")
            sample_id = exact_text(sample.get("id"), "sample.id")
            if sample_id in sample_ids:
                raise ReplayFailure(f"Duplicate sample ID in {case_id}: {sample_id}")
            sample_ids.add(sample_id)
            status = sample.get("status")
            if status not in ("completed", "invalid", "timeout", "failed"):
                raise ReplayFailure("Sample status must be completed, invalid, timeout or failed")
            if status == "completed":
                exact_text(sample.get("answer"), "completed sample.answer")
            elif "answer" not in sample or sample["answer"] is not None:
                raise ReplayFailure("Unsuccessful samples require answer: null and still consume a slot")
            seconds = sample.get("elapsed_seconds")
            if seconds is not None and (type(seconds) not in (int, float)
                                        or not math.isfinite(seconds) or seconds < 0):
                raise ReplayFailure("elapsed_seconds must be finite and non-negative, or null/omitted")
    return trace


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(sample["answer"] for sample in samples if sample["status"] == "completed")
    # Counter preserves insertion order, so a tied answer first seen wins.
    answer = max(counts, key=counts.get) if counts else None
    times = [sample.get("elapsed_seconds") for sample in samples]
    return {
        "answer": answer,
        "samples_used": len(samples),
        "valid_votes": sum(counts.values()),
        "failure_counts": dict(Counter(sample["status"] for sample in samples
                                       if sample["status"] != "completed")),
        "cached_sample_seconds": math.fsum(times) if all(t is not None for t in times) else None,
    }


def replay_case(samples: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    used = len(samples)
    for index, sample in enumerate(samples, 1):
        if sample["status"] == "completed":
            counts[sample["answer"]] += 1
        leaders = counts.most_common(2)
        if leaders:
            leader_count = leaders[0][1]
            runner_count = leaders[1][1] if len(leaders) > 1 else 0
            remaining = len(samples) - index
            if leader_count > runner_count + remaining:
                used = index
                break
    return {**summarize_samples(samples[:used]),
            "stop_reason": "irreversible_lead" if used < len(samples) else "sample_limit"}


def analyze_cases(trace: dict[str, Any], max_samples: int) -> dict[str, Any]:
    if type(max_samples) is not int or max_samples < 1:
        raise ReplayFailure("max-samples must be a positive integer")
    rows = []
    for case in trace["cases"]:
        if len(case["samples"]) < max_samples:
            raise ReplayFailure(f"{case['id']} has fewer recorded slots than max-samples; missing slots are unknown")
        samples = case["samples"][:max_samples]
        full = summarize_samples(samples)
        early = replay_case(samples)
        for outcome in [full, early]:
            outcome["correct"] = outcome["answer"] == case["target"]
        rows.append({"id": case["id"], "target": case["target"],
                     "correct_sample_available": any(sample["status"] == "completed"
                                                     and sample["answer"] == case["target"] for sample in samples),
                     "full_budget": full, "early_stop": early})

    def aggregate(key: str) -> dict[str, Any]:
        outcomes = [row[key] for row in rows]
        seconds = [outcome["cached_sample_seconds"] for outcome in outcomes]
        correct = sum(outcome["correct"] for outcome in outcomes)
        failures: Counter[str] = Counter()
        for outcome in outcomes:
            failures.update(outcome["failure_counts"])
        return {"correct_count": correct, "exact_match_accuracy": correct / len(rows),
                "no_answer_count": sum(outcome["answer"] is None for outcome in outcomes),
                "samples_used": sum(outcome["samples_used"] for outcome in outcomes),
                "failure_counts": dict(failures),
                "cached_sample_seconds": math.fsum(seconds) if all(t is not None for t in seconds) else None}

    full, early = aggregate("full_budget"), aggregate("early_stop")
    return {"case_count": len(rows), "full_budget": full, "early_stop": early,
            "skipped_sample_slots": full["samples_used"] - early["samples_used"],
            "answers_unchanged": all(row["full_budget"]["answer"] == row["early_stop"]["answer"] for row in rows),
            "cases_with_correct_sample": sum(row["correct_sample_available"] for row in rows),
            "cases": rows}


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    path = args.trace.expanduser().resolve(strict=True)
    raw = path.read_bytes()
    trace = read_trace(raw)
    report = analyze_cases(trace, args.max_samples)
    if path.read_bytes() != raw:
        raise ReplayFailure("Trace bytes changed during replay")
    configuration = {"max_samples": args.max_samples, "vote_rule": "plurality_first_seen",
                     "stop_rule": "leader_count_gt_runner_count_plus_remaining_slots",
                     "failed_samples": "consume_slot_without_vote"}
    analyzer_files = {p.name: evidence.sha256(p.read_bytes()) for p in
                      [pathlib.Path(__file__), pathlib.Path(evidence.__file__)]}
    return {"schema_version": 1, "status": "analyzed", "selection_scope": "cached_inference_votes_only",
            "input": {"path": str(path), "sha256": evidence.sha256(raw)},
            "generation": trace["generation"], "configuration": configuration,
            "configuration_sha256": evidence.sha256(evidence.canonical(configuration)),
            "analyzer_files": analyzer_files,
            "analyzer_sha256": evidence.sha256(evidence.canonical(analyzer_files)),
            **report,
            "note": "Development diagnostic on fixed, ordered, already parsed samples. Exact-match accuracy "
                    "is an unweighted cache statistic, not an official score or a new executed candidate. "
                    "Targets never select votes. Cached sample seconds only sum supplied per-sample costs; "
                    "they do not predict wall time, batching/cache effects or new interactive outcomes. "
                    "Missing costs remain unknown. The task adapter owns cache completeness and provenance."}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=pathlib.Path, help="ordered development answer cache")
    parser.add_argument("--max-samples", required=True, type=int, help="fixed per-case sample-slot budget")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="new diagnostic JSON; never overwritten")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        report = analyze(args)
        with args.output.expanduser().resolve().open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    except (OSError, ReplayFailure, evidence.ArchiveFailure, ValueError, OverflowError) as exc:
        print(json.dumps({"schema_version": 1, "status": "failed", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
