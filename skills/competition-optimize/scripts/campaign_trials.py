"""Retrieve prospective predictions beside their completed development outcomes.

This view adds recall independently of score leaders and pending work. It does
not turn an agent's explanation into a causal rule or forbid a justified retry.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import scoped_learning
from candidate_evidence import (
    ArchiveFailure, DEVELOPMENT_ROLES, canonical, directed_score, executed_snapshot, implementation_identity,
    observed_snapshot, proposal_identity_checks, sha256, validate_construction_targets,
)
from evidence_files import EvidenceReads, verify_artifacts, verify_result, verify_proposal_targets


_IDENTITY_FIELDS = ("role", "implementation", "artifact_paths", "result", "comparison_sha256",
                    "requires_revalidation", "identity_checks")
_PROPOSAL_FIELDS = ("proposal_id", "input_sha256", "parent_ids", "feedback_from",
                    "code_targets", "candidate_id", "outcome_role", "identity_checks")


def _retrieval_identity(archive_path: str, comparison_key: str | None,
                        trial: dict[str, Any]) -> dict[str, Any]:
    return {"archive_path": archive_path, "comparison_key": comparison_key,
            **{key: trial[key] for key in _PROPOSAL_FIELDS},
            **({"construction_mode": trial["construction_mode"]} if "construction_mode" in trial else {}),
            **({"learning_from": trial["learning_from"]} if "learning_from" in trial else {}),
            "evidence": {candidate_id: {**{key: card[key] for key in _IDENTITY_FIELDS},
                                        **({"implementation_review": card["implementation_review"]}
                                           if "implementation_review" in card else {}),
                                        **({"learning": card["learning"]} if "learning" in card else {})}
                         for candidate_id, card in trial["evidence"].items()}}


def trial_history(archive_path: pathlib.Path, records: list[dict[str, Any]],
                  comparison: dict[str, Any] | None, related_implementations: set[str],
                  seen: dict[str, int] | None = None, limit: int = 2, *,
                  reads: EvidenceReads | None = None) -> dict[str, Any]:
    """Select one recent related trial and rotate the remaining historical slot.

    Trials belong to their first parent's complete development comparison.
    Index metadata once; check bytes only for the selected prospective chains.
    Exposure is caller-owned and advances only after a successful handoff.
    """
    reads = EvidenceReads() if reads is None else reads
    if type(limit) is not int or limit < 0:
        raise ArchiveFailure("invalid_config", "Trial retrieval limit must be a nonnegative integer")
    if seen is None:
        seen = {}
    if (not isinstance(seen, dict) or any(not isinstance(key, str) or not key.strip()
                                        or type(turn) is not int or turn < 0 for key, turn in seen.items())):
        raise ArchiveFailure("invalid_config", "Trial exposures must map proposal IDs to nonnegative turns")
    limit = min(limit, 2)
    archive_name = reads.archive_name(archive_path)
    comparison_key = sha256(canonical(comparison)) if comparison is not None else None
    candidates: dict[str, dict[str, Any]] = {}
    identities: dict[str, dict[str, Any]] = {}
    observed: dict[str, bool] = {}
    proposals: dict[str, dict[str, Any]] = {}
    eligible: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for position, entry in enumerate(records):
        if entry["event"] == "proposal":
            proposals[entry["proposal_id"]] = entry
        elif entry["event"] == "candidate" and entry["role"] in DEVELOPMENT_ROLES:
            candidate_id = entry["candidate_id"]
            candidates[candidate_id] = entry
            identity = implementation_identity(entry)
            identities[candidate_id] = identity
            observed[candidate_id] = observed_snapshot(entry, identity, include_diagnostics=True)
            proposal = proposals.get(entry.get("proposal_id"))
            if proposal is None or not executed_snapshot(entry, identity):
                continue
            references = proposal["parent_ids"] + proposal["feedback_from"] + proposal.get("learning_from", [])
            if (any(candidate_id not in candidates for candidate_id in references)
                    or candidates[proposal["parent_ids"][0]]["comparison"] != comparison):
                continue
            eligible.append((position, proposal, entry))

    selected: list[tuple[tuple[int, dict[str, Any], dict[str, Any]], str]] = []
    if limit and related_implementations:
        related = [item for item in eligible
                   if any(identities[candidate_id]["fingerprint"] in related_implementations
                          for candidate_id in item[1]["parent_ids"] + [item[2]["candidate_id"]])]
        if related:
            selected.append((related[-1], "recent_related"))
    selected_ids = {item[1]["proposal_id"] for item, _ in selected}
    rotating = sorted((item for item in eligible if item[1]["proposal_id"] not in selected_ids),
                      key=lambda item: (item[1]["proposal_id"] in seen,
                                        seen.get(item[1]["proposal_id"], 0), item[0]))
    selected.extend((item, "least_recently_exposed") for item in rotating[:limit - len(selected)])

    verified: set[str] = set()
    checked_targets: set[tuple[str, str]] = set()
    cards: dict[str, dict[str, Any]] = {}

    def evidence(candidate_id: str) -> dict[str, Any]:
        if candidate_id not in verified:
            entry = candidates[candidate_id]
            verify_result(entry, reads=reads)
            verify_artifacts(entry, reads=reads)
            verified.add(candidate_id)
            result = entry["result"]
            matches = entry["comparison"] == comparison
            card = {"role": entry["role"], "implementation": identities[candidate_id],
                    "artifact_paths": entry["artifact_paths"],
                    "result": {key: result.get(key) for key in ("result_path", "result_sha256", "execution_status")},
                    "comparison_sha256": sha256(canonical(entry["comparison"])),
                    "requires_revalidation": not (matches and observed[candidate_id]),
                    "identity_checks": {"result_bytes": "checked" if result.get("result_path") else "not_recorded",
                                        "snapshot_bytes": "checked" if entry["artifact_paths"] else "not_recorded"}}
            if matches and observed[candidate_id]:
                card["objective"] = entry["objective"]
            if matches and "implementation_review" in entry:
                card["implementation_review"] = entry["implementation_review"]
            if matches and "learning" in entry:
                scoped_learning.verify_evidence(entry["learning"], candidates, reads=reads)
                card["learning"] = entry["learning"]
            cards[candidate_id] = card
        return cards[candidate_id]

    selection = []
    for (_, proposal, outcome), reason in selected:
        verify_proposal_targets(proposal, checked_targets, reads=reads)
        outcome_id = outcome["candidate_id"]
        matches = outcome["comparison"] == comparison
        gains = {}
        for parent_id in proposal["parent_ids"]:
            parent = candidates[parent_id]
            gains[parent_id] = (directed_score(outcome) - directed_score(parent)
                                if outcome["role"] == parent["role"] == "development"
                                and matches and observed[outcome_id] and observed[parent_id]
                                and parent["comparison"] == outcome["comparison"] else None)
        evidence_ids = dict.fromkeys(proposal["parent_ids"] + proposal["feedback_from"]
                                     + proposal.get("learning_from", []) + [outcome_id])
        trial = {key: proposal[key] for key in ("proposal_id", "parent_ids", "feedback_from", "code_targets",
                                               "basis", "change", "expected_observation", "validation", "stop_condition")}
        if "construction_mode" in proposal:
            trial["construction_mode"] = proposal["construction_mode"]
        if "learning_from" in proposal:
            trial["learning_from"] = proposal["learning_from"]
        trial.update(input_sha256=proposal.get("input_sha256"), candidate_id=outcome_id, outcome_role=outcome["role"],
                     state="measured" if observed[outcome_id] else "failed_or_unscored",
                     outcome_comparison_matches=matches,
                     prediction_status=outcome.get("prediction_status") if matches else None,
                     last_exposed_turn=seen.get(proposal["proposal_id"]), retrieval_reason=reason,
                     evidence={candidate_id: evidence(candidate_id) for candidate_id in evidence_ids},
                     feedback=outcome.get("feedback") if matches else None,
                     failure_mechanism=outcome.get("failure_mechanism") if matches else None,
                     objective_gain_vs_parents=gains, identity_checks=proposal_identity_checks(proposal),
                     scope="Original prospective prediction and actual outcome. Diagnostic outcomes inform design "
                           "without ranking or candidate gains. Measured means a scored "
                           "observation under the outcome's own contract; outcome_comparison_matches states whether "
                           "it matches the current contract. Prediction status and "
                           "feedback are agent reports, not causal findings. Missing or failed measurements do not "
                           "disprove an algorithm. Foreign-contract cards supply identities only and require "
                           "revalidation; compare scores only within the complete current contract. Retrieve full "
                           "fields with candidate_archive.py trace --proposal-id using this proposal ID. A similar "
                           "mechanism may be retried when relevant implementation, assumptions or evidence changed.")
        trial["retrieval_sha256"] = sha256(canonical(
            _retrieval_identity(archive_name, comparison_key, trial)))
        selection.append(trial)
    return {"comparison_key": comparison_key, "available": len(eligible),
            "omitted": len(eligible) - len(selection),
            "selection_policy": "recent_related_then_least_recently_exposed", "selection": selection,
            "scope": "Completed prospective development and diagnostic trials, independent of score leaders, open opportunities "
                     "and pending work. First-parent comparison defines ownership; confirmation never contributes. "
                     "At most one recent related trial precedes historical rotation. Exposure means evidence was "
                     "delivered, not that its explanation is correct, the method exhausted or the task complete."}


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _complete_card(card: dict[str, Any]) -> bool:
    identity, paths, result = card.get("implementation"), card.get("artifact_paths"), card.get("result")
    if (card.get("role") not in DEVELOPMENT_ROLES or not isinstance(identity, dict)
            or not isinstance(paths, dict) or not isinstance(result, dict)):
        return False
    artifacts = identity.get("artifacts")
    if (not _sha256(identity.get("fingerprint")) or not isinstance(artifacts, dict) or not artifacts
            or not set(artifacts) <= paths.keys() or not all(_sha256(value) for value in artifacts.values())
            or not all(isinstance(value, str) and pathlib.Path(value).is_absolute() for value in paths.values())
            or not _sha256(card.get("comparison_sha256"))):
        return False
    result_path, result_hash = result.get("result_path"), result.get("result_sha256")
    if result_path:
        if not isinstance(result_path, str) or not pathlib.Path(result_path).is_absolute() or not _sha256(result_hash):
            return False
    elif result_hash is not None:
        return False
    return card.get("identity_checks") == {
        "result_bytes": "checked" if result_path else "not_recorded",
        "snapshot_bytes": "checked" if paths else "not_recorded"}


def delivered_trials(packet: dict[str, Any]) -> list[str]:
    """Count only intact retrieval identities; prose can be shortened for context.

    Compare a pre-bounding seal, since the bounded omission index can aggregate
    paths and therefore cannot prove a required identifier survived truncation.
    """
    history = packet.get("trial_history")
    archive_name = packet.get("archive_path")
    if (not isinstance(history, dict) or not isinstance(history.get("selection"), list)
            or not isinstance(archive_name, str) or not pathlib.Path(archive_name).is_absolute()
            or not _sha256(history.get("comparison_key"))):
        return []
    delivered = []
    for trial in history["selection"]:
        try:
            validate_construction_targets(trial)
            if (not isinstance(trial, dict) or not isinstance(trial.get("proposal_id"), str)
                    or not trial["proposal_id"].strip() or not isinstance(trial.get("candidate_id"), str)
                    or not trial["candidate_id"] or trial.get("identity_checks") != proposal_identity_checks(trial)
                    or trial.get("outcome_role") not in DEVELOPMENT_ROLES
                    or trial["input_sha256"] is not None and not _sha256(trial["input_sha256"])):
                continue
            parents, feedback = trial["parent_ids"], trial["feedback_from"]
            targets, evidence = trial["code_targets"], trial["evidence"]
            if (not isinstance(parents, list) or not parents or not isinstance(feedback, list) or not feedback
                    or any(not isinstance(value, str) or not value for value in parents + feedback)
                    or not isinstance(targets, list)
                    or not all(isinstance(target, dict) and isinstance(target.get("path"), str)
                               and pathlib.Path(target["path"]).is_absolute() and _sha256(target.get("sha256"))
                               for target in targets)
                    or not isinstance(evidence, dict)
                    or set(evidence) != set(parents + feedback + trial.get("learning_from", []) + [trial["candidate_id"]])
                    or not all(isinstance(card, dict) and _complete_card(card) for card in evidence.values())):
                continue
            digest = sha256(canonical(
                _retrieval_identity(archive_name, history["comparison_key"], trial)))
            if _sha256(trial.get("retrieval_sha256")) and trial["retrieval_sha256"] == digest:
                if trial["proposal_id"] not in delivered:
                    delivered.append(trial["proposal_id"])
        except (KeyError, TypeError, ValueError, ArchiveFailure):
            # A bounded card may have omitted complete mappings or identifiers.
            continue
    return delivered
