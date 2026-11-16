"""Confirmed archive reads and per-turn evidence acceptance for the driver.

Callers own resource locks, worker exit verification and campaign persistence.
This module owns archive bytes and repair evidence, not receipt success. No
evidence or file verification cache survives an operation.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, TypedDict

import candidate_archive as archive_tools
from campaign_runtime import CampaignError, atomic_bytes, atomic_json, file_hash, read_json
from campaign_search import CampaignEvidence


class ArchivePrefix(TypedDict):
    size: int
    sha256: str


@dataclass(frozen=True)
class ArchiveHead:
    snapshot: ArchivePrefix
    evidence: CampaignEvidence


@dataclass(frozen=True)
class ReceivedArchive:
    snapshot: ArchivePrefix
    evidence: CampaignEvidence
    appended_events: list[dict[str, Any]]
    delta: dict[str, int]
    quarantined: bool
    quarantine_event: dict[str, Any] | None


class CampaignArchive:
    """Read or receive an archive under the driver's existing single-writer lock.

    Returned evidence borrows its records; callers must not mutate them. These
    methods never save campaign state or acknowledge a handoff. A failed CLI
    invocation can still supply valid records to receive().
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def _snapshot(self, prefix_bytes: int | None = None) -> ArchivePrefix:
        path = self._path
        if not path.exists():
            if prefix_bytes not in (None, 0):
                raise CampaignError("Candidate archive disappeared")
            return {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        if not path.is_file():
            raise CampaignError("Candidate archive is not a regular file")
        size = path.stat().st_size
        if prefix_bytes is not None and size < prefix_bytes:
            raise CampaignError("Confirmed candidate archive was truncated")
        remaining = size if prefix_bytes is None else prefix_bytes
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise CampaignError("Candidate archive changed while reading")
                digest.update(chunk)
                remaining -= len(chunk)
        return {"size": size if prefix_bytes is None else prefix_bytes, "sha256": digest.hexdigest()}

    def _require_unchanged(self, expected: ArchivePrefix) -> None:
        if self._snapshot() != expected:
            raise CampaignError("Candidate archive changed outside a campaign turn; inspect before resume")

    def _require_prefix(self, expected: ArchivePrefix) -> None:
        if self._snapshot(expected["size"]) != expected:
            raise CampaignError("Confirmed candidate archive history was edited in place")

    def _prefix_records(self, size: int) -> list[dict[str, Any]]:
        if not size:
            return []
        with self._path.open("rb") as stream:
            raw = stream.read(size)
        return archive_tools.parse_records(raw, str(self._path))

    @staticmethod
    def _verify_candidates(records: list[dict[str, Any]]) -> None:
        for entry in records:
            if entry["event"] != "candidate":
                continue
            archive_tools.verify_result(entry)
            archive_tools.verify_artifacts(entry)
            result = entry["result"]
            if result.get("result_path") and archive_tools.result_metadata(
                    pathlib.Path(result["result_path"]), include_case_profile="case_profile" in result,
                    include_resource_profile="resource_profile" in result) != result:
                raise CampaignError(f"Archived result metadata differs from its file: {entry['candidate_id']}")

    def verified(self, expected: ArchivePrefix | None = None) -> ArchiveHead:
        """Fully verify results, artifacts and metadata at creation or recovery.

        When expected is supplied, the entire file must match it. Errors remain
        errors; missing referenced files never become an empty evidence view.
        """
        snapshot = self._snapshot()
        if expected is not None and snapshot != expected:
            raise CampaignError("Candidate archive changed outside a campaign turn; inspect before resume")
        records = archive_tools.read_records(self._path)
        self._verify_candidates(records)
        if self._snapshot() != snapshot:
            raise CampaignError("Candidate archive changed while verifying evidence")
        return ArchiveHead(snapshot, CampaignEvidence(records))

    @contextmanager
    def confirmed(self, expected: ArchivePrefix) -> Iterator[CampaignEvidence]:
        """Check the whole file before and after preparing a read-only handoff.

        Only construct copied state, plans and packets inside this scope. It is
        not a transaction: save the turn intent only after normal scope exit.
        No candidate file verification happens here; handoff verifies its cards.
        """
        self._require_unchanged(expected)
        evidence = CampaignEvidence(self._prefix_records(expected["size"]))
        yield evidence
        if self._snapshot() != expected:
            raise CampaignError("Candidate archive changed while preparing context")

    def receive(self, before: ArchivePrefix, *, token: str,
                directory: pathlib.Path) -> ReceivedArchive:
        """Accept a complete suffix, or preserve and quarantine all of it.

        Call only after worker exit and output identity verification. Replay
        checks the full history, but file checks cover new candidates only.
        Confirmed-prefix or repair-evidence damage blocks without truncation.
        Reusing a sealed prefix/token after a crash preserves quarantine status.
        """
        self._require_prefix(before)
        old_records = self._prefix_records(before["size"])
        repair = directory / "archive-repair.json"
        quarantined = repair.exists()
        if quarantined:
            journal = read_json(repair)
            if (journal["token"] != token or
                    file_hash(pathlib.Path(journal["quarantine"])) != journal["suffix_sha256"]):
                raise CampaignError("Archive quarantine journal/evidence was modified")
        quarantine_event = None
        try:
            records = archive_tools.read_records(self._path)
            self._verify_candidates(records[len(old_records):])
        except (archive_tools.ArchiveFailure, CampaignError, OSError) as exc:
            # Only the unconfirmed suffix may be removed. Preserve it completely
            # before writing the journal, then truncate and fsync the archive.
            self._require_prefix(before)
            self._prefix_records(before["size"])
            raw = self._path.read_bytes()
            suffix = raw[before["size"]:]
            if not suffix:
                raise CampaignError(f"Confirmed archive artifacts failed verification: {exc}") from exc
            suffix_hash = hashlib.sha256(suffix).hexdigest()
            tail = directory / ("quarantined-archive-" + suffix_hash + ".bin")
            if not tail.exists() or file_hash(tail) != suffix_hash:
                atomic_bytes(tail, suffix)
            if file_hash(tail) != suffix_hash:
                raise CampaignError("Archive suffix was not completely preserved")
            atomic_json(repair, {
                "token": token, "confirmed_prefix": before, "original": self._snapshot(),
                "quarantine": str(tail), "suffix_sha256": suffix_hash, "reason": str(exc),
            })
            with self._path.open("r+b") as stream:
                stream.truncate(before["size"])
                stream.flush()
                os.fsync(stream.fileno())
            quarantine_event = {"event": "unconfirmed_archive_quarantined",
                                "evidence": str(tail), "error": str(exc)}
            records = old_records
            quarantined = True
        evidence = CampaignEvidence(records)
        previous_counts, current_counts = CampaignEvidence(old_records).counts, evidence.counts
        delta = {key: current_counts[key] - previous_counts[key] for key in current_counts}
        return ReceivedArchive(self._snapshot(), evidence, records[len(old_records):], delta,
                               quarantined, quarantine_event)
