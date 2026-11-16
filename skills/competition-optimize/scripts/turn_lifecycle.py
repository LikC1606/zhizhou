"""Own the ordering of sealed turn creation and accepted-outcome persistence.

The driver supplies process waiting and its completion verifier callback. Policy
and archive modules retain their facts; no second state or event store is added.
"""
from __future__ import annotations

import os
import pathlib
import time
import uuid
from typing import Any, Callable

from candidate_evidence import canonical, sha256
from campaign_archive import CampaignArchive
from campaign_policy import CampaignPolicy, TurnOutcome
from campaign_prompt import prompt_for_turn
from campaign_search import prepare_handoff
from campaign_state import append_event, check_control_files, save_state
from campaign_runtime import CampaignError, atomic_bytes, atomic_json, job_directory, output_hashes, read_json
from codex_invocation import CodexInvocation
from campaign_workflow import freeze_workflow

def materialize_request(campaign: pathlib.Path, turn: dict[str, Any]) -> pathlib.Path:
    directory = job_directory(campaign, turn["number"], turn.get("kind", "agent"))
    directory.mkdir(parents=True, exist_ok=True)
    if "context" in turn:
        raw = canonical(turn["context"]) + b"\n"
        if sha256(raw) != turn["context_sha256"]:
            raise CampaignError("Durable turn context identity changed")
        context = directory / "context.json"
        if context.exists() and context.read_bytes() != raw:
            raise CampaignError("Durable turn context was modified")
        if not context.exists():
            atomic_bytes(context, raw)
    request = {key: value for key, value in turn.items() if key != "prompt"}
    path = directory / "request.json"
    if path.exists():
        if read_json(path) != request:
            raise CampaignError("Durable turn request was modified")
    else:
        atomic_json(path, request)
    prompt = directory / "prompt.txt"
    if prompt.exists() and prompt.read_text() != turn["prompt"]:
        raise CampaignError("Durable turn prompt was modified")
    if not prompt.exists():
        temporary = directory / ("prompt." + uuid.uuid4().hex + ".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(turn["prompt"])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, prompt)
    return directory


def retry_later(state: dict[str, Any], error: str) -> None:
    state["failures"] += 1
    delay = min(state["retry_max_seconds"],
                state["retry_base_seconds"] * 2 ** min(state["failures"] - 1, 16))
    state["retry_at"] = time.time() + delay
    state["last_error"] = error
    state["recovery_needed"] = True
    state["next_action"] = "Reconcile prior artifacts, then execute the best remaining improvement"


class TurnLifecycle:
    """One persistence authority for a prepared turn and its accepted outcome."""

    @staticmethod
    def prepare(campaign: pathlib.Path, state: dict[str, Any]) -> None:
        accepted_state = state
        state = dict(state)
        number = state["turn_number"] + 1
        snapshot, protected, provenance = freeze_workflow(campaign, pathlib.Path(__file__).resolve().parent.parent, state)
        state.update(instruction_snapshot=snapshot, workflow_provenance=provenance,
                     protected_files={**state["protected_files"], **protected})
        archive = CampaignArchive(pathlib.Path(state["archive"]))
        with archive.confirmed(state["archive_snapshot"]) as evidence:
            prepared = CampaignPolicy().prepare(state, evidence)
            state.update(prepared.updates)
            fresh, reason = prepared.fresh_context, prepared.context_refresh_reason
            handoff = prepare_handoff(state, prepared, evidence, state["protected_files"][str(campaign / "task.md")])
            context = handoff.packet
        timeout = state["turn_timeout_seconds"]
        if state["max_wall_seconds"] is not None:
            left = max(0.1, state["created_unix"] + state["max_wall_seconds"] - time.time())
            timeout = left if timeout is None else min(timeout, left)
        turn = {"number": number, "token": uuid.uuid4().hex, "started_unix": time.time(),
                "archive_before": state["archive_snapshot"], "mode": state["next_mode"],
                "workspace": state["workspace"], "command": CodexInvocation.command(state, campaign, number),
                "timeout_seconds": timeout, "context": context,
                "context_sha256": sha256(canonical(context) + b"\n"),
                "fresh_context": fresh, "context_refresh_reason": reason,
                "instruction_snapshot": snapshot, "workflow_provenance": provenance,
                **handoff.delivery,
                "prompt": prompt_for_turn(state, campaign, number, context)}
        state["turn_number"] = number
        state["inflight"] = turn
        # Persist intent before creating files or processes. Resume can materialize missing files.
        accepted_state.update(state)
        save_state(campaign, state)
        append_event(campaign, {"event": "turn_prepared", "turn": number, "token": turn["token"],
                                "mode": turn["mode"], "session_id": state["session_id"],
                                "fresh_context": fresh, "context_refresh_reason": reason,
                "instruction_snapshot": snapshot, "workflow_provenance": provenance,
                                **{key: state[key] for key in ("objective_progress", "execution_health", "comparison_continuity")},
                                "frontier_exposure": turn["frontier_exposure"],
                                "pending_proposal_exposure": turn["pending_proposal_exposure"],
                                "trial_exposure": turn["trial_exposure"],
                                "learning_exposure": turn["learning_exposure"],
                                "review_checkpoints": turn["review_checkpoints"],
                                "context_sha256": turn["context_sha256"]})

    @staticmethod
    def accept(campaign: pathlib.Path, state: dict[str, Any],
               verify_completion: Callable[[dict[str, Any]], None]) -> None:
        turn = state["inflight"]
        directory = materialize_request(campaign, turn)
        result = read_json(directory / "exit.json")
        if result.get("token") != turn["token"]:
            raise CampaignError("Exit record does not belong to the in-flight turn")
        if result.get("outputs") != output_hashes(directory):
            raise CampaignError("Agent output changed after its durable exit record")
        check_control_files(state)
        received = CampaignArchive(pathlib.Path(state["archive"])).receive(
            turn["archive_before"], token=turn["token"], directory=directory)
        if received.quarantine_event is not None:
            append_event(campaign, {**received.quarantine_event, "turn": turn["number"], "token": turn["token"]})
        delta, quarantined, evidence = received.delta, received.quarantined, received.evidence
        state.update(archive_snapshot=received.snapshot, progress=evidence.counts)
        invocation = CodexInvocation.observe(directory, result, quarantined=quarantined)
        events = invocation.events
        for key, value in events["usage"].items():
            state["usage"][key] = state["usage"].get(key, 0) + value
        if events["terminal"] != "turn.completed":
            state["unreported_usage_turns"] += 1
        state["agent_seconds"] += result["elapsed_seconds"]
        if events["session_id"]:
            state["session_id"] = events["session_id"]
        state["inflight"] = None
        error, receipt = invocation.error, invocation.receipt
        # New archive evidence is accepted even if invocation delivery failed.
        outcome = TurnOutcome(evidence, received.appended_events, delta, receipt, time.time())
        state.update(CampaignPolicy().accept(state, turn, outcome))
        if receipt is None:
            retry_later(state, error)
            state["last_summary"] = f"Turn {turn['number']} interrupted: {error}"
            if invocation.reset_session:
                state["session_id"] = None
            if invocation.blocked:
                state["status"] = "blocked"
                state["stop_reason"] = (
                    "Observed CLI authentication/configuration or host dependency failure; inspect this turn's logs")
            event = {"event": "turn_interrupted", "error": error}
        else:
            event = {"event": "turn_completed", "receipt": receipt}
            if (delta["evaluated_candidates"] > delta["diagnostic_evaluations"]
                    or receipt["status"] == "complete"):
                verify_completion(turn)
        append_event(campaign, {**event, "turn": turn["number"], "token": turn["token"],
                                "event_id": turn["token"] + ":outcome", "archive_delta": delta,
                                "usage": events["usage"], "next_mode": state["next_mode"],
                                "objective_progress": state["objective_progress"],
                                "execution_health": state["execution_health"],
                                "comparison_continuity": state["comparison_continuity"]})
        save_state(campaign, state)
