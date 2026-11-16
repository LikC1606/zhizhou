from __future__ import annotations

import copy
import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from handoff_fixtures import bounded_packet
archive = importlib.import_module("candidate_archive")
search = importlib.import_module("campaign_search")
learning = importlib.import_module("scoped_learning")
fixtures = importlib.import_module("test_scoped_learning")


class LearningRotationTests(unittest.TestCase):
    # Reuse public-API fixtures without collecting their original test cases.
    setUp = fixtures.ScopedLearningTests.setUp
    arguments = fixtures.ScopedLearningTests.arguments
    record = fixtures.ScopedLearningTests.record
    propose = fixtures.ScopedLearningTests.propose
    lesson = staticmethod(fixtures.ScopedLearningTests.lesson)
    learned = fixtures.ScopedLearningTests.learned
    brief = fixtures.ScopedLearningTests.brief

    def packet(self, seen=None):
        return search.handoff_packet(
            self.path, archive.read_records(self.path),
            {"sha256": "a" * 64, "size": 1}, "t" * 64,
            learning_seen=seen)

    @staticmethod
    def rows(packet):
        return packet["development_brief"]["scoped_learning"]["selection"]

    def retrieve(self, *, seen=None, related=None, limit=2):
        return learning.retrieve(
            archive.candidate_index(archive.read_records(self.path)),
            self.control["comparison"], set() if related is None else related,
            seen=seen, archive_path=self.path, limit=limit)

    def test_related_head_stays_visible_while_four_old_heads_rotate(self):
        for number in range(4):
            self.learned(f"old-{number}", lesson=self.lesson(key=f"old-{number}"))
        self.learned("related", score=200, lesson=self.lesson(key="related"))
        prefix = self.path.read_bytes()
        seen = {}
        for turn in range(1, 6):
            packet = self.packet(seen)
            rows = self.rows(packet)
            expected = ["related", f"old-{(turn - 1) % 4}"]
            self.assertEqual([row["candidate_id"] for row in rows], expected)
            self.assertEqual([row["retrieval_reason"] for row in rows],
                             ["recent_related", "least_recently_exposed"])
            self.assertEqual(rows[0]["last_exposed_turn"], turn - 1 if turn > 1 else None)
            self.assertEqual(rows[1]["last_exposed_turn"], 1 if turn == 5 else None)
            history = packet["development_brief"]["scoped_learning"]
            self.assertEqual((history["available"], history["omitted"]), (5, 3))
            self.assertEqual(learning.delivered(packet), expected)
            seen.update({candidate_id: turn for candidate_id in learning.delivered(packet)})
        self.assertEqual(set(seen), {"related", "old-0", "old-1", "old-2", "old-3"})
        self.assertEqual(self.path.read_bytes(), prefix)

    def test_current_reports_rotate_even_when_trial_ownership_is_an_older_comparison(self):
        changed = {"workload_hash": "new-development-workload"}
        for name in ("old-useful", "newer", "latest"):
            self.learned(name, lesson=self.lesson(key=name), comparison=changed)
        for number in range(8):
            self.record(f"current-{number}", 110 + number, comparison=changed)
        seen = {}
        observed = set()
        for turn in (1, 2):
            packet = self.packet(seen)
            self.assertEqual(packet["trial_history"]["available"], 0)
            self.assertEqual(set(packet["development_brief"]["candidates"]),
                             {f"current-{number}" for number in range(4, 8)})
            ids = learning.delivered(packet)
            observed.update(ids)
            seen.update({candidate_id: turn for candidate_id in ids})
        self.assertEqual(observed, {"old-useful", "newer", "latest"})

    def test_revision_is_an_unseen_head_and_never_rotates_its_superseded_report(self):
        self.learned("first")
        self.learned("other", lesson=self.lesson(key="other"))
        seen = {"first": 5, "other": 6}
        self.propose("revision", learning_from=["first"])
        self.record("new-head", 95, proposal="revision",
                    learning=self.lesson(evidence=["first"], revises="first"))
        current = self.retrieve(seen=seen)
        self.assertEqual(current["available"], 2)
        self.assertEqual([row["candidate_id"] for row in current["selection"]], ["new-head", "other"])
        self.assertIsNone(current["selection"][0]["last_exposed_turn"])
        self.assertEqual(current["selection"][0]["learning"]["revises"], "first")
        for turn in (7, 8, 9):
            current = self.retrieve(seen=seen)
            self.assertNotIn("first", [row["candidate_id"] for row in current["selection"]])
            seen.update({row["candidate_id"]: turn for row in current["selection"]})

    def test_standalone_brief_preserves_related_then_recent_default(self):
        self.learned("first")
        self.learned("newer", lesson=self.lesson(key="newer"))
        self.learned("latest", lesson=self.lesson(key="latest"))
        result = self.brief("first")["scoped_learning"]
        self.assertEqual([row["candidate_id"] for row in result["selection"]], ["first", "latest"])
        self.assertNotIn("selection_policy", result)
        self.assertNotIn("comparison_key", result)
        self.assertTrue(all("retrieval_sha256" not in row and "last_exposed_turn" not in row
                            for row in result["selection"]))
        rotating = self.packet()["development_brief"]["scoped_learning"]
        self.assertEqual(rotating["selection_policy"], "recent_related_then_least_recently_exposed")

    def test_confirmation_and_foreign_comparison_cannot_enter_current_rotation(self):
        self.learned("current")
        foreign = self.learned("foreign", lesson=self.lesson(key="foreign"),
                               comparison={"workload_hash": "foreign-workload"})
        confirmation = self.record("confirmation", 10000, role="confirmation")
        self.propose("confirmation-report")
        args, _ = self.arguments("invalid-report", proposal="confirmation-report",
                                  learning=self.lesson(key="confirmation"), role="confirmation")
        prefix = self.path.read_bytes()
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(args)
        self.assertEqual(self.path.read_bytes(), prefix)
        self.record("anchor-current", 110)
        seen = {"current": 10, "foreign": 1, "confirmation": 0}
        packet = self.packet(seen)
        self.assertEqual(learning.delivered(packet), ["current"])
        for entry in (foreign, confirmation):
            Path(entry["artifact_paths"]["source"]).write_bytes(b"changed excluded bytes\n")
        current = self.retrieve(seen=seen)
        self.assertEqual(current["available"], 1)
        self.assertEqual([row["candidate_id"] for row in current["selection"]], ["current"])

    def test_invalid_exposure_values_and_limits_are_rejected(self):
        self.learned()
        for seen in ([], "bad", {"": 0}, {" 	": 1}, {1: 0},
                     {"first": True}, {"first": -1}, {"first": 1.5}):
            with self.subTest(seen=seen), self.assertRaises(learning.LearningFailure):
                self.retrieve(seen=seen)
        for limit in (True, -1, 1.5):
            with self.subTest(limit=limit), self.assertRaises(learning.LearningFailure):
                self.retrieve(seen={}, limit=limit)
        self.assertEqual(self.retrieve(seen={}, limit=0)["selection"], [])
        self.assertEqual(len(self.retrieve(seen={}, limit=100)["selection"]), 1)

    def test_delivery_rejects_changed_reports_targets_evidence_and_missing_seal(self):
        self.learned()
        packet = self.packet()
        self.assertEqual(learning.delivered(packet), ["first"])
        mutations = {
            "lesson": lambda row: row["learning"].update(lesson="shortened report"),
            "conditions": lambda row: row["learning"].update(conditions="partial"),
            "missing_report_field": lambda row: row["learning"].pop("limitations"),
            "source_target": lambda row: row["evidence"]["first"]["artifact_paths"].update(source="/partial/source.py"),
            "result_target": lambda row: row["evidence"]["first"]["result"].update(result_path="/partial/result.json"),
            "evidence": lambda row: row["evidence"].pop("first"),
            "evidence_hash": lambda row: row["learning"].update(evidence_sha256="0" * 64),
            "missing_seal": lambda row: row.pop("retrieval_sha256"),
            "candidate": lambda row: row.update(candidate_id="other"),
        }
        for name, mutation in mutations.items():
            changed = copy.deepcopy(packet)
            mutation(self.rows(changed)[0])
            with self.subTest(name=name):
                self.assertEqual(learning.delivered(changed), [])
        for key, value in (("archive_path", str(self.root / "different.jsonl")),):
            changed = copy.deepcopy(packet)
            changed[key] = value
            self.assertEqual(learning.delivered(changed), [])
        changed = copy.deepcopy(packet)
        changed["development_brief"]["scoped_learning"]["comparison_key"] = "0" * 64
        self.assertEqual(learning.delivered(changed), [])
        changed = copy.deepcopy(packet)
        self.rows(changed)[0].update(retrieval_reason="shortened", last_exposed_turn=None)
        self.assertEqual(learning.delivered(changed), ["first"])

    def test_bounded_report_is_not_consumed_but_unchanged_report_survives_bounding(self):
        self.learned()
        packet = self.packet()
        self.assertEqual(learning.delivered(bounded_packet(packet)), ["first"])
        self.learned("long", lesson=self.lesson(key="long", text="Detailed conditional observation " * 4000))
        packet = {"archive_path": str(self.path),
                  "development_brief": {"comparison": self.control["comparison"],
                                        "scoped_learning": self.retrieve(seen={})}}
        self.assertEqual(set(learning.delivered(packet)), {"first", "long"})
        bounded = bounded_packet(packet)
        self.assertEqual(learning.delivered(bounded), ["first"])

    def test_new_retrieval_rechecks_source_and_result_bytes(self):
        self.learned()
        self.assertEqual(learning.delivered(self.packet()), ["first"])
        first = self.entries["first"]
        for location in (first["artifact_paths"]["source"], first["result"]["result_path"]):
            path = Path(location)
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            try:
                with self.subTest(location=location), self.assertRaises(archive.ArchiveFailure):
                    self.packet({"first": 1})
            finally:
                path.write_bytes(original)
            self.assertEqual(learning.delivered(self.packet({"first": 1})), ["first"])


if __name__ == "__main__":
    unittest.main()
