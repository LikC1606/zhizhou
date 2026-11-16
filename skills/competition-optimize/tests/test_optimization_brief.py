from __future__ import annotations

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


class OptimizationBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "archive.jsonl"
        self.records: dict[str, dict] = {}

    def record(self, name: str, score: float | None = 1.0, route: str = "current",
               status: str = "runner_up", valid: bool = True, parent: str | None = None,
               role: str = "development", direction: str = "maximize", feedback: str = "",
               failure: str = "", comparison: dict | None = None, reuse: str | None = None,
               result: bool = True, receipt_fields: dict | None = None, score_fields: dict | None = None,
               snapshot: bool = True, proposal: str | None = None, prediction: str = "supported",
               parents: list[str] | None = None) -> dict:
        folder = self.root / name
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"def solve(): return {name!r}\n", encoding="utf-8")
        if reuse:
            source.write_bytes(Path(self.records[reuse]["artifact_paths"]["source"]).read_bytes())
        result_path = folder / "result.json"
        receipt = {"status": "success" if valid else "failed", "valid": valid,
                   "candidate_hash": archive.hash_path(source), "evaluator_hash": "e" * 64,
                   "workload_hash": "w" * 64, "score_model_hash": "m" * 64,
                   "stage": "full", "score": {"kind": "official_metric" if score is not None else "unknown",
                                               "metric": "score", "direction": direction, "value": score,
                                               "components": {"quality": 0.8, "runtime": 2.0}},
                   "elapsed_seconds": 2.0,
                   "evaluation": {"config_hash": "c" * 64, "runtime_environment": {"python": "fixture"}}}
        receipt.update(receipt_fields or {})
        receipt["score"].update(score_fields or {})
        for key, value in (comparison or {}).items():
            if key in {"config_hash", "runtime_environment"}:
                receipt["evaluation"][key] = value
            else:
                receipt[key] = value
        result_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        arguments = ["record", "--archive", str(self.path), "--candidate-id", name,
                     "--route", route, "--status", status,
                     "--mechanism", f"implementation-{name}"]
        if snapshot:
            arguments += ["--source", str(source)]
        if result:
            arguments += ["--result", str(result_path)]
        else:
            arguments += ["--valid" if valid else "--invalid", "--objective-value", str(score), "--objective-direction", direction,
                          "--objective-kind", "official_metric", "--objective-name", "score", "--stage", "full",
                          "--evaluator-hash", "e" * 64, "--workload-hash", "w" * 64, "--score-model-hash", "m" * 64]
        if parent:
            arguments += ["--parent", parent]
        for parent_id in parents or []:
            arguments += ["--parent", parent_id]
        if role:
            arguments += ["--role", role]
        if feedback:
            arguments += ["--feedback", feedback]
        if failure:
            arguments += ["--failure", failure]
        if reuse:
            arguments += ["--reuse-reason", "necessary repeated measurement"]
        if proposal:
            arguments += ["--proposal-id", proposal, "--prediction-status", prediction]
        entry = archive.record_candidate(archive.parser().parse_args(arguments))
        self.records[name] = entry
        return entry

    def brief(self, *arguments: str, seen: dict[str, int] | None = None,
              pending_seen: dict[str, int] | None = None) -> dict:
        return archive.optimization_brief(
            archive.parser().parse_args(["brief", "--archive", str(self.path), *arguments]),
            frontier_seen=seen, pending_seen=pending_seen)

    def propose(self, name: str, parent: str, route: str = "next", *,
                parents: list[str] | None = None, feedback: list[str] | None = None) -> dict:
        parent_ids = parents if parents is not None else [parent]
        value = {"proposal_id": name, "parent_ids": parent_ids,
                 "feedback_from": feedback if feedback is not None else [parent],
                 "route": route, "code_targets": [self.records[i]["artifact_paths"]["source"] for i in parent_ids],
                 "basis": "Measured failure and inspected implementation", "change": "Replace the representation",
                 "expected_observation": "Lower residual error", "validation": "Same development evaluator",
                 "stop_condition": "Reserve or contradicted hypothesis"}
        path = self.root / (name + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return archive.propose_candidate(archive.parser().parse_args(["propose", "--archive", str(self.path), "--proposal", str(path)]))

    def trace(self, *arguments: str) -> dict:
        return archive.trace_report(archive.parser().parse_args(["trace", "--archive", str(self.path), *arguments]))

    def decide(self, *arguments: str) -> dict:
        run = subprocess.run([sys.executable, str(SCRIPTS / "candidate_archive.py"), "decide",
                              "--archive", str(self.path), "--recent", "4", "--min-stagnant", "2",
                              *arguments], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def assert_open_in_decide_and_brief(self, expected: str) -> None:
        decision = self.decide()
        self.assertEqual(decision["action"], "exploit")
        self.assertEqual(decision["unresolved_candidates"], [expected])
        value = self.brief()
        self.assertEqual([row["candidate_id"] for row in value["review_frontier"]["selection"]], [expected])
        self.assertEqual(value["routes"][0]["unresolved"], expected)

    def test_decide_and_brief_keep_opportunity_after_failed_successor(self) -> None:
        self.record("baseline", 10, status="incumbent")
        self.record("open-parent", 9, status="unresolved", feedback="Decoder mechanism remains incomplete")
        self.record("failed-child", None, valid=False, status="rejected", parent="open-parent",
                    score_fields={"kind": "official_metric"}, feedback="Execution failed before comparison")
        self.record("unrelated", 8, status="rejected")
        self.assert_open_in_decide_and_brief("open-parent")

    def test_decide_and_brief_keep_opportunity_after_unscored_successor(self) -> None:
        self.record("baseline", 10, status="incumbent")
        self.record("open-parent", 9, status="unresolved", feedback="Decoder mechanism remains incomplete")
        self.record("unscored-child", None, status="rejected", parent="open-parent",
                    score_fields={"kind": "official_metric"}, feedback="Output exists but the metric is unavailable")
        self.record("unrelated", 8, status="rejected")
        self.assert_open_in_decide_and_brief("open-parent")

    def test_decide_and_brief_keep_explicitly_unresolved_successor(self) -> None:
        self.record("baseline", 10, status="incumbent")
        self.record("open-parent", 9, status="unresolved", feedback="Decoder mechanism remains incomplete")
        self.propose("partial", "open-parent", route="current")
        self.record("partial-child", 8, parent="open-parent", proposal="partial", prediction="unresolved",
                    feedback="Coupled decoder component still missing")
        self.record("unrelated", 7, status="rejected")
        self.assert_open_in_decide_and_brief("open-parent")

    def test_decide_and_brief_keep_independent_control_opportunity(self) -> None:
        self.record("baseline", 10, status="incumbent")
        self.record("open-parent", 9, status="unresolved", feedback="Decoder mechanism remains incomplete")
        proposal = {"proposal_id": "independent", "parent_ids": ["open-parent"], "feedback_from": ["open-parent"],
                    "route": "current", "construction_mode": "independent", "code_targets": [],
                    "basis": "Task-derived construction with the parent as a control", "change": "Implement an independent decoder",
                    "expected_observation": "Different valid construction", "validation": "Same evaluator", "stop_condition": "Measured outcome"}
        path = self.root / "independent.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        archive.propose_candidate(archive.parser().parse_args(["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.record("independent-child", 8, parent="open-parent", proposal="independent", feedback="Independent route measured")
        self.record("unrelated", 7, status="rejected")
        self.assert_open_in_decide_and_brief("open-parent")

    def test_decide_and_brief_close_opportunity_through_parent_alias(self) -> None:
        self.record("baseline", 10, status="incumbent")
        self.record("open-parent", 9, status="unresolved", feedback="Decoder mechanism remains incomplete")
        self.record("alias", 9, reuse="open-parent")
        self.record("completed-child", 8, parent="alias", feedback="Decoder mechanism tested")
        self.assertEqual(self.decide()["unresolved_candidates"], [])
        self.assertEqual(self.brief()["review_frontier"]["selection"], [])

    def test_best_representatives_survive_weak_recent_history(self) -> None:
        self.record("best-current", 10, status="incumbent")
        self.record("alternative-best", 12, route="alternative")
        for number in range(8):
            self.record(f"weak-{number}", 2 + number / 10, status="rejected", feedback="No useful gain",
                        failure="Local change leaves the representation unchanged")
        value = self.brief("--recent", "2")
        self.assertEqual(value["best_development"], "alternative-best")
        self.assertEqual(value["routes"][0]["best"], "best-current")
        self.assertEqual(value["recent_current"], ["weak-6", "weak-7"])
        self.assertIn("best-current", value["candidates"])
        self.assertNotIn("weak-0", value["candidates"])
        self.assertEqual(value["candidates"]["weak-7"]["objective_gain_vs_best"], -9.3)
        self.assertIn("representation", value["candidates"]["weak-7"]["failure_mechanism"])

    def test_alternatives_rank_by_matched_objective_not_trial_count(self) -> None:
        self.record("few-weak", 9, "few", direction="minimize")
        self.record("many-best", 1, "many", direction="minimize")
        for number in range(5):
            self.record(f"many-{number}", 5, "many", direction="minimize")
        self.record("current", 4, direction="minimize")
        value = self.brief("--routes", "2")
        self.assertEqual([route["route"] for route in value["routes"]], ["current", "many"])
        self.assertEqual(value["best_development"], "many-best")
        self.assertEqual(value["omitted"]["routes"], 1)

    def test_each_comparison_dependency_is_scoped(self) -> None:
        self.record("anchor", 1)
        for number, comparison in enumerate([{"evaluator_hash": "other"}, {"workload_hash": "other"},
                                             {"score_model_hash": "other"}, {"stage": "short"},
                                             {"config_hash": "other"}, {"runtime_environment": {"python": "other"}}]):
            self.record(f"foreign-{number}", 100, route=f"foreign-{number}", comparison=comparison)
        value = self.brief("--anchor", "anchor")
        self.assertEqual(value["best_development"], "anchor")
        self.assertEqual(set(value["candidates"]), {"anchor"})
        self.assertEqual(value["omitted"]["other_development_comparisons"], 6)

    def test_confirmation_neither_changes_brief_nor_requires_artifacts(self) -> None:
        self.record("baseline", 1)
        before = self.brief()
        confirmation = self.record("confirmation", 100, route="confirmation-only", role="confirmation")
        Path(confirmation["artifact_paths"]["source"]).unlink()
        Path(confirmation["result"]["result_path"]).unlink()
        self.assertEqual(self.brief(), before)
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.brief("--anchor", "confirmation")
        self.assertEqual(caught.exception.kind, "confirmation_feedback")

    def test_invalid_latest_keeps_previous_best_and_failure_feedback(self) -> None:
        self.record("valid", 3)
        self.record("broken", 100, status="rejected", valid=False,
                    feedback="Implementation failed before the full comparison", failure="Decoder violates capacity")
        value = self.brief()
        self.assertEqual(value["anchor_candidate"], "broken")
        self.assertEqual(value["best_development"], "valid")
        self.assertEqual(value["routes"][0]["latest_failure"], "broken")
        self.assertIsNone(value["candidates"]["broken"]["objective_gain_vs_best"])

    def test_unknown_score_preserves_components_without_ranking(self) -> None:
        self.record("unknown", None)
        value = self.brief()
        self.assertIsNone(value["best_development"])
        self.assertIsNone(value["routes"][0]["best"])
        self.assertEqual(value["candidates"]["unknown"]["objective"]["components"], {"quality": 0.8, "runtime": 2.0})

    def test_changed_selected_result_or_snapshot_blocks_reuse(self) -> None:
        entry = self.record("candidate", 3)
        for field, kind in [("result", "result_changed"), ("source", "parent_artifact_changed")]:
            path = Path(entry["result"]["result_path"] if field == "result" else entry["artifact_paths"]["source"])
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            with self.subTest(field=field), self.assertRaises(archive.ArchiveFailure) as caught:
                self.brief()
            self.assertEqual(caught.exception.kind, kind)
            path.write_bytes(original)

    def test_old_unselected_artifact_is_not_rehashed_or_loaded(self) -> None:
        old = self.record("old-low", 1)
        self.record("best", 10)
        for number in range(6):
            self.record(f"later-{number}", 5)
        Path(old["artifact_paths"]["source"]).unlink()
        Path(old["result"]["result_path"]).unlink()
        opened: set[Path] = set()
        read_bytes = Path.read_bytes
        def read(path: Path) -> bytes:
            opened.add(path.resolve())
            return read_bytes(path)
        with mock.patch.object(Path, "read_bytes", read):
            value = self.brief("--recent", "2")
        displayed = set(value["candidates"])
        expected = {self.path.resolve()}
        for name in displayed:
            expected.add(Path(self.records[name]["result"]["result_path"]))
            expected.add(Path(self.records[name]["artifact_paths"]["source"]))
        self.assertEqual(opened, expected)
        self.assertNotIn("old-low", displayed)

    def test_pending_details_recover_code_and_feedback_without_duplicate_cards(self) -> None:
        self.record("parent", 1, feedback="Remaining nonlinear residuals")
        self.propose("p0", "parent")
        self.propose("p1", "parent")
        self.propose("p2", "parent")
        value = self.brief("--recent", "2")
        self.assertEqual(value["pending_proposals"], ["p0", "p1", "p2"])
        self.assertEqual([p["proposal_id"] for p in value["pending_details"]], ["p1", "p2"])
        self.assertEqual(value["pending_details"][0]["code_targets"][0]["path"], self.records["parent"]["artifact_paths"]["source"])
        self.assertEqual(set(value["candidates"]), {"parent"})
        self.assertEqual(value["omitted"]["pending_details"], 1)
        archive.stop_proposal(archive.parser().parse_args(["stop", "--archive", str(self.path), "--proposal-id", "p1",
                                                          "--reason", "Superseded proposal"]))
        self.assertEqual(self.brief()["pending_proposals"], ["p0", "p2"])

    def test_pending_other_comparison_remains_visible_without_its_scores(self) -> None:
        self.record("old-parent", 100, comparison={"workload_hash": "old"})
        self.propose("old-pending", "old-parent")
        self.record("new-parent", 1)
        self.propose("new-pending", "new-parent")
        value = self.brief()
        self.assertEqual(value["pending_proposals"], ["old-pending", "new-pending"])
        self.assertEqual([p["proposal_id"] for p in value["pending_details"]], ["new-pending"])
        self.assertNotIn("old-parent", value["candidates"])

    def test_pending_seven_proposals_keep_latest_default_and_original_target_identities(self) -> None:
        self.record("parent", 1)
        proposals = [self.propose(f"p{number}", "parent") for number in range(7)]
        value = self.brief()
        self.assertEqual(value["matched_pending_proposals"], [f"p{number}" for number in range(7)])
        self.assertEqual([entry["proposal_id"] for entry in value["pending_details"]], ["p3", "p4", "p5", "p6"])
        self.assertEqual(value["pending_summary"]["available"], 7)
        self.assertEqual(value["pending_summary"]["omitted"], 3)
        self.assertEqual(value["pending_summary"]["selection_policy"], "latest")
        for entry in value["pending_details"]:
            proposal = proposals[int(entry["proposal_id"][1:])]
            self.assertEqual(entry["input_sha256"], proposal["input_sha256"])
            self.assertEqual(entry["code_targets"], proposal["code_targets"])
            self.assertIsNone(entry["last_exposed_turn"])
            self.assertEqual(entry["identity_checks"], {"code_targets": "checked"})

    def test_pending_seen_rotates_unexposed_then_oldest_without_mutating_caller(self) -> None:
        self.record("parent", 1)
        for number in range(7):
            self.propose(f"p{number}", "parent")
        seen = {}
        first = self.brief(pending_seen=seen)
        self.assertEqual([entry["proposal_id"] for entry in first["pending_details"]], ["p0", "p1", "p2", "p3"])
        self.assertEqual(seen, {})
        self.assertEqual(self.brief(pending_seen=seen), first)
        seen.update({entry["proposal_id"]: 5 for entry in first["pending_details"]})
        second = self.brief(pending_seen=seen)
        self.assertEqual([entry["proposal_id"] for entry in second["pending_details"]], ["p4", "p5", "p6", "p0"])
        self.assertEqual([entry["last_exposed_turn"] for entry in second["pending_details"]], [None, None, None, 5])
        self.assertEqual(second["pending_summary"]["selection_policy"], "least_recently_exposed")
        seen.update({entry["proposal_id"]: 6 for entry in second["pending_details"]})
        third = self.brief(pending_seen=seen)
        self.assertEqual([entry["proposal_id"] for entry in third["pending_details"]], ["p1", "p2", "p3", "p0"])
        self.assertEqual(seen, {"p0": 6, "p1": 5, "p2": 5, "p3": 5, "p4": 6, "p5": 6, "p6": 6})

    def test_pending_rotation_excludes_evaluated_and_stopped_proposals(self) -> None:
        self.record("parent", 1)
        for number in range(7):
            self.propose(f"p{number}", "parent")
        archive.stop_proposal(archive.parser().parse_args(
            ["stop", "--archive", str(self.path), "--proposal-id", "p1", "--reason", "Explicitly stopped"]))
        self.record("outcome", 2, parent="parent", proposal="p2", route="next", feedback="Completed measured successor")
        value = self.brief(pending_seen={"p0": 9, "p1": 0, "p2": 0})
        self.assertEqual(value["matched_pending_proposals"], ["p0", "p3", "p4", "p5", "p6"])
        self.assertEqual([entry["proposal_id"] for entry in value["pending_details"]], ["p3", "p4", "p5", "p6"])
        self.assertEqual(value["pending_summary"]["available"], 5)
        self.assertEqual(value["pending_summary"]["omitted"], 1)

    def test_pending_repair_restores_cross_contract_reference_without_score_or_feedback(self) -> None:
        reference = self.record("good", 987654321, feedback="foreign-secret-feedback")
        self.record("failed", None, parent="good", valid=False, status="rejected",
                    feedback="Decoder failed before producing a score", failure="IndexError")
        self.propose("repair", "failed", feedback=["good", "failed"])
        value = self.brief(pending_seen={})
        self.assertEqual(value["matched_pending_proposals"], ["repair"])
        self.assertEqual([entry["proposal_id"] for entry in value["pending_details"]], ["repair"])
        self.assertEqual(set(value["candidates"]), {"failed"})
        self.assertEqual(set(value["pending_references"]), {"good"})
        recovered = value["pending_references"]["good"]
        self.assertEqual(set(recovered), {"role", "implementation", "artifact_paths", "result", "comparison_sha256",
                                          "requires_revalidation", "identity_checks", "scope"})
        self.assertEqual(recovered["implementation"], reference["implementation"])
        self.assertEqual(recovered["comparison_sha256"], archive.sha256(archive.canonical(reference["comparison"])))
        self.assertEqual(recovered["result"]["result_sha256"], reference["result"]["result_sha256"])
        self.assertTrue(recovered["requires_revalidation"])
        self.assertEqual(recovered["identity_checks"], {"result_bytes": "checked", "snapshot_bytes": "checked"})
        self.assertNotIn("987654321", json.dumps(value))
        self.assertNotIn("foreign-secret-feedback", json.dumps(value))
        outcome = self.record("repaired", 13, parent="failed", proposal="repair", route="next",
                              feedback="Repair produced a full scored result")
        self.assertNotEqual(outcome["comparison"], self.records["failed"]["comparison"])
        self.assertEqual(self.brief()["matched_pending_proposals"], [])

    def test_pending_mixed_parents_belong_to_first_parent_and_deduplicate_references(self) -> None:
        self.record("a", 1)
        self.record("b", 2, comparison={"workload_hash": "other"}, feedback="foreign-secret-feedback")
        self.propose("a-owned", "a", parents=["a", "b"], feedback=["b", "a"])
        self.propose("b-owned", "b", parents=["b", "a"], feedback=["a", "b"])
        for owner, foreign, proposal in [("a", "b", "a-owned"), ("b", "a", "b-owned")]:
            value = self.brief("--anchor", owner, pending_seen={})
            self.assertEqual(value["matched_pending_proposals"], [proposal])
            self.assertEqual([entry["proposal_id"] for entry in value["pending_details"]], [proposal])
            self.assertEqual(set(value["pending_references"]), {foreign})
            self.assertEqual(set(value["candidates"]), {owner})
            self.assertEqual(value["pending_summary"]["available"], 1)
            self.assertEqual(value["pending_summary"]["omitted"], 0)
            self.assertEqual(value["omitted"]["pending_details"], 1)
            self.assertEqual(value["omitted"]["current_comparison_candidates"], 0)

    def test_unselected_foreign_pending_does_not_read_its_artifacts(self) -> None:
        foreign = self.record("foreign", 50, comparison={"workload_hash": "other"})
        self.propose("foreign-pending", "foreign")
        self.record("current", 1)
        self.propose("current-pending", "current")
        Path(foreign["artifact_paths"]["source"]).unlink()
        Path(foreign["result"]["result_path"]).unlink()
        value = self.brief(pending_seen={})
        self.assertEqual(value["matched_pending_proposals"], ["current-pending"])
        self.assertEqual(value["pending_references"], {})
        self.assertNotIn("foreign", value["candidates"])

    def test_pending_cards_precede_ordinary_route_and_recent_cards(self) -> None:
        self.record("old-parent", 1, route="old")
        self.propose("old-pending", "old-parent")
        for number in range(5):
            self.record(f"elite-{number}", 10 + number, route=f"route-{number}")
        value = self.brief(pending_seen={})
        self.assertEqual(list(value["candidates"])[:2], ["elite-4", "old-parent"])
        self.assertEqual(value["pending_details"][0]["identity_checks"]["code_targets"], "checked")

    def test_pending_selected_cross_contract_reference_hashes_are_checked(self) -> None:
        reference = self.record("reference", 50, feedback="Useful diagnostic reference")
        self.record("failed", None, valid=False, status="rejected")
        self.propose("repair", "failed", feedback=["reference", "failed"])
        for field, error in [("source", "parent_artifact_changed"), ("result", "result_changed")]:
            path = Path(reference["result"]["result_path"] if field == "result" else reference["artifact_paths"]["source"])
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            try:
                with self.subTest(field=field), self.assertRaises(archive.ArchiveFailure) as caught:
                    self.brief(pending_seen={})
                self.assertEqual(caught.exception.kind, error)
            finally:
                path.write_bytes(original)

    def test_pending_seen_rejects_invalid_identity_or_checkpoint(self) -> None:
        self.record("parent", 1)
        for seen in ({"": 1}, {" ": 1}, {1: 1}, {"p0": -1}, {"p0": True}, {"p0": 1.5}, []):
            with self.subTest(seen=seen), self.assertRaises(archive.ArchiveFailure) as caught:
                self.brief(pending_seen=seen)
            self.assertEqual(caught.exception.kind, "invalid_config")

    def test_exact_trace_recovers_old_pending_with_full_code_targets_and_checks_only_selected(self) -> None:
        self.record("old-parent", 1)
        old = self.propose("old-pending", "old-parent")
        other = self.record("other-parent", 2)
        for number in range(10):
            self.propose(f"new-{number}", "other-parent")
        Path(other["artifact_paths"]["source"]).write_text("external mutation\n", encoding="utf-8")
        value = self.trace("--proposal-id", "old-pending")
        self.assertEqual(value["pending_proposals"], ["old-pending"])
        self.assertEqual(len(value["iterations"]), 1)
        row = value["iterations"][0]
        self.assertEqual(row["proposal_id"], "old-pending")
        self.assertEqual(row["state"], "pending")
        for field in ("code_targets", "validation", "stop_condition", "input_sha256"):
            self.assertEqual(row[field], old[field])
        self.assertEqual(row["identity_checks"], {"code_targets": "checked"})
        run = subprocess.run([sys.executable, str(SCRIPTS / "candidate_archive.py"), "trace", "--archive", str(self.path),
                              "--proposal-id", "old-pending"], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["iterations"], value["iterations"])
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.trace("--proposal-id", "missing")
        self.assertEqual(caught.exception.kind, "unknown_proposal")

    def test_exact_trace_returns_evaluated_or_stopped_outcome_without_other_pending_ids(self) -> None:
        self.record("parent", 1)
        self.propose("evaluated", "parent")
        self.propose("stopped", "parent")
        self.propose("unrelated", "parent")
        self.record("outcome", 2, parent="parent", route="next", proposal="evaluated", feedback="Supported implementation")
        archive.stop_proposal(archive.parser().parse_args(
            ["stop", "--archive", str(self.path), "--proposal-id", "stopped", "--reason", "Dependency unavailable"]))
        evaluated = self.trace("--proposal-id", "evaluated")
        self.assertEqual(evaluated["pending_proposals"], [])
        self.assertEqual(evaluated["iterations"][0]["state"], "evaluated_valid")
        self.assertEqual(evaluated["iterations"][0]["candidate_id"], "outcome")
        stopped = self.trace("--proposal-id", "stopped")
        self.assertEqual(stopped["pending_proposals"], [])
        self.assertEqual(stopped["iterations"][0]["state"], "stopped")
        self.assertEqual(stopped["iterations"][0]["reason"], "Dependency unavailable")

    def test_pending_legacy_without_original_input_hash_does_not_invent_or_rewrite_it(self) -> None:
        self.record("parent", 1)
        self.propose("legacy", "parent")
        records = archive.read_records(self.path)
        records[-1].pop("input_sha256")
        self.path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in records))
        before = self.path.read_bytes()
        self.assertIsNone(self.brief(pending_seen={})["pending_details"][0]["input_sha256"])
        self.assertIsNone(self.trace("--proposal-id", "legacy")["iterations"][0]["input_sha256"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_different_route_successor_supersedes_old_unresolved_opportunity(self) -> None:
        self.record("promising", 1, status="promising", feedback="Needs a complete decoder")
        self.record("successor", 2, route="different", parent="promising")
        value = self.brief("--anchor", "promising")
        self.assertIsNone(value["routes"][0]["unresolved"])
        self.assertEqual(value["review_frontier"]["available"], 0)

    def test_frontier_recovers_low_scoring_open_route_outside_elites(self) -> None:
        self.record("decoder", 50, route="decoder", status="promising", feedback="Complete batching remains untested")
        for number in range(4):
            self.record(f"elite-{number}", 100 - number, route=f"elite-{number}")
        self.record("current", 101)
        value = self.brief()
        self.assertEqual([row["route"] for row in value["routes"]], ["current", "elite-0", "elite-1", "elite-2"])
        self.assertEqual(value["best_development"], "current")
        self.assertEqual([row["candidate_id"] for row in value["review_frontier"]["selection"]], ["decoder"])
        self.assertIn("decoder", value["candidates"])
        self.assertEqual(list(value["candidates"])[:2], ["current", "decoder"])
        self.assertEqual(value["review_frontier"]["available"], 1)
        self.assertEqual(value["review_frontier"]["omitted"], 0)
        self.assertEqual(value["omitted"]["current_comparison_candidates"], 1)

    def test_frontier_recovers_multiple_old_opportunities_in_same_route(self) -> None:
        self.record("indexed-updates", 5, status="promising", feedback="Indexed updates can reduce runtime")
        self.record("lookahead", 6, status="unresolved", feedback="Complete lookahead remains untested")
        self.record("best", 10)
        for number in range(6):
            self.record(f"later-{number}", 9)
        value = self.brief("--recent", "2", "--routes", "1")
        self.assertEqual(value["routes"][0]["unresolved"], "lookahead")
        self.assertEqual([row["candidate_id"] for row in value["review_frontier"]["selection"]],
                         ["indexed-updates", "lookahead"])
        self.assertIn("indexed-updates", value["candidates"])

    def test_failed_successor_preserves_parent_and_exposes_actual_failure(self) -> None:
        parent = self.record("promising", 7, route="decoder", status="promising", feedback="Needs complete decoder")
        self.record("crash", 0, route="repair", parent="promising", valid=False, status="rejected",
                    feedback="Decoder did not finish", failure="IndexError")
        value = self.brief()
        frontier = value["review_frontier"]["selection"]
        self.assertEqual(len(frontier), 1)
        self.assertEqual(frontier[0], {"candidate_id": "promising", "feedback_candidate_id": "promising",
                                      "implementation_fingerprint": parent["implementation"]["fingerprint"],
                                      "last_exposed_turn": None, "successor_implementations": 1,
                                      "measured_successor_implementations": 0, "latest_successor": "crash"})
        self.assertEqual(next(row for row in value["routes"] if row["route"] == "decoder")["unresolved"], "promising")
        self.assertEqual(value["candidates"]["crash"]["result"]["execution_status"], "failed")
        self.assertEqual(value["candidates"]["crash"]["failure_mechanism"], "IndexError")

    def test_valid_unresolved_proposal_does_not_close_parent_opportunity(self) -> None:
        self.record("promising", 7, status="promising", feedback="Decoder leaves a conditional opportunity")
        self.propose("p0", "promising")
        self.record("partial", 8, parent="promising", route="next", proposal="p0", prediction="unresolved",
                    feedback="Full decoder not completed; outcome remains unresolved")
        value = self.brief()
        row = value["review_frontier"]["selection"][0]
        self.assertEqual(row["candidate_id"], "promising")
        self.assertEqual(row["successor_implementations"], 1)
        self.assertEqual(row["measured_successor_implementations"], 1)
        self.assertEqual(row["latest_successor"], "partial")

    def test_opportunity_alias_uses_first_valid_score_and_respects_declaration_time(self) -> None:
        self.record("original", 7)
        self.record("earlier-successor", 8, parent="original")
        self.record("feedback-alias", 100, reuse="original", route="renamed", status="promising",
                    feedback="A new follow-up opportunity was identified after this child")
        value = self.brief()
        row = value["review_frontier"]["selection"][0]
        self.assertEqual(row["candidate_id"], "original")
        self.assertEqual(row["feedback_candidate_id"], "feedback-alias")
        self.assertEqual(row["successor_implementations"], 0)
        self.assertIsNone(row["latest_successor"])
        self.assertEqual(value["candidates"]["original"]["objective"]["value"], 7)
        self.assertEqual(value["best_development"], "earlier-successor")
        self.assertIn("feedback-alias", value["candidates"])
        self.record("later-successor", 9, parent="feedback-alias", route="other")
        self.assertEqual(self.brief()["review_frontier"]["available"], 0)
        self.record("repeat-declaration", 200, reuse="original", status="unresolved", feedback="Same opportunity repeated")
        final = self.brief()
        self.assertEqual(final["review_frontier"]["available"], 0)
        self.assertTrue(all(row["unresolved"] is None for row in final["routes"]))
        self.assertEqual(final["best_development"], "later-successor")

    def test_parent_aliases_and_successor_repetitions_share_implementation_nodes(self) -> None:
        self.record("root", 2, status="promising", feedback="Useful full implementation is missing")
        self.record("renamed-root", 100, reuse="root", route="renamed")
        self.record("failed-a", 0, parent="root", valid=False, status="rejected")
        self.record("failed-a-repeat", 0, parent="renamed-root", reuse="failed-a", valid=False, status="rejected")
        self.record("failed-b", 0, parent="renamed-root", valid=False, status="rejected")
        value = self.brief()
        self.assertEqual(value["review_frontier"]["available"], 1)
        row = value["review_frontier"]["selection"][0]
        self.assertEqual(row["candidate_id"], "root")
        self.assertEqual(row["successor_implementations"], 2)
        self.assertEqual(row["measured_successor_implementations"], 0)
        self.assertEqual(row["latest_successor"], "failed-b")
        self.assertEqual(value["best_development"], "root")

    def test_manual_unscored_output_only_and_unbound_children_cannot_close_opportunity(self) -> None:
        comparison = {"config_hash": None, "runtime_environment": None}
        self.record("root", 2, status="promising", feedback="Execution is needed", comparison=comparison)
        self.record("manual-child", 9, parent="root", result=False)
        self.record("unscored-child", None, parent="root", comparison=comparison,
                    score_fields={"kind": "official_metric"})
        self.record("output-child", 8, parent="root", comparison=comparison,
                    receipt_fields={"candidate_scope": "generated_artifact"})
        self.record("unbound-child", 7, parent="root", comparison=comparison, snapshot=False)
        value = self.brief("--anchor", "root")
        row = value["review_frontier"]["selection"][0]
        self.assertEqual(row["candidate_id"], "root")
        self.assertEqual(row["successor_implementations"], 1)
        self.assertEqual(row["measured_successor_implementations"], 0)
        self.assertEqual(row["latest_successor"], "unscored-child")
        self.assertEqual(value["routes"][0]["unresolved"], "root")

    def test_frontier_ignores_confirmation_foreign_contracts_and_unusable_roots(self) -> None:
        self.record("root", 2, status="promising", feedback="Matched open opportunity")
        foreign = self.record("foreign", 100, parent="root", status="promising", feedback="Foreign opportunity",
                              comparison={"workload_hash": "foreign"})
        confirmation = self.record("confirmation", 200, parent="root", role="confirmation", status="promising",
                                   feedback="Confirmation must not influence search")
        for entry in (foreign, confirmation):
            Path(entry["artifact_paths"]["source"]).unlink()
            Path(entry["result"]["result_path"]).unlink()
        self.record("output", 1, status="promising", feedback="Output alone is not code",
                    receipt_fields={"candidate_scope": "generated_artifact"})
        self.record("unbound", 1, status="promising", feedback="No retained code snapshot", snapshot=False)
        self.record("unknown", None, status="promising", feedback="No usable objective",
                    score_fields={"kind": "official_metric"})
        self.record("invalid", 1, valid=False, status="unresolved", feedback="Invalid observations cannot rank parents")
        self.record("manual", 5, result=False, status="promising", feedback="Manual objective is not a measured opportunity")
        value = self.brief("--anchor", "root")
        self.assertEqual([row["candidate_id"] for row in value["review_frontier"]["selection"]], ["root"])
        self.assertEqual(value["review_frontier"]["available"], 1)
        self.assertEqual(value["review_frontier"]["selection"][0]["successor_implementations"], 0)
        self.assertNotIn("foreign", value["candidates"])
        self.assertNotIn("confirmation", value["candidates"])

    def test_frontier_exposure_round_robin_precedes_scores_and_trial_counts(self) -> None:
        entries = [self.record(name, score, route=name, status="promising", feedback="Untested opportunity")
                   for name, score in [("a", 1), ("b", 100), ("c", 50)]]
        fingerprints = [entry["implementation"]["fingerprint"] for entry in entries]
        self.record("current", 101)
        seen = {}
        for turn, expected in [(5, "a"), (6, "b"), (7, "c"), (8, "a"), (9, "b")]:
            value = self.brief("--frontier", "1", seen=seen)
            row = value["review_frontier"]["selection"][0]
            self.assertEqual(row["candidate_id"], expected)
            self.assertEqual(row["last_exposed_turn"], seen.get(row["implementation_fingerprint"]))
            self.assertEqual(value["review_frontier"]["available"], 3)
            self.assertEqual(value["review_frontier"]["omitted"], 2)
            seen[row["implementation_fingerprint"]] = turn
        tied = self.brief("--frontier", "1", seen=dict.fromkeys(fingerprints, 10))
        self.assertEqual(tied["review_frontier"]["selection"][0]["candidate_id"], "a")

    def test_frontier_zero_disables_extra_cards_and_cli_keeps_available_count(self) -> None:
        self.record("old", 1, route="old", status="promising", feedback="Low scoring open opportunity")
        self.record("current", 10)
        value = self.brief("--routes", "1", "--frontier", "0")
        self.assertEqual(value["review_frontier"]["selection"], [])
        self.assertEqual(value["review_frontier"]["available"], 1)
        self.assertEqual(value["review_frontier"]["omitted"], 1)
        self.assertNotIn("old", value["candidates"])
        run = subprocess.run([sys.executable, str(SCRIPTS / "candidate_archive.py"), "brief", "--archive", str(self.path),
                              "--routes", "1", "--frontier", "0"], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        cli_value = json.loads(run.stdout)
        self.assertEqual(cli_value.pop("status"), "success")
        self.assertEqual(cli_value, value)

    def test_frontier_checks_hidden_root_and_latest_successor_hashes(self) -> None:
        root = self.record("root", 1, route="old", status="promising", feedback="Untested representation")
        child = self.record("child", 0, route="old", parent="root", status="rejected", valid=False)
        self.record("current", 10)
        for number in range(6):
            self.record(f"later-{number}", 9)
        before = self.brief("--routes", "1", "--recent", "1", "--frontier", "1")
        self.assertEqual(list(before["candidates"])[:4], ["later-5", "current", "root", "child"])
        for entry in (root, child):
            for field, error in [("source", "parent_artifact_changed"), ("result", "result_changed")]:
                path = Path(entry["result"]["result_path"] if field == "result" else entry["artifact_paths"]["source"])
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                try:
                    with self.subTest(candidate=entry["candidate_id"], field=field), self.assertRaises(archive.ArchiveFailure) as caught:
                        self.brief("--routes", "1", "--recent", "1", "--frontier", "1")
                    self.assertEqual(caught.exception.kind, error)
                finally:
                    path.write_bytes(original)

    def test_frontier_uses_first_valid_observation_and_optional_rankable_filter(self) -> None:
        self.record("invalid-first", 3, valid=False, status="unresolved", feedback="Not a valid parent yet")
        self.record("valid-first", 2, reuse="invalid-first")
        self.record("lucky-declaration", 100, reuse="invalid-first", status="promising", feedback="Useful follow-up")
        value = self.brief()
        row = value["review_frontier"]["selection"][0]
        self.assertEqual(row["candidate_id"], "valid-first")
        self.assertEqual(row["feedback_candidate_id"], "lucky-declaration")
        self.assertEqual(value["best_development"], "valid-first")
        args = archive.parser().parse_args(["brief", "--archive", str(self.path)])
        filtered = archive.optimization_brief(args, rankable=lambda entry: False)
        self.assertEqual(filtered["review_frontier"]["available"], 0)

    def test_frontier_seen_rejects_malformed_checkpoint_identity(self) -> None:
        self.record("root", 1)
        for seen in ({"not-a-fingerprint": 1}, {"a" * 64: -1}, {"a" * 64: True}, {"a" * 64: 1.5}, []):
            with self.subTest(seen=seen), self.assertRaises(archive.ArchiveFailure) as caught:
                self.brief(seen=seen)
            self.assertEqual(caught.exception.kind, "invalid_config")

    def test_repetitions_do_not_add_implementations_or_select_lucky_best(self) -> None:
        self.record("baseline", 2)
        self.record("repeat", 100, reuse="baseline", parent="baseline")
        value = self.brief()
        self.assertEqual(value["best_development"], "baseline")
        self.assertEqual(value["routes"][0]["distinct_implementations"], 1)
        self.assertEqual(value["routes"][0]["measurements"], 2)
        self.assertEqual(value["recent_current"], ["baseline"])
        self.assertEqual(value["candidates"]["repeat"]["reused_from"], ["baseline"])
        self.assertEqual(value["candidates"]["repeat"]["reused_implementation_from"], ["baseline"])
        self.assertEqual(value["candidates"]["baseline"]["reused_implementation_from"], [])

    def test_renaming_route_does_not_turn_repetition_into_a_best_representative(self) -> None:
        self.record("baseline", 2)
        self.record("repeat-renamed", 100, route="renamed", reuse="baseline")
        value = self.brief()
        self.assertEqual(value["best_development"], "baseline")
        self.assertIsNone(value["routes"][0]["best"])
        self.assertIsNone(value["candidates"]["repeat-renamed"]["objective_gain_vs_best"])

    def test_legacy_unchecked_result_is_labeled_without_inventing_verification(self) -> None:
        self.record("legacy", 1, result=False)
        value = self.brief()["candidates"]["legacy"]
        self.assertEqual(value["identity_checks"]["result_bytes"], "not_recorded")
        self.assertEqual(value["identity_checks"]["snapshot_bytes"], "checked")

    def test_cli_rejects_bad_limits_empty_archive_and_unknown_anchor(self) -> None:
        for extra, error in [([], "empty_archive"), (["--recent", "0"], "invalid_config"),
                             (["--routes", "0"], "invalid_config"), (["--frontier", "-1"], "invalid_config")]:
            with self.subTest(extra=extra):
                run = subprocess.run([sys.executable, str(SCRIPTS / "candidate_archive.py"), "brief",
                                      "--archive", str(self.path), *extra], capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(json.loads(run.stderr)["error"]["type"], error)
        self.record("baseline", 1)
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.brief("--anchor", "missing")
        self.assertEqual(caught.exception.kind, "unknown_candidate")

    def test_brief_does_not_mutate_archive_or_evaluation_files(self) -> None:
        self.record("baseline", 1)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.brief()
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)


if __name__ == "__main__":
    unittest.main()
