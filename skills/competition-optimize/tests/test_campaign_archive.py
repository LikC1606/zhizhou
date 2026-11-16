from __future__ import annotations

import copy
import importlib
import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")
campaign_archive = importlib.import_module("campaign_archive")
fixtures = importlib.import_module("test_campaign_search")


class CampaignArchiveTests(unittest.TestCase):
    # Reuse public archive fixtures without inheriting their unrelated tests.
    record = fixtures.CampaignSearchTests.record
    propose = fixtures.CampaignSearchTests.propose

    def setUp(self) -> None:
        fixtures.CampaignSearchTests.setUp(self)
        self.control = self.record("baseline", 10)
        self.store = campaign_archive.CampaignArchive(self.path)
        self.head = self.store.verified()
        self.prefix = self.path.read_bytes()
        self.directory = self.root / "turn"
        self.directory.mkdir()
        self.token = "sealed-turn-token"

    def receive(self, *, token: str | None = None):
        return self.store.receive(self.head.snapshot, token=token or self.token,
                                  directory=self.directory)

    def write(self, records: list[dict]) -> None:
        self.path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in records))

    def append_broken_suffix(self) -> bytes:
        self.record("unconfirmed", 11)
        with self.path.open("ab") as stream:
            stream.write(b'{"schema_version":1,"event":"candi')
        return self.path.read_bytes()[len(self.prefix):]

    def assert_quarantined(self, received, suffix: bytes) -> Path:
        self.assertTrue(received.quarantined)
        self.assertEqual(received.snapshot, self.head.snapshot)
        self.assertEqual(received.evidence.records, self.head.evidence.records)
        self.assertEqual(received.appended_events, [])
        self.assertEqual(received.delta, {key: 0 for key in self.head.evidence.counts})
        self.assertEqual(self.path.read_bytes(), self.prefix)
        journal = json.loads((self.directory / "archive-repair.json").read_text())
        tail = Path(journal["quarantine"])
        self.assertEqual(tail.read_bytes(), suffix)
        self.assertEqual(journal["suffix_sha256"], archive.sha256(suffix))
        self.assertEqual(journal["confirmed_prefix"], self.head.snapshot)
        self.assertEqual(journal["token"], self.token)
        return tail

    def test_missing_empty_archive_has_a_usable_head(self) -> None:
        missing = self.root / "missing.jsonl"
        store = campaign_archive.CampaignArchive(missing)
        head = store.verified()
        self.assertEqual(head.snapshot, {"size": 0, "sha256": archive.sha256(b"")})
        with store.confirmed(head.snapshot) as evidence:
            self.assertEqual(evidence.records, [])
        received = store.receive(head.snapshot, token=self.token, directory=self.directory)
        self.assertEqual(received.evidence.records, [])
        self.assertEqual(received.appended_events, [])
        self.assertFalse(received.quarantined)
        self.assertFalse(missing.exists())

    def test_verified_checks_every_candidate_result_and_artifact(self) -> None:
        self.record("second", 11)
        unchanged = self.path.read_bytes()
        for entry in (self.control, self.entries["second"]):
            for path in (Path(entry["artifact_paths"]["source"]),
                         Path(entry["result"]["result_path"])):
                with self.subTest(candidate=entry["candidate_id"], path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original + b"# changed\n")
                    with self.assertRaises(archive.ArchiveFailure):
                        self.store.verified()
                    self.assertEqual(self.path.read_bytes(), unchanged)
                    path.write_bytes(original)
        self.assertEqual(len(self.store.verified().evidence.records), 2)

    def test_verified_compares_archived_metadata_with_result_file(self) -> None:
        records = copy.deepcopy(self.head.evidence.records)
        records[0]["result"]["execution_status"] = "failed"
        self.write(records)
        unchanged = self.path.read_bytes()
        with self.assertRaisesRegex(campaign_archive.CampaignError, "metadata differs"):
            self.store.verified()
        self.assertEqual(self.path.read_bytes(), unchanged)

    def test_confirmed_does_not_verify_old_candidate_files(self) -> None:
        Path(self.control["artifact_paths"]["source"]).unlink()
        Path(self.control["result"]["result_path"]).unlink()
        with self.store.confirmed(self.head.snapshot) as evidence:
            self.assertEqual(evidence.records, self.head.evidence.records)
            self.assertEqual(evidence.counts, self.head.evidence.counts)
        with self.assertRaises(OSError):
            self.store.verified(self.head.snapshot)

    def test_confirmed_detects_changes_before_scope(self) -> None:
        self.record("outside-turn", 11)
        changed = self.path.read_bytes()
        with self.assertRaisesRegex(campaign_archive.CampaignError, "outside a campaign turn"):
            with self.store.confirmed(self.head.snapshot):
                self.fail("Changed archive must not be handed to the caller")
        self.assertEqual(self.path.read_bytes(), changed)

    def test_confirmed_detects_changes_on_normal_scope_exit(self) -> None:
        entered = False
        with self.assertRaisesRegex(campaign_archive.CampaignError, "preparing context"):
            with self.store.confirmed(self.head.snapshot) as evidence:
                entered = True
                self.assertEqual(evidence.records, self.head.evidence.records)
                self.record("changed-during-handoff", 11)
        self.assertTrue(entered)
        self.assertEqual(len(archive.read_records(self.path)), 2)

    def test_unchanged_receive_returns_zero_delta(self) -> None:
        received = self.receive()
        self.assertEqual(received.snapshot, self.head.snapshot)
        self.assertEqual(received.evidence.records, self.head.evidence.records)
        self.assertEqual(received.appended_events, [])
        self.assertEqual(received.delta, {key: 0 for key in self.head.evidence.counts})
        self.assertFalse(received.quarantined)
        self.assertIsNone(received.quarantine_event)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_valid_receive_returns_only_appended_events_and_count_changes(self) -> None:
        self.propose("pending", "baseline")
        self.record("improved", 12)
        expected = archive.read_records(self.path)
        current = self.path.read_bytes()
        received = self.receive()
        self.assertEqual(received.evidence.records, expected)
        self.assertEqual(received.appended_events, expected[1:])
        self.assertEqual(received.snapshot, {"size": len(current), "sha256": archive.sha256(current)})
        self.assertEqual(received.delta, {
            "events": 2, "candidates": 1, "executed_implementations": 1,
            "evaluated_candidates": 1, "diagnostic_evaluations": 0,
            "measurable_candidates": 1, "proposals": 1, "pending_proposals": 1,
        })
        self.assertFalse(received.quarantined)
        self.assertIsNone(received.quarantine_event)
        self.assertEqual(self.path.read_bytes(), current)

    def test_receive_checks_only_new_candidate_files(self) -> None:
        self.record("new", 11)
        Path(self.control["artifact_paths"]["source"]).unlink()
        Path(self.control["result"]["result_path"]).unlink()
        received = self.receive()
        self.assertEqual([entry["candidate_id"] for entry in received.appended_events], ["new"])
        self.assertEqual(received.delta["executed_implementations"], 1)
        self.assertFalse(received.quarantined)

    def test_repeated_receive_with_sealed_token_returns_same_facts(self) -> None:
        self.record("new", 11)
        current = self.path.read_bytes()
        first, second = self.receive(), self.receive()
        self.assertEqual(first.snapshot, second.snapshot)
        self.assertEqual(first.evidence.records, second.evidence.records)
        self.assertEqual(first.appended_events, second.appended_events)
        self.assertEqual(first.delta, second.delta)
        self.assertEqual(first.quarantined, second.quarantined)
        self.assertEqual(first.quarantine_event, second.quarantine_event)
        self.assertEqual(self.path.read_bytes(), current)

    def test_confirmed_prefix_damage_is_rejected_without_repair(self) -> None:
        operations = {
            "receive": self.receive,
            "verified": lambda: self.store.verified(self.head.snapshot),
        }

        def confirmed() -> None:
            with self.store.confirmed(self.head.snapshot):
                self.fail("Damaged prefix must not reach the caller")

        operations["confirmed"] = confirmed
        for damage in ("edited", "truncated", "missing"):
            for name, operation in operations.items():
                with self.subTest(damage=damage, operation=name):
                    changed = (self.prefix.replace(b"baseline", b"tampered") if damage == "edited"
                               else self.prefix[:10] if damage == "truncated" else None)
                    self.path.unlink(missing_ok=True)
                    if changed is not None:
                        self.path.write_bytes(changed)
                    with self.assertRaises(campaign_archive.CampaignError):
                        operation()
                    self.assertEqual(self.path.read_bytes() if self.path.exists() else None, changed)
                    self.assertEqual(list(self.directory.iterdir()), [])
                    self.path.write_bytes(self.prefix)

    def test_bad_suffix_is_quarantined_as_a_whole_including_valid_events(self) -> None:
        suffix = self.append_broken_suffix()
        received = self.receive()
        tail = self.assert_quarantined(received, suffix)
        self.assertEqual(json.loads(suffix.splitlines()[0])["candidate_id"], "unconfirmed")
        self.assertEqual(received.quarantine_event["event"], "unconfirmed_archive_quarantined")
        self.assertEqual(received.quarantine_event["evidence"], str(tail))
        self.assertNotIn("turn", received.quarantine_event)
        self.assertNotIn("token", received.quarantine_event)

    def test_new_result_and_artifact_damage_quarantine_the_append(self) -> None:
        for field in ("result", "source"):
            with self.subTest(field=field):
                self.record("damaged-" + field, 11)
                entry = self.entries["damaged-" + field]
                path = Path(entry["result"]["result_path"] if field == "result"
                            else entry["artifact_paths"]["source"])
                path.write_bytes(path.read_bytes() + b"# damaged\n")
                suffix = self.path.read_bytes()[len(self.prefix):]
                received = self.receive()
                self.assert_quarantined(received, suffix)
                # Each subtest represents a distinct fresh turn.
                for file in self.directory.iterdir():
                    file.unlink()

    def test_new_metadata_mismatch_quarantines_without_accepting_candidate(self) -> None:
        self.record("new", 11)
        records = archive.read_records(self.path)
        records[-1]["result"]["execution_status"] = "failed"
        self.path.write_bytes(self.prefix + archive.canonical(records[-1]) + b"\n")
        suffix = self.path.read_bytes()[len(self.prefix):]
        received = self.receive()
        self.assert_quarantined(received, suffix)
        self.assertIn("metadata differs", received.quarantine_event["error"])

    def test_partial_quarantine_before_journal_is_replaced_before_truncation(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        self.path.write_bytes(self.prefix + suffix)
        (self.directory / "archive-repair.json").unlink()
        tail.write_bytes(suffix[:8])
        received = self.receive()
        self.assertEqual(self.assert_quarantined(received, suffix), tail)

    def test_existing_journal_before_truncation_recovers_the_same_suffix(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        self.path.write_bytes(self.prefix + suffix)
        received = self.receive()
        self.assertEqual(self.assert_quarantined(received, suffix), tail)
        self.assertIsNotNone(received.quarantine_event)

    def test_already_truncated_receive_preserves_quarantine_status(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        received = self.receive()
        self.assertEqual(self.assert_quarantined(received, suffix), tail)
        self.assertIsNone(received.quarantine_event)

    def test_journal_token_mismatch_blocks_before_any_archive_repair(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        current = self.prefix + suffix
        self.path.write_bytes(current)
        with self.assertRaisesRegex(campaign_archive.CampaignError, "journal/evidence was modified"):
            self.receive(token="different-turn-token")
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(tail.read_bytes(), suffix)

    def test_quarantine_evidence_hash_mismatch_blocks_without_truncation(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        current = self.prefix + suffix
        self.path.write_bytes(current)
        tail.write_bytes(suffix + b"changed")
        with self.assertRaisesRegex(campaign_archive.CampaignError, "journal/evidence was modified"):
            self.receive()
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(tail.read_bytes(), suffix + b"changed")

    def test_unreadable_journal_is_not_replaced_or_treated_as_no_repair(self) -> None:
        suffix = self.append_broken_suffix()
        tail = self.assert_quarantined(self.receive(), suffix)
        current = self.prefix + suffix
        self.path.write_bytes(current)
        repair = self.directory / "archive-repair.json"
        repair.write_bytes(b"{broken")
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.path.read_bytes(), current)
        self.assertEqual(repair.read_bytes(), b"{broken")
        self.assertEqual(tail.read_bytes(), suffix)


if __name__ == "__main__":
    unittest.main()
