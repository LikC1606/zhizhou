"""Freeze a paired repeatability experiment before its result files exist.

Plans live in the candidate JSONL archive. A plan names two archived source/recipe
identities, one complete comparison and a finite set of paired run slots. Later
results must carry the plan and run identities in their evaluation metadata.
This module tracks completion and explicit stops; the task's declared decision
rule remains human or adapter interpreted and never changes the archive's
first-observation ranking.
"""

from __future__ import annotations

from typing import Any

from candidate_evidence import (
    ArchiveFailure, ComparisonEvidence, candidate_index, canonical,
    implementation_identity, nonempty_text, observed_snapshot, sha256,
)
from evidence_files import EvidenceReads, verify_artifacts, verify_result


def _text(value: Any, name: str) -> str:
    result = nonempty_text(value, name)
    if len(result) > 128:
        raise ArchiveFailure("invalid_measurement_plan", f"{name} exceeds 128 characters")
    return result


def _runs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ArchiveFailure("invalid_measurement_plan", "runs must be a nonempty list")
    seen: set[str] = set()
    runs = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"run_id", "seeds", "repetitions"}:
            raise ArchiveFailure("invalid_measurement_plan", "Each run needs run_id, seeds and repetitions")
        run_id = _text(item["run_id"], "run_id")
        seeds = item["seeds"]
        if (run_id in seen or not isinstance(seeds, list)
                or any(type(seed) not in (int, str) or isinstance(seed, str) and not seed.strip()
                       for seed in seeds)
                or any(isinstance(seed, str) and len(seed) > 128 for seed in seeds)
                or len({(type(seed).__name__, seed) for seed in seeds}) != len(seeds)
                or type(item["repetitions"]) is not int or item["repetitions"] < 1):
            raise ArchiveFailure("invalid_measurement_plan", "Runs require unique IDs/seeds and positive repetitions")
        seen.add(run_id)
        runs.append({"run_id": run_id, "seeds": seeds, "repetitions": item["repetitions"]})
    return runs


def validate_plan(plan: dict[str, Any], records: list[dict[str, Any]]) -> None:
    plan_id = _text(plan.get("plan_id"), "plan_id")
    signature = _text(plan.get("conflict_signature"), "conflict_signature")
    comparison = plan.get("comparison")
    if not isinstance(comparison, dict):
        raise ArchiveFailure("invalid_measurement_plan", "comparison must be the complete frozen contract")
    if not isinstance(plan.get("decision_rule"), str) or not plan["decision_rule"].strip():
        raise ArchiveFailure("invalid_measurement_plan", "decision_rule must describe the task-specific paired decision")
    _runs(plan.get("runs"))
    if any(entry["event"] == "measurement_plan" and entry["plan_id"] == plan_id for entry in records):
        raise ArchiveFailure("duplicate_measurement_plan", "Measurement plan ID already exists")
    if any(entry["event"] == "measurement_plan" and entry["conflict_signature"] == signature
           for entry in records):
        raise ArchiveFailure("duplicate_measurement_plan", "This conflict already has a frozen measurement plan")
    candidates = candidate_index(records)
    leader_id = _text(plan.get("leader_candidate"), "leader_candidate")
    challenger_id = _text(plan.get("challenger_candidate"), "challenger_candidate")
    if leader_id not in candidates or challenger_id not in candidates:
        raise ArchiveFailure("invalid_measurement_plan", "Plan implementations must already be archived")
    view = ComparisonEvidence(
        records, eligible=lambda entry: observed_snapshot(
            entry, implementation_identity(entry))).for_candidate(leader_id)
    conflict = view.ranking_conflict()
    if (not conflict or conflict["signature"] != signature
            or conflict["leader_candidate"] != leader_id
            or conflict["challenger_candidate"] != challenger_id
            or conflict["witness_candidate"] != plan.get("witness_candidate")
            or view.comparison != comparison):
        raise ArchiveFailure("invalid_measurement_plan", "Plan does not match the current verified ordering conflict")


def validate_candidate(candidate: dict[str, Any], records: list[dict[str, Any]], *,
                       plans: dict[str, dict[str, Any]] | None = None,
                       candidates: dict[str, dict[str, Any]] | None = None,
                       filled_slots: set[tuple[str, str, str]] | None = None,
                       closed_plans: set[str] | None = None) -> tuple[str, str, str] | None:
    result = candidate["result"]
    if "measurement_plan_id" not in result:
        return None
    plan_id = result["measurement_plan_id"]
    plan = (plans.get(plan_id) if plans is not None and isinstance(plan_id, str) else
            next((entry for entry in records if entry["event"] == "measurement_plan"
                  and entry["plan_id"] == plan_id), None))
    if plan is None:
        raise ArchiveFailure("unplanned_measurement", "Measurement result must follow its archived plan")
    if (plan_id in closed_plans if closed_plans is not None else
            any(entry["event"] in {"measurement_decision", "measurement_stop"}
                and entry["plan_id"] == plan_id for entry in records)):
        raise ArchiveFailure("closed_measurement_plan", "The plan already has a recorded decision or stop")
    run = next((item for item in plan["runs"] if item["run_id"] == result.get("measurement_run_id")), None)
    candidates = candidates if candidates is not None else candidate_index(records)
    planned = {implementation_identity(candidates[plan[name]])["fingerprint"]
               for name in ("leader_candidate", "challenger_candidate")}
    identity = implementation_identity(candidate)["fingerprint"]
    if (run is None or candidate["role"] != "development" or candidate["comparison"] != plan["comparison"]
            or identity not in planned or not isinstance(result.get("seeds"), list)
            or canonical(result["seeds"]) != canonical(run["seeds"])
            or type(result.get("repetitions")) is not int
            or result["repetitions"] != run["repetitions"]):
        raise ArchiveFailure("unplanned_measurement", "Result differs from the frozen plan's run, recipe or comparison")
    if observed_snapshot(candidate, implementation_identity(candidate)):
        slot = (plan_id, run["run_id"], identity)
        if filled_slots is not None:
            duplicate = slot in filled_slots
        else:
            duplicate = any(
                entry["event"] == "candidate" and entry["result"].get("measurement_plan_id") == plan_id
                and entry["result"].get("measurement_run_id") == run["run_id"]
                and implementation_identity(entry)["fingerprint"] == identity
                and observed_snapshot(entry, implementation_identity(entry))
                for entry in records)
        if duplicate:
            raise ArchiveFailure("duplicate_measurement_slot", "A successful planned slot is already recorded")
        return slot
    return None


def _status(plan: dict[str, Any], measurements: list[dict[str, Any]],
            candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fingerprints = {name: implementation_identity(candidates[plan[name]])["fingerprint"]
                    for name in ("leader_candidate", "challenger_candidate")}
    observations: dict[tuple[str, str], dict[str, Any]] = {}
    attempts: dict[tuple[str, str], int] = {}
    evidence = []
    for entry in measurements:
        identity = implementation_identity(entry)["fingerprint"]
        name = next(name for name, fingerprint in fingerprints.items() if fingerprint == identity)
        key = (entry["result"]["measurement_run_id"], name)
        attempts[key] = attempts.get(key, 0) + 1
        observed = observed_snapshot(entry, implementation_identity(entry))
        evidence.append({"candidate_id": entry["candidate_id"], "run_id": key[0],
                         "implementation": "leader" if name == "leader_candidate" else "challenger",
                         "implementation_fingerprint": identity,
                         "result_sha256": entry["result"]["result_sha256"],
                         "execution_status": entry["result"]["execution_status"],
                         "valid": entry["valid"], "observed": observed,
                         "value": entry["objective"]["value"] if observed else None})
        if observed:
            observations[key] = {"candidate_id": entry["candidate_id"],
                                 "result_sha256": entry["result"]["result_sha256"],
                                 "value": entry["objective"]["value"]}
    runs = []
    for run in plan["runs"]:
        run_id = run["run_id"]
        runs.append({**run, "leader": observations.get((run_id, "leader_candidate")),
                     "challenger": observations.get((run_id, "challenger_candidate")),
                     "leader_attempts": attempts.get((run_id, "leader_candidate"), 0),
                     "challenger_attempts": attempts.get((run_id, "challenger_candidate"), 0)})
    complete = all(item["leader"] is not None and item["challenger"] is not None for item in runs)
    return {"plan_id": plan["plan_id"], "conflict_signature": plan["conflict_signature"],
            "comparison": plan["comparison"], "leader_candidate": plan["leader_candidate"],
            "challenger_candidate": plan["challenger_candidate"],
            "witness_candidate": plan["witness_candidate"], "decision_rule": plan["decision_rule"],
            "runs": runs, "attempts": evidence, "complete": complete,
            "scope": "Only successful, valid, scored paired results fulfill slots. Interpret the predeclared rule; do not auto-promote."}


def status(plan: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    view = _status(plan, [entry for entry in records if entry["event"] == "candidate"
                          and entry["result"].get("measurement_plan_id") == plan["plan_id"]],
                   candidate_index(records))
    view["decision"] = next((entry for entry in records if entry["event"] == "measurement_decision"
                             and entry["plan_id"] == plan["plan_id"]), None)
    view["stop"] = next((entry for entry in records if entry["event"] == "measurement_stop"
                         and entry["plan_id"] == plan["plan_id"]), None)
    view["state"] = ("decided" if view["decision"] else "stopped_unresolved" if view["stop"] else
                     "awaiting_decision" if view["complete"] else "measuring")
    return view


def evidence_sha256(view: dict[str, Any]) -> str:
    pairs = [{"run_id": item["run_id"], "leader": item["leader"], "challenger": item["challenger"]}
             for item in view["runs"]]
    return sha256(canonical({"plan_id": view["plan_id"],
                             "conflict_signature": view["conflict_signature"], "pairs": pairs}))


def validate_decision(decision: dict[str, Any], records: list[dict[str, Any]]) -> None:
    plan_id = _text(decision.get("plan_id"), "plan_id")
    for field in ("conclusion", "reason", "next_action"):
        nonempty_text(decision.get(field), field)
    plan = next((entry for entry in records if entry["event"] == "measurement_plan"
                 and entry["plan_id"] == plan_id), None)
    if plan is None:
        raise ArchiveFailure("unknown_measurement_plan", "Decision requires an earlier measurement plan")
    if any(entry["event"] == "measurement_decision" and entry["plan_id"] == plan_id for entry in records):
        raise ArchiveFailure("duplicate_measurement_decision", "The plan already has a decision")
    view = status(plan, records)
    if view["stop"] is not None:
        raise ArchiveFailure("closed_measurement_plan", "The measurement plan was stopped unresolved")
    if not view["complete"]:
        raise ArchiveFailure("incomplete_measurement_plan", "Every frozen paired run must be validly measured before a decision")
    if decision.get("evidence_sha256") != evidence_sha256(view):
        raise ArchiveFailure("measurement_evidence_changed", "Decision does not cite the completed paired results")


def stop_evidence_sha256(view: dict[str, Any]) -> str:
    """Bind the frozen protocol and all attempts, including failed or invalid runs."""
    fields = ("plan_id", "conflict_signature", "comparison", "leader_candidate", "challenger_candidate",
              "witness_candidate", "decision_rule", "runs", "attempts")
    return sha256(canonical({key: view[key] for key in fields}))


def validate_stop(stop: dict[str, Any], records: list[dict[str, Any]]) -> None:
    plan_id = _text(stop.get("plan_id"), "plan_id")
    for field in ("reason", "next_action"):
        nonempty_text(stop.get(field), field)
    plan = next((entry for entry in records if entry["event"] == "measurement_plan"
                 and entry["plan_id"] == plan_id), None)
    if plan is None:
        raise ArchiveFailure("unknown_measurement_plan", "Stop requires an earlier measurement plan")
    view = status(plan, records)
    if view["decision"] is not None or view["stop"] is not None:
        raise ArchiveFailure("closed_measurement_plan", "The plan already has a recorded decision or stop")
    if stop.get("evidence_sha256") != stop_evidence_sha256(view):
        raise ArchiveFailure("measurement_evidence_changed", "Stop does not cite the frozen protocol and all attempts")


def verify_stop_evidence(view: dict[str, Any], records: list[dict[str, Any]], *,
                         reads: EvidenceReads | None = None) -> None:
    candidates = candidate_index(records)
    candidate_ids = {view[name] for name in ("leader_candidate", "challenger_candidate", "witness_candidate")}
    candidate_ids.update(item["candidate_id"] for item in view["attempts"])
    for candidate_id in sorted(candidate_ids):
        verify_result(candidates[candidate_id], reads=reads)
        verify_artifacts(candidates[candidate_id], reads=reads)


def first_pending(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the oldest open plan, even after the active contract changes."""
    candidates: dict[str, dict[str, Any]] = {}
    measurements: dict[str, list[dict[str, Any]]] = {}
    plans = []
    for entry in records:
        if entry["event"] == "measurement_plan":
            plans.append(entry)
        elif entry["event"] == "candidate":
            candidates[entry["candidate_id"]] = entry
            plan_id = entry["result"].get("measurement_plan_id")
            if isinstance(plan_id, str):
                measurements.setdefault(plan_id, []).append(entry)
    closed = {entry["plan_id"] for entry in records
              if entry["event"] in {"measurement_decision", "measurement_stop"}}
    for plan in plans:
        if plan["plan_id"] in closed:
            continue
        view = _status(plan, measurements.get(plan["plan_id"], []), candidates)
        view["decision"] = None
        view["stop"] = None
        view["state"] = "awaiting_decision" if view["complete"] else "measuring"
        return view
    return None


def latest_stop(records: list[dict[str, Any]],
                active_comparison: dict[str, Any] | None, *,
                reads: EvidenceReads | None = None) -> dict[str, Any] | None:
    """Carry an unresolved stop without treating partial pairs as a conclusion."""
    plans = {entry["plan_id"]: entry for entry in records if entry["event"] == "measurement_plan"}
    stops = [entry for entry in records if entry["event"] == "measurement_stop"]
    stop = next((entry for entry in reversed(stops)
                 if plans[entry["plan_id"]]["comparison"] == active_comparison),
                stops[-1] if stops else None)
    if stop is None:
        return None
    plan = plans[stop["plan_id"]]
    view = status(plan, records)
    if stop_evidence_sha256(view) != stop["evidence_sha256"]:
        raise ArchiveFailure("measurement_evidence_changed", "Stopped plan no longer matches its attempts")
    verify_stop_evidence(view, records, reads=reads)
    return {"plan_id": plan["plan_id"], "state": "stopped_unresolved",
            "comparison_key": sha256(canonical(plan["comparison"])),
            "comparison_matches_active": plan["comparison"] == active_comparison,
            "leader_candidate": plan["leader_candidate"], "challenger_candidate": plan["challenger_candidate"],
            "remaining_slots": sum(item[name] is None for item in view["runs"] for name in ("leader", "challenger")),
            "attempts": len(view["attempts"]),
            "failed_attempts": sum(not item["observed"] for item in view["attempts"]),
            "reason": stop["reason"], "next_action": stop["next_action"],
            "evidence_sha256": stop["evidence_sha256"],
            "scope": "Explicit unresolved stop, not a paired conclusion or campaign completion. "
                     "Do not reopen this conflict; inspect the protocol and all attempts with measure-status. "
                     "Execution failures still require repair; apply the next action only within its comparison."}


def latest_decision(records: list[dict[str, Any]],
                    active_comparison: dict[str, Any] | None, *,
                    reads: EvidenceReads | None = None) -> dict[str, Any] | None:
    """Prefer the active comparison's last conclusion and verify its evidence."""
    plans = {entry["plan_id"]: entry for entry in records if entry["event"] == "measurement_plan"}
    decisions = [entry for entry in records if entry["event"] == "measurement_decision"]
    decision = next((entry for entry in reversed(decisions)
                     if plans[entry["plan_id"]]["comparison"] == active_comparison),
                    decisions[-1] if decisions else None)
    if decision is None:
        return None
    plan = plans[decision["plan_id"]]
    view = status(plan, records)
    if not view["complete"] or evidence_sha256(view) != decision["evidence_sha256"]:
        raise ArchiveFailure("measurement_evidence_changed", "Archived paired decision no longer matches its results")
    candidates = candidate_index(records)
    for run in view["runs"]:
        for name in ("leader", "challenger"):
            entry = candidates[run[name]["candidate_id"]]
            # The decision hash binds archived metadata. Recheck the immutable
            # source/result bytes before carrying the conclusion across turns.
            verify_result(entry, reads=reads)
            verify_artifacts(entry, reads=reads)
    return {"plan_id": plan["plan_id"], "comparison_key": sha256(canonical(plan["comparison"])),
            "comparison_matches_active": plan["comparison"] == active_comparison,
            "leader_candidate": plan["leader_candidate"], "challenger_candidate": plan["challenger_candidate"],
            "paired_runs": len(view["runs"]), "decision_rule": plan["decision_rule"],
            "conclusion": decision["conclusion"], "reason": decision["reason"],
            "next_action": decision["next_action"], "evidence_sha256": decision["evidence_sha256"],
            "scope": "Agent interpretation of prespecified paired results, not automatic promotion. "
                     "If the comparison differs, revalidate before applying it; retrieve exact runs with measure-status."}
