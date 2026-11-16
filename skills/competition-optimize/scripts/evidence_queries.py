"""Decision-relevant queries over one accepted candidate archive prefix.

Records are borrowed and must not be mutated during this snapshot's lifetime.
Queries own their indexes, comparison projection and request-local byte checks;
construct a new snapshot after accepting events or starting another handoff.
The module does not parse/write archives or acknowledge delivered evidence.
"""
from __future__ import annotations

import math
import pathlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

import candidate_profiles
import resource_profiles
import scoped_learning
from campaign_trials import trial_history
from candidate_evidence import (
    ArchiveFailure, ComparisonEvidence, DEVELOPMENT_ROLES, OUTPUT_ONLY_SCOPES,
    candidate_index, canonical, directed_score, distinct_implementations,
    implementation_identity, load_json, measurable, observed_snapshot,
    proposal_identity_checks, review_opportunities, sha256,
)
from evidence_files import (ArtifactResolver, EvidenceReads, verify_artifacts, verify_result,
                            verify_proposal_targets)


@dataclass(frozen=True)
class BriefQuery:
    anchor: str | None = None
    recent: int = 4
    routes: int = 4
    frontier: int = 2
    frontier_seen: dict[str, int] | None = None
    pending_seen: dict[str, int] | None = None
    learning_seen: dict[str, int] | None = None

    def validate(self) -> None:
        if self.recent < 1 or self.routes < 1:
            raise ArchiveFailure("invalid_config", "recent and routes must be positive")
        if type(self.frontier) is not int or self.frontier < 0:
            raise ArchiveFailure("invalid_config", "frontier must be a nonnegative integer")
        if self.frontier_seen is not None and (not isinstance(self.frontier_seen, dict) or any(
                not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                or type(turn) is not int or turn < 0 for fingerprint, turn in self.frontier_seen.items())):
            raise ArchiveFailure("invalid_config", "frontier_seen must map implementation SHA-256 hashes to nonnegative checkpoint turns")
        if self.pending_seen is not None and (not isinstance(self.pending_seen, dict) or any(
                not isinstance(proposal_id, str) or not proposal_id.strip() or type(turn) is not int or turn < 0
                for proposal_id, turn in self.pending_seen.items())):
            raise ArchiveFailure("invalid_config", "pending_seen must map nonempty proposal IDs to nonnegative checkpoint turns")


def read_case_profile(entry: dict[str, Any], *, reads: EvidenceReads | None = None) -> dict[str, Any]:
    """Read the immutable vector only when its archived descriptor was opted in."""
    result = entry["result"]
    path = pathlib.Path(result["result_path"])
    raw = reads.read_bytes(path) if reads is not None else path.read_bytes()
    if sha256(raw) != result["result_sha256"]:
        raise ArchiveFailure("result_changed", f"Result bytes changed for {entry['candidate_id']}")
    value = load_json(raw, str(path))
    profile = value.get("case_profile") if isinstance(value, dict) else None
    try:
        descriptor = candidate_profiles.describe(profile)
    except candidate_profiles.ProfileFailure as exc:
        raise ArchiveFailure("invalid_case_profile", str(exc)) from exc
    if descriptor != result.get("case_profile"):
        raise ArchiveFailure("invalid_case_profile", f"Profile metadata differs from its result: {entry['candidate_id']}")
    return profile


def verify_resource_profile(entry: dict[str, Any], *, reads: EvidenceReads) -> None:
    result = entry["result"]
    raw = reads.read_bytes(pathlib.Path(result["result_path"]))
    if sha256(raw) != result["result_sha256"]:
        raise ArchiveFailure("result_changed", f"Result bytes changed for {entry['candidate_id']}")
    value = load_json(raw, result["result_path"])
    try:
        profile = resource_profiles.describe(value.get("resource_profile") if isinstance(value, dict) else None)
    except resource_profiles.ResourceFailure as exc:
        raise ArchiveFailure("invalid_resource_profile", str(exc)) from exc
    if profile != result["resource_profile"]:
        raise ArchiveFailure("invalid_resource_profile", f"Resource metadata differs from its result: {entry['candidate_id']}")


def evidence_summary(entry: dict[str, Any]) -> dict[str, Any]:
    result = entry["result"]
    summary = {"candidate_id": entry["candidate_id"], "role": entry["role"], "valid": entry["valid"],
            "objective": entry["objective"], "feedback": entry["feedback"],
            "result_path": result.get("result_path"), "result_sha256": result.get("result_sha256"),
            "validity_scope": result.get("validity_scope"), "implementation": implementation_identity(entry)}
    if "implementation_review" in entry:
        summary["implementation_review"] = entry["implementation_review"]
    if "construction_mode" in entry:
        summary["construction_mode"] = entry["construction_mode"]
    for key in ("learning", "learning_from"):
        if key in entry:
            summary[key] = entry[key]
    return summary


class EvidenceSnapshot:
    """Query accepted records through a shared, operation-local evidence view.

    observed_only keeps driver ranking tied to actual scored executions. The
    default retains the legacy standalone brief's manual-score presentation;
    opportunity closure and trial eligibility always require executed evidence.
    """

    def __init__(self, archive_path: pathlib.Path | None, records: list[dict[str, Any]], *,
                 observed_only: bool = False, resolver: ArtifactResolver | None = None) -> None:
        self._archive_path = archive_path
        self._records = records
        self._candidates = candidate_index(records)
        self._reads = EvidenceReads(resolver)
        self._rankable = ((lambda entry: observed_snapshot(entry, implementation_identity(entry)))
                          if observed_only else None)
        self._comparisons: ComparisonEvidence | None = None

    @classmethod
    def _from_views(cls, archive_path: pathlib.Path | None, records: list[dict[str, Any]], *,
                    rankable: Callable[[dict[str, Any]], bool] | None = None,
                    reads: EvidenceReads | None = None,
                    comparisons: ComparisonEvidence | None = None) -> "EvidenceSnapshot":
        """Internal adapter for old callers already holding request-local views."""
        value = cls(archive_path, records)
        value._rankable = rankable
        if reads is not None:
            value._reads = reads
        value._comparisons = comparisons
        return value

    def trials(self, comparison: dict[str, Any] | None, related_implementations: set[str], *,
               seen: dict[str, int] | None = None, limit: int = 2) -> dict[str, Any]:
        if self._archive_path is None:
            raise ArchiveFailure("invalid_config", "An archive path is required for trial history")
        return trial_history(self._archive_path, self._records, comparison, related_implementations,
                             seen=seen, limit=limit, reads=self._reads)

    def trace(self, *, proposal_id: str | None = None, recent: int | None = None) -> list[dict[str, Any]]:
        """Read prospective chains and verify only their selected evidence."""
        records, reads, candidates = self._records, self._reads, self._candidates
        outcomes = {entry["proposal_id"]: entry for entry in records
                    if entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id")}
        trace = []
        verified: set[str] = set()
        def verify(entry: dict[str, Any]) -> None:
            if entry["candidate_id"] not in verified:
                verify_result(entry, reads=reads)
                verify_artifacts(entry, reads=reads)
                if "learning" in entry:
                    scoped_learning.verify_evidence(entry["learning"], candidates, reads=reads)
                verified.add(entry["candidate_id"])
        proposals = [entry for entry in records if entry["event"] == "proposal"]
        if proposal_id is not None:
            proposals = [entry for entry in proposals if entry["proposal_id"] == proposal_id]
            if not proposals:
                raise ArchiveFailure("unknown_proposal", f"No archived proposal {proposal_id!r}")
        checked_targets: set[tuple[str, str]] = set()
        for proposal in proposals if recent is None else proposals[-recent:]:
            outcome = outcomes.get(proposal["proposal_id"])
            row = {key: proposal[key] for key in ("proposal_id", "parent_ids", "feedback_from", "route", "basis", "change",
                                                  "expected_observation", "code_targets", "validation", "stop_condition")}
            row["input_sha256"] = proposal.get("input_sha256")
            if "construction_mode" in proposal:
                row["construction_mode"] = proposal["construction_mode"]
            if "learning_from" in proposal:
                row["learning_from"] = proposal["learning_from"]
            row["feedback_evidence"] = [evidence_summary(candidates[i]) for i in proposal["feedback_from"]]
            if "learning_from" in proposal:
                row["learning_evidence"] = {i: candidates[i]["learning"] for i in proposal["learning_from"]}
            for candidate_id in proposal["parent_ids"] + proposal["feedback_from"] + proposal.get("learning_from", []):
                verify(candidates[candidate_id])
            for candidate_id in proposal.get("learning_from", []):
                scoped_learning.verify_evidence(candidates[candidate_id]["learning"], candidates, reads=reads)
            verify_proposal_targets(proposal, checked_targets, reads=reads)
            row["identity_checks"] = proposal_identity_checks(proposal)
            row["state"] = "pending"
            if outcome is not None and outcome["event"] == "proposal_stop":
                row.update(state="stopped", reason=outcome["reason"])
            elif outcome is not None:
                verify(outcome)
                row.update(state="evaluated_valid" if outcome["valid"] else "evaluation_failed_or_invalid",
                           candidate_id=outcome["candidate_id"], evidence=evidence_summary(outcome), objective=outcome["objective"],
                           feedback=outcome["feedback"], prediction_status=outcome["prediction_status"],
                           failure_mechanism=outcome["failure_mechanism"], cost=outcome["cost"])
                gains = {}
                for parent_id in proposal["parent_ids"]:
                    parent = candidates[parent_id]
                    verify(parent)
                    if measurable(outcome) and measurable(parent) and outcome["comparison"] == parent["comparison"]:
                        delta = outcome["objective"]["value"] - parent["objective"]["value"]
                        gains[parent_id] = delta * (-1 if outcome["objective"]["direction"] == "minimize" else 1)
                    else:
                        gains[parent_id] = None
                row["objective_gain_vs_parents"] = gains
            trace.append(row)
        return trace

    def brief(self, query: BriefQuery | None = None) -> dict[str, Any]:
        """Retrieve decision-relevant development evidence without another ledger/card."""
        query = BriefQuery() if query is None else query
        if self._archive_path is None:
            raise ArchiveFailure("invalid_config", "An archive path is required for a brief")
        query.validate()
        args = query
        records, reads, index = self._records, self._reads, self._candidates
        rankable, evidence = self._rankable, self._comparisons
        frontier_limit = query.frontier
        frontier_seen = query.frontier_seen if query.frontier_seen is not None else {}
        pending_seen, learning_seen = query.pending_seen, query.learning_seen
        if not index:
            raise ArchiveFailure("empty_archive", "Record a baseline before requesting optimization context")
        development = [entry for entry in index.values() if entry["role"] == "development"]
        if args.anchor is not None:
            if args.anchor not in index:
                raise ArchiveFailure("unknown_candidate", f"No archived candidate {args.anchor!r}")
            anchor = index[args.anchor]
            if anchor["role"] != "development":
                raise ArchiveFailure("confirmation_feedback", "Only ordinary development evidence can anchor optimization context")
        elif development:
            anchor = development[-1]
        else:
            raise ArchiveFailure("no_development_evidence", "Confirmation evidence cannot guide new optimization")
        context = anchor["comparison"]
        if evidence is None:
            scoped = [entry for entry in development if entry["comparison"] == context]
            evidence = ComparisonEvidence(self._records, eligible=lambda entry: measurable(entry) and
                                          (rankable is None or rankable(entry)))
            self._comparisons = evidence
        view = evidence.for_candidate(anchor["candidate_id"])
        scoped = list(view.entries)
        by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in scoped:
            by_route[entry["route"]].append(entry)
        measured = view.representatives
        measured_ids = {entry["candidate_id"] for entry in measured}
        best = max(measured, key=directed_score) if measured else None
        route_bests = {}
        for route, entries in by_route.items():
            eligible = [entry for entry in entries if entry["candidate_id"] in measured_ids]
            route_bests[route] = max(eligible, key=directed_score) if eligible else None
        # The active route is always included. Alternatives are a factual score
        # ordering, not an effort quota or an automated choice of the next method.
        alternatives = sorted((route for route in by_route if route != anchor["route"]),
                              key=lambda route: (-directed_score(route_bests[route]) if route_bests[route] else math.inf, route))
        selected_routes = [anchor["route"]] + alternatives[:args.routes - 1]
        selected: dict[str, dict[str, Any]] = {}

        def include(entry: dict[str, Any] | None) -> str | None:
            if entry is None:
                return None
            selected[entry["candidate_id"]] = entry
            return entry["candidate_id"]

        include(anchor)
        include(best)
        resource_entries = [entry for entry in scoped if "resource_profile" in entry["result"]
                            and observed_snapshot(entry, implementation_identity(entry))
                            and (rankable is None or rankable(entry))]
        resource_tradeoffs = resource_profiles.retrieve(
            resource_entries, best, anchor, identity=lambda entry: implementation_identity(entry)["fingerprint"],
            score=directed_score)
        if resource_tradeoffs["reference_candidate_id"] is not None:
            include(index[resource_tradeoffs["reference_candidate_id"]])
        for point in resource_tradeoffs["selection"]:
            include(index[point["candidate_id"]])
        opportunities, identities = review_opportunities(scoped, index, rankable)

        def include_opportunity(opportunity: dict[str, Any] | None) -> str | None:
            if opportunity is None:
                return None
            candidate_id = include(opportunity["candidate"])
            include(opportunity["feedback_candidate"])
            return candidate_id

        # Preserve the actual exploration evidence before route/recent cards when
        # an automatic handoff must bound a large candidate-card mapping.
        frontier = sorted(opportunities.items(), key=lambda item: (
            item[0] in frontier_seen, frontier_seen.get(item[0], 0), item[1]["position"]))
        frontier_selection = []
        for fingerprint, opportunity in frontier[:frontier_limit]:
            candidate_id = include_opportunity(opportunity)
            frontier_selection.append({"candidate_id": candidate_id,
                                       "implementation_fingerprint": fingerprint,
                                       "feedback_candidate_id": opportunity["feedback_candidate"]["candidate_id"],
                                       "last_exposed_turn": frontier_seen.get(fingerprint),
                                       "successor_implementations": len(opportunity["successors"]),
                                       "measured_successor_implementations": len(opportunity["measured_successors"]),
                                       "latest_successor": include(opportunity["latest_successor"])})

        profile_entries = view.first_profiles("case_profile")
        try:
            complementary = candidate_profiles.retrieve(
                profile_entries, best, identity=lambda entry: implementation_identity(entry)["fingerprint"],
                read_profile=lambda entry: read_case_profile(entry, reads=reads), score=directed_score)
        except candidate_profiles.ProfileFailure as exc:
            raise ArchiveFailure("invalid_case_profile", str(exc)) from exc
        if complementary["reference_candidate_id"] is not None:
            include(index[complementary["reference_candidate_id"]])
        for item in complementary["selection"]:
            include(index[item["candidate_id"]])

        closed = {entry["proposal_id"] for entry in records
                  if entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id")}
        pending = [entry for entry in records if entry["event"] == "proposal" and entry["proposal_id"] not in closed]
        # A proposal belongs to its first parent's own comparison. Other parents
        # or feedback may supply code or diagnostic references under a different
        # contract; their control relationship does not move proposal ownership.
        matching_pending = [entry for entry in pending if index[entry["parent_ids"][0]]["comparison"] == context]
        if pending_seen is None:
            details = matching_pending[-args.recent:]
        else:
            details = sorted(matching_pending, key=lambda entry: (
                entry["proposal_id"] in pending_seen, pending_seen.get(entry["proposal_id"], 0)))[:args.recent]
        reference_entries: dict[str, dict[str, Any]] = {}
        diagnostics = [entry for entry in index.values() if entry["role"] == "diagnostic"
                       and index[entry["parent_ids"][0]]["comparison"] == context]
        selected_diagnostics = diagnostics[-2:]
        for entry in selected_diagnostics:
            include(index[entry["parent_ids"][0]])
            if entry["comparison"] == context:
                include(entry)
            else:
                reference_entries[entry["candidate_id"]] = entry
        for proposal in details:
            for candidate_id in proposal.get("learning_from", []):
                scoped_learning.verify_evidence(index[candidate_id]["learning"], index, reads=reads)
            for candidate_id in proposal["parent_ids"] + proposal["feedback_from"] + proposal.get("learning_from", []):
                entry = index[candidate_id]
                if entry["role"] not in DEVELOPMENT_ROLES:
                    raise ArchiveFailure("confirmation_feedback", "Confirmation evidence cannot supply pending work or references")
                if entry["role"] == "diagnostic":
                    control = index[entry["parent_ids"][0]]
                    if control["comparison"] == context:
                        include(control)
                    else:
                        reference_entries[control["candidate_id"]] = control
                if entry["comparison"] == context:
                    include(entry)
                else:
                    reference_entries[candidate_id] = entry

        recent = distinct_implementations(by_route[anchor["route"]])[-args.recent:]
        recent_ids = [include(entry) for entry in recent]
        routes = []
        for route in selected_routes:
            entries = by_route[route]
            unresolved = next((opportunities[identities[entry["candidate_id"]]["fingerprint"]]
                               for entry in reversed(entries)
                               if identities[entry["candidate_id"]]["fingerprint"] in opportunities), None)
            failure = next((entry for entry in reversed(entries)
                            if not entry["valid"] or entry["status"] == "rejected" or entry.get("failure_mechanism")), None)
            routes.append({"route": route, "measurements": len(entries),
                           "distinct_artifact_fingerprints": len({entry["fingerprint"] for entry in entries}),
                           "distinct_implementations": (len(distinct_implementations(entries))
                                                        if all(implementation_identity(entry)["scope"] not in OUTPUT_ONLY_SCOPES
                                                               for entry in entries) else None),
                           "best": include(route_bests[route]), "latest": include(entries[-1]),
                           "unresolved": include_opportunity(unresolved),
                           "unresolved_feedback": (unresolved["feedback_candidate"]["candidate_id"] if unresolved else None),
                           "latest_failure": include(failure)})
        artifact_groups: dict[str, list[str]] = defaultdict(list)
        artifact_reused: dict[str, list[str]] = {}
        for entry in index.values():
            fingerprint = entry["fingerprint"]
            if entry["candidate_id"] in selected:
                artifact_reused[entry["candidate_id"]] = list(artifact_groups[fingerprint])
            artifact_groups[fingerprint].append(entry["candidate_id"])
        implementation_groups: dict[str, list[str]] = defaultdict(list)
        reused: dict[str, list[str]] = {}
        for entry in index.values():
            if entry["role"] not in DEVELOPMENT_ROLES or entry["comparison"] != context:
                continue
            fingerprint = implementation_identity(entry)["fingerprint"]
            # Only displayed cards consume these prefixes. Copying a growing list
            # for every unselected repeat makes long-running retrieval quadratic.
            if entry["candidate_id"] in selected:
                reused[entry["candidate_id"]] = list(implementation_groups[fingerprint])
            implementation_groups[fingerprint].append(entry["candidate_id"])
        cards = {}
        for candidate_id, entry in selected.items():
            verify_result(entry, reads=reads)
            verify_artifacts(entry, reads=reads)
            card = {key: entry.get(key) for key in ("role", "parent_ids", "fingerprint", "artifact_paths", "route", "mechanism",
                                                  "valid", "status", "objective", "cost", "feedback", "failure_mechanism",
                                                  "proposal_id", "prediction_status")}
            result = entry["result"]
            card["reused_from"] = artifact_reused[candidate_id]
            card["implementation"] = implementation_identity(entry)
            card["reused_implementation_from"] = reused[candidate_id]
            card["result"] = {key: result.get(key) for key in ("result_path", "result_sha256", "execution_status",
                                                             "validity_scope", "unchecked_rules")}
            if "case_profile" in result:
                card["result"]["case_profile"] = result["case_profile"]
            if "resource_profile" in result:
                verify_resource_profile(entry, reads=reads)
                card["result"]["resource_profile"] = result["resource_profile"]
            card["identity_checks"] = {"result_bytes": "checked" if result.get("result_path") else "not_recorded",
                                       "snapshot_bytes": "checked" if entry["artifact_paths"] else "not_recorded"}
            card["objective_gain_vs_best"] = (directed_score(entry) - directed_score(best)
                                              if best is not None and candidate_id in measured_ids else None)
            if "implementation_review" in entry:
                card["implementation_review"] = entry["implementation_review"]
            if "construction_mode" in entry:
                card["construction_mode"] = entry["construction_mode"]
            for key in ("learning", "learning_from"):
                if key in entry:
                    if key == "learning":
                        scoped_learning.verify_evidence(entry[key], index, reads=reads)
                    card[key] = entry[key]
            cards[candidate_id] = card
        checked_targets: set[tuple[str, str]] = set()
        for proposal in details:
            verify_proposal_targets(proposal, checked_targets, reads=reads)
        pending_references = {}
        for candidate_id, entry in reference_entries.items():
            verify_result(entry, reads=reads)
            verify_artifacts(entry, reads=reads)
            result = entry["result"]
            pending_references[candidate_id] = {
                "role": entry["role"],
                "implementation": implementation_identity(entry), "artifact_paths": entry["artifact_paths"],
                "result": {key: result.get(key) for key in ("result_path", "result_sha256", "execution_status")},
                "comparison_sha256": sha256(canonical(entry["comparison"])), "requires_revalidation": True,
                "identity_checks": {"result_bytes": "checked" if result.get("result_path") else "not_recorded",
                                    "snapshot_bytes": "checked" if entry["artifact_paths"] else "not_recorded"},
                "scope": "Development or diagnostic code/result identity from another comparison. Read cited artifacts for repair or transfer; "
                         "revalidate under the target contract. Its objective and feedback do not guide active score ranking."}
        return {"schema_version": 1, "archive_path": reads.archive_name(self._archive_path),
                "anchor_candidate": anchor["candidate_id"], "comparison": context,
                "best_development": best["candidate_id"] if best else None,
                "recent_current": recent_ids, "routes": routes, "candidates": cards,
                "pending_references": pending_references,
                "complementary_evidence": complementary,
                "resource_tradeoffs": resource_tradeoffs,
                "scoped_learning": scoped_learning.retrieve(
                    index, context, {implementation_identity(entry)["fingerprint"]
                                     for entry in (anchor, best) if entry is not None}, reads=reads,
                    seen=learning_seen, archive_path=self._archive_path),
                "diagnostic_evidence": {"selection": [entry["candidate_id"] for entry in selected_diagnostics],
                                        "available": len(diagnostics), "omitted": len(diagnostics) - len(selected_diagnostics),
                                        "scope": "Latest two diagnostic interventions whose first development control matches the complete active comparison. "
                                                 "Diagnostics inform the next change, not candidate ranking, route progress, opportunity closure or promotion. "
                                                 "A diagnostic under another contract supplies identity only and requires revalidation. "
                                                 "This retrieval window does not limit diagnostic experiments."},
                "review_frontier": {"selection": frontier_selection, "available": len(frontier),
                                    "omitted": len(frontier) - len(frontier_selection),
                                    "scope": "Matched development opportunities, separate from elite ranking. "
                                             "Never exposed implementations precede least recently exposed ones; "
                                             "archive declaration order breaks ties. Exposure turns are caller-supplied checkpoints. "
                                             "First valid scored execution represents each code/recipe; feedback may come from an alias. "
                                             "Successor counts cover distinct executed implementations after the first opportunity declaration. "
                                             "Only a measured changed successor with a non-unresolved outcome supersedes an opportunity. "
                                             "This retrieval size does not limit experiments or establish causal value."},
                "pending_proposals": [entry["proposal_id"] for entry in pending],
                "matched_pending_proposals": [entry["proposal_id"] for entry in matching_pending],
                "pending_summary": {"available": len(matching_pending), "omitted": len(matching_pending) - len(details),
                                    "selection_policy": "latest" if pending_seen is None else "least_recently_exposed",
                                    "scope": "Unfinished work belongs to its first parent's own complete comparison. "
                                             "Other development or diagnostic references require revalidation and supply no active objective or feedback. "
                                             "Exposure turns are caller-supplied successful checkpoints, not execution or closure. "
                                             "Retrieval windows do not limit experiments."},
                "pending_details": [{**{key: entry[key] for key in ("proposal_id", "parent_ids", "feedback_from", "route",
                                                                   "code_targets", "basis", "change", "expected_observation",
                                                                   "validation", "stop_condition")},
                                     **({"construction_mode": entry["construction_mode"]} if "construction_mode" in entry else {}),
                                     **({"learning_from": entry["learning_from"]} if "learning_from" in entry else {}),
                                     "input_sha256": entry.get("input_sha256"),
                                     "last_exposed_turn": pending_seen.get(entry["proposal_id"]) if pending_seen is not None else None,
                                     "identity_checks": proposal_identity_checks(entry)} for entry in details],
                "omitted": {"routes": len(by_route) - len(routes),
                            "current_comparison_candidates": len(scoped) - sum(entry["role"] == "development" for entry in selected.values()),
                            "other_development_comparisons": len(development) - len(scoped),
                            "pending_details": len(pending) - len(details)},
                "scope": "Development ranking with separate diagnostic evidence; first valid development observation per implementation identity ranks representatives. "
                         "Output-only artifacts do not establish distinct code/recipe counts. "
                         "Identity checks cover displayed evidence, not all history, score recomputation, causality or promotion. "
                         "Inspect relevant code and raw results before proposing the next implementation."}
