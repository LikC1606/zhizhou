from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")


class ArchiveGrowthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "archive.jsonl"
        self.source = self.root / "solve.py"
        self.source.write_text("print(1)\n", encoding="utf-8")

    def record(self, name: str, *, role: str = "development", workload: str = "workload-a") -> dict:
        # Synthetic adapter evidence tests recording/storage, not solver quality.
        result = {"status": "success", "valid": True, "candidate_scope": "program_source",
                  "candidate_hash": archive.hash_path(self.source), "evaluator_hash": "evaluator",
                  "workload_hash": workload, "score_model_hash": "score-model",
                  "stage": "confirmation" if role == "confirmation" else "development",
                  "score": {"kind": "official_metric", "metric": "score", "direction": "maximize", "value": 1}}
        result_path = self.root / (name + "-result.json")
        result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        arguments = ["record", "--archive", str(self.path), "--candidate-id", name,
                     "--source", str(self.source), "--result", str(result_path),
                     "--route", "fixed", "--mechanism", "Declared repeated measurement",
                     "--status", "runner_up", "--role", role, "--reuse-reason", "Storage fixture repetition"]
        return archive.record_candidate(archive.parser().parse_args(arguments))

    def brief(self, path: Path | None = None) -> dict:
        return archive.optimization_brief(archive.parser().parse_args(
            ["brief", "--archive", str(path or self.path)]))

    def test_compact_events_keep_complete_return_and_correct_prefix_links(self) -> None:
        first = self.record("first")
        second = self.record("second")
        third = self.record("third")
        self.assertEqual(first["reused_from"], [])
        self.assertEqual(second["reused_from"], ["first"])
        self.assertEqual(third["reused_from"], ["first", "second"])
        self.assertEqual(third["reused_implementation_from"], ["first", "second"])
        records = archive.read_records(self.path)
        for entry in records:
            self.assertNotIn("reused_from", entry)
            self.assertNotIn("reused_implementation_from", entry)
            self.assertEqual(entry["schema_version"], 1)
            self.assertEqual(entry["reuse_links"]["format"], "candidate-prefix-v1")
        for field in ("artifacts", "implementation"):
            self.assertEqual(records[0]["reuse_links"][field], {"count": 0, "first": None, "previous": None})
            self.assertEqual(records[1]["reuse_links"][field], {"count": 1, "first": "first", "previous": "first"})
            self.assertEqual(records[2]["reuse_links"][field], {"count": 2, "first": "first", "previous": "second"})

    def test_legacy_prefix_bytes_and_identity_survive_compact_append(self) -> None:
        legacy = self.record("legacy")
        legacy.pop("reuse_links")
        legacy_bytes = archive.canonical(legacy) + b"\n"
        self.path.write_bytes(legacy_bytes)
        current = self.record("current")
        self.assertTrue(self.path.read_bytes().startswith(legacy_bytes))
        records = archive.read_records(self.path)
        self.assertEqual(records[0], legacy)
        self.assertEqual(records[1]["fingerprint"], legacy["fingerprint"])
        self.assertEqual(records[1]["implementation"], legacy["implementation"])
        self.assertEqual(current["reuse_links"]["artifacts"],
                         {"count": 1, "first": "legacy", "previous": "legacy"})
        self.assertEqual(self.brief()["candidates"]["current"]["reused_from"], ["legacy"])

    def test_confirmation_and_comparison_scopes_are_preserved(self) -> None:
        self.record("same-comparison")
        self.record("other-comparison", workload="workload-b")
        self.record("confirmation", role="confirmation")
        latest = self.record("latest")
        self.assertEqual(latest["reused_from"], ["same-comparison", "other-comparison", "confirmation"])
        self.assertEqual(latest["reused_implementation_from"], ["same-comparison", "other-comparison"])
        self.assertEqual(latest["reuse_links"]["artifacts"],
                         {"count": 3, "first": "same-comparison", "previous": "confirmation"})
        self.assertEqual(latest["reuse_links"]["implementation"],
                         {"count": 2, "first": "same-comparison", "previous": "other-comparison"})
        brief = self.brief()
        self.assertNotIn("confirmation", brief["candidates"])
        self.assertEqual(brief["candidates"]["latest"]["reused_from"], latest["reused_from"])
        self.assertEqual(brief["candidates"]["latest"]["reused_implementation_from"], ["same-comparison"])
        self.assertEqual(brief["best_development"], "same-comparison")

    def test_compact_and_legacy_briefs_are_identical(self) -> None:
        complete = [self.record("c000"), self.record("c001"), self.record("c002", role="confirmation"),
                    self.record("c003", workload="workload-b"), self.record("c004")]
        compact_bytes = self.path.read_bytes()
        legacy_path = self.root / "legacy-archive.jsonl"
        legacy_records = [{key: value for key, value in entry.items() if key != "reuse_links"} for entry in complete]
        legacy_path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in legacy_records))
        compact_brief, legacy_brief = self.brief(), self.brief(legacy_path)
        compact_brief.pop("archive_path")
        legacy_brief.pop("archive_path")
        self.assertEqual(compact_brief, legacy_brief)
        self.assertEqual(self.path.read_bytes(), compact_bytes)

    def test_repeated_measurement_storage_grows_linearly(self) -> None:
        for index in range(64):
            self.record(f"c{index:05d}")
        first_size = self.path.stat().st_size
        for index in range(64, 128):
            self.record(f"c{index:05d}")
        self.assertLess(self.path.stat().st_size, 2.03 * first_size)
        lines = self.path.read_bytes().splitlines()
        self.assertLess(max(map(len, lines)) - min(map(len, lines)), 64)
        records = archive.read_records(self.path)
        self.assertEqual(records[-1]["reuse_links"]["artifacts"]["count"], 127)
        self.assertTrue(all("reused_from" not in entry and "reused_implementation_from" not in entry
                            for entry in records))


if __name__ == "__main__":
    unittest.main()
