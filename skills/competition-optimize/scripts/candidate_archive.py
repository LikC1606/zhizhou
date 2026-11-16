#!/usr/bin/env python3
"""Record immutable candidate evidence and route decisions for a competition run.

The archive is JSONL so a damaged or interrupted append never requires rewriting
older evidence.  This helper deliberately does not decide the official score:
adapters provide the objective value and validity evidence, while this script
enforces identity, duplicate detection, and an evidence-based explore/exploit
recommendation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
from collections import defaultdict
from typing import Any, Callable

import candidate_profiles
import implementation_reviews
import measurement_plans
import resource_profiles
import scoped_learning
from candidate_evidence import (
    ArchiveFailure, ComparisonEvidence, ComparisonView, DEVELOPMENT_ROLES, DIRECTIONS,
    KINDS, OUTPUT_ONLY_SCOPES, PIPELINE_SCOPES, candidate_index, canonical, directed_score,
    executed_snapshot as _executed_snapshot, implementation_identity, load_json, measurable,
    nonempty_text, observed_snapshot as _observed_snapshot, reject_constant, sha256, unique_object,
    construction_mode, review_opportunities as _review_opportunities, distinct_implementations,
    proposal_identity_checks, validate_construction_targets,
)
from evidence_files import (EvidenceReads, hash_path, verify_artifacts, verify_result,
                            verify_proposal_targets as _verify_proposal_targets)
from result_evidence import ObservationClaims, ResultEvidence, finite_number
from evidence_queries import (BriefQuery, EvidenceSnapshot, evidence_summary, read_case_profile,
                              verify_resource_profile)


STATUSES = {"incumbent", "runner_up", "promising", "rejected", "unresolved"}


def read_records(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ArchiveFailure("invalid_archive", f"Archive is not a file: {path}")
    return parse_records(path.read_bytes(), str(path))


def parse_records(raw: bytes, source: str) -> list[dict[str, Any]]:
    """Replay JSONL bytes without reading candidate result or artifact files."""
    records: list[dict[str, Any]] = []
    if raw and not raw.endswith(b"\n"):
        raise ArchiveFailure("incomplete_event", "Archive ends without a newline; reconcile the interrupted write first")
    seen: set[str] = set()
    candidates: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    closed_plans: set[str] = set()
    result_hashes: set[str] = set()
    closed: set[str] = set()
    filled_slots: set[tuple[str, str, str]] = set()
    for index, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        value = load_json(line, f"{source}:{index}")
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise ArchiveFailure("invalid_archive", f"{source}:{index}: expected schema_version 1 object")
        if value.get("event") not in {"candidate", "decision", "proposal", "proposal_stop",
                                      "measurement_plan", "measurement_decision", "measurement_stop"}:
            raise ArchiveFailure("invalid_archive", f"{source}:{index}: unknown event")
        if value["event"] == "candidate":
            validate_candidate(value)
            slot = measurement_plans.validate_candidate(value, records,
                                                        plans=plans, candidates=candidates,
                                                        filled_slots=filled_slots,
                                                        closed_plans=closed_plans)
            candidate_id = value["candidate_id"]
            if candidate_id in seen or not set(value["parent_ids"]) <= seen:
                raise ArchiveFailure("invalid_archive", f"{source}:{index}: duplicate ID or unknown parent")
            validate_diagnostic_parent(value, candidates)
            if value.get("proposal_id") is not None:
                proposal_id = value["proposal_id"]
                if proposal_id not in proposals or proposal_id in closed:
                    raise ArchiveFailure("invalid_archive", "Candidate names an unknown or closed proposal")
                validate_successor(value, proposals[proposal_id], records,
                                   candidates=candidates, result_hashes=result_hashes)
                closed.add(proposal_id)
            if "learning" in value:
                try:
                    scoped_learning.validate(value["learning"], value, candidates)
                except scoped_learning.LearningFailure as exc:
                    raise ArchiveFailure("invalid_learning", str(exc)) from exc
            seen.add(candidate_id)
            candidates[candidate_id] = value
            if slot is not None:
                filled_slots.add(slot)
            digest = value["result"].get("result_sha256")
            if isinstance(digest, str):
                result_hashes.add(digest)
        elif value["event"] == "proposal":
            validate_proposal(value, records, candidates=candidates)
            proposal_id = value["proposal_id"]
            if proposal_id in proposals:
                raise ArchiveFailure("invalid_archive", "Duplicate proposal ID")
            proposals[proposal_id] = value
        elif value["event"] == "measurement_plan":
            measurement_plans.validate_plan(value, records)
            plans[value["plan_id"]] = value
        elif value["event"] == "measurement_decision":
            measurement_plans.validate_decision(value, records)
            closed_plans.add(value["plan_id"])
        elif value["event"] == "measurement_stop":
            measurement_plans.validate_stop(value, records)
            closed_plans.add(value["plan_id"])
        elif value["event"] == "proposal_stop":
            proposal_id = nonempty_text(value.get("proposal_id"), "proposal_id")
            nonempty_text(value.get("reason"), "reason")
            if proposal_id not in proposals or proposal_id in closed:
                raise ArchiveFailure("invalid_archive", "Stop names an unknown or closed proposal")
            closed.add(proposal_id)
        elif value.get("action") not in {"exploit", "explore", "diagnose"}:
            raise ArchiveFailure("invalid_archive", f"{source}:{index}: invalid route decision")
        records.append(value)
    return records


def validate_candidate(value: dict[str, Any]) -> None:
    for field in ("candidate_id", "fingerprint", "route", "mechanism"):
        nonempty_text(value.get(field), field)
    if value.get("status") not in STATUSES or type(value.get("valid")) is not bool:
        raise ArchiveFailure("invalid_archive", "Candidate status/validity is malformed")
    parents = value.get("parent_ids")
    if (not isinstance(parents, list) or any(not isinstance(p, str) or not p for p in parents)
            or len(set(parents)) != len(parents)):
        raise ArchiveFailure("invalid_archive", "Candidate parents are malformed")
    for field in ("artifacts", "artifact_paths", "objective", "comparison", "result", "cost"):
        if not isinstance(value.get(field), dict):
            raise ArchiveFailure("invalid_archive", f"Candidate {field} must be an object")
    if (not value["artifacts"] or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
                                      for item in value["artifacts"].values())
            or value["fingerprint"] != sha256(canonical(value["artifacts"]))):
        raise ArchiveFailure("invalid_archive", "Artifact hashes/fingerprint are malformed or inconsistent")
    if value.get("role") not in DEVELOPMENT_ROLES | {"confirmation"}:
        raise ArchiveFailure("invalid_archive", "Candidate role is malformed")
    if value["role"] == "diagnostic":
        if value["status"] in {"incumbent", "runner_up"}:
            raise ArchiveFailure("invalid_candidate", "Diagnostic evidence cannot be an incumbent or runner-up")
        if (value["comparison"].get("stage") in {"confirmation", "test", "holdout"}
                or value["result"].get("stage") in {"confirmation", "test", "holdout"}):
            raise ArchiveFailure("result_override", "Confirmation/test evidence cannot become diagnostic evidence")
    if value["objective"].get("value") is not None:
        finite_number(value["objective"]["value"], "objective.value")
        if value["objective"].get("direction") not in DIRECTIONS:
            raise ArchiveFailure("invalid_archive", "A scalar score requires its direction")
    for key, field in [("direction", "direction"), ("objective_kind", "kind"), ("objective_name", "name")]:
        if value["comparison"].get(key) != value["objective"].get(field):
            raise ArchiveFailure("invalid_archive", "Objective metadata differs from its comparison identity")
    if "implementation" in value and value["implementation"] != implementation_identity(value):
        raise ArchiveFailure("invalid_archive", "Implementation identity differs from its artifact scope/hashes")
    if "construction_mode" in value:
        construction_mode(value)
        if not value.get("proposal_id"):
            raise ArchiveFailure("invalid_archive", "Construction mode requires its prospective proposal")
    if "learning_from" in value and not value.get("proposal_id"):
        raise ArchiveFailure("invalid_learning", "Learning use requires its prospective proposal")
    if "implementation_review" in value:
        try:
            implementation_reviews.validate(value["implementation_review"], value, implementation_identity(value))
        except implementation_reviews.ReviewFailure as exc:
            raise ArchiveFailure("invalid_implementation_review", str(exc)) from exc
    if "case_profile" in value["result"]:
        try:
            candidate_profiles.validate_descriptor(value["result"]["case_profile"])
        except candidate_profiles.ProfileFailure as exc:
            raise ArchiveFailure("invalid_case_profile", str(exc)) from exc
    if "resource_profile" in value["result"]:
        try:
            resource_profiles.describe(value["result"]["resource_profile"])
        except resource_profiles.ResourceFailure as exc:
            raise ArchiveFailure("invalid_resource_profile", str(exc)) from exc


def result_metadata(path: pathlib.Path | None, *, include_case_profile: bool = True,
                    include_resource_profile: bool = True) -> dict[str, Any]:
    """Compatibility facade for the shared result-evidence Interface."""
    return ResultEvidence.read(path, include_case_profile=include_case_profile,
                               include_resource_profile=include_resource_profile).metadata


def make_fingerprint(source: pathlib.Path | None, configuration: pathlib.Path | None,
                     result: dict[str, Any]) -> tuple[str, dict[str, str]]:
    artifacts: dict[str, str] = {}
    if source is not None:
        source = source.expanduser().resolve(strict=True)
        artifacts["source"] = hash_path(source)
        if source.is_file() and result.get("candidate_hash") and artifacts["source"] != result["candidate_hash"]:
            raise ArchiveFailure("source_result_mismatch", "Source bytes differ from the evaluated candidate_hash")
    if configuration is not None:
        artifacts["configuration"] = hash_path(configuration)
    if result.get("candidate_hash") and "source" not in artifacts:
        artifacts["source"] = nonempty_text(result["candidate_hash"], "result.candidate_hash")
    if not artifacts:
        raise ArchiveFailure("invalid_candidate", "Provide --source, --configuration, or a result with candidate_hash")
    return sha256(canonical(artifacts)), artifacts


def duplicate_matches(old: list[dict[str, Any]], fingerprint: str) -> list[str]:
    return [entry["candidate_id"] for entry in old
            if entry["event"] == "candidate" and entry["fingerprint"] == fingerprint]


def reuse_prefix(matches: list[str]) -> dict[str, Any]:
    """Summarize an earlier matching prefix without copying it into every event."""
    return {"count": len(matches), "first": matches[0] if matches else None,
            "previous": matches[-1] if matches else None}


def changed_implementation(child: dict[str, Any], parent: dict[str, Any]) -> bool:
    child_identity, parent_identity = implementation_identity(child), implementation_identity(parent)
    if {child_identity["scope"], parent_identity["scope"]} & OUTPUT_ONLY_SCOPES:
        return False
    return child_identity["fingerprint"] != parent_identity["fingerprint"]


def check_candidate(args: argparse.Namespace) -> dict[str, Any]:
    old = read_records(args.archive.expanduser().resolve())
    fingerprint, artifacts = make_fingerprint(args.source, args.configuration, {})
    # Training can be checked before prediction artifacts exist: compare exactly
    # the supplied artifact hashes, without pretending to check absent files.
    matches = [entry["candidate_id"] for entry in old if entry["event"] == "candidate"
               and all(entry["artifacts"].get(key) == value for key, value in artifacts.items())]
    if args.reuse_reason is not None:
        nonempty_text(args.reuse_reason, "reuse_reason")
    if matches and not args.reuse_reason:
        raise ArchiveFailure("duplicate_fingerprint", f"Same artifacts as {matches}; explain a necessary re-evaluation or change the implementation")
    return {"schema_version": 1, "status": "ready", "fingerprint": fingerprint,
            "artifacts": artifacts, "matches": matches, "reuse_reason": args.reuse_reason,
            "checked_scope": "Provided artifact hashes only; absent artifacts are not checked",
            "unchecked": ["semantic_near_duplicates", "candidate_validity", "budget"]}


def append_record(path: pathlib.Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")
    # Use one writer per run. This is append-only, not a concurrent database.
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def validate_diagnostic_parent(value: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> None:
    if value["role"] != "diagnostic":
        return
    parents = value["parent_ids"]
    if not parents or candidates.get(parents[0], {}).get("role") != "development":
        raise ArchiveFailure("invalid_diagnostic_parent", "A diagnostic requires its ordinary development control as first parent")
    if any(candidates.get(candidate_id, {}).get("role") not in DEVELOPMENT_ROLES for candidate_id in parents):
        raise ArchiveFailure("confirmation_feedback", "Confirmation evidence cannot supply diagnostic parents")


def validate_proposal(value: dict[str, Any], records: list[dict[str, Any]], *,
                      candidates: dict[str, dict[str, Any]] | None = None) -> None:
    for field in ("proposal_id", "route", "basis", "change", "expected_observation", "validation", "stop_condition"):
        nonempty_text(value.get(field), field)
    if candidates is None:
        candidates = candidate_index(records)
    for field in ("parent_ids", "feedback_from"):
        ids = value.get(field)
        if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in candidates for i in ids)
                or len(set(ids)) != len(ids)):
            raise ArchiveFailure("invalid_proposal", f"{field} must name distinct archived candidates")
        if any(candidates[i]["role"] not in DEVELOPMENT_ROLES for i in ids):
            raise ArchiveFailure("confirmation_feedback", "Confirmation evidence cannot supply search parents or feedback")
    try:
        scoped_learning.validate_references(value, candidates)
    except scoped_learning.LearningFailure as exc:
        raise ArchiveFailure("invalid_learning", str(exc)) from exc
    validate_construction_targets(value)
    for target in value["code_targets"]:
        if (not isinstance(target, dict) or not isinstance(target.get("path"), str)
                or not pathlib.Path(target["path"]).is_absolute()
                or not isinstance(target.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", target["sha256"])):
            raise ArchiveFailure("invalid_proposal", "Code targets need absolute paths and SHA-256 hashes")


def propose_candidate(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive.expanduser().resolve())
    raw = args.proposal.expanduser().resolve(strict=True).read_bytes()
    proposal = load_json(raw, str(args.proposal))
    if not isinstance(proposal, dict):
        raise ArchiveFailure("invalid_proposal", "Proposal input must be an object")
    value = {key: proposal.get(key) for key in ("proposal_id", "parent_ids", "feedback_from", "route", "basis",
                                               "change", "expected_observation", "validation", "stop_condition")}
    if "construction_mode" in proposal:
        value["construction_mode"] = proposal["construction_mode"]
    if "learning_from" in proposal:
        value["learning_from"] = proposal["learning_from"]
    targets = proposal.get("code_targets")
    validate_construction_targets({**value, "code_targets": targets})
    if any(not isinstance(target, str) for target in targets):
        raise ArchiveFailure("invalid_proposal", "code_targets must contain parent file paths")
    value.update(schema_version=1, event="proposal", input_sha256=sha256(raw),
                 code_targets=[{"path": str(pathlib.Path(target).expanduser().resolve(strict=True)),
                                "sha256": hash_path(pathlib.Path(target))} for target in targets])
    validate_proposal(value, records)
    if any(entry["event"] == "proposal" and entry["proposal_id"] == value["proposal_id"] for entry in records):
        raise ArchiveFailure("duplicate_proposal_id", "Proposal ID already exists")
    value["recorded_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    candidates = candidate_index(records)
    for candidate_id in value.get("learning_from", []):
        scoped_learning.verify_evidence(candidates[candidate_id]["learning"], candidates)
    parent_roots = []
    for candidate_id in set(value["parent_ids"] + value["feedback_from"]):
        entry = candidates[candidate_id]
        verify_result(entry)
        if candidate_id in value["parent_ids"]:
            roots = verify_artifacts(entry)
            identity = implementation_identity(entry)
            if identity["scope"] in OUTPUT_ONLY_SCOPES:
                raise ArchiveFailure("missing_implementation_snapshot", "Reconcile the executed code/recipe before proposing a code change")
            if identity["scope"] in PIPELINE_SCOPES:
                roots = [pathlib.Path(entry["artifact_paths"]["configuration"]).resolve(strict=True)]
            parent_roots.extend(roots)
    for target in value["code_targets"]:
        path = pathlib.Path(target["path"])
        if not path.is_file() or not any(path == root or root.is_dir() and path.is_relative_to(root) for root in parent_roots):
            raise ArchiveFailure("unbound_code_target", "Code target must be a file in a verified parent artifact snapshot")
    append_record(args.archive, value)
    return value


def record_measurement_plan(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive.expanduser().resolve())
    path = args.plan.expanduser().resolve(strict=True)
    raw = path.read_bytes()
    authored = load_json(raw, str(path))
    if not isinstance(authored, dict):
        raise ArchiveFailure("invalid_measurement_plan", "Plan input must be an object")
    fields = ("plan_id", "conflict_signature", "comparison", "leader_candidate",
              "challenger_candidate", "witness_candidate", "runs", "decision_rule")
    if set(authored) != set(fields):
        raise ArchiveFailure("invalid_measurement_plan", "Plan must contain exactly the declared measurement fields")
    plan = {key: authored[key] for key in fields}
    plan.update(schema_version=1, event="measurement_plan", input_sha256=sha256(raw),
                recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
    measurement_plans.validate_plan(plan, records)
    candidates = candidate_index(records)
    for candidate_id in (plan["leader_candidate"], plan["challenger_candidate"], plan["witness_candidate"]):
        verify_result(candidates[candidate_id])
        verify_artifacts(candidates[candidate_id])
    append_record(args.archive, plan)
    return plan


def record_measurement_decision(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive.expanduser().resolve())
    path = args.decision.expanduser().resolve(strict=True)
    raw = path.read_bytes()
    authored = load_json(raw, str(path))
    fields = ("plan_id", "conclusion", "reason", "next_action")
    if not isinstance(authored, dict) or set(authored) != set(fields):
        raise ArchiveFailure("invalid_measurement_decision", "Decision needs plan_id, conclusion, reason and next_action")
    plan = next((entry for entry in records if entry["event"] == "measurement_plan"
                 and entry["plan_id"] == authored["plan_id"]), None)
    if plan is None:
        raise ArchiveFailure("unknown_measurement_plan", "Decision requires an earlier measurement plan")
    view = measurement_plans.status(plan, records)
    if view["stop"] is not None:
        raise ArchiveFailure("closed_measurement_plan", "The measurement plan was stopped unresolved")
    if not view["complete"]:
        raise ArchiveFailure("incomplete_measurement_plan", "Every frozen paired run must be validly measured before a decision")
    index = candidate_index(records)
    for run in view["runs"]:
        for name in ("leader", "challenger"):
            entry = index[run[name]["candidate_id"]]
            verify_result(entry)
            verify_artifacts(entry)
    decision = {key: authored[key] for key in fields}
    decision.update(schema_version=1, event="measurement_decision", input_sha256=sha256(raw),
                    evidence_sha256=measurement_plans.evidence_sha256(view),
                    recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
    measurement_plans.validate_decision(decision, records)
    append_record(args.archive, decision)
    return decision


def record_measurement_stop(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive.expanduser().resolve())
    plan = next((entry for entry in records if entry["event"] == "measurement_plan"
                 and entry["plan_id"] == args.plan_id), None)
    if plan is None:
        raise ArchiveFailure("unknown_measurement_plan", "Stop requires an earlier measurement plan")
    view = measurement_plans.status(plan, records)
    stop = {"schema_version": 1, "event": "measurement_stop", "plan_id": args.plan_id,
            "reason": args.reason, "next_action": args.next_action,
            "evidence_sha256": measurement_plans.stop_evidence_sha256(view),
            "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    measurement_plans.validate_stop(stop, records)
    measurement_plans.verify_stop_evidence(view, records, reads=EvidenceReads())
    append_record(args.archive, stop)
    return stop


def validate_successor(candidate: dict[str, Any], proposal: dict[str, Any], records: list[dict[str, Any]], *,
                       candidates: dict[str, dict[str, Any]] | None = None,
                       result_hashes: set[str] | None = None) -> None:
    if candidate.get("learning_from") != proposal.get("learning_from"):
        raise ArchiveFailure("proposal_mismatch", "Successor learning references must match its prospective proposal")
    if (candidate.get("construction_mode") != proposal.get("construction_mode")
            or construction_mode(candidate) != construction_mode(proposal)):
        raise ArchiveFailure("proposal_mismatch", "Successor construction mode must match its proposal")
    if (set(candidate["parent_ids"]) != set(proposal["parent_ids"]) or candidate["route"] != proposal["route"]
            or candidate["role"] not in DEVELOPMENT_ROLES):
        raise ArchiveFailure("proposal_mismatch", "Successor must use the proposal's parents and route in development or diagnostic work")
    parents = candidate_index(records) if candidates is None else candidates
    if any(candidate["fingerprint"] == parents[i]["fingerprint"] for i in proposal["parent_ids"]):
        raise ArchiveFailure("unchanged_successor", "An unchanged measurement cannot fulfill an implementation proposal")
    # Old events retain their original acceptance scope. New events distinguish
    # a prediction pipeline from algorithm source plus ordinary configuration.
    configured = [parents[i] for i in proposal["parent_ids"]
                  if implementation_identity(parents[i])["scope"] in PIPELINE_SCOPES or
                  "implementation" not in candidate and "configuration" in parents[i]["artifacts"]]
    unchanged = any if "implementation" in candidate else all
    if configured and ("configuration" not in candidate["artifacts"] or
                       unchanged(candidate["artifacts"]["configuration"] == parent["artifacts"]["configuration"] for parent in configured)):
        raise ArchiveFailure("unchanged_pipeline", "An implementation proposal requires changed code/recipe, not only new predictions")
    nonempty_text(candidate.get("feedback"), "successor.feedback")
    if candidate.get("prediction_status") not in {"supported", "contradicted", "unresolved"}:
        raise ArchiveFailure("missing_prediction_status", "Record whether the proposed observation was supported, contradicted or unresolved")
    result = candidate["result"]
    if not result.get("result_path") or result.get("execution_status") not in {"success", "failed"}:
        raise ArchiveFailure("missing_execution_evidence", "A proposal successor requires a completed adapter result")
    if "implementation" in candidate:
        identity = implementation_identity(candidate)
        if (construction_mode(proposal) == "independent"
                and (identity["scope"] in OUTPUT_ONLY_SCOPES
                     or not set(identity["artifacts"]) <= candidate["artifact_paths"].keys())):
            raise ArchiveFailure("missing_implementation_snapshot", "Independent construction requires its executed source/recipe snapshot, not only outputs or a claimed hash")
        if any(implementation_identity(parents[i])["scope"] in OUTPUT_ONLY_SCOPES for i in proposal["parent_ids"]):
            raise ArchiveFailure("missing_implementation_snapshot", "Output-only parents do not identify the executed code/recipe")
        if configured and implementation_identity(candidate)["scope"] not in PIPELINE_SCOPES:
            raise ArchiveFailure("missing_implementation_snapshot", "Keep the changed pipeline snapshot with its evaluated outputs")
    digest = result["result_sha256"]
    # Replay owns an append-only index for this read. Preserve legacy equality
    # semantics for unusual non-string values rather than changing acceptance.
    reused = (digest in result_hashes if result_hashes is not None and isinstance(digest, str)
              else any(entry["result"].get("result_sha256") == digest for entry in parents.values()))
    if reused:
        raise ArchiveFailure("reused_execution_evidence", "An old result cannot complete a new implementation proposal")


def stop_proposal(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive)
    proposal_id = nonempty_text(args.proposal_id, "proposal_id")
    if not any(entry["event"] == "proposal" and entry["proposal_id"] == proposal_id for entry in records):
        raise ArchiveFailure("unknown_proposal", "No such proposal in this archive")
    if any(entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id") == proposal_id for entry in records):
        raise ArchiveFailure("closed_proposal", "Proposal already has an outcome")
    value = {"schema_version": 1, "event": "proposal_stop", "proposal_id": proposal_id,
             "reason": nonempty_text(args.reason, "reason"), "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    append_record(args.archive, value)
    return value


def iteration_trace(records: list[dict[str, Any]], recent: int | None = None, *,
                    proposal_id: str | None = None, reads: EvidenceReads | None = None) -> list[dict[str, Any]]:
    return EvidenceSnapshot._from_views(None, records, reads=reads).trace(proposal_id=proposal_id, recent=recent)


def optimization_brief(args: argparse.Namespace,
                       records: list[dict[str, Any]] | None = None, *,
                       rankable: Callable[[dict[str, Any]], bool] | None = None,
                       frontier_seen: dict[str, int] | None = None,
                       pending_seen: dict[str, int] | None = None,
                       learning_seen: dict[str, int] | None = None,
                       reads: EvidenceReads | None = None,
                       evidence: ComparisonEvidence | None = None) -> dict[str, Any]:
    """Compatibility adapter; new callers query an EvidenceSnapshot directly."""
    query = BriefQuery(anchor=args.anchor, recent=args.recent, routes=args.routes,
                       frontier=getattr(args, "frontier", 2), frontier_seen=frontier_seen,
                       pending_seen=pending_seen, learning_seen=learning_seen)
    query.validate()
    if records is None:
        records = read_records(args.archive.expanduser().resolve())
    return EvidenceSnapshot._from_views(args.archive, records, rankable=rankable,
                                        reads=reads, comparisons=evidence).brief(query)


def trace_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.recent < 1:
        raise ArchiveFailure("invalid_config", "recent must be positive")
    records = read_records(args.archive)
    proposals = [entry for entry in records if entry["event"] == "proposal"]
    closed = {entry["proposal_id"] for entry in records
              if entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id")}
    requested = getattr(args, "proposal_id", None)
    trace = iteration_trace(records, None if args.all or requested is not None else args.recent,
                            proposal_id=requested)
    return {"schema_version": 1, "total_iterations": len(proposals),
            "omitted_iterations": len(proposals) - len(trace),
            "pending_proposals": [entry["proposal_id"] for entry in proposals if entry["proposal_id"] not in closed
                                  and (requested is None or entry["proposal_id"] == requested)],
            "iterations": trace,
            "scope": "Linked code/result identities and adapter-declared checks; mechanism causality and promotion are not certified"}


def record_candidate(args: argparse.Namespace) -> dict[str, Any]:
    archive = args.archive.expanduser().resolve()
    old = read_records(archive)
    candidate_id = nonempty_text(args.candidate_id, "candidate_id")
    route = nonempty_text(args.route, "route")
    mechanism = nonempty_text(args.mechanism, "mechanism")
    status = args.status
    if args.reuse_reason is not None:
        nonempty_text(args.reuse_reason, "reuse_reason")
    evidence = ResultEvidence.read(args.result)
    result = evidence.metadata
    fingerprint, artifacts = make_fingerprint(args.source, args.configuration, result)
    for previous in old:
        if previous.get("event") != "candidate":
            continue
        if previous.get("candidate_id") == candidate_id:
            raise ArchiveFailure("duplicate_candidate_id", f"Candidate ID already exists: {candidate_id}")
        if previous.get("fingerprint") == fingerprint and not args.reuse_reason:
            raise ArchiveFailure("duplicate_fingerprint",
                                 f"Candidate has the same source/configuration fingerprint as {previous.get('candidate_id')}")
    parents = [nonempty_text(parent, "parent") for parent in args.parent]
    if len(set(parents)) != len(parents):
        raise ArchiveFailure("invalid_candidate", "Duplicate parent IDs")
    known_ids = {entry["candidate_id"] for entry in old if entry["event"] == "candidate"}
    if not set(parents) <= known_ids:
        raise ArchiveFailure("unknown_parent", "Record or reconcile the parent candidates first")
    observation = evidence.resolve(ObservationClaims(
        objective_value=args.objective_value, objective_direction=args.objective_direction,
        objective_kind=args.objective_kind, objective_name=args.objective_name,
        evaluator_hash=args.evaluator_hash, workload_hash=args.workload_hash,
        score_model_hash=args.score_model_hash, stage=args.stage, valid=args.valid, role=args.role),
        candidate_status=status)
    objective, comparison = observation.objective, observation.comparison
    validity, role = observation.valid, observation.role
    cost: Any = {"evaluation_elapsed_seconds": result["elapsed_seconds"]} if "elapsed_seconds" in result else {}
    if args.cost is not None:
        cost = load_json(args.cost.encode("utf-8"), "--cost")
        if not isinstance(cost, dict):
            raise ArchiveFailure("invalid_candidate", "--cost must be a JSON object")
    record: dict[str, Any] = {
        "schema_version": 1,
        "event": "candidate",
        "recorded_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "candidate_id": candidate_id,
        "parent_ids": parents,
        "fingerprint": fingerprint,
        "artifacts": artifacts,
        "artifact_paths": {key: str(path.expanduser().resolve()) for key, path in
                           [("source", args.source), ("configuration", args.configuration)] if path is not None},
        "route": route,
        "mechanism": mechanism,
        "status": status,
        "valid": bool(validity),
        "role": role,
        "comparison": comparison,
        "objective": objective,
        "cost": cost,
        "feedback": args.feedback or None,
        "failure_mechanism": args.failure or None,
        "reuse_reason": args.reuse_reason,
        "reused_from": duplicate_matches(old, fingerprint),
        "result": result,
    }
    record["implementation"] = implementation_identity(record)
    record["reused_implementation_from"] = [entry["candidate_id"] for entry in old if entry["event"] == "candidate"
                                            and entry["role"] in DEVELOPMENT_ROLES
                                            and implementation_identity(entry)["fingerprint"] == record["implementation"]["fingerprint"]]
    record["reuse_links"] = {"format": "candidate-prefix-v1",
                            "artifacts": reuse_prefix(record["reused_from"]),
                            "implementation": reuse_prefix(record["reused_implementation_from"])}
    if args.proposal_id is not None:
        proposal = next((entry for entry in old if entry["event"] == "proposal" and entry["proposal_id"] == args.proposal_id), None)
        if proposal is None:
            raise ArchiveFailure("unknown_proposal", "Record the implementation proposal before its successor")
        if any(entry["event"] in {"candidate", "proposal_stop"} and entry.get("proposal_id") == args.proposal_id for entry in old):
            raise ArchiveFailure("closed_proposal", "Proposal already has an outcome")
        record["proposal_id"] = args.proposal_id
        if "construction_mode" in proposal:
            record["construction_mode"] = proposal["construction_mode"]
        if "learning_from" in proposal:
            record["learning_from"] = proposal["learning_from"]
        record["prediction_status"] = args.prediction_status
        validate_successor(record, proposal, old)
    if getattr(args, "implementation_review", None) is not None:
        raw_review = args.implementation_review.expanduser().resolve(strict=True).read_bytes()
        review = load_json(raw_review, str(args.implementation_review))
        try:
            record["implementation_review"] = implementation_reviews.normalize(
                review, raw_review, record, implementation_identity(record), hash_path)
        except implementation_reviews.ReviewFailure as exc:
            raise ArchiveFailure("invalid_implementation_review", str(exc)) from exc
    if getattr(args, "learning", None) is not None:
        raw_learning = args.learning.expanduser().resolve(strict=True).read_bytes()
        try:
            record["learning"] = scoped_learning.normalize(
                load_json(raw_learning, str(args.learning)), raw_learning, record,
                candidate_index(old))
        except scoped_learning.LearningFailure as exc:
            raise ArchiveFailure("invalid_learning", str(exc)) from exc
    validate_candidate(record)
    measurement_plans.validate_candidate(record, old)
    validate_diagnostic_parent(record, candidate_index(old))
    # Repeated measurements can share one implementation for a long campaign.
    # Persisting every earlier ID in each event makes that history quadratic.
    # Keep old events intact; these optional presentation lists are derived from
    # identities for briefs. The Python/CLI return retains its complete lists.
    append_record(archive, {key: value for key, value in record.items()
                            if key not in {"reused_from", "reused_implementation_from"}})
    return record


def route_decision(args: argparse.Namespace) -> dict[str, Any]:
    records = [record for record in read_records(args.archive.expanduser().resolve())
               if record.get("event") == "candidate"]
    if not records:
        raise ArchiveFailure("empty_archive", "Record a baseline before requesting a route decision")
    development = [entry for entry in records if entry["role"] == "development"]
    if not development:
        raise ArchiveFailure("no_development_evidence", "Confirmation evidence cannot guide new optimization")
    current_route = args.current_route or development[-1]["route"]
    current_route = nonempty_text(current_route, "current_route")
    route_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in development:
        route_entries[entry.get("route", "unknown")].append(entry)
    current = [entry for entry in route_entries.get(current_route, []) if entry["role"] == "development"]
    if not current:
        raise ArchiveFailure("unknown_route", f"No development candidates for route {current_route!r}")
    latest = current[-1]
    context = latest["comparison"]
    direction = latest["objective"].get("direction")
    if args.objective_direction and direction != args.objective_direction:
        raise ArchiveFailure("result_override", "Requested direction differs from the selected comparison")
    # Compare only complete, valid measurements in the latest evaluation regime.
    # A rebound below the route's best is not new progress; repeats do not add
    # distinct implementation evidence to the stagnation window.
    representatives = distinct_implementations([entry for entry in development
                                                 if measurable(entry) and entry["comparison"] == context
                                                 and implementation_identity(entry)["scope"] not in OUTPUT_ONLY_SCOPES])
    measured = [entry for entry in representatives if entry["route"] == current_route]
    recent = measured[-args.recent:]
    progress: set[str] = set()
    best_value: float | None = None
    for entry in measured:
        score = entry["objective"]["value"] * (-1 if direction == "minimize" else 1)
        if best_value is not None and score > best_value + args.tie_epsilon:
            progress.add(entry["candidate_id"])
        best_value = score if best_value is None else max(best_value, score)
    recent_progress = [entry["candidate_id"] for entry in recent if entry["candidate_id"] in progress]
    opportunities, _ = _review_opportunities(
        [entry for entry in development if entry["comparison"] == context],
        candidate_index(records), include_manual=True)
    # Keep this command's recent-route presentation window while sharing the
    # same lineage/observation closure rules used by brief and the campaign.
    current_ids = {entry["candidate_id"] for entry in current[-args.recent:]}
    unresolved = [opportunity["feedback_candidate"] for opportunity in opportunities.values()
                  if opportunity["feedback_candidate"]["candidate_id"] in current_ids]
    for entry in measured:
        verify_result(entry)
    if latest["valid"] is False:
        action = "diagnose"
        reason = "Latest candidate is invalid or incomplete; diagnose implementation/evaluation before judging its method."
    elif not measurable(latest):
        action = "diagnose"
        reason = "Comparable development evidence is insufficient; inspect code/history or gather the smallest decision-changing diagnostic."
    elif implementation_identity(latest)["scope"] in OUTPUT_ONLY_SCOPES:
        action = "diagnose"
        reason = "Output scores are available, but the executed pipeline snapshot is missing; reconcile it before judging distinct implementation progress."
    elif recent_progress or unresolved:
        action = "exploit"
        reason = "Route has a new historical best or a feedback-supported unresolved opportunity; propose a specific successor from its code and evidence."
    elif len(recent) < args.min_stagnant:
        action = "diagnose"
        reason = "Too few distinct comparable implementations to judge stagnation; inspect code/history for an actionable mechanism."
    else:
        action = "explore"
        reason = (f"The last {len(recent)} valid comparable candidates on {current_route!r} produced no "
                  "new historical best and have no feedback-supported unresolved opportunity; consider a materially different mechanism.")
    alternatives = []
    for route, entries in sorted(route_entries.items(), key=lambda item: (len(item[1]), item[0])):
        eligible = [entry for entry in entries if entry["role"] == "development" and entry["comparison"] == context]
        if route != current_route and eligible:
            alternatives.append({"route": route, "candidates": len(eligible),
                                 "latest_candidate": eligible[-1]["candidate_id"],
                                 "latest_status": eligible[-1]["status"]})
    decision = {
        "schema_version": 1,
        "event": "decision",
        "action": action,
        "current_route": current_route,
        "objective_direction": direction,
        "recent_valid_candidates": len(recent),
        "progress_candidates": recent_progress,
        "evidence_candidates": [entry["candidate_id"] for entry in recent],
        "comparison": context,
        "unresolved_candidates": [entry["candidate_id"] for entry in unresolved],
        "reason": reason,
        "alternative_routes": alternatives,
        "policy": {"recent": args.recent, "min_stagnant": args.min_stagnant, "tie_epsilon": args.tie_epsilon},
        "scope": "Advisory route review only; proxy progress is provisional. No promotion, budget or mechanism selection is automated.",
    }
    if args.output is not None:
        output = args.output.expanduser().resolve()
        if output.exists():
            raise ArchiveFailure("output_exists", f"Refusing to overwrite decision output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(decision, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        decision["output_file"] = str(output)
    if args.append:
        append_record(args.archive.expanduser().resolve(), decision)
    return decision


def summarize(args: argparse.Namespace) -> dict[str, Any]:
    records = read_records(args.archive.expanduser().resolve())
    candidates = [record for record in records if record.get("event") == "candidate"]
    routes: dict[str, dict[str, Any]] = {}
    for entry in candidates:
        if entry["role"] != "development":
            continue
        route = entry.get("route", "unknown")
        summary = routes.setdefault(route, {"candidates": 0, "statuses": defaultdict(int), "latest": None})
        summary["candidates"] += 1
        summary["statuses"][entry.get("status", "unknown")] += 1
        summary["latest"] = entry["candidate_id"]
    return {"schema_version": 1, "candidate_count": len(candidates),
            "decision_count": sum(entry["event"] == "decision" for entry in records),
            "proposal_count": sum(entry["event"] == "proposal" for entry in records),
            "recent_candidates": [{key: entry[key] for key in ("candidate_id", "parent_ids", "fingerprint", "artifact_paths", "route", "status", "valid", "role", "objective", "comparison", "cost", "result", "feedback", "failure_mechanism")}
                                  for entry in candidates[-args.recent:]],
            "routes": {route: {"candidates": info["candidates"],
                               "statuses": dict(info["statuses"]), "latest": info["latest"]}
                       for route, info in sorted(routes.items())}}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check for exact artifact duplicates before evaluation")
    check.add_argument("--archive", type=pathlib.Path, required=True)
    check.add_argument("--source", type=pathlib.Path)
    check.add_argument("--configuration", type=pathlib.Path)
    check.add_argument("--reuse-reason", help="why an unchanged candidate needs another measurement")
    propose = sub.add_parser("propose", help="bind an agent-authored implementation proposal to code and feedback")
    propose.add_argument("--archive", type=pathlib.Path, required=True)
    propose.add_argument("--proposal", type=pathlib.Path, required=True)
    stop = sub.add_parser("stop", help="record why an unexecuted proposal was stopped")
    stop.add_argument("--archive", type=pathlib.Path, required=True)
    stop.add_argument("--proposal-id", required=True)
    stop.add_argument("--reason", required=True)
    measure = sub.add_parser("measure-plan", help="freeze a paired conflict measurement before its runs")
    measure.add_argument("--archive", type=pathlib.Path, required=True)
    measure.add_argument("--plan", type=pathlib.Path, required=True)
    measure_status = sub.add_parser("measure-status", help="read the frozen plan and its actual paired results")
    measure_status.add_argument("--archive", type=pathlib.Path, required=True)
    measure_status.add_argument("--plan-id", required=True)
    measure_decide = sub.add_parser("measure-decide", help="record the task-rule interpretation after all paired runs")
    measure_decide.add_argument("--archive", type=pathlib.Path, required=True)
    measure_decide.add_argument("--decision", type=pathlib.Path, required=True)
    measure_stop = sub.add_parser("measure-stop", help="stop a frozen plan unresolved and retain all attempts")
    measure_stop.add_argument("--archive", type=pathlib.Path, required=True)
    measure_stop.add_argument("--plan-id", required=True)
    measure_stop.add_argument("--reason", required=True)
    measure_stop.add_argument("--next-action", required=True)
    trace = sub.add_parser("trace", help="show proposals and their actual evaluation outcomes")
    trace.add_argument("--archive", type=pathlib.Path, required=True)
    trace.add_argument("--recent", type=int, default=8, help="recent proposals to include; all pending IDs remain visible")
    trace.add_argument("--all", action="store_true", help="include every iteration when a complete audit is needed")
    trace.add_argument("--proposal-id", help="retrieve one exact proposal and its current outcome, including complete code targets")
    brief = sub.add_parser("brief", help="retrieve matched best versions, recent failures, code paths and pending proposals")
    brief.add_argument("--archive", type=pathlib.Path, required=True)
    brief.add_argument("--anchor", help="development candidate defining the comparison; defaults to the latest development record")
    brief.add_argument("--routes", type=int, default=4, help="routes to show, including the active route")
    brief.add_argument("--recent", type=int, default=4, help="recent distinct active-route candidates and matching pending details")
    brief.add_argument("--frontier", type=int, default=2, help="open implementation opportunities to retrieve separately from elite routes; 0 disables retrieval, not experiments")
    record = sub.add_parser("record", help="append one candidate evidence record")
    record.add_argument("--archive", type=pathlib.Path, required=True)
    record.add_argument("--candidate-id", required=True)
    record.add_argument("--proposal-id", help="implementation proposal this evaluated successor fulfills")
    record.add_argument("--prediction-status", choices=["supported", "contradicted", "unresolved"])
    record.add_argument("--implementation-review", type=pathlib.Path,
                        help="source-bound agent assessment of which proposed mechanism actually reached this successor")
    record.add_argument("--learning", type=pathlib.Path,
                        help="conditional agent conclusion with measured evidence and an explicit prior revision")
    record.add_argument("--parent", action="append", default=[])
    record.add_argument("--source", type=pathlib.Path)
    record.add_argument("--configuration", type=pathlib.Path)
    record.add_argument("--result", type=pathlib.Path)
    record.add_argument("--evaluator-hash")
    record.add_argument("--workload-hash")
    record.add_argument("--score-model-hash")
    record.add_argument("--stage")
    record.add_argument("--role", choices=["development", "diagnostic", "confirmation"])
    record.add_argument("--reuse-reason", help="required for recording unchanged artifacts under a new measurement")
    record.add_argument("--route", required=True)
    record.add_argument("--mechanism", required=True)
    record.add_argument("--status", choices=sorted(STATUSES), required=True)
    validity = record.add_mutually_exclusive_group()
    validity.add_argument("--valid", dest="valid", action="store_true")
    validity.add_argument("--invalid", dest="valid", action="store_false")
    record.set_defaults(valid=None)
    record.add_argument("--objective-value", type=float)
    record.add_argument("--objective-direction", choices=sorted(DIRECTIONS))
    record.add_argument("--objective-kind", choices=sorted(KINDS))
    record.add_argument("--objective-name")
    record.add_argument("--cost", help="JSON object with measured resource costs")
    record.add_argument("--feedback")
    record.add_argument("--failure")
    decide = sub.add_parser("decide", help="recommend exploit or explore from archive evidence")
    decide.add_argument("--archive", type=pathlib.Path, required=True)
    decide.add_argument("--current-route")
    decide.add_argument("--objective-direction", choices=sorted(DIRECTIONS))
    decide.add_argument("--recent", type=int, default=4)
    decide.add_argument("--min-stagnant", type=int, default=2)
    decide.add_argument("--tie-epsilon", type=float, default=1e-12)
    decide.add_argument("--output", type=pathlib.Path)
    decide.add_argument("--append", action="store_true", help="append the decision event to the archive")
    show = sub.add_parser("summary", help="print a compact route/status summary")
    show.add_argument("--archive", type=pathlib.Path, required=True)
    show.add_argument("--recent", type=int, default=8, help="number of compact candidate records to show")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "check":
            result = check_candidate(args)
        elif args.command == "record":
            result = record_candidate(args)
        elif args.command == "propose":
            result = {"schema_version": 1, "status": "pending", "proposal": propose_candidate(args)}
        elif args.command == "measure-plan":
            result = {"schema_version": 1, "status": "planned", "plan": record_measurement_plan(args)}
        elif args.command == "measure-decide":
            result = {"schema_version": 1, "status": "decided", "decision": record_measurement_decision(args)}
        elif args.command == "measure-stop":
            result = {"schema_version": 1, "status": "stopped_unresolved", "stop": record_measurement_stop(args)}
        elif args.command == "measure-status":
            records = read_records(args.archive.expanduser().resolve())
            plan = next((entry for entry in records if entry["event"] == "measurement_plan"
                         and entry["plan_id"] == args.plan_id), None)
            if plan is None:
                raise ArchiveFailure("unknown_measurement_plan", "No such measurement plan")
            result = measurement_plans.status(plan, records)
        elif args.command == "stop":
            result = stop_proposal(args)
        elif args.command == "trace":
            result = trace_report(args)
        elif args.command == "brief":
            result = optimization_brief(args)
        elif args.command == "decide":
            if (args.recent < 2 or args.min_stagnant < 2 or args.min_stagnant > args.recent
                    or not math.isfinite(args.tie_epsilon) or args.tie_epsilon < 0):
                raise ArchiveFailure("invalid_config", "Require recent >= min-stagnant >= 2 and a finite non-negative tie-epsilon")
            result = route_decision(args)
        else:
            if args.recent < 1:
                raise ArchiveFailure("invalid_config", "recent must be positive")
            result = summarize(args)
    except (OSError, ArchiveFailure, TypeError, ValueError, KeyError, OverflowError) as exc:
        report = {"schema_version": 1, "status": "blocked",
                  "error": {"type": exc.kind if isinstance(exc, ArchiveFailure) else
                             "io_error" if isinstance(exc, OSError) else "invalid_input",
                             "message": str(exc)}}
        print(json.dumps(report, ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2
    result = ({"schema_version": 1, "status": "success", "candidate": result}
              if args.command == "record" else dict(result))
    result.setdefault("status", "success")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
