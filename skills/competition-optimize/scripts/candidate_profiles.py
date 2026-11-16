"""Retrieve executed development implementations with complementary case outcomes.

Profiles guide construction only. They neither replace the scalar objective nor
claim that independently best case outcomes form an executable solution.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Callable


class ProfileFailure(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def describe(profile: Any) -> dict[str, Any]:
    """Validate the opt-in result field and retain only a fixed-size identity."""
    if not isinstance(profile, dict):
        raise ProfileFailure("case_profile must be an object")
    metric, direction, cases = (profile.get(key) for key in ("metric", "direction", "cases"))
    if (not isinstance(metric, str) or not metric.strip()
            or direction not in ("maximize", "minimize")
            or not isinstance(cases, dict) or not cases):
        raise ProfileFailure("case_profile requires a metric, direction and nonempty cases mapping")
    for key, value in cases.items():
        try:
            valid = (isinstance(key, str) and bool(key.strip()) and not isinstance(value, bool)
                     and isinstance(value, (int, float)) and math.isfinite(value))
        except OverflowError:
            valid = False
        if not valid:
            raise ProfileFailure("case_profile case IDs must be nonempty strings and values finite numbers")
    return {"metric": metric, "direction": direction, "case_count": len(cases),
            "case_keys_sha256": _hash(sorted(cases)),
            "profile_sha256": _hash({"metric": metric, "direction": direction, "cases": cases})}


def validate_descriptor(value: Any) -> None:
    keys = {"metric", "direction", "case_count", "case_keys_sha256", "profile_sha256"}
    if (not isinstance(value, dict) or set(value) != keys
            or not isinstance(value["metric"], str) or not value["metric"].strip()
            or value["direction"] not in ("maximize", "minimize")
            or type(value["case_count"]) is not int or value["case_count"] < 1
            or any(not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key])
                   for key in ("case_keys_sha256", "profile_sha256"))):
        raise ProfileFailure("Malformed archived case_profile descriptor")


def retrieve(entries: list[dict[str, Any]], best: dict[str, Any] | None, *,
             identity: Callable[[dict[str, Any]], str],
             read_profile: Callable[[dict[str, Any]], dict[str, Any]],
             score: Callable[[dict[str, Any]], float]) -> dict[str, Any]:
    """Select at most two parents by actual wins, adding uncovered winning cases.

    Callers supply only ordinary, observed implementations from one complete
    comparison. Keep the first eligible profile per implementation. Read one
    vector at a time rather than accumulating a history-by-case matrix.
    """
    evidence: dict[str, Any] = {
        "best_candidate_id": best["candidate_id"] if best else None,
        "reference_candidate_id": None, "reference_profile": None,
        "selection": [], "available": 0, "omitted": 0,
        "selection_policy": "Uncovered winning cases, total wins, observed scalar score, then archive order",
        "scope": "First valid same-comparison profile per executed development implementation. "
                 "Profiles require matching metric, direction and case IDs. Actual wins guide construction; "
                 "they are not a combined score, promotion or evidence of a realizable gain. "
                 "Two retrieved parents do not limit experiments. Read the cited source/results and evaluate a successor."}
    if best is None:
        return evidence
    representatives, seen = [], set()
    for entry in entries:
        fingerprint = identity(entry)
        if fingerprint not in seen:
            seen.add(fingerprint)
            representatives.append(entry)
    best_identity = identity(best)
    reference = next((entry for entry in representatives if identity(entry) == best_identity), None)
    if reference is None:
        return evidence
    descriptor = reference["result"]["case_profile"]
    evidence.update(reference_candidate_id=reference["candidate_id"], reference_profile=descriptor)
    if descriptor["case_count"] < 2:
        return evidence
    ref = read_profile(reference)["cases"]
    case_ids = sorted(ref)
    candidates = [entry for entry in representatives if identity(entry) != best_identity and all(
        entry["result"]["case_profile"][key] == descriptor[key]
        for key in ("metric", "direction", "case_count", "case_keys_sha256"))]
    covered: set[str] = set()
    chosen: set[str] = set()
    sign = -1 if descriptor["direction"] == "minimize" else 1
    for round_number in range(2):
        choice, best_key, choice_wins = None, None, set()
        for entry in candidates:
            candidate_id = entry["candidate_id"]
            if candidate_id in chosen:
                continue
            cases = read_profile(entry)["cases"]
            if cases.keys() != ref.keys():
                raise ProfileFailure("Matching profile case-key hashes have different actual case IDs")
            wins, losses, winning_cases, losing_cases = set(), 0, [], []
            for case_id in case_ids:
                candidate, baseline = cases[case_id], ref[case_id]
                sample = {"case_id": case_id, "reference": baseline, "candidate": candidate}
                if sign * candidate > sign * baseline:
                    wins.add(case_id)
                    if len(winning_cases) < 3:
                        winning_cases.append(sample)
                elif sign * candidate < sign * baseline:
                    losses += 1
                    if len(losing_cases) < 3:
                        losing_cases.append(sample)
            if round_number == 0 and wins:
                evidence["available"] += 1
            additional = len(wins - covered)
            if not additional:
                continue
            key = (additional, len(wins), score(entry))
            if best_key is None or key > best_key:
                best_key, choice_wins = key, wins
                choice = {"candidate_id": candidate_id, "wins": len(wins), "losses": losses,
                          "ties": len(case_ids) - len(wins) - losses, "additional_wins": additional,
                          "winning_cases": winning_cases, "losing_cases": losing_cases}
        if choice is None:
            break
        evidence["selection"].append(choice)
        chosen.add(choice["candidate_id"])
        covered.update(choice_wins)
    evidence["omitted"] = evidence["available"] - len(evidence["selection"])
    return evidence
