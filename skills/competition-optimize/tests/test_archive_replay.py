from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")


class ArchiveReplayTests(unittest.TestCase):
    """Preserve sequential archive validation while reusing per-read indexes."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "archive.jsonl"
        self.entries: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.sequence = 0
        self.control = self.record("control", 10)

    def record(self, name: str, score: int, *, proposal: str | None = None,
               role: str = "development") -> dict:
        self.sequence += 1
        folder = self.root / str(self.sequence)
        folder.mkdir()
        source = folder / "solve.py"
        source.write_text(f"# {name}\nprint({score})\n", encoding="utf-8")
        run = subprocess.run(["/usr/bin/python3", str(source)], check=True,
                             capture_output=True, text=True)
        receipt = {"status": "success", "valid": True, "candidate_hash": archive.hash_path(source),
                   "candidate_scope": "program_source", "evaluator_hash": "e" * 64,
                   "workload_hash": "w" * 64, "score_model_hash": "m" * 64,
                   "stage": "development",
                   "score": {"kind": "official_metric", "metric": "quality",
                             "direction": "maximize", "value": int(run.stdout)}}
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--source", str(source), "--result", str(result), "--route", "main",
                "--mechanism", name, "--status", "runner_up", "--role", role,
                "--feedback", "Inspected actual executed outcome"]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", "supported"]
            for parent_id in self.proposals[proposal]["parent_ids"]:
                args += ["--parent", parent_id]
        entry = archive.record_candidate(archive.parser().parse_args(args))
        self.entries[name] = entry
        return entry

    def propose(self, name: str, mode: str | None = None, parent: str = "control") -> dict:
        value = {"proposal_id": name, "parent_ids": [parent], "feedback_from": [parent],
                 "route": "main", "basis": "The executed control leaves a measurable residual",
                 "change": "Implement a new construction", "expected_observation": "Score improves",
                 "validation": "Use the fixed development adapter",
                 "stop_condition": "Record actual success or failure",
                 "code_targets": [] if mode == "independent" else [self.entries[parent]["artifact_paths"]["source"]]}
        if mode is not None:
            value["construction_mode"] = mode
        self.sequence += 1
        path = self.root / f"proposal-{self.sequence}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        event = archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.proposals[name] = event
        return event

    def chain(self) -> list[dict]:
        self.propose("legacy")
        self.record("legacy-child", 11, proposal="legacy")
        self.propose("independent", "independent")
        self.record("independent-child", 12, proposal="independent")
        self.propose("refinement", "refinement", "legacy-child")
        self.record("refinement-child", 13, proposal="refinement")
        self.propose("pending", "independent")
        self.propose("stopped")
        archive.stop_proposal(archive.parser().parse_args(
            ["stop", "--archive", str(self.path), "--proposal-id", "stopped",
             "--reason", "Superseded before implementation"]))
        return archive.read_records(self.path)

    def write(self, records: list[dict]) -> None:
        self.path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in records))

    def failure(self, operation, kind: str, message: str) -> None:
        with self.assertRaises(archive.ArchiveFailure) as caught:
            operation()
        self.assertEqual((caught.exception.kind, str(caught.exception)), (kind, message))

    def test_mixed_public_api_history_replays_in_order_without_rewriting(self) -> None:
        records = self.chain()
        before = self.path.read_bytes()
        self.assertEqual(archive.read_records(self.path), records)
        self.assertEqual(archive.parse_records(before, str(self.path)), records)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([entry["event"] for entry in records],
                         ["candidate", "proposal", "candidate", "proposal", "candidate",
                          "proposal", "candidate", "proposal", "proposal", "proposal_stop"])
        self.assertNotIn("construction_mode", records[1])
        self.assertNotIn("construction_mode", records[2])
        self.assertEqual(records[3]["construction_mode"], "independent")
        self.assertEqual(records[5]["construction_mode"], "refinement")
        trace = archive.iteration_trace(records)
        self.assertEqual([row["state"] for row in trace],
                         ["evaluated_valid", "evaluated_valid", "evaluated_valid", "pending", "stopped"])

    def test_first_invalid_event_and_validator_error_precedence_are_preserved(self) -> None:
        self.propose("independent", "independent")
        self.record("child", 11, proposal="independent")
        records = archive.read_records(self.path)
        cases = []
        bad = copy.deepcopy(records)
        bad[1]["parent_ids"] = ["missing"]
        bad[1]["code_targets"] = ["also-invalid"]
        cases.append((bad, "invalid_proposal", "parent_ids must name distinct archived candidates"))
        bad = copy.deepcopy(records)
        bad[2]["candidate_id"] = "control"
        bad[2]["proposal_id"] = "missing"
        cases.append((bad, "invalid_archive", f"{self.path}:3: duplicate ID or unknown parent"))
        bad = copy.deepcopy(records)
        bad[2]["construction_mode"] = "refinement"
        bad[2]["result"]["result_sha256"] = bad[0]["result"]["result_sha256"]
        cases.append((bad, "proposal_mismatch", "Successor construction mode must match its proposal"))
        bad = copy.deepcopy(records)
        bad[2]["prediction_status"] = "not-recorded"
        bad[2]["result"]["result_sha256"] = bad[0]["result"]["result_sha256"]
        cases.append((bad, "missing_prediction_status",
                      "Record whether the proposed observation was supported, contradicted or unresolved"))
        bad = copy.deepcopy(records)
        stopped = {"schema_version": 1, "event": "proposal_stop", "proposal_id": "independent",
                   "reason": "Stopped before candidate"}
        bad.insert(2, stopped)
        cases.append((bad, "invalid_archive", "Candidate names an unknown or closed proposal"))
        for index, (bad, kind, message) in enumerate(cases):
            self.write(bad)
            with self.subTest(case=index):
                self.failure(lambda: archive.parse_records(self.path.read_bytes(), str(self.path)), kind, message)

    def test_result_reuse_checks_unrelated_history_and_legacy_digest_equality(self) -> None:
        self.record("unrelated-confirmation", 999, role="confirmation")
        self.propose("independent", "independent")
        self.record("child", 11, proposal="independent")
        records = archive.read_records(self.path)
        for digest in (records[1]["result"]["result_sha256"], None, ["legacy"], {"legacy": True}):
            changed = copy.deepcopy(records)
            changed[1]["result"]["result_sha256"] = digest
            changed[-1]["result"]["result_sha256"] = copy.deepcopy(digest)
            self.write(changed)
            with self.subTest(digest=digest):
                self.failure(lambda: archive.parse_records(self.path.read_bytes(), str(self.path)), "reused_execution_evidence",
                             "An old result cannot complete a new implementation proposal")
                self.failure(lambda: archive.validate_successor(changed[-1], changed[-2], changed[:-1]),
                             "reused_execution_evidence",
                             "An old result cannot complete a new implementation proposal")

    def test_each_read_replays_current_bytes_without_a_stale_index(self) -> None:
        self.propose("independent", "independent")
        self.record("child", 11, proposal="independent")
        original = archive.read_records(self.path)
        changed = copy.deepcopy(original)
        changed[-1]["result"]["result_sha256"] = original[0]["result"]["result_sha256"]
        self.write(changed)
        self.failure(lambda: archive.read_records(self.path), "reused_execution_evidence",
                     "An old result cannot complete a new implementation proposal")
        self.write(original)
        self.assertEqual(archive.read_records(self.path), original)
        self.propose("new-pending", "independent")
        updated = archive.read_records(self.path)
        self.assertEqual(updated[:-1], original)
        self.assertEqual(updated[-1]["proposal_id"], "new-pending")
        updated[0]["candidate_id"] = "replacement"
        self.write(updated)
        self.failure(lambda: archive.read_records(self.path), "invalid_proposal",
                     "parent_ids must name distinct archived candidates")

    def test_byte_replay_needs_no_archive_or_artifact_files(self) -> None:
        expected = self.chain()
        raw = self.path.read_bytes()
        for path in self.root.rglob("*"):
            if path.is_file():
                path.unlink()
        self.assertEqual(archive.parse_records(raw, "sealed-prefix"), expected)

    def test_byte_replay_keeps_physical_lines_and_rejects_incomplete_tail(self) -> None:
        raw = self.path.read_bytes()
        self.failure(lambda: archive.parse_records(raw + b"\n{}\n", "sealed-prefix"),
                     "invalid_archive", "sealed-prefix:3: expected schema_version 1 object")
        self.failure(lambda: archive.parse_records(raw[:-1], "sealed-prefix"),
                     "incomplete_event", "Archive ends without a newline; reconcile the interrupted write first")
        self.assertEqual(archive.parse_records(b"", "empty-prefix"), [])

    def test_file_reader_keeps_missing_and_nonfile_behavior(self) -> None:
        self.assertEqual(archive.read_records(self.root / "missing.jsonl"), [])
        self.failure(lambda: archive.read_records(self.root), "invalid_archive",
                     f"Archive is not a file: {self.root}")

    def test_standalone_validators_keep_their_original_no_keyword_path(self) -> None:
        self.propose("independent", "independent")
        self.record("child", 11, proposal="independent")
        records = archive.read_records(self.path)
        with mock.patch.object(archive, "candidate_index", wraps=archive.candidate_index) as index:
            archive.validate_proposal(records[1], records[:1])
            archive.validate_successor(records[2], records[1], records[:2])
        self.assertEqual(index.call_count, 2)
        bad = copy.deepcopy(records[2])
        bad["parent_ids"] = []
        self.failure(lambda: archive.validate_successor(bad, records[1], records[:2]),
                     "proposal_mismatch",
                     "Successor must use the proposal's parents and route in development or diagnostic work")


if __name__ == "__main__":
    unittest.main()
