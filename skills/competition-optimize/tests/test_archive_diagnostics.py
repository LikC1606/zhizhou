from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
archive = importlib.import_module("candidate_archive")
evidence = importlib.import_module("candidate_evidence")


class ArchiveDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "archive.jsonl"
        self.entries: dict[str, dict] = {}

    def arguments(self, name: str, score: float = 10, *, role: str | None = None,
                  parents: list[str] | None = None, status: str | None = None,
                  comparison: dict | None = None, reuse: str | None = None,
                  proposal: str | None = None) -> argparse.Namespace:
        folder = self.root / name
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"def solve(): return {name!r}\n", encoding="utf-8")
        if reuse:
            source.write_bytes(Path(self.entries[reuse]["artifact_paths"]["source"]).read_bytes())
        receipt = {
            "status": "success", "valid": True, "candidate_hash": archive.hash_path(source),
            "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
            "score_model_hash": "m" * 64, "stage": "full", "measurement": name,
            "score": {"kind": "official_metric", "metric": "score", "direction": "maximize", "value": score},
            "evaluation": {"config_hash": "c" * 64, "runtime_environment": {"python": "fixture"}},
        }
        for key, value in (comparison or {}).items():
            if key in {"config_hash", "runtime_environment"}:
                receipt["evaluation"][key] = value
            else:
                receipt[key] = value
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        flags = ["record", "--archive", str(self.path), "--candidate-id", name,
                 "--source", str(source), "--result", str(result), "--route", "current",
                 "--mechanism", f"implementation-{name}",
                 "--status", status or ("promising" if role == "diagnostic" else "runner_up"),
                 "--feedback", f"feedback-{name}"]
        if role:
            flags += ["--role", role]
        for parent in parents or []:
            flags += ["--parent", parent]
        if reuse:
            flags += ["--reuse-reason", "repeat to resolve the measured uncertainty"]
        if proposal:
            flags += ["--proposal-id", proposal, "--prediction-status", "supported"]
        return archive.parser().parse_args(flags)

    def record(self, name: str, score: float = 10, **kwargs: Any) -> dict:
        entry = archive.record_candidate(self.arguments(name, score, **kwargs))
        self.entries[name] = entry
        return entry

    def brief(self, anchor: str = "control") -> dict:
        args = archive.parser().parse_args(["brief", "--archive", str(self.path), "--anchor", anchor])
        return archive.optimization_brief(args)

    def propose(self, name: str, parents: list[str], feedback: list[str], *, target: str | None = None) -> dict:
        value = {"proposal_id": name, "parent_ids": parents, "feedback_from": feedback,
                 "route": "current", "code_targets": [self.entries[target or parents[0]]["artifact_paths"]["source"]],
                 "basis": "The intervention locates the controlling error", "change": "Replace that implementation step",
                 "expected_observation": "The located error decreases", "validation": "Use the target development contract",
                 "stop_condition": "The intervention prediction is contradicted"}
        path = self.root / (name + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return archive.propose_candidate(archive.parser().parse_args([
            "propose", "--archive", str(self.path), "--proposal", str(path)]))

    def assert_kind(self, kind: str, operation: Callable[[], Any]) -> None:
        with self.assertRaises(archive.ArchiveFailure) as caught:
            operation()
        self.assertEqual(caught.exception.kind, kind)

    def test_high_scoring_diagnostic_is_observed_without_ranking_or_closing_opportunity(self) -> None:
        self.record("control", status="unresolved")
        args = archive.parser().parse_args(["decide", "--archive", str(self.path)])
        before = archive.route_decision(args)
        diagnostic = self.record("ablation", 10000, role="diagnostic", parents=["control"])
        identity = evidence.implementation_identity(diagnostic)
        self.assertTrue(evidence.executed_snapshot(diagnostic, identity))
        self.assertFalse(archive.measurable(diagnostic))
        self.assertTrue(archive.measurable(diagnostic, include_diagnostics=True))
        self.assertFalse(evidence.observed_snapshot(diagnostic, identity))
        self.assertTrue(evidence.observed_snapshot(diagnostic, identity, include_diagnostics=True))
        self.assertEqual(archive.route_decision(args), before)
        brief = self.brief()
        self.assertEqual(brief["best_development"], "control")
        self.assertEqual(brief["routes"][0]["measurements"], 1)
        self.assertEqual(brief["recent_current"], ["control"])
        self.assertEqual(brief["candidates"]["control"]["role"], "development")
        card = brief["candidates"]["ablation"]
        self.assertEqual(card["role"], "diagnostic")
        self.assertIsNone(card["objective_gain_vs_best"])
        self.assertEqual(card["reused_implementation_from"], [])
        frontier = brief["review_frontier"]["selection"]
        self.assertEqual([item["candidate_id"] for item in frontier], ["control"])
        self.assertEqual(frontier[0]["successor_implementations"], 0)
        summary = archive.summarize(archive.parser().parse_args(["summary", "--archive", str(self.path)]))
        self.assertEqual(summary["routes"]["current"]["candidates"], 1)

    def test_latest_diagnostic_window_follows_complete_control_comparison(self) -> None:
        self.record("control")
        self.record("foreign-control", comparison={"config_hash": "different"})
        self.record("foreign-diagnostic", 90000, role="diagnostic", parents=["foreign-control"])
        self.record("old-diagnostic", 1000, role="diagnostic", parents=["control"])
        self.record("short-diagnostic", 2000, role="diagnostic", parents=["control"], comparison={"stage": "short"})
        self.record("other-environment", 3000, role="diagnostic", parents=["control"],
                    comparison={"runtime_environment": {"python": "other"}})
        brief = self.brief()
        self.assertEqual(brief["diagnostic_evidence"]["selection"], ["short-diagnostic", "other-environment"])
        self.assertEqual(brief["diagnostic_evidence"]["available"], 3)
        self.assertEqual(brief["diagnostic_evidence"]["omitted"], 1)
        self.assertEqual(set(brief["candidates"]), {"control"})
        self.assertEqual(set(brief["pending_references"]), {"short-diagnostic", "other-environment"})
        for card in brief["pending_references"].values():
            self.assertEqual(card["role"], "diagnostic")
            self.assertTrue(card["requires_revalidation"])
            self.assertEqual(card["identity_checks"]["snapshot_bytes"], "checked")
            self.assertNotIn("objective", card)
            self.assertNotIn("feedback", card)
        self.assertGreaterEqual(brief["omitted"]["current_comparison_candidates"], 0)

    def test_old_schema_one_archive_remains_byte_unchanged_and_defaults_to_development(self) -> None:
        control = self.record("control")
        self.assertEqual(control["role"], "development")
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        for field in ("implementation", "reuse_links"):
            rows[0].pop(field, None)
        original = (json.dumps(rows[0]) + "\n").encode()
        self.path.write_bytes(original)
        self.assertEqual(archive.read_records(self.path)[0]["schema_version"], 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.record("diagnostic", role="diagnostic", parents=["control"])
        self.assertTrue(self.path.read_bytes().startswith(original))
        self.assertEqual(self.brief()["best_development"], "control")

    def test_diagnostic_requires_development_control_and_cannot_be_promoted(self) -> None:
        self.record("control")
        self.record("confirmation", role="confirmation")
        self.record("diagnostic", role="diagnostic", parents=["control"])
        for name, parents in [("missing", []), ("wrong-control", ["diagnostic"]),
                              ("confirmation-control", ["confirmation"])]:
            with self.subTest(name=name):
                self.assert_kind("invalid_diagnostic_parent", lambda: self.record(name, role="diagnostic", parents=parents))
        self.assert_kind("confirmation_feedback", lambda: self.record(
            "confirmation-secondary", role="diagnostic", parents=["control", "confirmation"]))
        for status in ("incumbent", "runner_up"):
            with self.subTest(status=status):
                self.assert_kind("invalid_candidate", lambda: self.record(
                    "status-" + status, role="diagnostic", parents=["control"], status=status))
        original = self.path.read_bytes()
        for parents in ([], ["confirmation"], ["control", "confirmation"]):
            rows = [json.loads(line) for line in original.splitlines()]
            rows[-1]["parent_ids"] = parents
            self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.subTest(raw_parents=parents), self.assertRaises(archive.ArchiveFailure):
                archive.read_records(self.path)
        self.path.write_bytes(original)

    def test_confirmation_stages_and_references_cannot_become_diagnostic(self) -> None:
        self.record("control")
        for stage in ("confirmation", "test", "holdout"):
            with self.subTest(stage=stage):
                self.assert_kind("result_override", lambda: self.record(
                    "stage-" + stage, role="diagnostic", parents=["control"], comparison={"stage": stage}))
        diagnostic = self.record("diagnostic", role="diagnostic", parents=["control"])
        original = self.path.read_bytes()
        rows = [json.loads(line) for line in original.splitlines()]
        rows[-1]["result"]["stage"] = "test"
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.assert_kind("result_override", lambda: archive.read_records(self.path))
        self.path.write_bytes(original)
        before = self.brief()
        confirmation = self.record("confirmation", 99999, role="confirmation", comparison={"stage": "test"})
        Path(confirmation["artifact_paths"]["source"]).unlink()
        Path(confirmation["result"]["result_path"]).unlink()
        self.assertEqual(self.brief(), before)
        self.assert_kind("confirmation_feedback", lambda: self.propose("leak", ["control"], ["confirmation"]))
        self.assertEqual(diagnostic["role"], "diagnostic")

    def test_diagnostic_can_supply_proposal_code_feedback_and_real_outcome(self) -> None:
        self.record("control", status="unresolved")
        diagnostic = self.record("diagnostic", 100, role="diagnostic", parents=["control"])
        self.propose("next-change", ["control", "diagnostic"], ["diagnostic"], target="diagnostic")
        pending = self.brief()
        self.assertEqual(pending["matched_pending_proposals"], ["next-change"])
        self.assertEqual(pending["candidates"]["diagnostic"]["role"], "diagnostic")
        outcome = self.record("next-diagnostic", 200, role="diagnostic", parents=["control", "diagnostic"],
                              proposal="next-change")
        rows = archive.read_records(self.path)
        self.assertEqual(rows[-1]["proposal_id"], "next-change")
        self.assertEqual(outcome["role"], "diagnostic")
        trace = archive.iteration_trace(rows, proposal_id="next-change")[0]
        self.assertEqual(trace["evidence"]["role"], "diagnostic")
        self.assertEqual(trace["feedback_evidence"][0]["role"], "diagnostic")
        self.assertEqual(trace["objective_gain_vs_parents"], {"control": None, "diagnostic": None})
        brief = self.brief()
        self.assertEqual(brief["pending_proposals"], [])
        self.assertEqual(brief["review_frontier"]["selection"][0]["successor_implementations"], 0)
        self.assertEqual(brief["best_development"], "control")
        self.propose("use-diagnostic-parent", ["diagnostic"], ["diagnostic"])
        self.assertIn("use-diagnostic-parent", self.brief()["matched_pending_proposals"])
        self.assertEqual(diagnostic["comparison"], self.entries["control"]["comparison"])

    def test_foreign_diagnostic_references_keep_proposal_own_comparison_and_allow_remeasurement(self) -> None:
        self.record("control")
        self.record("short", 9999, role="diagnostic", parents=["control"], comparison={"stage": "short"})
        self.propose("control-change", ["control", "short"], ["short"], target="short")
        self.propose("foreign-change", ["short"], ["short"])
        brief = self.brief()
        self.assertEqual(brief["matched_pending_proposals"], ["control-change"])
        self.assertEqual(brief["pending_references"]["short"]["role"], "diagnostic")
        self.assertNotIn("feedback", brief["pending_references"]["short"])
        repeated = self.record("repeat", 9998, role="diagnostic", parents=["control"], reuse="short",
                               comparison={"stage": "short"})
        self.assertNotIn("proposal_id", repeated)
        same_contract = self.record("same-contract", 20, role="diagnostic", parents=["control"], reuse="control")
        card = self.brief()["candidates"]["same-contract"]
        self.assertEqual(card["reused_implementation_from"], ["control"])
        self.assertEqual(card["reused_from"], ["control"])
        self.assertIsNone(card["objective_gain_vs_best"])
        self.assertTrue(evidence.observed_snapshot(same_contract, evidence.implementation_identity(same_contract),
                                                 include_diagnostics=True))

    def test_displayed_control_and_diagnostic_snapshot_or_result_damage_still_fails(self) -> None:
        self.record("control")
        self.record("diagnostic", role="diagnostic", parents=["control"], comparison={"stage": "short"})
        for name in ("control", "diagnostic"):
            entry = self.entries[name]
            for field, kind in (("source", "parent_artifact_changed"), ("result", "result_changed")):
                path = Path(entry["artifact_paths"][field] if field == "source" else entry["result"]["result_path"])
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.subTest(candidate=name, field=field):
                    self.assert_kind(kind, self.brief)
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
