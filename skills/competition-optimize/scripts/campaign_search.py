#!/usr/bin/env python3
"""Evidence retrieval and search signals for the unattended campaign driver.

Signals request strategy, execution or measurement review; they never promote
a candidate, prove a plateau or stop a campaign. Scores stay contract-scoped.
"""

from __future__ import annotations

import argparse
import pathlib
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, Mapping

import candidate_archive as archive_tools
from campaign_trials import delivered_trials, trial_history
from campaign_handoff import bound_packet

if TYPE_CHECKING:
    from campaign_policy import TurnPlan


HANDOFF_BYTES = 48 * 1024
DEFAULT_STAGNATION_WINDOW = 4
DEFAULT_SESSION_CHECKPOINTS = 8
DEFAULT_FAILURE_REVIEW_WINDOW = 3
DEFAULT_COMPARISON_REVIEW_WINDOW = 4


class CampaignEvidence:
    """One borrowed, accepted archive prefix and its request-local projections.

    Callers must not mutate records while this view is used. Policy signals do
    no file I/O; handoff verification reuses EvidenceReads only in this view.
    Create a new view after accepting another prefix or preparing another turn.
    """

    def __init__(self, records: list[dict[str, Any]], *,
                 comparisons: archive_tools.ComparisonEvidence | None = None) -> None:
        self.records = records
        self._provided_comparisons = comparisons
        self._continuities: dict[int, dict[str, Any]] = {}

    @cached_property
    def _comparisons(self) -> archive_tools.ComparisonEvidence:
        return (self._provided_comparisons if self._provided_comparisons is not None else
                archive_tools.ComparisonEvidence(self.records, eligible=observed_implementation))

    @cached_property
    def _index(self) -> dict[str, dict[str, Any]]:
        return archive_tools.candidate_index(self.records)

    @cached_property
    def _reads(self) -> archive_tools.EvidenceReads:
        return archive_tools.EvidenceReads()

    @cached_property
    def _progress(self) -> dict[str, Any]:
        return objective_progress(self.records, evidence=self._comparisons)

    @cached_property
    def _health(self) -> dict[str, Any]:
        return execution_health(self.records)

    @cached_property
    def _measurement_plan(self) -> dict[str, Any] | None:
        return archive_tools.measurement_plans.first_pending(self.records)

    @cached_property
    def _repeat_conflict(self) -> dict[str, Any] | None:
        anchor = self._progress["anchor_candidate"]
        return self._comparisons.for_candidate(anchor).ranking_conflict() if anchor else None

    @cached_property
    def _measurement_comparisons(self) -> dict[str, dict[str, Any]]:
        return {entry["plan_id"]: entry["comparison"] for entry in self.records if entry["event"] == "measurement_plan"}

    @cached_property
    def _measurement_signatures(self) -> set[str]:
        return {entry["conflict_signature"] for entry in self.records if entry["event"] == "measurement_plan"}

    @cached_property
    def counts(self) -> dict[str, int]:
        candidates = [entry for entry in self.records if entry["event"] == "candidate"]
        identities = [executed_implementation(entry) for entry in candidates]
        proposals = {entry["proposal_id"] for entry in self.records if entry["event"] == "proposal"}
        closed = {entry["proposal_id"] for entry in self.records
                  if entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id")}
        return {
            "events": len(self.records), "candidates": len(candidates),
            "executed_implementations": len({identity for identity in identities if identity}),
            "evaluated_candidates": sum(bool(entry["result"].get("result_path") and
                                             entry["result"].get("execution_status")) for entry in candidates),
            "diagnostic_evaluations": sum(bool(entry["role"] == "diagnostic" and
                                                entry["result"].get("result_path") and
                                                entry["result"].get("execution_status")) for entry in candidates),
            "measurable_candidates": sum(archive_tools.measurable(entry) for entry in candidates),
            "proposals": len(proposals), "pending_proposals": len(proposals - closed),
        }

    def signals(self, checkpoint: Mapping[str, Any] | None = None) -> dict[str, Any]:
        position = checkpoint["distinct_observations"] if checkpoint else 0
        if position not in self._continuities:
            self._continuities[position] = comparison_continuity(self.records, checkpoint, evidence=self._comparisons)
        return {
            "objective_progress": self._progress, "execution_health": self._health,
            "comparison_continuity": self._continuities[position],
            "measurement_plan": self._measurement_plan, "repeat_conflict": self._repeat_conflict,
            "measurement_comparisons": self._measurement_comparisons,
            "measurement_signatures": self._measurement_signatures,
        }


def executed_implementation(entry: dict[str, Any]) -> str | None:
    if entry["event"] != "candidate" or entry["role"] not in archive_tools.DEVELOPMENT_ROLES:
        return None
    result = entry["result"]
    if not result.get("result_path") or not result.get("execution_status"):
        return None
    identity = archive_tools.implementation_identity(entry)
    if identity["scope"] in archive_tools.OUTPUT_ONLY_SCOPES:
        return None
    if not set(identity["artifacts"]) <= entry["artifact_paths"].keys():
        return None
    return identity["fingerprint"]


def observed_implementation(entry: dict[str, Any]) -> bool:
    # Explicit archive flags may describe a known score, but they cannot invent
    # a measured gain when the adapter result contains no objective.
    if entry["event"] != "candidate" or entry["role"] != "development":
        return False
    result, objective = entry["result"], entry["objective"]
    return bool(archive_tools.measurable(entry) and executed_implementation(entry) and all(
        result.get(result_key) == objective.get(objective_key)
        for result_key, objective_key in (("objective_value", "value"), ("objective_direction", "direction"),
                                          ("objective_kind", "kind"), ("objective_name", "name"))))


def objective_progress(records: list[dict[str, Any]], *,
                       evidence: archive_tools.ComparisonEvidence | None = None) -> dict[str, Any]:
    anchor = next((entry for entry in reversed(records)
                   if entry["event"] == "candidate" and entry["role"] == "development"), None)
    if anchor is None:
        return {"comparison_key": None, "comparison": None, "anchor_candidate": None,
                "best_candidate": None, "best_value": None, "comparable_implementations": 0,
                "implementations_since_best": 0, "latest_eligible": False,
                "nonimproving_candidates": [], "improvement_candidates": []}
    context = anchor["comparison"]
    evidence = evidence or archive_tools.ComparisonEvidence(records, eligible=observed_implementation)
    measured = evidence.for_candidate(anchor["candidate_id"]).representatives
    best = None
    best_position = 0
    improvements = []
    for position, entry in enumerate(measured):
        if best is None or archive_tools.directed_score(entry) > archive_tools.directed_score(best):
            if best is not None:
                improvements.append(entry["candidate_id"])
            best, best_position = entry, position
    return {"comparison_key": archive_tools.sha256(archive_tools.canonical(context)),
            "comparison": context, "anchor_candidate": anchor["candidate_id"],
            "best_candidate": best["candidate_id"] if best else None,
            "best_value": best["objective"]["value"] if best else None,
            "comparable_implementations": len(measured),
            "implementations_since_best": len(measured) - best_position - 1 if best else 0,
            "latest_eligible": observed_implementation(anchor),
            "nonimproving_candidates": [entry["candidate_id"] for entry in measured[best_position + 1:]][-8:],
            "improvement_candidates": improvements[-8:]}


def review_due(progress: dict[str, Any], previous: dict[str, Any] | None, window: int) -> bool:
    """Count new implementations since both the best and the last review.

    Route labels and promising/unresolved declarations cannot reset objective
    history. A review is a context boundary, never an experiment allowance.
    """
    if (not progress["latest_eligible"] or not progress["best_candidate"] or
            progress["implementations_since_best"] < window):
        return False
    if previous and (previous["comparison_key"], previous["best_candidate"]) == (
            progress["comparison_key"], progress["best_candidate"]):
        return progress["comparable_implementations"] - previous["comparable_implementations"] >= window
    return True


def comparison_continuity(records: list[dict[str, Any]],
                          previous: dict[str, Any] | None = None, *,
                          evidence: archive_tools.ComparisonEvidence | None = None) -> dict[str, Any]:
    """Find development contracts still lacking a second measured implementation.

    Count first valid (complete comparison, implementation) observations, not
    scores or result files. A stable smoke contract cannot erase an isolated
    full evaluation; remeasuring another implementation under that full
    contract can. The checkpoint marks evidence handed off, not work resolved.
    """
    seen = set()
    paired = set()
    unpaired = {}
    checkpoint = previous["distinct_observations"] if previous else 0
    evidence = evidence or archive_tools.ComparisonEvidence(records, eligible=observed_implementation)
    for comparison_bytes, identity, entry in evidence.first_observations():
        comparison = archive_tools.sha256(comparison_bytes)
        pair = (comparison, identity)
        seen.add(pair)
        if comparison in unpaired:
            del unpaired[comparison]
            paired.add(comparison)
        elif comparison not in paired:
            unpaired[comparison] = (len(seen), entry["candidate_id"])
    pending = list(unpaired.values())  # First observation order; never score order.
    return {"distinct_observations": len(seen), "paired_contracts": len(paired),
            "unpaired_contracts": len(pending),
            "new_unpaired_contracts": sum(position > checkpoint for position, _ in pending),
            "reviewed_observations": checkpoint,
            "latest_unpaired_candidate": pending[-1][1] if pending else None,
            "recent_unpaired_candidates": [candidate_id for _, candidate_id in pending[-8:]],
            "scope": "First valid scored development observations by complete contract and implementation. "
                     "Unpaired contracts lack another measured implementation; this can be legitimate exploration. "
                     "New means first observed after the last successful measurement-review handoff. "
                     "No cross-contract score comparison, promotion or stopping judgement."}


def comparison_review_due(continuity: dict[str, Any], window: int) -> bool:
    return continuity["new_unpaired_contracts"] >= window


def comparison_recovery(records: list[dict[str, Any]], continuity: dict[str, Any], *,
                        reads: archive_tools.EvidenceReads | None = None) -> dict[str, Any] | None:
    reads = archive_tools.EvidenceReads() if reads is None else reads
    if not continuity["latest_unpaired_candidate"]:
        return None
    index = archive_tools.candidate_index(records)
    target = index[continuity["latest_unpaired_candidate"]]
    identity = executed_implementation(target)
    parents = list(target["parent_ids"])
    visited = set()
    reference = None
    position = 0
    while position < len(parents):
        candidate_id = parents[position]
        position += 1
        if candidate_id in visited:
            continue
        visited.add(candidate_id)
        entry = index[candidate_id]
        if entry["role"] not in archive_tools.DEVELOPMENT_ROLES:
            continue
        if observed_implementation(entry) and executed_implementation(entry) != identity:
            reference = entry
            break
        parents.extend(entry["parent_ids"])
    relationship = "different_implementation_ancestor" if reference else "earlier_development_observation"
    if reference is None:
        for entry in records:
            if entry["event"] != "candidate":
                continue
            if entry["candidate_id"] == target["candidate_id"]:
                break
            if observed_implementation(entry) and executed_implementation(entry) != identity:
                reference = entry

    def card(entry: dict[str, Any], *, compact: bool = False) -> dict[str, Any]:
        archive_tools.verify_result(entry, reads=reads)
        archive_tools.verify_artifacts(entry, reads=reads)
        implementation = archive_tools.implementation_identity(entry)
        result = {"candidate_id": entry["candidate_id"],
                  "implementation_fingerprint": implementation["fingerprint"],
                  "comparison_sha256": archive_tools.sha256(archive_tools.canonical(entry["comparison"])),
                  "result_path": entry["result"]["result_path"],
                  "result_sha256": entry["result"]["result_sha256"],
                  "identity_checks": {"result_bytes": "checked", "snapshot_bytes": "checked"}}
        if not compact:
            result.update(implementation=implementation, artifact_paths=entry["artifact_paths"],
                          comparison=entry["comparison"], requires_revalidation=True)
        return result

    examples = continuity["recent_unpaired_candidates"][-4:]
    return {"target": card(target), "reference": card(reference) if reference else None,
            "reference_relationship": relationship if reference else None,
            "changed_fields": sorted(key for key in target["comparison"]
                                     if reference and target["comparison"][key] != reference["comparison"].get(key)),
            "unpaired_examples": [card(index[candidate_id], compact=True) for candidate_id in examples],
            "examples_omitted": continuity["unpaired_contracts"] - len(examples),
            "scope": "Identity and retrieval evidence only; no cross-contract scores or feedback. "
                     "Inspect changed fields and the fixed task, then select an existing legal common development "
                     "contract and measure a trusted reference and candidate under it. Reuse source snapshots "
                     "and record genuine new results with a reuse reason when appropriate. Compare only within "
                     "the complete matching contract. Do not alter the fixed evaluator or use confirmation feedback."}


def execution_health(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay operational failures without assigning them an objective score.

    Early failures often have no metric/evaluator identity, so full comparison
    buckets would disconnect a failed run from its preceding successful run.
    This chronological signal compares no scores and ignores confirmation.
    """
    attempts = []
    seen = set()
    for entry in records:
        identity = executed_implementation(entry)
        if identity is None:
            continue
        result = entry["result"]
        reference = (identity, result["result_path"], result.get("result_sha256"))
        if reference not in seen:
            attempts.append(entry)
            seen.add(reference)
    anchor = attempts[-1] if attempts else None
    last_scored = None
    tail = []
    for entry in reversed(attempts):
        if archive_tools._observed_snapshot(entry, archive_tools.implementation_identity(entry),
                                            include_diagnostics=True):
            last_scored = entry["candidate_id"]
            break
        tail.append(entry["candidate_id"])
    issue = None
    if tail:
        result = anchor["result"]
        issue = ("failed_or_invalid_execution" if not anchor["valid"] or result.get("valid") is False
                 or result.get("execution_status") != "success" or result.get("partial")
                 else "unusable_objective")
    return {"anchor_candidate": anchor["candidate_id"] if anchor else None,
            "execution_attempts": len(attempts), "attempts_without_observation": len(tail),
            "last_scored_candidate": last_scored, "needs_attention": bool(tail), "issue": issue,
            "recent_unmeasured_candidates": list(reversed(tail[:8])),
            "scope": "Chronological development and diagnostic execution health only; contracts may differ. "
                     "No objective ranking or causal judgement; duplicate result references are ignored."}


def execution_review_due(health: dict[str, Any], previous: dict[str, Any] | None, window: int) -> bool:
    if not health["needs_attention"] or health["attempts_without_observation"] < window:
        return False
    if previous and previous["last_scored_candidate"] == health["last_scored_candidate"]:
        return health["execution_attempts"] - previous["execution_attempts"] >= window
    return True


def recovery_evidence(records: list[dict[str, Any]], health: dict[str, Any], *,
                      reads: archive_tools.EvidenceReads | None = None) -> dict[str, Any] | None:
    reads = archive_tools.EvidenceReads() if reads is None else reads
    if not health["needs_attention"]:
        return None
    index = archive_tools.candidate_index(records)
    anchor = index[health["anchor_candidate"]]
    # Search the actual development lineage; a confirmation ancestor cannot
    # become a source of repair feedback or a parent selection hint.
    parents = list(anchor["parent_ids"])
    visited = set()
    reference = None
    position = 0
    while position < len(parents):
        candidate_id = parents[position]
        position += 1
        if candidate_id in visited:
            continue
        visited.add(candidate_id)
        entry = index[candidate_id]
        if entry["role"] not in archive_tools.DEVELOPMENT_ROLES:
            continue
        if observed_implementation(entry):
            reference = entry
            break
        parents.extend(entry["parent_ids"])
    relationship = "scored_ancestor" if reference else "earlier_development_observation"
    if reference is None:
        reference = next((entry for entry in reversed(records) if observed_implementation(entry)), None)

    def card(entry: dict[str, Any]) -> dict[str, Any]:
        archive_tools.verify_result(entry, reads=reads)
        archive_tools.verify_artifacts(entry, reads=reads)
        result = entry["result"]
        raw = reads.read_bytes(pathlib.Path(result["result_path"]))
        if archive_tools.sha256(raw) != result["result_sha256"]:
            raise archive_tools.ArchiveFailure("result_changed", "Recovery result changed while reading")
        value = archive_tools.load_json(raw, result["result_path"])
        error = value.get("error")
        diagnostic = {"error": ({key: error.get(key) if isinstance(error.get(key), str) else None
                                  for key in ("type", "phase", "message")}
                                  if isinstance(error, dict) else error if isinstance(error, str) else None),
                      "partial": bool(result.get("partial")),
                      "artifacts": [item for item in value.get("artifacts", []) if isinstance(item, str)]
                                   if isinstance(value.get("artifacts"), list) else []}
        return {"candidate_id": entry["candidate_id"], "role": entry["role"], "parent_ids": entry["parent_ids"],
                "implementation": archive_tools.implementation_identity(entry),
                "artifact_paths": entry["artifact_paths"], "comparison": entry["comparison"],
                "result_path": result["result_path"], "result_sha256": result["result_sha256"],
                "execution_status": result["execution_status"], "diagnostic": diagnostic,
                "identity_checks": {"result_bytes": "checked", "snapshot_bytes": "checked"}}

    return {"target": card(anchor), "reference": card(reference) if reference else None,
            "reference_relationship": relationship if reference else None,
            "reference_comparison_matches": reference["comparison"] == anchor["comparison"] if reference else None,
            "scope": "Inspect actual error/phase and cited logs before choosing the responsible code or environment. "
                     "An unscored run is not evidence against its algorithm. A reference under another contract "
                     "must be revalidated; do not modify the fixed evaluator to make a candidate pass."}


def delivered_exposures(packet: dict[str, Any]) -> dict[str, list[str]]:
    """A bounded hint counts as delivered only with its full evidence identity.

    Feedback prose and reuse history may be shortened. Original code/result
    pointers, proposal targets and referenced IDs must remain recoverable.
    """
    brief = packet.get("development_brief") or {}
    cards = brief.get("candidates", {})
    references = brief.get("pending_references", {})
    omissions = packet.get("truncated_fields", {})

    def complete_field(prefix: str) -> bool:
        return not any(path == prefix or path.startswith(prefix + "/") for path in omissions)

    def complete_card(candidate_id: str, *, unmeasured: bool = False) -> bool:
        collection = "candidates" if candidate_id in cards else "pending_references"
        if collection == "pending_references" and not unmeasured:
            return False
        card = (cards if collection == "candidates" else references).get(candidate_id, {})
        identity, result = card.get("implementation", {}), card.get("result", {})
        expected = {"result_bytes": "checked" if result.get("result_path") else "not_recorded",
                    "snapshot_bytes": "checked" if card.get("artifact_paths") else "not_recorded"}
        if (not identity.get("fingerprint") or not identity.get("artifacts")
                or card.get("identity_checks") != expected
                or bool(result.get("result_path")) != bool(result.get("result_sha256"))
                or not all(complete_field(f"/development_brief/{collection}/{candidate_id}/{key}")
                           for key in ("artifact_paths", "implementation", "result"))):
            return False
        return unmeasured or expected == {"result_bytes": "checked", "snapshot_bytes": "checked"}

    implementations = []
    for item in brief.get("review_frontier", {}).get("selection", []):
        fingerprint = item["implementation_fingerprint"]
        roots = {item["candidate_id"], item.get("feedback_candidate_id", item["candidate_id"])}
        required = roots | ({item["latest_successor"]} if item.get("latest_successor") else set())
        if (all(complete_card(candidate_id) for candidate_id in required)
                and all(cards[candidate_id]["implementation"]["fingerprint"] == fingerprint for candidate_id in roots)):
            implementations.append(fingerprint)

    proposals = []
    for position, item in enumerate(brief.get("pending_details", [])):
        prefix = f"/development_brief/pending_details/{position}"
        try:
            archive_tools.validate_construction_targets(item)
            checks = archive_tools.proposal_identity_checks(item)
        except archive_tools.ArchiveFailure:
            continue
        if (item.get("identity_checks") != checks
                or not item.get("proposal_id")
                or not all(complete_field(f"{prefix}/{key}")
                           for key in ("proposal_id", "input_sha256", "parent_ids", "feedback_from", "code_targets", "construction_mode", "learning_from"))):
            continue
        required = set(item["parent_ids"] + item["feedback_from"] + item.get("learning_from", []))
        if all(complete_card(candidate_id, unmeasured=True) for candidate_id in required):
            proposals.append(item["proposal_id"])
    return {"implementations": implementations, "proposals": proposals}


def _comparison_review_identity(packet: dict[str, Any]) -> dict[str, Any]:
    recovery = packet["comparison_recovery"]
    result = {"archive_path": packet["archive_path"], "changed_fields": recovery["changed_fields"]}
    for name in ("target", "reference"):
        card = recovery[name]
        result[name] = ({key: card.get(key) for key in
                         ("candidate_id", "implementation_fingerprint", "comparison_sha256", "result_path",
                          "result_sha256", "identity_checks")} if card else None)
    return result


def delivered_comparison_review(packet: dict[str, Any]) -> bool:
    """Do not consume a review whose recovery pointers were lost to bounding."""
    recovery = packet.get("comparison_recovery")
    if not recovery or not recovery.get("target"):
        return False
    if not isinstance(packet.get("archive_path"), str) or not isinstance(recovery.get("changed_fields"), list):
        return False
    for name in ("target", "reference"):
        card = recovery.get(name)
        if card is None and name == "reference":
            continue
        for key in ("candidate_id", "implementation_fingerprint", "comparison_sha256", "result_path", "result_sha256"):
            if not isinstance(card.get(key), str) or not card[key]:
                return False
        if card.get("identity_checks") != {"result_bytes": "checked", "snapshot_bytes": "checked"}:
            return False
    # The bounded omission index may merge paths after 64 entries. Compare the
    # actual retrieval material with its pre-bounding digest instead of treating
    # absence from that index as proof that every critical pointer survived.
    return recovery.get("retrieval_sha256") == archive_tools.sha256(
        archive_tools.canonical(_comparison_review_identity(packet)))


def _repeat_conflict_identity(packet: dict[str, Any]) -> dict[str, Any]:
    conflict = packet["repeat_conflict"]
    result = {"archive_path": packet["archive_path"], "signature": conflict["signature"],
              "comparison_key": conflict["comparison_key"], "reason": conflict["reason"]}
    for name in ("leader", "challenger", "witness"):
        result[name] = {key: conflict["cards"][name].get(key) for key in
                        ("candidate_id", "implementation_fingerprint", "comparison_sha256",
                         "result_path", "result_sha256", "identity_checks")}
    return result


def delivered_repeat_conflict(packet: dict[str, Any]) -> bool:
    """Only a complete, verified conflict card can consume its review."""
    conflict = packet.get("repeat_conflict")
    if not isinstance(conflict, dict) or not isinstance(conflict.get("cards"), dict):
        return False
    if any(not isinstance(conflict.get(key), str) or not conflict[key] for key in
           ("signature", "comparison_key", "reason")):
        return False
    try:
        for name in ("leader", "challenger", "witness"):
            card = conflict["cards"][name]
            if not isinstance(card, dict):
                return False
            if any(not isinstance(card.get(key), str) or not card[key] for key in
                   ("candidate_id", "implementation_fingerprint", "comparison_sha256",
                    "result_path", "result_sha256")):
                return False
            if card.get("identity_checks") != {"result_bytes": "checked", "snapshot_bytes": "checked"}:
                return False
        return conflict.get("retrieval_sha256") == archive_tools.sha256(
            archive_tools.canonical(_repeat_conflict_identity(packet)))
    except (KeyError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Handoff:
    packet: dict[str, Any]
    delivery: dict[str, Any]


def prepare_handoff(memory: Mapping[str, Any], prepared: TurnPlan, view: CampaignEvidence,
                    task_sha256: str) -> Handoff:
    """Prepare bounded evidence and its schema-v2 delivery intent together.

    Only complete cards remaining in the final packet are offered for later
    acknowledgment. Persisting or rendering a packet does not acknowledge it.
    """
    facts = view.signals(memory["comparison_review_checkpoint"])
    key = facts["objective_progress"]["comparison_key"]
    packet = handoff_packet(
        pathlib.Path(memory["archive"]), view.records, memory["archive_snapshot"], task_sha256,
        progress=facts["objective_progress"], health=facts["execution_health"],
        continuity=facts["comparison_continuity"], _view=view,
        measurement_plan=facts["measurement_plan"], mode=prepared.updates["next_mode"],
        frontier_seen=memory["frontier_exposures"].get(key, {}),
        pending_seen=memory["pending_proposal_exposures"].get(key, {}),
        trial_seen=memory["trial_exposures"].get(key, {}),
        learning_seen=memory["learning_exposures"].get(key, {}))
    exposed = delivered_exposures(packet)
    reviews = dict(prepared.review_requests)
    if "comparison" in reviews and not delivered_comparison_review(packet):
        reviews.pop("comparison")
    if "repeat" in reviews and not delivered_repeat_conflict(packet):
        reviews.pop("repeat")
    return Handoff(packet, {
        "frontier_exposure": {"comparison_key": key, "implementations": exposed["implementations"]},
        "pending_proposal_exposure": {"comparison_key": key, "proposals": exposed["proposals"]},
        "trial_exposure": {"comparison_key": key, "proposals": delivered_trials(packet)},
        "learning_exposure": {"comparison_key": key,
                              "candidates": archive_tools.scoped_learning.delivered(packet)},
        "review_checkpoints": reviews,
    })


def handoff_packet(archive: pathlib.Path, records: list[dict[str, Any]],
                   snapshot: dict[str, Any], task_sha256: str, *,
                   progress: dict[str, Any] | None = None,
                   health: dict[str, Any] | None = None,
                   continuity: dict[str, Any] | None = None,
                   frontier_seen: dict[str, int] | None = None,
                   pending_seen: dict[str, int] | None = None,
                   trial_seen: dict[str, int] | None = None,
                   learning_seen: dict[str, int] | None = None,
                   evidence: archive_tools.ComparisonEvidence | None = None,
                   measurement_plan: dict[str, Any] | None = None,
                   _view: CampaignEvidence | None = None, mode: str = "work") -> dict[str, Any]:
    view = _view if _view is not None else CampaignEvidence(records, comparisons=evidence)
    reads, evidence = view._reads, view._comparisons
    if progress is None:
        progress = view._progress
    if health is None:
        health = view._health
    if continuity is None:
        continuity = view.signals()["comparison_continuity"]
    if measurement_plan is None:
        measurement_plan = view._measurement_plan
    index = view._index
    repeat_conflict = None
    if progress["anchor_candidate"]:
        repeat_conflict = (view._repeat_conflict if progress["anchor_candidate"] == view._progress["anchor_candidate"] else
                           evidence.for_candidate(progress["anchor_candidate"]).ranking_conflict())
        if repeat_conflict:
            repeat_conflict = dict(repeat_conflict)
            cards = {}
            for name in ("leader", "challenger", "witness"):
                entry = index[repeat_conflict[name + "_candidate"]]
                archive_tools.verify_result(entry, reads=reads)
                archive_tools.verify_artifacts(entry, reads=reads)
                cards[name] = {"candidate_id": entry["candidate_id"],
                               "implementation_fingerprint": archive_tools.implementation_identity(entry)["fingerprint"],
                               "comparison_sha256": archive_tools.sha256(archive_tools.canonical(entry["comparison"])),
                               "result_path": entry["result"]["result_path"],
                               "result_sha256": entry["result"]["result_sha256"],
                               "identity_checks": {"result_bytes": "checked", "snapshot_bytes": "checked"}}
            repeat_conflict["cards"] = cards
    related = {identity for candidate_id in (progress["anchor_candidate"], progress["best_candidate"])
               if candidate_id and (identity := executed_implementation(index[candidate_id]))}
    brief = None
    if progress["anchor_candidate"]:
        brief = archive_tools.optimization_brief(
            argparse.Namespace(archive=archive, anchor=progress["anchor_candidate"], recent=4, routes=4, frontier=2),
            records, rankable=observed_implementation, frontier_seen=frontier_seen,
            pending_seen=pending_seen, learning_seen={} if learning_seen is None else learning_seen,
            reads=reads, evidence=evidence)
        brief["scope"] += " Best representatives in this packet additionally require a scored adapter result and code/recipe snapshot."
        # Other comparison contracts remain in the archive for reconciliation;
        # they must not become the new session's active proposal list.
        brief["pending_proposals"] = brief.pop("matched_pending_proposals")
        # Preserve parent-relative observations without turning explanations into
        # universal rules. Cross-contract parents cannot supply a signed gain.
        for candidate_id, card in brief["candidates"].items():
            entry = index[candidate_id]
            gains = {}
            for parent_id in entry["parent_ids"]:
                parent = index[parent_id]
                gains[parent_id] = (archive_tools.directed_score(entry) - archive_tools.directed_score(parent)
                                    if observed_implementation(entry) and observed_implementation(parent)
                                    and parent["comparison"] == entry["comparison"] else None)
            card["objective_gain_vs_parents"] = gains
            card["feedback_scope"] = "Agent observations for this implementation and comparison; causal claims unverified"
    packet = {"schema_version": 1, "archive_path": str(archive), "archive_snapshot": snapshot,
              "task_sha256": task_sha256, "objective_progress": progress,
              "execution_health": health, "execution_recovery": recovery_evidence(records, health, reads=reads),
              "comparison_continuity": continuity,
              "comparison_recovery": comparison_recovery(records, continuity, reads=reads),
              "repeat_conflict": repeat_conflict,
              "measurement_plan": ({"plan_id": measurement_plan["plan_id"],
                                    "conflict_signature": measurement_plan["conflict_signature"],
                                    "comparison_key": archive_tools.sha256(archive_tools.canonical(measurement_plan["comparison"])),
                                    "remaining_slots": sum(item[name] is None for item in measurement_plan["runs"]
                                                           for name in ("leader", "challenger")),
                                    "pairs_complete": measurement_plan["complete"],
                                    "next_run_id": next((item["run_id"] for item in measurement_plan["runs"]
                                                         if item["leader"] is None or item["challenger"] is None), None),
                                    "scope": "Read the full frozen protocol and paired outcomes with candidate_archive.py "
                                             "measure-status --archive PATH --plan-id ID; complete its unmatched slots."}
                                   if measurement_plan else None),
              "measurement_decision": archive_tools.measurement_plans.latest_decision(
                  records, progress["comparison"], reads=reads),
              "measurement_stop": archive_tools.measurement_plans.latest_stop(
                  records, progress["comparison"], reads=reads),
              "trial_history": trial_history(archive, records, progress["comparison"], related, seen=trial_seen, reads=reads),
              "development_brief": brief,
              "scope": "Matched development evidence only. Best scores are observations, not certified promotion. "
                       "Read the cited code/results for the next decision. Truncated fields are retrieval hints, "
                       "not complete identifiers or executable paths. Confirmation scores never guide the next proposal."}
    if packet["comparison_recovery"]:
        packet["comparison_recovery"]["retrieval_sha256"] = archive_tools.sha256(
            archive_tools.canonical(_comparison_review_identity(packet)))
    if repeat_conflict:
        repeat_conflict["retrieval_sha256"] = archive_tools.sha256(
            archive_tools.canonical(_repeat_conflict_identity(packet)))
    return bound_packet(packet, budget=HANDOFF_BYTES, mode=mode)
