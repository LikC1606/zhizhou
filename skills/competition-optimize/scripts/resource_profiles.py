"""Retrieve measured quality/resource tradeoffs without changing scalar ranking."""

from __future__ import annotations

import math
import re
from typing import Any, Callable


class ResourceFailure(ValueError):
    pass


def describe(value: Any) -> dict[str, Any]:
    """Accept an explicit adapter measurement, never inferred evaluation cost."""
    keys = {"metric", "unit", "scope", "protocol_sha256", "value"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ResourceFailure("resource_profile requires metric, unit, scope, protocol_sha256 and value")
    if any(not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 128
           for key in ("metric", "unit", "scope")):
        raise ResourceFailure("resource_profile metric, unit and scope must be nonempty strings of at most 128 characters")
    if not isinstance(value["protocol_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["protocol_sha256"]):
        raise ResourceFailure("resource_profile protocol_sha256 must be a SHA-256 hash")
    number = value["value"]
    try:
        valid = not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number) and number >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ResourceFailure("resource_profile value must be finite, nonnegative consumed resource (lower is better)")
    return dict(value)


def _protocol(profile: dict[str, Any]) -> tuple[str, ...]:
    return tuple(profile[key] for key in ("metric", "unit", "scope", "protocol_sha256"))


def retrieve(entries: list[dict[str, Any]], best: dict[str, Any] | None,
             anchor: dict[str, Any], *, identity: Callable[[dict[str, Any]], str],
             score: Callable[[dict[str, Any]], float]) -> dict[str, Any]:
    """Return fastest and highest-quality endpoints of one measured subset.

    Callers supply actual successful ordinary development snapshots under one
    complete comparison. Each point uses the score and resource from the same
    first profiled observation of an implementation under that protocol.
    """
    result: dict[str, Any] = {
        "best_candidate_id": best["candidate_id"] if best else None,
        "reference_candidate_id": None, "reference_reason": None, "protocol": None,
        "profiled_implementations": 0, "protocol_groups": 0,
        "available": 0, "omitted": 0, "selection": [],
        "scope": "Measured profile-subset tradeoffs, not global Pareto optimality or promotion. "
                 "The best implementation's first profile selects the resource protocol, otherwise the anchor's. "
                 "Each point uses one actual score/resource observation; first valid profile per implementation "
                 "and protocol avoids selecting a lucky repeat. Resource is lower-is-better under the exact "
                 "metric, unit, scope and protocol hash; no unit conversion or inference from elapsed_seconds/cost. "
                 "Compare the fastest and highest-quality endpoints by the actual objective and constraints, "
                 "inspect their code and measurement protocol, then execute a successor. "
                 "Missing profiles, noise and interior tradeoffs remain unresolved; two hints do not limit experiments."}
    representatives: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for entry in entries:
        profile = entry["result"]["resource_profile"]
        representatives.setdefault((identity(entry), _protocol(profile)), entry)
    result["protocol_groups"] = len({key[1] for key in representatives})
    reference = None
    for subject, reason in ((best, "best_implementation_first_profile"), (anchor, "anchor_implementation_first_profile")):
        if subject is None:
            continue
        reference = next((entry for (fingerprint, _), entry in representatives.items()
                          if fingerprint == identity(subject)), None)
        if reference is not None:
            result["reference_reason"] = reason
            break
    if reference is None:
        return result
    protocol = _protocol(reference["result"]["resource_profile"])
    result["reference_candidate_id"] = reference["candidate_id"]
    result["protocol"] = {key: reference["result"]["resource_profile"][key]
                          for key in ("metric", "unit", "scope", "protocol_sha256")}
    candidates = [entry for (_, group), entry in representatives.items() if group == protocol]
    result["profiled_implementations"] = len(candidates)
    # Stable sort handles equal points by archive order; scan avoids O(n^2).
    candidates.sort(key=lambda entry: (entry["result"]["resource_profile"]["value"], -score(entry)))
    frontier, highest = [], None
    for entry in candidates:
        quality = score(entry)
        if highest is None or quality > highest:
            frontier.append(entry)
            highest = quality
    result["available"] = len(frontier)
    endpoints = frontier[:1] + (frontier[-1:] if len(frontier) > 1 else [])
    for entry in endpoints:
        result["selection"].append({
            "candidate_id": entry["candidate_id"], "implementation_fingerprint": identity(entry),
            "objective": entry["objective"], "resource_profile": entry["result"]["resource_profile"],
            "endpoint": "fastest_and_highest_quality" if len(frontier) == 1 else
                        "fastest" if entry is frontier[0] else "highest_quality"})
    result["omitted"] = len(frontier) - len(endpoints)
    return result
