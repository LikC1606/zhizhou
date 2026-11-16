from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")
files = importlib.import_module("evidence_files")
search = importlib.import_module("campaign_search")
trials = importlib.import_module("campaign_trials")
fixtures = importlib.import_module("test_scoped_learning")


class EvidenceReadsTests(unittest.TestCase):
    # Reuse public-API fixtures without collecting the original test methods.
    setUp = fixtures.ScopedLearningTests.setUp
    arguments = fixtures.ScopedLearningTests.arguments
    record = fixtures.ScopedLearningTests.record
    propose = fixtures.ScopedLearningTests.propose
    lesson = staticmethod(fixtures.ScopedLearningTests.lesson)
    learned = fixtures.ScopedLearningTests.learned

    def assert_kind(self, operation, kind: str) -> None:
        with self.assertRaises(archive.ArchiveFailure) as caught:
            operation()
        self.assertEqual(caught.exception.kind, kind)

    def wait_for_stable_fixtures(self) -> None:
        paths = [Path(value) for entry in self.entries.values()
                 for value in (*entry["artifact_paths"].values(), entry["result"]["result_path"])]
        latest = max(max(path.stat().st_mtime_ns, path.stat().st_ctime_ns) for path in paths)
        delay = (latest + 1_050_000_000 - time.time_ns()) / 1_000_000_000
        if delay > 0:
            time.sleep(delay)

    def learning_chain(self) -> list[dict]:
        self.learned(lesson=self.lesson(evidence=["control"]))
        self.propose("apply", learning_from=["first"])
        self.record("application", 105, proposal="apply")
        return archive.read_records(self.path)

    def brief(self, records: list[dict], *, reads=None) -> dict:
        args = archive.parser().parse_args(["brief", "--archive", str(self.path)])
        return archive.optimization_brief(args, records, reads=reads)

    def packet(self, records: list[dict]) -> dict:
        return search.handoff_packet(self.path, records, {"sha256": "a" * 64, "size": 1}, "t" * 64)

    @staticmethod
    def counted_reads(counts: Counter):
        original = Path.read_bytes

        def read(path: Path) -> bytes:
            counts[path.resolve()] += 1
            return original(path)

        return read

    def test_file_digest_reuse_never_reuses_another_expected_hash(self) -> None:
        source = Path(self.control["artifact_paths"]["source"])
        result = Path(self.control["result"]["result_path"])
        self.wait_for_stable_fixtures()
        reads = files.EvidenceReads()
        counts = Counter()
        with mock.patch.object(Path, "read_bytes", self.counted_reads(counts)):
            files.verify_artifacts(self.control, reads=reads)
            files.hash_path(source, reads=reads)
            files.verify_artifacts(self.control, reads=reads)
            files.verify_result(self.control, reads=reads)
            files.verify_result(self.control, reads=reads)
            bad_result = copy.deepcopy(self.control)
            bad_result["result"]["result_sha256"] = "0" * 64
            self.assert_kind(lambda: files.verify_result(bad_result, reads=reads), "result_changed")
            bad_source = copy.deepcopy(self.control)
            bad_source["artifacts"]["source"] = "0" * 64
            self.assert_kind(lambda: files.verify_artifacts(bad_source, reads=reads), "parent_artifact_changed")
        self.assertEqual(counts, Counter({source: 1, result: 1}))
        files.verify_result(self.control)
        files.verify_artifacts(self.control)

    def test_same_size_rewrite_with_restored_mtime_is_not_a_cache_hit(self) -> None:
        source = Path(self.control["artifact_paths"]["source"])
        original = source.read_bytes()
        reads = files.EvidenceReads()
        files.verify_artifacts(self.control, reads=reads)
        before = source.stat()
        # This filesystem can assign one timestamp to adjacent writes.
        time.sleep(0.01)
        source.write_bytes(original.replace(b"100", b"101"))
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = source.stat()
        self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))
        self.assertNotEqual(after.st_ctime_ns, before.st_ctime_ns)
        self.assert_kind(lambda: files.verify_artifacts(self.control, reads=reads), "parent_artifact_changed")

    def test_recent_same_stat_rewrites_are_reread_for_source_and_result(self) -> None:
        for key, kind in (("source", "parent_artifact_changed"), ("result", "result_changed")):
            path = Path(self.control["artifact_paths"]["source"] if key == "source"
                        else self.control["result"]["result_path"])
            original = path.read_bytes()
            reads = files.EvidenceReads()
            identity = reads._identity(path)
            verify = files.verify_artifacts if key == "source" else files.verify_result
            # Simulate the real filesystem alias: same-size writes in one tick
            # retain both timestamps, so unchanged stat fields prove no reuse.
            with self.subTest(evidence=key), mock.patch.object(reads, "_identity", return_value=identity):
                verify(self.control, reads=reads)
                changed = original.replace(b"100", b"101")
                self.assertNotEqual(changed, original)
                self.assertEqual(len(changed), len(original))
                path.write_bytes(changed)
                self.assert_kind(lambda: verify(self.control, reads=reads), kind)
            path.write_bytes(original)

    def test_renamed_file_and_retargeted_symlink_are_rechecked(self) -> None:
        source = Path(self.control["artifact_paths"]["source"])
        original = source.read_bytes()
        reads = files.EvidenceReads()
        files.verify_artifacts(self.control, reads=reads)
        before = source.stat()
        replacement = source.with_suffix(".replacement")
        replacement.write_bytes(original.replace(b"100", b"101"))
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(source)
        self.assertNotEqual(source.stat().st_ino, before.st_ino)
        self.assert_kind(lambda: files.verify_artifacts(self.control, reads=reads), "parent_artifact_changed")
        first, second = self.root / "first.py", self.root / "second.py"
        first.write_bytes(original)
        second.write_bytes(original.replace(b"100", b"102"))
        link = self.root / "active.py"
        link.symlink_to(first)
        entry = copy.deepcopy(self.control)
        entry["artifact_paths"]["source"] = str(link)
        files.verify_artifacts(entry, reads=reads)
        link.unlink()
        link.symlink_to(second)
        self.assert_kind(lambda: files.verify_artifacts(entry, reads=reads), "parent_artifact_changed")

    def test_recipe_directory_reenumerates_add_remove_and_nested_edits(self) -> None:
        recipe = self.root / "recipe"
        nested = recipe / "module"
        nested.mkdir(parents=True)
        first, second = recipe / "train.py", nested / "model.py"
        first.write_text("print('train')\n", encoding="utf-8")
        second.write_text("print('model')\n", encoding="utf-8")
        reads = files.EvidenceReads()
        expected = files.hash_path(recipe, reads=reads)
        original = second.read_bytes()
        self.assertEqual(files.hash_path(recipe, reads=reads), expected)
        second.write_bytes(original.replace(b"model", b"other"))
        self.assertNotEqual(files.hash_path(recipe, reads=reads), expected)
        second.write_bytes(original)
        self.assertEqual(files.hash_path(recipe, reads=reads), expected)
        added = nested / "features.py"
        added.write_text("feature = 1\n", encoding="utf-8")
        self.assertNotEqual(files.hash_path(recipe, reads=reads), expected)
        added.unlink()
        self.assertEqual(files.hash_path(recipe, reads=reads), expected)
        first.unlink()
        self.assertNotEqual(files.hash_path(recipe, reads=reads), expected)

    def test_shared_views_preserve_outputs_and_read_each_file_once(self) -> None:
        records = self.learning_chain()
        expected_brief = self.brief(records)
        expected_trace = archive.iteration_trace(records)
        expected_trials = trials.trial_history(self.path, records, self.control["comparison"], set())
        self.wait_for_stable_fixtures()
        reads = files.EvidenceReads()
        counts = Counter()
        with mock.patch.object(Path, "read_bytes", self.counted_reads(counts)):
            self.assertEqual(self.brief(records, reads=reads), expected_brief)
            self.assertEqual(archive.iteration_trace(records, reads=reads), expected_trace)
            self.assertEqual(trials.trial_history(self.path, records, self.control["comparison"], set(), reads=reads), expected_trials)
        expected_files = {Path(entry["artifact_paths"]["source"]) for entry in self.entries.values()}
        expected_files.update(Path(entry["result"]["result_path"]) for entry in self.entries.values())
        self.assertEqual(counts, Counter(dict.fromkeys(expected_files, 1)))

    def test_handoff_shares_reads_but_next_handoff_or_brief_checks_new_bytes(self) -> None:
        records = self.learning_chain()
        expected = self.packet(records)
        self.wait_for_stable_fixtures()
        counts = Counter()
        with mock.patch.object(Path, "read_bytes", self.counted_reads(counts)):
            self.assertEqual(self.packet(records), expected)
        self.assertTrue(counts)
        self.assertEqual(set(counts.values()), {1})
        source = Path(self.control["artifact_paths"]["source"])
        original = source.read_bytes()
        source.write_bytes(original + b"# changed between calls\n")
        for consumer in (lambda: self.packet(records), lambda: self.brief(records),
                         lambda: archive.iteration_trace(records)):
            self.assert_kind(consumer, "parent_artifact_changed")
        source.write_bytes(original)
        self.assertEqual(self.packet(records), expected)
        result = Path(self.control["result"]["result_path"])
        result.write_bytes(result.read_bytes() + b" ")
        self.assert_kind(lambda: self.packet(records), "result_changed")
        self.assert_kind(lambda: self.brief(records), "result_changed")

    def test_campaign_signals_reuse_one_projection_without_reading_evidence_bytes(self) -> None:
        records = self.learning_chain()
        before = copy.deepcopy(records)
        expected = search.objective_progress(records)
        checkpoint = {"distinct_observations": search.comparison_continuity(records)["distinct_observations"]}
        view = search.CampaignEvidence(records)
        with mock.patch.object(archive, "ComparisonEvidence", wraps=archive.ComparisonEvidence) as projections:
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("policy signals must not read files")):
                initial = view.signals()
                reviewed = view.signals(checkpoint)
                self.assertEqual(view.signals(), initial)
                self.assertEqual(view.signals(checkpoint), reviewed)
                self.assertEqual(view.counts["events"], len(records))
            self.assertEqual(projections.call_count, 1)
        self.assertEqual(initial["objective_progress"], expected)
        self.assertEqual(initial["comparison_continuity"]["reviewed_observations"], 0)
        self.assertEqual(reviewed["comparison_continuity"]["reviewed_observations"], checkpoint["distinct_observations"])
        self.assertEqual(records, before)

    def test_profile_and_recovery_views_keep_their_results_and_errors(self) -> None:
        result = Path(self.control["result"]["result_path"])
        original = result.read_bytes()
        value = json.loads(original)
        profile = {"metric": "per-case-quality", "direction": "maximize", "cases": {"a": 3, "b": 5}}
        value["case_profile"] = profile
        result.write_text(json.dumps(value), encoding="utf-8")
        entry = copy.deepcopy(self.control)
        entry["result"] = archive.result_metadata(result)
        reads = files.EvidenceReads()
        files.verify_result(entry, reads=reads)
        self.assertEqual(archive.read_case_profile(entry, reads=reads), archive.read_case_profile(entry))
        result.write_bytes(result.read_bytes() + b" ")
        self.assert_kind(lambda: archive.read_case_profile(entry, reads=reads), "result_changed")
        result.write_bytes(original)
        self.propose("failure")
        self.record("failed", proposal="failure", failed=True)
        records = archive.read_records(self.path)
        health = search.execution_health(records)
        self.assertTrue(health["needs_attention"])
        self.assertEqual(search.recovery_evidence(records, health, reads=files.EvidenceReads()),
                         search.recovery_evidence(records, health))
        self.record("new-contract", 80, comparison={"workload_hash": "new-workload"})
        records = archive.read_records(self.path)
        continuity = search.comparison_continuity(records)
        self.assertIsNotNone(continuity["latest_unpaired_candidate"])
        self.assertEqual(search.comparison_recovery(records, continuity, reads=files.EvidenceReads()),
                         search.comparison_recovery(records, continuity))


if __name__ == "__main__":
    unittest.main()
