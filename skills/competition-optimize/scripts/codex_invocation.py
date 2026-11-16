"""Codex CLI command and result semantics behind one local invocation seam.

The process runtime owns launches and crash adoption. This adapter interprets
Codex events/receipts; accepted experiment evidence remains independent.
"""
from __future__ import annotations

import errno
import json
import pathlib
from dataclasses import dataclass
from typing import Any
from campaign_runtime import CampaignError, read_json, turn_directory

FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["continue", "complete", "blocked"]},
        "summary": {"type": "string"},
        "next_action": {"type": "string"},
        "stop_reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "next_action", "stop_reason", "evidence"],
    "additionalProperties": False,
}


def _parse_events(path: pathlib.Path) -> dict[str, Any]:
    result: dict[str, Any] = {"session_id": None, "terminal": None, "usage": {}, "errors": []}
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "thread.started" and isinstance(event.get("thread_id"), str):
                result["session_id"] = event["thread_id"]
            if kind in {"turn.completed", "turn.failed"}:
                result["terminal"] = kind
            if kind == "turn.completed" and isinstance(event.get("usage"), dict):
                for key, value in event["usage"].items():
                    if type(value) is int and value >= 0:
                        result["usage"][key] = result["usage"].get(key, 0) + value
            if kind in {"error", "turn.failed"}:
                result["errors"].append(json.dumps(event, ensure_ascii=False))
    return result


def _parse_receipt(path: pathlib.Path) -> dict[str, Any]:
    try:
        receipt = read_json(path)
    except (OSError, ValueError) as exc:
        raise CampaignError(f"No valid final receipt: {exc}") from exc
    if (not isinstance(receipt, dict) or set(receipt) != set(FINAL_SCHEMA["required"]) or
            receipt["status"] not in {"continue", "complete", "blocked"} or
            any(not isinstance(receipt[key], str) for key in ("summary", "next_action", "stop_reason")) or
            not isinstance(receipt["evidence"], list) or
            any(not isinstance(item, str) for item in receipt["evidence"])):
        raise CampaignError("Final receipt does not match the campaign schema")
    return receipt


@dataclass(frozen=True)
class InvocationOutcome:
    events: dict[str, Any]
    receipt: dict[str, Any] | None
    error: str
    reset_session: bool
    blocked: bool


class CodexInvocation:
    """Build the command and classify its durable result without launching it."""

    @staticmethod
    def command(state: dict[str, Any], campaign: pathlib.Path, number: int) -> list[str]:
        message = str(turn_directory(campaign, number) / "message.json")
        common = ["--json", "--output-schema", str(campaign / "receipt.schema.json"), "-o", message]
        if state["model"]:
            common += ["--model", state["model"]]
        if state["session_id"] and state["next_mode"] != "rethink":
            return [state["agent_bin"], "exec", "resume", "--skip-git-repo-check",
                    *common, state["session_id"], "-"]
        command = [state["agent_bin"], "exec", "-C", state["workspace"], "--skip-git-repo-check",
                   "--sandbox", state["sandbox"], *common]
        for directory in sorted({str(campaign), str(pathlib.Path(state["archive"]).parent)}):
            if directory != state["workspace"]:
                command += ["--add-dir", directory]
        return [*command, "-"]

    @staticmethod
    def observe(directory: pathlib.Path, result: dict[str, Any], *, quarantined: bool) -> InvocationOutcome:
        events = _parse_events(directory / "events.jsonl")
        error = result.get("error", "")
        receipt = None
        try:
            if result["returncode"] != 0:
                raise CampaignError(f"Agent process exited with code {result['returncode']}; {error}")
            if error:
                raise CampaignError(error)
            if events["terminal"] != "turn.completed":
                raise CampaignError("CLI did not record a successful turn.completed terminal event")
            if quarantined:
                raise CampaignError("Unconfirmed archive suffix quarantined; reconcile its artifacts")
            receipt = _parse_receipt(directory / "message.json")
        except CampaignError as exc:
            error = str(exc)
        reset_session = blocked = False
        if receipt is None:
            diagnostics = "\n".join(events["errors"])
            stderr = directory / "stderr.log"
            if stderr.exists():
                diagnostics += stderr.read_text(errors="replace")[-16000:]
            low = diagnostics.lower()
            reset_session = any(text in low for text in (
                "session not found", "no saved session", "could not find session", "failed to load session", "rollout not found"))
            auth = any(text in low for text in (
                "not logged in", "authentication required", "invalid_api_key", "incorrect api key",
                "unauthorized: 401", "401 unauthorized", "please run codex login"))
            configuration = any(text in low for text in (
                "unexpected argument", "unrecognized option", "unknown option", "unsupported model"))
            blocked = bool(auth or configuration or result.get("survivors") or
                           result.get("launch_errno") in {errno.ENOENT, errno.EACCES, errno.ENOSPC, errno.EROFS})
        return InvocationOutcome(events, receipt, error, reset_session, blocked)
