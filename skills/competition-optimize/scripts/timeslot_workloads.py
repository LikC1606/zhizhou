"""The fixed-timeslot workload protocol shared by execution and evidence readers.

Schema-2 results predate the explicit seal, but their complete rows can still be
verified against this exact protocol. A producer's claimed case list is never
used as the definition of a full or short evaluation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


PROTOCOL = "fixed-timeslot-v1"
SEEDS = (1, 7, 17, 31, 101)
FULL_SIZES = (400, 10000)
SHORT_SIZES = (100, 400, 10000)
SHORT_LENGTHS = (1, 10, 100)
SCENARIOS = ("mixed", "sparse", "dense", "single", "bulk", "many-types", "dominant", "uneven", "fresh-id")
WorkloadKey = tuple[int, int, int, str]


class WorkloadFailure(ValueError):
    pass


def invocations(stage: str) -> tuple[tuple[int, int, int], ...]:
    """Return the ordered (N, Q, seed) invocations for a fixed stage."""
    if stage == "smoke":
        return ((100, 1, 17),)
    if stage == "short":
        return tuple((n, q, seed) for n in SHORT_SIZES for q in SHORT_LENGTHS for seed in SEEDS)
    if stage == "full":
        return tuple((n, 1000, seed) for n in FULL_SIZES for seed in SEEDS)
    raise WorkloadFailure(f"Unknown workload stage: {stage}")


def expected_keys(stage: str) -> frozenset[WorkloadKey]:
    return frozenset((n, q, seed, scenario) for n, q, seed in invocations(stage) for scenario in SCENARIOS)


def seal(stage: str) -> dict[str, Any]:
    definition = {"protocol": PROTOCOL, "stage": stage, "invocations": invocations(stage), "scenarios": SCENARIOS}
    encoded = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"workload_protocol": PROTOCOL, "workload_hash": hashlib.sha256(encoded).hexdigest(),
            "expected_cases": len(expected_keys(stage))}


def validate_coverage(stage: str, keys: Iterable[WorkloadKey]) -> dict[str, Any]:
    actual = list(keys)
    unique = set(actual)
    if len(unique) != len(actual):
        raise WorkloadFailure("Duplicate workload key in evaluation")
    expected = expected_keys(stage)
    missing, extra = sorted(expected - unique), sorted(unique - expected)
    if missing or extra:
        raise WorkloadFailure(f"Incomplete or unexpected workload coverage for {stage}: "
                              f"expected={len(expected)}, received={len(actual)}, "
                              f"missing={missing[:3]}, extra={extra[:3]}")
    return seal(stage)


def validate_result(result: dict[str, Any], keys: Iterable[WorkloadKey]) -> dict[str, Any]:
    """Verify independent expected coverage, then any producer-supplied seal."""
    try:
        contract = validate_coverage(result["stage"], keys)
    except WorkloadFailure as exc:
        if result.get("schema_version") == 2:
            raise WorkloadFailure(f"Legacy schema-2 result lacks complete fixed-protocol evidence: {exc}") from exc
        raise
    evaluation = result.get("evaluation")
    if result.get("schema_version") == 3 or "workload_hash" in result or evaluation is not None:
        if not isinstance(evaluation, dict):
            raise WorkloadFailure("Result lacks sealed workload evaluation metadata")
        if result.get("workload_hash") != contract["workload_hash"]:
            raise WorkloadFailure("Result workload_hash differs from the fixed protocol")
        if evaluation.get("workload_protocol") != contract["workload_protocol"]:
            raise WorkloadFailure("Result workload_protocol differs from the fixed protocol")
        for field in ("expected_cases", "completed_cases"):
            if type(evaluation.get(field)) is not int or evaluation[field] != contract["expected_cases"]:
                raise WorkloadFailure(f"Result {field} differs from the complete fixed protocol")
    return contract
