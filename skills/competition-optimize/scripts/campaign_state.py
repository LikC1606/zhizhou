"""Campaign schema-v2 defaults and persistence, shared by creation and recovery."""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any
from evidence_files import hash_path
from campaign_runtime import CampaignError, atomic_json, read_json, utc_now
from campaign_search import (DEFAULT_COMPARISON_REVIEW_WINDOW, DEFAULT_FAILURE_REVIEW_WINDOW,
                             DEFAULT_SESSION_CHECKPOINTS, DEFAULT_STAGNATION_WINDOW)

SCHEMA_VERSION = 2


def complete_state(state: dict[str, Any]) -> dict[str, Any]:
    """Preserve unknown/legacy fields and sealed requests; fill optional defaults."""
    state = dict(state)
    state.setdefault("manager_generation", None)
    state.setdefault("unreported_usage_turns", 0)
    state.setdefault("stagnation_window", DEFAULT_STAGNATION_WINDOW)
    state.setdefault("session_checkpoints", DEFAULT_SESSION_CHECKPOINTS)
    state.setdefault("session_turns", 0)
    state.setdefault("context_refreshes", 0)
    state.setdefault("strategy_review_checkpoints", {})
    state.setdefault("objective_progress", None)
    state.setdefault("execution_health", None)
    state.setdefault("failure_review_window", DEFAULT_FAILURE_REVIEW_WINDOW)
    state.setdefault("execution_review_checkpoint", None)
    state.setdefault("comparison_review_window", DEFAULT_COMPARISON_REVIEW_WINDOW)
    state.setdefault("comparison_review_checkpoint", None)
    state.setdefault("comparison_continuity", None)
    state.setdefault("repeat_review_checkpoints", {})
    state.setdefault("frontier_exposures", {})
    state.setdefault("pending_proposal_exposures", {})
    state.setdefault("trial_exposures", {})
    state.setdefault("learning_exposures", {})
    state.setdefault("context_refresh_reason", "")
    state.setdefault("instruction_snapshot", None)
    state.setdefault("workflow_provenance", None)
    return state


def read_state(campaign: pathlib.Path) -> dict[str, Any]:
    try:
        state = read_json(campaign / "state.json")
    except (OSError, ValueError) as exc:
        raise CampaignError(f"Cannot read campaign state: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise CampaignError("Unsupported campaign state version")
    return complete_state(state)


def save_state(campaign: pathlib.Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_json(campaign / "state.json", state)


def append_event(campaign: pathlib.Path, event: dict[str, Any]) -> None:
    with (campaign / "events.jsonl").open("ab") as stream:
        stream.write((json.dumps({"at": utc_now(), **event}, ensure_ascii=False,
                                allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def check_control_files(state: dict[str, Any]) -> None:
    for name, expected in state["protected_files"].items():
        path = pathlib.Path(name)
        if not path.exists() or hash_path(path) != expected:
            raise CampaignError(f"Task/receipt schema/completion verifier identity changed: {path}")
