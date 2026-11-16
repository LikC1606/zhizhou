"""Fit complete retrieval cards into one turn's evidence allowance.

Identifiers, source/result pointers and sealed reports are never substringed.
Large cards stay in the archive; only descriptive prose is abbreviated. Work
mode changes priority under pressure, not the meaning of a score or contract.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from candidate_evidence import canonical, sha256


PROSE = {"scope", "selection_policy", "feedback", "failure_mechanism", "mechanism", "basis",
         "change", "expected_observation", "next_action", "feedback_scope", "message", "error"}
SEALED = {"implementation", "implementation_review", "artifact_paths", "result", "code_targets",
          "learning", "evidence", "comparison", "scoped_learning"}


def bound_packet(packet: dict[str, Any], *, budget: int, mode: str = "work") -> dict[str, Any]:
    """Return copied evidence plus omissions; never mutate accepted records."""
    omissions: dict[str, int] = {}

    def omitted(path: str, count: int = 1) -> None:
        if len(path) > 160:
            path = path[:120] + "/sha256:" + sha256(path.encode())[:16]
        if len(omissions) >= 64 and path not in omissions:
            path = "/additional_truncated_fields"
        omissions[path] = omissions.get(path, 0) + count

    def prose(value: Any, path: str = "", field: str = "") -> Any:
        if field in SEALED:
            return copy.deepcopy(value)
        if isinstance(value, str) and field in PROSE and len(value) > 1200:
            omitted(path, len(value) - 1200)
            return value[:1200] + " [abbreviated; retrieve the original evidence]"
        if isinstance(value, dict):
            return {key: prose(item, f"{path}/{key}", key) for key, item in value.items()}
        if isinstance(value, list):
            return [prose(item, f"{path}/{i}", field) for i, item in enumerate(value)]
        return value

    def size(value: Any) -> int:
        # Standard JSON spacing is an upper bound for the canonical wire form.
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) + 1

    source = prose(packet)
    source["truncated_fields"] = omissions
    if size(source) <= budget:
        return source

    def compact_recovery(name: str, recovery: dict[str, Any] | None) -> Any:
        if not recovery or size(recovery) <= budget // 3:
            return recovery
        keys = (("reference_relationship", "changed_fields", "scope", "retrieval_sha256")
                if name == "comparison_recovery" else
                ("reference_relationship", "reference_comparison_matches", "scope"))
        result = {key: recovery[key] for key in keys}
        for role in ("target", "reference"):
            card = recovery[role]
            if card is None:
                result[role] = None
                continue
            if name == "comparison_recovery":
                fields = ("candidate_id", "implementation_fingerprint", "comparison_sha256", "result_path",
                          "result_sha256", "identity_checks")
                result[role] = {key: card[key] for key in fields}
            else:
                result[role] = {key: card[key] for key in
                                ("candidate_id", "role", "result_path", "result_sha256", "execution_status")}
                result[role]["implementation_fingerprint"] = card["implementation"]["fingerprint"]
                result[role]["comparison_sha256"] = sha256(canonical(card["comparison"]))
                diagnostic = copy.deepcopy(card["diagnostic"])
                if size(diagnostic.get("artifacts", [])) > budget // 8:
                    omitted(f"/{name}/{role}/diagnostic/artifacts", len(diagnostic["artifacts"]))
                    diagnostic["artifacts"] = []
                result[role]["diagnostic"] = diagnostic
        result["details_omitted"] = "Read complete source paths and metadata from the cited archive/result files"
        omitted(f"/{name}/detailed_cards")
        return result

    for name in ("comparison_recovery", "execution_recovery"):
        source[name] = compact_recovery(name, source.get(name))
    for name in ("objective_progress", "development_brief"):
        value = source.get(name)
        if value and size(value.get("comparison")) > budget // 8:
            value["comparison_sha256"] = sha256(canonical(value["comparison"]))
            value["comparison"] = None
            omitted(f"/{name}/comparison")
    if size(source) <= budget:
        return source

    # Reserve room for at most 65 compact omission locators, so adding an omitted
    # card cannot make a previously fitted payload exceed its hard byte limit.
    allowance = max(1024, budget - 12 * 1024)
    selected = {key: source[key] for key in
                ("schema_version", "archive_path", "archive_snapshot", "task_sha256", "scope")}
    selected["truncated_fields"] = omissions
    for key in source:
        if key not in selected:
            selected[key] = None

    def fits() -> bool:
        return size(selected) <= allowance

    def add(name: str, value: Any) -> None:
        selected[name] = value
        if not fits():
            selected[name] = None
            omitted("/" + name)

    priorities = (["execution_recovery"] if mode == "repair" else
                  ["measurement_plan", "repeat_conflict", "comparison_recovery"] if mode == "measure" else [])
    priorities += [name for name in ("execution_recovery", "measurement_plan", "repeat_conflict",
                                     "comparison_recovery", "objective_progress", "execution_health",
                                     "comparison_continuity", "measurement_decision", "measurement_stop")
                   if name not in priorities]
    for name in priorities:
        add(name, source.get(name))

    def fit_collection(parent: dict[str, Any], name: str, value: Any, path: str) -> None:
        parent[name] = value
        if fits():
            return
        if isinstance(value, list):
            parent[name] = []
            for item in value:
                parent[name].append(item)
                if not fits():
                    parent[name].pop()
                    omitted(path + "/omitted_items")
        elif isinstance(value, dict) and isinstance(value.get("selection"), list):
            parent[name] = {**value, "selection": []}
            if not fits():
                parent[name] = {"selection": [], "available": value.get("available", len(value["selection"])),
                                "omitted": len(value["selection"])}
            fit_collection(parent[name], "selection", value["selection"], path + "/selection")
        else:
            parent[name] = None
            omitted(path)

    brief = source.get("development_brief")
    if brief:
        selected["development_brief"] = {}
        target = selected["development_brief"]
        for key in ("schema_version", "archive_path", "anchor_candidate", "comparison", "comparison_sha256",
                    "best_development", "scope"):
            if key in brief:
                fit_collection(target, key, brief[key], "/development_brief/" + key)
        for name in ("candidates", "pending_references"):
            target[name] = {}
            cards = brief.get(name, {})
            order = list(dict.fromkeys([brief.get("best_development"), brief.get("anchor_candidate"), *cards]))
            for identity in order:
                if identity not in cards:
                    continue
                target[name][identity] = cards[identity]
                if not fits():
                    del target[name][identity]
                    omitted(f"/development_brief/{name}/{identity}")
        for key, value in brief.items():
            if key not in target:
                fit_collection(target, key, value, "/development_brief/" + key)
    fit_collection(selected, "trial_history", source.get("trial_history"), "/trial_history")
    # Even an unusually long archive path must not silently exceed the contract.
    if size(selected) > budget:
        raise ValueError("Required handoff envelope exceeds the evidence byte allowance")
    return selected
