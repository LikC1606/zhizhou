#!/usr/bin/env python3
"""Run an open-ended, resumable competition optimization campaign with Codex CLI.

Strategy belongs to the agent; scoring belongs to the task adapter. This driver
owns continuation, verified evidence, process recovery, and explicit stop rules.
Linux and Python 3.10+ are required. No third-party Python packages are needed.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, BinaryIO

import candidate_archive as archive_tools
from campaign_archive import CampaignArchive
from campaign_prompt import prompt_for_turn
from codex_invocation import FINAL_SCHEMA
from campaign_state import (SCHEMA_VERSION, append_event, check_control_files, complete_state, read_state, save_state)
from turn_lifecycle import TurnLifecycle, materialize_request

# Compatibility entrypoint; turn creation is owned by the lifecycle module.
prepare_turn = TurnLifecycle.prepare
from campaign_search import (
    DEFAULT_COMPARISON_REVIEW_WINDOW, DEFAULT_FAILURE_REVIEW_WINDOW, DEFAULT_SESSION_CHECKPOINTS,
    DEFAULT_STAGNATION_WINDOW,
)
from campaign_runtime import (
    CampaignError, HEARTBEAT_SECONDS, POLL_SECONDS, WORKER_TOKEN, acquire_resources,
    atomic_bytes, atomic_json, exclusive_lock, file_hash, job_directory, lock_busy, output_hashes, owned_processes,
    process_alive, process_info, read_json, recorded_group, run_worker, terminate_owned,
    turn_directory, utc_now,
)


TERMINAL = {"complete", "blocked", "stopped_by_user", "limit_reached"}
LIMITS = ("max_turns", "max_tokens", "max_wall_seconds")
def evidence_exists(evidence: list[str], state: dict[str, Any], campaign: pathlib.Path) -> bool:
    return bool(evidence) and all(
        pathlib.Path(name).exists() if pathlib.Path(name).is_absolute() else
        (pathlib.Path(state["workspace"]) / name).exists() or (campaign / name).exists()
        for name in evidence)


def completion_job(campaign: pathlib.Path, state: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    directory = job_directory(campaign, turn["number"], "completion")
    command = [sys.executable, state["completion_check"], "--workspace", state["workspace"],
               "--archive", state["archive"]]
    request = directory / "request.json"
    if request.exists():
        job = {**read_json(request), "prompt": ""}
        if (job.get("kind") != "completion" or job.get("number") != turn["number"] or
                job.get("command") != command or job.get("workspace") != state["workspace"]):
            raise CampaignError("Durable completion verifier request was modified")
    else:
        timeout = state["completion_timeout_seconds"]
        if state["max_wall_seconds"] is not None:
            timeout = min(timeout, max(0.1, state["created_unix"] +
                                      state["max_wall_seconds"] - time.time()))
        job = {"number": turn["number"], "kind": "completion", "token": uuid.uuid4().hex,
               "started_unix": time.time(), "workspace": state["workspace"], "command": command,
               "timeout_seconds": timeout, "prompt": ""}
    return job


def completion_check(campaign: pathlib.Path, state: dict[str, Any], turn: dict[str, Any],
                     resources: list[BinaryIO]) -> None:
    if not state["completion_check"]:
        return
    check_control_files(state)
    job = completion_job(campaign, state, turn)
    directory = job_directory(campaign, turn["number"], "completion")
    # The same durable worker/exec shim owns both kinds of job. A manager crash
    # adopts the verifier instead of launching a second one or leaving an orphan.
    await_job(campaign, state, job, resources)
    outcome = read_json(directory / "exit.json")
    if outcome.get("token") != job["token"] or outcome.get("outputs") != output_hashes(directory):
        raise CampaignError("Completion verifier outcome identity changed")
    stop = stop_request(campaign)
    if (stop and stop.get("immediate") or state["max_wall_seconds"] is not None and
            time.time() - state["created_unix"] >= state["max_wall_seconds"]):
        return  # Let the normal campaign stop/limit path retain the accepted candidate.
    if outcome["returncode"] != 0 or outcome.get("error") or outcome.get("survivors"):
        raise CampaignError(f"Configured completion verifier failed: {outcome.get('error') or outcome['returncode']}")
    check_control_files(state)
    try:
        result = read_json(directory / "events.jsonl")
        if (not isinstance(result, dict) or set(result) != {"complete", "reason", "evidence"} or
                type(result["complete"]) is not bool or not isinstance(result["reason"], str) or
                not isinstance(result["evidence"], list) or
                any(not isinstance(item, str) for item in result["evidence"])):
            raise ValueError("expected complete:boolean, reason:string, evidence:string[]")
    except (OSError, ValueError) as exc:
        raise CampaignError(f"Invalid completion verifier output: {exc}") from exc
    append_event(campaign, {"event": "completion_checked", "turn": turn["number"], "result": result,
                            "event_id": job["token"] + ":completion"})
    if result["complete"]:
        if (not result["reason"].strip() or not evidence_exists(result["evidence"], state, campaign) or
                not state["progress"]["executed_implementations"]):
            raise CampaignError("Completion verifier claimed success without executed implementation/evidence")
        CampaignArchive(pathlib.Path(state["archive"])).verified()
        state["status"] = "complete"
        state["stop_reason"] = result["reason"]


def heartbeat(campaign: pathlib.Path, state: dict[str, Any]) -> None:
    atomic_json(campaign / "manager.json", {**process_info(os.getpid()), "at": utc_now(),
                "turn": state["turn_number"], "status": state["status"], "retry_at": state["retry_at"],
                "generation": state["manager_generation"]})


def stop_request(campaign: pathlib.Path) -> dict[str, Any] | None:
    path = campaign / "stop.request.json"
    return read_json(path) if path.exists() else None


def await_turn(campaign: pathlib.Path, state: dict[str, Any],
               resources: list[BinaryIO] | None) -> list[BinaryIO]:
    turn = state["inflight"]
    if (job_directory(campaign, turn["number"], "completion") / "request.json").exists():
        # A verifier may own the inherited resource FDs after BOTH its worker and
        # manager died. Recover that job first: waiting for the original agent's
        # lock cannot enforce the verifier's deadline or cancel its process tree.
        resources = await_job(campaign, state, completion_job(campaign, state, turn), resources)
    return await_job(campaign, state, turn, resources)


def await_job(campaign: pathlib.Path, state: dict[str, Any], turn: dict[str, Any],
              resources: list[BinaryIO] | None) -> list[BinaryIO]:
    directory = materialize_request(campaign, turn)
    worker = None
    heartbeat_at = 0.0
    cleanup_at = 0.0
    while True:
        now = time.monotonic()
        if worker is not None:
            code = worker.poll()
            if code is not None and code > 0 and code != 75 and not (directory / "exit.json").exists():
                raise CampaignError(f"Turn worker could not persist an outcome (exit {code}); inspect worker.log")
        if now >= heartbeat_at:
            heartbeat(campaign, state)
            heartbeat_at = now + HEARTBEAT_SECONDS
        if resources is None:
            resources = acquire_resources(campaign, state)
        request = stop_request(campaign)
        timeout = turn["timeout_seconds"]
        expired = timeout is not None and time.time() - turn["started_unix"] >= timeout
        group = recorded_group(directory, turn["token"])
        if (request and request.get("immediate") or expired) and now >= cleanup_at:
            # This also works after a worker crash, when no one is polling the original CLI.
            atomic_json(directory / "cancel.request.json", {"token": turn["token"], "at": utc_now(),
                        "reason": "User requested immediate stop" if request and request.get("immediate")
                        else "Per-turn watchdog expired"})
            terminate_owned(turn["token"], group)
            cleanup_at = now + HEARTBEAT_SECONDS
        busy = lock_busy(directory / "execution.lock")
        if not busy:
            agents = owned_processes(turn["token"], group)
            if agents:
                # Orphan tool children might have closed the inherited lock descriptors.
                terminate_owned(turn["token"], group)
                time.sleep(POLL_SECONDS)
                continue
            if (directory / "exit.json").exists() and resources is not None:
                return resources
            workers = owned_processes(turn["token"], worker=True)
            if not workers and resources is not None:
                environment = {**os.environ, WORKER_TOKEN: turn["token"]}
                command = [sys.executable, str(pathlib.Path(__file__).resolve()), "_worker",
                           "--campaign", str(campaign), "--number", str(turn["number"]),
                           "--kind", turn.get("kind", "agent")]
                for stream in resources:
                    command += ["--resource-fd", str(stream.fileno())]
                with (directory / "worker.log").open("ab") as log:
                    worker = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                              stdout=log, stderr=log, env=environment,
                                              start_new_session=True,
                                              pass_fds=tuple(stream.fileno() for stream in resources))
        time.sleep(POLL_SECONDS)


def limit_reason(state: dict[str, Any]) -> str:
    if state["max_turns"] is not None and state["turn_number"] >= state["max_turns"]:
        return "Explicit max-turns limit reached"
    tokens = state["usage"].get("input_tokens", 0) + state["usage"].get("output_tokens", 0)
    if state["max_tokens"] is not None and tokens >= state["max_tokens"]:
        return "Explicit max-tokens limit reached (checked between invocations)"
    if (state["max_wall_seconds"] is not None and
            time.time() - state["created_unix"] >= state["max_wall_seconds"]):
        return "Explicit max-wall-seconds limit reached"
    return ""


def run_campaign(campaign: pathlib.Path, overrides: dict[str, Any] | None = None,
                 managed: bool = False, generation: str | None = None) -> dict[str, Any]:
    if not managed and lock_busy(campaign / "supervisor.lock"):
        raise CampaignError("Background supervisor is already running; use status or stop")
    try:
        leader = exclusive_lock(campaign / "runner.lock")
    except BlockingIOError as exc:
        raise CampaignError("Another campaign manager is already running") from exc
    resources = None
    state = read_state(campaign)
    try:
        state["manager_generation"] = generation or uuid.uuid4().hex
        check_control_files(state)
        if not state["inflight"]:
            CampaignArchive(pathlib.Path(state["archive"])).verified(state["archive_snapshot"])
        if overrides:
            state.update(overrides)
        if state["status"] in TERMINAL:
            if state["status"] == "stopped_by_user":
                (campaign / "stop.request.json").unlink(missing_ok=True)
            state["status"] = "running"
            state["stop_reason"] = ""
            state["retry_at"] = None
            # Preserve in-flight intent and recovery context across an explicit resume.
        save_state(campaign, state)
        resources = acquire_resources(campaign, state)
        heartbeat_at = 0.0
        while state["status"] == "running":
            try:
                if state["inflight"]:
                    resources = await_turn(campaign, state, resources)
                    TurnLifecycle.accept(campaign, state,
                                         lambda turn: completion_check(campaign, state, turn, resources))
                    continue
                request = stop_request(campaign)
                reason = limit_reason(state)
                if request or reason:
                    state["status"] = "stopped_by_user" if request else "limit_reached"
                    state["stop_reason"] = request["reason"] if request else reason
                    save_state(campaign, state)
                    append_event(campaign, {"event": state["status"], "reason": state["stop_reason"]})
                    break
                now = time.monotonic()
                if now >= heartbeat_at:
                    heartbeat(campaign, state)
                    heartbeat_at = now + HEARTBEAT_SECONDS
                if state["retry_at"] and time.time() < state["retry_at"]:
                    time.sleep(POLL_SECONDS)
                    continue
                check_control_files(state)
                prepare_turn(campaign, state)
            except KeyboardInterrupt:
                atomic_json(campaign / "stop.request.json", {"reason": "User interrupted foreground runner",
                            "immediate": True, "at": utc_now()})
        heartbeat(campaign, state)
        return state
    except (CampaignError, archive_tools.ArchiveFailure, OSError, ValueError, KeyError) as exc:
        # Actual host/evidence failures are distinct from an agent saying it has no ideas.
        state["status"] = "blocked"
        state["stop_reason"] = str(exc)
        save_state(campaign, state)
        append_event(campaign, {"event": "driver_blocked", "error": str(exc)})
        return state
    finally:
        if resources:
            for stream in resources:
                stream.close()
        leader.close()


def new_campaign(args: argparse.Namespace) -> pathlib.Path:
    workspace = args.workspace.expanduser().resolve(strict=True)
    task = args.task_file.expanduser().resolve(strict=True)
    if not workspace.is_dir() or not task.is_file():
        raise CampaignError("Workspace must be a directory and task must be a file")
    binary = shutil.which(args.agent_bin)
    if binary is None:
        raise CampaignError(f"Agent executable not found: {args.agent_bin}")
    campaign = args.campaign.expanduser().resolve()
    if campaign.exists():
        raise CampaignError("Campaign directory already exists; use resume")
    archive = args.archive.expanduser().resolve()
    head = CampaignArchive(archive).verified()
    evidence, snapshot = head.evidence, head.snapshot
    signals = evidence.signals()
    protected = {}
    checker = None
    if args.completion_check:
        checker = str(args.completion_check.expanduser().resolve(strict=True))
        for path in [pathlib.Path(checker), *args.check_dependency]:
            path = path.expanduser().resolve(strict=True)
            protected[str(path)] = archive_tools.hash_path(path)
    elif args.check_dependency:
        raise CampaignError("check-dependency requires completion-check")
    campaign.mkdir(parents=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(task, campaign / "task.md")
    atomic_json(campaign / "receipt.schema.json", FINAL_SCHEMA)
    for path in (campaign / "task.md", campaign / "receipt.schema.json"):
        protected[str(path)] = file_hash(path)
    state: dict[str, Any] = complete_state({
        "schema_version": SCHEMA_VERSION, "campaign_id": uuid.uuid4().hex, "status": "running",
        "workspace": str(workspace), "archive": str(archive), "archive_snapshot": snapshot,
        "agent_bin": binary, "model": args.model, "sandbox": args.sandbox,
        **{key: getattr(args, key) for key in LIMITS},
        "turn_timeout_seconds": args.turn_timeout_seconds, "turn_number": 0,
        "turns_without_implementation": 0, "failures": 0, "session_id": None, "inflight": None,
        "stagnation_window": args.stagnation_window, "session_checkpoints": args.session_checkpoints,

        "objective_progress": signals["objective_progress"],
        "execution_health": signals["execution_health"],
        "failure_review_window": args.failure_review_window,
        "comparison_continuity": signals["comparison_continuity"],
        "comparison_review_window": args.comparison_review_window,
        "next_mode": "work", "recovery_needed": False, "last_summary": "",
        "next_action": "Establish or resume the credible baseline",
        "last_agent_status": None, "last_error": "", "retry_at": None,
        "retry_base_seconds": args.retry_base_seconds, "retry_max_seconds": args.retry_max_seconds,
        "stop_reason": "", "created_at": utc_now(), "created_unix": time.time(),
        "usage": {}, "agent_seconds": 0.0, "progress": evidence.counts,
        "completion_check": checker, "completion_timeout_seconds": args.completion_timeout_seconds,
        "protected_files": protected,
    })
    save_state(campaign, state)
    append_event(campaign, {"event": "campaign_created", "campaign_id": state["campaign_id"],
                            "workspace": str(workspace), "archive": str(archive),
                            "completion": "verifier" if checker else "open_ended"})
    return campaign


def supervise(campaign: pathlib.Path, overrides: dict[str, Any]) -> int:
    try:
        lock = exclusive_lock(campaign / "supervisor.lock")
    except BlockingIOError as exc:
        raise CampaignError("Another background supervisor is already running") from exc
    restarts = 0
    child = None
    child_generation = None
    adopted_generation = None
    entry_generation = read_state(campaign)["manager_generation"]
    adopted = False
    first = True
    retry_at = 0.0
    heartbeat_at = 0.0
    with lock:
        while True:
            state = read_state(campaign)
            now = time.monotonic()
            if now >= heartbeat_at:
                atomic_json(campaign / "supervisor.json", {**process_info(os.getpid()),
                            "at": utc_now(), "restarts": restarts})
                heartbeat_at = now + HEARTBEAT_SECONDS
            if child is not None:
                code = child.poll()
                if code is None:
                    time.sleep(POLL_SECONDS)
                    continue
                child = None
                state = read_state(campaign)
                if (state["manager_generation"] == child_generation and state["status"] in TERMINAL):
                    return 0 if state["status"] != "blocked" else 2
                restarts += 1
                retry_at = now + min(60, state["retry_base_seconds"] * 2 ** min(restarts - 1, 12))
                append_event(campaign, {"event": "manager_restart_scheduled",
                                        "restart": restarts, "exit_code": code})
            busy = lock_busy(campaign / "runner.lock")
            if busy:
                # If an earlier supervisor died, adopt its still-running manager.
                adopted = True
                if state["status"] == "running" or state["manager_generation"] != entry_generation:
                    adopted_generation = state["manager_generation"]
                first = False
                time.sleep(POLL_SECONDS)
                continue
            if adopted:
                state = read_state(campaign)
                if (state["status"] in TERMINAL and
                        (state["manager_generation"] == adopted_generation or
                         state["manager_generation"] != entry_generation)):
                    return 0 if state["status"] != "blocked" else 2
                adopted = False
            if now < retry_at:
                time.sleep(POLL_SECONDS)
                continue
            child_generation = uuid.uuid4().hex
            command = [sys.executable, str(pathlib.Path(__file__).resolve()), "_run",
                       "--campaign", str(campaign), "--generation", child_generation]
            if first:
                for key, value in overrides.items():
                    command += (["--clear-" + key.replace("_", "-")] if value is None else
                                ["--" + key.replace("_", "-"), str(value)])
            with (campaign / "manager.log").open("ab") as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            first = False
            time.sleep(POLL_SECONDS)


def launch_background(campaign: pathlib.Path, overrides: dict[str, Any]) -> dict[str, Any]:
    if lock_busy(campaign / "supervisor.lock"):
        raise CampaignError("Background supervisor is already running; use status or stop")
    if overrides and lock_busy(campaign / "runner.lock"):
        raise CampaignError("Cannot change limits while an existing manager is running")
    command = [sys.executable, str(pathlib.Path(__file__).resolve()), "_supervise",
               "--campaign", str(campaign)]
    for key, value in overrides.items():
        command += (["--clear-" + key.replace("_", "-")] if value is None else
                    ["--" + key.replace("_", "-"), str(value)])
    with (campaign / "supervisor.log").open("ab") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        marker = campaign / "supervisor.json"
        if marker.exists() and read_json(marker).get("pid") == process.pid:
            return read_state(campaign)
        if process.poll() is not None:
            raise CampaignError(f"Could not start background supervisor; inspect {campaign / 'supervisor.log'}")
        time.sleep(POLL_SECONDS)
    raise CampaignError("Background supervisor did not become ready; inspect supervisor.log before retrying")


def public_status(campaign: pathlib.Path, state: dict[str, Any]) -> dict[str, Any]:
    value = {key: state[key] for key in (
        "status", "turn_number", "session_id", "turns_without_implementation",
        "last_summary", "next_action", "stop_reason", "next_mode", "progress",
        "usage", "agent_seconds", "retry_at", "last_error", "objective_progress",
        "stagnation_window", "session_checkpoints", "session_turns", "context_refreshes",
        "context_refresh_reason", "execution_health", "failure_review_window",
        "comparison_continuity", "comparison_review_window", "workflow_provenance", *LIMITS)}
    value["unreported_usage_turns"] = state["unreported_usage_turns"]
    comparison_key = (state["objective_progress"] or {}).get("comparison_key")
    value["frontier_exposed_implementations"] = len(state["frontier_exposures"].get(comparison_key, {}))
    value["pending_exposed_proposals"] = len(state["pending_proposal_exposures"].get(comparison_key, {}))
    value["trial_exposed_proposals"] = len(state["trial_exposures"].get(comparison_key, {}))
    value["learning_exposed_heads"] = len(state["learning_exposures"].get(comparison_key, {}))
    value["campaign"] = str(campaign)
    value["completion_mode"] = "verifier" if state["completion_check"] else "open_ended"
    for role in ("manager", "supervisor"):
        path = campaign / f"{role}.json"
        marker = read_json(path) if path.exists() else None
        value[role] = {**marker, "alive": process_alive(marker)} if marker else None
    turn = state["inflight"]
    value["inflight"] = ({key: turn[key] for key in ("number", "token", "mode", "started_unix")}
                         if turn else None)
    if turn:
        value["inflight"].update({key: turn[key] for key in
                                  ("fresh_context", "context_refresh_reason", "context_sha256") if key in turn})
        directory = turn_directory(campaign, turn["number"])
        for name in ("worker", "agent", "heartbeat"):
            path = directory / f"{name}.json"
            value["inflight"][name] = read_json(path) if path.exists() else None
        completion = directory / "completion"
        if (completion / "request.json").exists():
            value["inflight"]["completion"] = {
                name: read_json(completion / (name + ".json")) if (completion / (name + ".json")).exists()
                else None for name in ("worker", "agent", "heartbeat", "exit")}
    request = stop_request(campaign)
    value["stop_requested"] = request
    return value


def add_limits(command: argparse.ArgumentParser, clear: bool = False) -> None:
    for name in LIMITS:
        command.add_argument("--" + name.replace("_", "-"), type=int)
        if clear:
            command.add_argument("--clear-" + name.replace("_", "-"), action="store_true")


def add_search_policy(command: argparse.ArgumentParser, defaults: bool = False) -> None:
    command.add_argument("--stagnation-window", type=int,
                         default=DEFAULT_STAGNATION_WINDOW if defaults else None,
                         help="new comparable implementations without a historical best before strategy review")
    command.add_argument("--session-checkpoints", type=int,
                         default=DEFAULT_SESSION_CHECKPOINTS if defaults else None,
                         help="successful checkpoints per context before rotation; 0 disables periodic rotation")
    command.add_argument("--failure-review-window", type=int,
                         default=DEFAULT_FAILURE_REVIEW_WINDOW if defaults else None,
                         help="unmeasured development executions before a fresh repair review; never stops work")
    command.add_argument("--comparison-review-window", type=int,
                         default=DEFAULT_COMPARISON_REVIEW_WINDOW if defaults else None,
                         help="new contracts still lacking another measured implementation before common-contract review")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="create and run an open-ended optimization campaign")
    start.add_argument("--workspace", type=pathlib.Path, required=True)
    start.add_argument("--campaign", type=pathlib.Path, required=True)
    start.add_argument("--task-file", type=pathlib.Path, required=True)
    start.add_argument("--archive", type=pathlib.Path, required=True)
    start.add_argument("--agent-bin", default="codex")
    start.add_argument("--model")
    start.add_argument("--sandbox", choices=["workspace-write", "read-only", "danger-full-access"],
                       default="workspace-write")
    start.add_argument("--background", action="store_true", help="detach a manager-restarting supervisor")
    add_limits(start)
    start.add_argument("--turn-timeout-seconds", type=float, help="optional watchdog; no default turn timeout")
    start.add_argument("--retry-base-seconds", type=float, default=5.0)
    start.add_argument("--retry-max-seconds", type=float, default=300.0)
    start.add_argument("--completion-check", type=pathlib.Path, help="fixed Python task completion verifier")
    start.add_argument("--check-dependency", type=pathlib.Path, action="append", default=[])
    start.add_argument("--completion-timeout-seconds", type=float, default=60.0)
    add_search_policy(start, defaults=True)
    for name in ("resume", "status", "stop", "_run", "_supervise", "_worker"):
        command = sub.add_parser(name, help=argparse.SUPPRESS if name.startswith("_") else None)
        command.add_argument("--campaign", type=pathlib.Path, required=True)
        if name in {"resume", "_run", "_supervise"}:
            add_limits(command, clear=True)
            add_search_policy(command)
        if name == "_run":
            command.add_argument("--generation")
        if name == "resume":
            command.add_argument("--background", action="store_true")
        if name == "stop":
            command.add_argument("--reason", default="User requested stop")
            command.add_argument("--now", action="store_true", help="cancel the active local invocation")
        if name == "_worker":
            command.add_argument("--number", type=int, required=True)
            command.add_argument("--kind", choices=["agent", "completion"], default="agent")
            command.add_argument("--resource-fd", type=int, action="append", default=[])
    return root


def limit_overrides(args: argparse.Namespace) -> dict[str, Any]:
    result = {}
    for key in LIMITS:
        value = getattr(args, key, None)
        clear = getattr(args, "clear_" + key, False)
        if value is not None and (value < 1 or clear):
            raise CampaignError(f"{key} must be positive and cannot be combined with its clear flag")
        if value is not None or clear:
            result[key] = None if clear else value
    for key, minimum in (("stagnation_window", 1), ("session_checkpoints", 0), ("failure_review_window", 1),
                         ("comparison_review_window", 1)):
        value = getattr(args, key, None)
        if value is not None:
            if value < minimum:
                raise CampaignError(f"{key} must be at least {minimum}")
            result[key] = value
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        overrides = limit_overrides(args)
        if args.command == "start":
            for key in ("turn_timeout_seconds", "retry_base_seconds", "retry_max_seconds",
                        "completion_timeout_seconds"):
                value = getattr(args, key)
                if value is not None and (not 0 < value < float("inf")):
                    raise CampaignError(f"{key} must be finite and positive")
            if args.retry_max_seconds < args.retry_base_seconds:
                raise CampaignError("retry-max-seconds must be at least retry-base-seconds")
            campaign = new_campaign(args)
            state = launch_background(campaign, {}) if args.background else run_campaign(campaign)
        else:
            campaign = args.campaign.expanduser().resolve(strict=True)
            if args.command == "_worker":
                return run_worker(campaign, args.number, args.resource_fd, args.kind)
            if args.command == "_supervise":
                return supervise(campaign, overrides)
            if args.command == "_run":
                state = run_campaign(campaign, overrides, managed=True, generation=args.generation)
            elif args.command == "status":
                state = read_state(campaign)
            elif args.command == "stop":
                state = read_state(campaign)
                if state["status"] not in {"running", "blocked"}:
                    raise CampaignError("Only a running or blocked campaign can be stopped")
                atomic_json(campaign / "stop.request.json", {"reason": args.reason,
                            "immediate": args.now, "at": utc_now()})
            else:
                state = (launch_background(campaign, overrides) if args.background else
                         run_campaign(campaign, overrides))
        print(json.dumps(public_status(campaign, state), ensure_ascii=False, indent=2))
        return 2 if state["status"] == "blocked" and args.command not in {"status", "stop"} else 0
    except (CampaignError, archive_tools.ArchiveFailure, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
