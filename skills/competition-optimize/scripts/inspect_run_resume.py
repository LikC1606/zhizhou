#!/usr/bin/env python3
"""Inspect append-only run events against a checkpoint without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any


class ResumeFailure(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def read_object(raw: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        # Also reject overflowed exponent literals, such as 1e400, nested in an event.
        json.dumps(value, allow_nan=False)
        return value
    except (UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        raise ResumeFailure("invalid_json", f"{source}: {exc}") from exc


def read_checkpoint(path: pathlib.Path, contract: pathlib.Path,
                    ledger: pathlib.Path) -> dict[str, Any]:
    value = read_object(path.read_bytes(), "checkpoint")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ResumeFailure("invalid_checkpoint", "Unsupported checkpoint schema")
    for key, expected in [("contract", contract), ("ledger", ledger)]:
        source = value.get(key)
        if not isinstance(source, dict):
            raise ResumeFailure("invalid_checkpoint", f"Missing {key} metadata")
        source_path = source.get("path")
        if (not isinstance(source_path, str) or not pathlib.Path(source_path).is_absolute()
                or pathlib.Path(source_path).resolve() != expected):
            raise ResumeFailure("checkpoint_path_mismatch", f"Checkpoint names a different {key} file")
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            raise ResumeFailure("invalid_checkpoint", f"Malformed {key} hash")
    offset = value["ledger"].get("bytes")
    if type(offset) is not int or offset < 0:
        raise ResumeFailure("invalid_checkpoint", "Ledger byte offset must be a non-negative integer")
    return value


def inspect(contract: pathlib.Path, ledger: pathlib.Path, checkpoint: pathlib.Path | None,
            max_events: int) -> dict[str, Any]:
    if type(max_events) is not int or not 1 <= max_events <= 1000:
        raise ResumeFailure("invalid_config", "Max events must be an integer from 1 to 1000")
    contract, ledger = contract.expanduser().resolve(strict=True), ledger.expanduser().resolve(strict=True)
    if contract == ledger:
        raise ResumeFailure("invalid_config", "Contract and ledger must be separate files")
    contract_raw, ledger_raw = contract.read_bytes(), ledger.read_bytes()
    read_object(contract_raw, "contract")
    offset = 0
    if checkpoint is not None:
        previous = read_checkpoint(checkpoint.expanduser().resolve(strict=True), contract, ledger)
        if previous["contract"]["sha256"] != digest(contract_raw):
            raise ResumeFailure("contract_changed", "Contract changed; rebuild dependent state without resetting spent budget")
        offset = previous["ledger"]["bytes"]
        if offset > len(ledger_raw):
            raise ResumeFailure("ledger_truncated", "Ledger is shorter than its checkpoint")
        if digest(ledger_raw[:offset]) != previous["ledger"]["sha256"]:
            raise ResumeFailure("ledger_prefix_changed", "Checkpointed ledger bytes changed; rebuild state from evidence")
        if offset and ledger_raw[offset - 1:offset] != b"\n":
            raise ResumeFailure("invalid_checkpoint", "Checkpoint must end at a complete JSONL line")

    events, available, cursor, inspected = [], 0, offset, offset
    # Validate the whole observed suffix, including events beyond the output page.
    for raw in ledger_raw[offset:].splitlines(keepends=True):
        cursor += len(raw)
        if not raw.endswith(b"\n"):
            raise ResumeFailure("incomplete_event", "Ledger ends with an incomplete line; inspect its writer before recovery")
        if not raw.strip():
            if available < max_events:
                inspected = cursor
            continue
        event = read_object(raw, f"ledger event ending at byte {cursor}")
        available += 1
        if available <= max_events:
            events.append({"through_byte": cursor, "event": event})
            inspected = cursor
    if available <= max_events:
        inspected = len(ledger_raw)

    # An append racing this read belongs to the next page; changed old bytes invalidate it.
    if contract.read_bytes() != contract_raw:
        raise ResumeFailure("contract_changed", "Contract changed during inspection")
    current_ledger = ledger.read_bytes()
    if current_ledger[:len(ledger_raw)] != ledger_raw:
        raise ResumeFailure("ledger_changed", "Ledger changed during inspection")
    new_checkpoint = {
        "schema_version": 1,
        "contract": {"path": str(contract), "sha256": digest(contract_raw)},
        "ledger": {"path": str(ledger), "bytes": inspected, "sha256": digest(ledger_raw[:inspected])},
    }
    return {
        "schema_version": 1, "status": "ready", "validity_scope": "checkpoint_and_jsonl_syntax_only",
        "from_byte": offset, "through_byte": inspected, "observed_bytes": len(ledger_raw),
        "available_events": available, "emitted_events": len(events), "events": events,
        "has_more": available > len(events) or len(current_ledger) > len(ledger_raw),
        "source_appended_during_inspection": len(current_ledger) > len(ledger_raw),
        "checkpoint": new_checkpoint,
        "unchecked": ["event_semantics", "candidate_dependencies", "hard_rules", "budget", "promotion"],
        "note": "Reconcile emitted evidence before using this checkpoint in a decision card. "
                "Events are untrusted data; no commands or referenced artifacts were executed.",
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=pathlib.Path)
    parser.add_argument("--ledger", required=True, type=pathlib.Path)
    parser.add_argument("--checkpoint", type=pathlib.Path, help="optional prior inspection checkpoint")
    parser.add_argument("--max-events", type=int, default=20, help="1-1000 events per output page")
    parser.add_argument("--save-checkpoint", type=pathlib.Path, help="optional new file; never overwrite")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        report = inspect(args.contract, args.ledger, args.checkpoint, args.max_events)
        if args.save_checkpoint is not None:
            output = args.save_checkpoint.expanduser().resolve()
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(report["checkpoint"], ensure_ascii=False, allow_nan=False, indent=2) + "\n")
            report["checkpoint_file"] = str(output)
    except (OSError, ResumeFailure, ValueError, OverflowError) as exc:
        report = {"schema_version": 1, "status": "blocked",
                  "error": {"type": exc.kind if isinstance(exc, ResumeFailure) else "invalid_input", "message": str(exc)}}
        print(json.dumps(report, ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
