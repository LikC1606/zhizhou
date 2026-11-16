"""Conditional agent conclusions bound to measured development trials.

Learning is an interpretation of cited evidence, not a causal rule, score or
permission to stop exploring. Revisions append with actual successor outcomes.
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any

from candidate_evidence import canonical, implementation_identity, observed_snapshot, sha256
from evidence_files import EvidenceReads, verify_artifacts, verify_result


class LearningFailure(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _body(value: Any) -> None:
    if (not isinstance(value, dict)
            or any(not _text(value.get(key)) for key in
                   ("key", "lesson", "conditions", "next_action", "limitations"))
            or not isinstance(value.get("evidence_from"), list)
            or any(not _text(item) for item in value["evidence_from"])
            or len(set(value["evidence_from"])) != len(value["evidence_from"])
            or value.get("revises") is not None and not _text(value["revises"])):
        raise LearningFailure("Learning needs key, lesson, conditions, next_action, limitations, distinct evidence_from IDs and optional revises")


def active(candidates: dict[str, dict[str, Any]], comparison: dict[str, Any]) -> dict[str, dict[str, Any]]:
    heads = {}
    for entry in candidates.values():
        if entry["comparison"] == comparison and "learning" in entry:
            heads[entry["learning"]["key"]] = entry
    return heads


def evidence_identity(entry: dict[str, Any]) -> dict[str, Any]:
    return {"candidate_id": entry["candidate_id"], "role": entry["role"],
            "implementation": implementation_identity(entry),
            "artifact_paths": entry["artifact_paths"],
            "comparison_sha256": sha256(canonical(entry["comparison"])),
            "result": {key: entry["result"].get(key)
                       for key in ("result_path", "result_sha256", "execution_status")}}


def verify_evidence(value: dict[str, Any], candidates: dict[str, dict[str, Any]], *,
                    reads: EvidenceReads | None = None) -> None:
    for candidate_id in value["evidence_from"]:
        verify_result(candidates[candidate_id], reads=reads)
        verify_artifacts(candidates[candidate_id], reads=reads)


def validate(value: Any, entry: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> None:
    _body(value)
    if (not entry.get("proposal_id") or value.get("candidate_id") != entry["candidate_id"]
            or value.get("proposal_id") != entry["proposal_id"]
            or value.get("assessment_kind") != "agent_report"
            or value.get("comparison_sha256") != sha256(canonical(entry["comparison"]))
            or not isinstance(value.get("input_sha256"), str)
            or len(value["input_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in value["input_sha256"])
            or entry["candidate_id"] not in value["evidence_from"]):
        raise LearningFailure("Learning must bind its prospective measured successor and comparison")
    evidence = {**candidates, entry["candidate_id"]: entry}
    for candidate_id in value["evidence_from"]:
        reference = evidence.get(candidate_id)
        if (reference is None or reference["comparison"] != entry["comparison"]
                or not observed_snapshot(reference, implementation_identity(reference),
                                         include_diagnostics=True)):
            raise LearningFailure("Learning evidence requires measured development/diagnostic snapshots under the same complete comparison")
    previous = active(candidates, entry["comparison"]).get(value["key"])
    if value.get("revises") != (previous["candidate_id"] if previous else None):
        raise LearningFailure("A learning update must explicitly revise the current head for its key and comparison")
    if previous and previous["candidate_id"] not in value["evidence_from"]:
        raise LearningFailure("A learning revision must retain its previous head as evidence")
    identities = {candidate_id: evidence_identity(evidence[candidate_id])
                  for candidate_id in value["evidence_from"]}
    if value.get("evidence_sha256") != sha256(canonical(identities)):
        raise LearningFailure("Learning evidence identities differ from the recorded sources")


def normalize(value: Any, raw: bytes, entry: dict[str, Any],
              candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _body(value)
    report = {key: value[key] for key in ("key", "lesson", "conditions", "next_action", "limitations")}
    ids = list(dict.fromkeys(value["evidence_from"] + [entry["candidate_id"]]))
    all_entries = {**candidates, entry["candidate_id"]: entry}
    if any(candidate_id not in all_entries for candidate_id in ids):
        raise LearningFailure("Unknown learning evidence candidate")
    report.update(assessment_kind="agent_report", candidate_id=entry["candidate_id"],
                  proposal_id=entry.get("proposal_id"), input_sha256=hashlib.sha256(raw).hexdigest(),
                  comparison_sha256=sha256(canonical(entry["comparison"])),
                  evidence_from=ids, revises=value.get("revises"),
                  evidence_sha256=sha256(canonical(
                      {candidate_id: evidence_identity(all_entries[candidate_id]) for candidate_id in ids})))
    validate(report, entry, candidates)
    verify_evidence(report, all_entries)
    return report


def validate_references(proposal: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> None:
    if "learning_from" not in proposal:
        return
    ids = proposal["learning_from"]
    if (not isinstance(ids, list) or not ids or any(not _text(item) for item in ids)
            or len(set(ids)) != len(ids)):
        raise LearningFailure("learning_from must name distinct current learning candidate IDs")
    comparison = candidates[proposal["parent_ids"][0]]["comparison"]
    heads = {entry["candidate_id"] for entry in active(candidates, comparison).values()}
    if not set(ids) <= heads:
        raise LearningFailure("learning_from must reference current learning under the first parent's complete comparison")


def retrieve(candidates: dict[str, dict[str, Any]], comparison: dict[str, Any],
             related: set[str], limit: int = 2, *, reads: EvidenceReads | None = None,
             seen: dict[str, int] | None = None, archive_path: pathlib.Path | None = None) -> dict[str, Any]:
    if type(limit) is not int or limit < 0:
        raise LearningFailure("Learning retrieval limit must be a nonnegative integer")
    if seen is not None and (not isinstance(seen, dict) or any(
            not _text(key) or type(turn) is not int or turn < 0 for key, turn in seen.items())):
        raise LearningFailure("Learning exposures must map candidate IDs to nonnegative turns")
    heads = list(active(candidates, comparison).values())
    positions = {entry["candidate_id"]: i for i, entry in enumerate(candidates.values())}
    heads.sort(key=lambda entry: (implementation_identity(entry)["fingerprint"] not in related,
                                  -positions[entry["candidate_id"]]))
    limit = min(limit, 2)
    selected = [(entry, "related_then_recent") for entry in heads[:limit]]
    if seen is not None:
        selected = []
        related_heads = [entry for entry in heads
                         if implementation_identity(entry)["fingerprint"] in related]
        if limit and related_heads:
            selected.append((related_heads[0], "recent_related"))
        chosen = {entry["candidate_id"] for entry, _ in selected}
        rotating = sorted((entry for entry in heads if entry["candidate_id"] not in chosen),
                          key=lambda entry: (entry["candidate_id"] in seen,
                                             seen.get(entry["candidate_id"], 0), positions[entry["candidate_id"]]))
        selected.extend((entry, "least_recently_exposed") for entry in rotating[:limit - len(selected)])
    selection = []
    comparison_key = sha256(canonical(comparison))
    for entry, reason in selected:
        report = entry["learning"]
        evidence = {}
        for candidate_id in report["evidence_from"]:
            reference = candidates[candidate_id]
            verify_result(reference, reads=reads)
            verify_artifacts(reference, reads=reads)
            evidence[candidate_id] = evidence_identity(reference)
        row = {"candidate_id": entry["candidate_id"], "learning": report, "evidence": evidence}
        if seen is not None:
            row.update(retrieval_reason=reason, last_exposed_turn=seen.get(entry["candidate_id"]))
            if archive_path is not None:
                row["retrieval_sha256"] = sha256(canonical(
                    _retrieval_identity(reads.archive_name(archive_path) if reads is not None else
                                        str(archive_path.expanduser().resolve()), comparison_key, row)))
        selection.append(row)
    result = {"available": len(heads), "omitted": len(heads) - len(selection), "selection": selection,
            "scope": "Current conditional agent reports under this complete development comparison; related implementations then recent revisions. "
                     "Inspect conditions, limitations and cited code/results before applying. Reports do not prove causality, "
                     "rank candidates, ban a method or stop the campaign. Exact trace restores omitted details."}
    if seen is not None:
        result.update(comparison_key=comparison_key, selection_policy="recent_related_then_least_recently_exposed")
        result["scope"] = ("Current conditional reports: at most one recent related head, then never/least recently delivered current heads. "
                           "Only successful complete handoffs advance caller-owned exposure; a revision is a new head. "
                           "Inspect conditions, limitations and cited code/results. Exposure does not mean application, "
                           "causality, promotion, method exhaustion or completion; exact trace restores omitted details.")
    return result


def _retrieval_identity(archive_path: str, comparison_key: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"archive_path": archive_path, "comparison_key": comparison_key,
            **{key: row[key] for key in ("candidate_id", "learning", "evidence")}}


def delivered(packet: dict[str, Any]) -> list[str]:
    """Accept only complete reports and evidence surviving handoff bounding."""
    brief = packet.get("development_brief")
    archive_path = packet.get("archive_path")
    if not isinstance(brief, dict) or not isinstance(archive_path, str) or not pathlib.Path(archive_path).is_absolute():
        return []
    history = brief.get("scoped_learning")
    if (not isinstance(history, dict) or not isinstance(history.get("selection"), list)
            or history.get("comparison_key") != sha256(canonical(brief.get("comparison")))):
        return []
    delivered_ids = []
    for row in history["selection"]:
        try:
            report = row["learning"]
            _body(report)
            evidence = row["evidence"]
            candidate_id = row["candidate_id"]
            if (not _text(candidate_id) or candidate_id != report["candidate_id"]
                    or report["comparison_sha256"] != history["comparison_key"]
                    or not isinstance(evidence, dict) or set(evidence) != set(report["evidence_from"])
                    or candidate_id not in evidence
                    or report["evidence_sha256"] != sha256(canonical(evidence))
                    or row.get("retrieval_sha256") != sha256(canonical(
                        _retrieval_identity(archive_path, history["comparison_key"], row)))):
                continue
            if candidate_id not in delivered_ids:
                delivered_ids.append(candidate_id)
        except (KeyError, TypeError, ValueError):
            continue
    return delivered_ids
