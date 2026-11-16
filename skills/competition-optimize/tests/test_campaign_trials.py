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
trials = importlib.import_module("campaign_trials")
search = importlib.import_module("campaign_search")


class CampaignTrialTests(unittest.TestCase):
    """Create prospective chains through the public archive API and real runs."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_root = self.root
        self.path = self.root / "candidates.jsonl"
        self.entries: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.sequence = 0
        self.baseline = self.record("baseline", 100)
        self.comparison = self.baseline["comparison"]

    def record(self, name: str, value: int = 90, *, proposal: str | None = None,
               parents: list[str] | None = None, feedback: str = "Actual observed outcome",
               prediction: str = "contradicted", failure: str | None = None,
               valid: bool = True, adapter_score: bool = True,
               comparison: dict | None = None, scope: str = "program_source",
               reuse: str | None = None, role: str = "development",
               snapshot: bool = True, executed: bool = True) -> dict:
        self.sequence += 1
        folder = self.run_root / str(self.sequence)
        folder.mkdir(parents=True)
        source = folder / "solution.py"
        source.write_text(f"def solve():\n    label = {name!r}\n    return {value}\nprint(solve())\n", encoding="utf-8")
        if reuse:
            source.write_bytes(Path(self.entries[reuse]["artifact_paths"]["source"]).read_bytes())
        execution = subprocess.run(["/usr/bin/python3", str(source)], capture_output=True, text=True, check=True)
        measured = int(execution.stdout.strip())
        receipt = {"status": "success" if valid else "failed", "valid": valid,
                   "candidate_hash": archive.hash_path(source), "candidate_scope": scope,
                   "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
                   "score_model_hash": "m" * 64, "stage": "development"}
        if adapter_score:
            receipt["score"] = {"kind": "official_metric", "metric": "quality",
                                "direction": "maximize", "value": measured}
        for key, item in (comparison or {}).items():
            if key == "config_hash":
                receipt.setdefault("evaluation", {})[key] = item
            else:
                receipt[key] = item
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        parent_ids = self.proposals[proposal]["parent_ids"] if proposal else parents or []
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--route", "main", "--mechanism", f"implementation {name}",
                "--status", ("unresolved" if role == "diagnostic" else "runner_up") if valid else "rejected", "--role", role,
                "--feedback", feedback]
        if snapshot:
            args += ["--source", str(source)]
        if executed:
            args += ["--result", str(result)]
        if not executed or not adapter_score:
            # These explicit flags keep a complete claimed comparison, but a
            # missing adapter score must never become an observed objective.
            args += ["--valid" if valid else "--invalid", "--objective-value", str(measured),
                     "--objective-direction", "maximize", "--objective-kind", "official_metric",
                     "--objective-name", "quality"]
            if not executed:
                args += ["--evaluator-hash", "e" * 64, "--workload-hash", "w" * 64,
                         "--score-model-hash", "m" * 64, "--stage", "development"]
        for parent in parent_ids:
            args += ["--parent", parent]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", prediction]
        if reuse:
            args += ["--reuse-reason", "A genuine new measurement of archived implementation bytes"]
        if failure:
            args += ["--failure", failure]
        entry = archive.record_candidate(archive.parser().parse_args(args))
        self.entries[name] = entry
        return entry

    def propose(self, name: str, parents: list[str] | None = None, *,
                feedback_from: list[str] | None = None, prose: str | None = None) -> dict:
        parent_ids = parents or ["baseline"]
        proposal = {"proposal_id": name, "parent_ids": parent_ids,
                    "feedback_from": feedback_from or parent_ids,
                    "route": "main", "code_targets": [self.entries[parent_ids[0]]["artifact_paths"]["source"]],
                    "basis": prose or f"The measured parent suggests testing {name}",
                    "change": f"Implement the prospective mechanism {name}",
                    "expected_observation": f"Prediction made before execution for {name}",
                    "validation": "Use the fixed development adapter and complete matching contract",
                    "stop_condition": "Record an actual supported, contradicted or unresolved outcome"}
        path = self.root / f"proposal-{len(self.proposals)}.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        event = archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.proposals[name] = event
        return event

    def history(self, *, related: set[str] | None = None, seen: dict | None = None,
                comparison: dict | None = None, limit: int = 2) -> dict:
        return trials.trial_history(self.path, archive.read_records(self.path),
                                    self.comparison if comparison is None else comparison,
                                    related or set(), seen=seen, limit=limit)

    def packet(self, history: dict) -> dict:
        raw = self.path.read_bytes()
        return {"schema_version": 1, "archive_path": str(self.path),
                "archive_snapshot": {"size": len(raw), "sha256": archive.sha256(raw)},
                "task_sha256": "t" * 64, "scope": "Test development evidence", "trial_history": history}

    def test_diagnostics_recall_predictions_and_inform_successors_without_candidate_gains(self) -> None:
        for name, score in (("ablation", 1), ("counterfactual", 150)):
            self.propose(name)
            self.record(name + "-result", score, proposal=name, role="diagnostic",
                        feedback=f"Observed intervention {name}; inspect the measured component")
        history = self.history()
        self.assertEqual(history["available"], 2)
        for row in history["selection"]:
            self.assertEqual(row["state"], "measured")
            self.assertEqual(row["outcome_role"], "diagnostic")
            self.assertEqual(row["objective_gain_vs_parents"], {"baseline": None})
            self.assertEqual(row["evidence"][row["candidate_id"]]["role"], "diagnostic")
            self.assertEqual(row["feedback"], self.entries[row["candidate_id"]]["feedback"])
        bounded = search.bound_packet(self.packet(history), budget=48 * 1024, mode="work")
        self.assertEqual(trials.delivered_trials(bounded), ["ablation", "counterfactual"])
        bounded["trial_history"]["selection"][0]["evidence"]["ablation-result"]["role"] = "development"
        self.assertEqual(trials.delivered_trials(bounded), ["counterfactual"])

        brief = archive.optimization_brief(archive.parser().parse_args(["brief", "--archive", str(self.path)]))
        self.assertEqual(brief["best_development"], "baseline")
        self.propose("guided-change", ["baseline", "ablation-result"],
                     feedback_from=["counterfactual-result", "ablation-result"])
        child = self.record("guided-child", 101, proposal="guided-change", prediction="supported")
        row = self.history(related={child["implementation"]["fingerprint"]})["selection"][0]
        self.assertEqual(row["proposal_id"], "guided-change")
        self.assertEqual(row["outcome_role"], "development")
        self.assertEqual(row["objective_gain_vs_parents"], {"baseline": 1, "ablation-result": None})
        self.assertEqual(row["evidence"]["counterfactual-result"]["role"], "diagnostic")

    def test_old_closed_prediction_and_actual_outcome_survive_score_history(self) -> None:
        original = self.propose("old-pruning")
        old = self.record("old-outcome", 90, proposal="old-pruning",
                          feedback="The claimed safe pruning excluded an improving path")
        for number in range(6):
            self.propose(f"new-{number}")
            self.record(f"new-outcome-{number}", 101 + number, proposal=f"new-{number}", prediction="supported")
        history = self.history()
        self.assertEqual((history["available"], history["omitted"]), (7, 5))
        retained = history["selection"][0]
        self.assertEqual(retained["proposal_id"], "old-pruning")
        for field in ("basis", "change", "expected_observation", "validation", "stop_condition", "code_targets"):
            self.assertEqual(retained[field], original[field])
        self.assertEqual(retained["candidate_id"], "old-outcome")
        self.assertEqual(retained["prediction_status"], "contradicted")
        self.assertEqual(retained["feedback"], old["feedback"])
        self.assertEqual(retained["state"], "measured")
        self.assertEqual(retained["objective_gain_vs_parents"], {"baseline": -10})
        for candidate_id in ("baseline", "old-outcome"):
            card = retained["evidence"][candidate_id]
            self.assertEqual(card["result"]["result_sha256"], self.entries[candidate_id]["result"]["result_sha256"])
            self.assertEqual(card["artifact_paths"], self.entries[candidate_id]["artifact_paths"])
        self.assertEqual(trials.delivered_trials(self.packet(history)), ["old-pruning", "new-0"])

    def test_latest_related_trial_uses_implementation_alias_while_other_slot_rotates(self) -> None:
        for number in range(3):
            self.record(f"parent-{number}", 100 + number)
            self.propose(f"trial-{number}", [f"parent-{number}"])
            self.record(f"outcome-{number}", 110 + number, proposal=f"trial-{number}")
        self.propose("latest-related", ["parent-2"])
        self.record("latest-related-outcome", 1, proposal="latest-related")
        alias = self.record("renamed-parent-alias", reuse="parent-2")
        related = {alias["implementation"]["fingerprint"]}
        first = self.history(related=related)
        self.assertEqual([row["proposal_id"] for row in first["selection"]], ["latest-related", "trial-0"])
        self.assertEqual([row["retrieval_reason"] for row in first["selection"]],
                         ["recent_related", "least_recently_exposed"])
        second = self.history(related=related, seen={"latest-related": 1, "trial-0": 1})
        self.assertEqual([row["proposal_id"] for row in second["selection"]], ["latest-related", "trial-1"])
        no_related = self.history(seen={"trial-0": 1, "trial-1": 2}, limit=10)
        self.assertEqual([row["proposal_id"] for row in no_related["selection"]], ["trial-2", "latest-related"])
        self.assertEqual(self.history(limit=0)["omitted"], 4)

    def test_failed_and_claimed_scores_do_not_disprove_method_or_invent_gains(self) -> None:
        for name, options in (("failed", {"valid": False}), ("unscored", {"adapter_score": False})):
            self.propose(name)
            outcome = self.record(name + "-outcome", 999, proposal=name,
                                  feedback="An execution or observation issue remains unresolved",
                                  prediction="unresolved", **options)
            row = self.history(related={outcome["implementation"]["fingerprint"]})["selection"][0]
            self.assertEqual(row["state"], "failed_or_unscored")
            self.assertEqual(row["prediction_status"], "unresolved")
            self.assertEqual(row["objective_gain_vs_parents"], {"baseline": None})
            self.assertNotIn("objective", row["evidence"][outcome["candidate_id"]])
            self.assertIn("agent reports", row["scope"])
        self.propose("supported-other-observation")
        outcome = self.record("lower-score-but-supported", 80, proposal="supported-other-observation", prediction="supported",
                              feedback="The predicted representation behavior was observed; objective declined")
        row = self.history(related={outcome["implementation"]["fingerprint"]})["selection"][0]
        self.assertEqual((row["state"], row["prediction_status"]), ("measured", "supported"))
        self.assertEqual(row["objective_gain_vs_parents"], {"baseline": -20})

    def test_pending_stopped_manual_outputs_alias_and_confirmation_do_not_add_trials(self) -> None:
        self.propose("completed")
        self.record("completed-outcome", proposal="completed")
        before = self.history()
        self.propose("pending")
        self.propose("stopped")
        archive.stop_proposal(archive.parser().parse_args(
            ["stop", "--archive", str(self.path), "--proposal-id", "stopped", "--reason", "Observed missing optional data"]))
        self.record("manual", executed=False)
        self.propose("output-only")
        self.record("output-outcome", proposal="output-only", scope="prediction_csv")
        self.propose("unsnapshotted")
        self.record("missing-source-outcome", proposal="unsnapshotted", snapshot=False)
        self.record("repeat-alias", reuse="completed-outcome")
        confirmation = self.record("secret-confirmation", 987654321, role="confirmation",
                                   feedback="secret-confirmation-feedback")
        Path(confirmation["artifact_paths"]["source"]).unlink()
        Path(confirmation["result"]["result_path"]).unlink()
        self.assertEqual(self.history(), before)
        self.assertNotIn("secret-confirmation", json.dumps(self.history()))

    def test_first_parent_owns_trial_and_foreign_cards_carry_no_evaluation_explanation(self) -> None:
        other = {"workload_hash": "foreign-workload"}
        foreign = self.record("foreign-reference", 987654321, comparison=other,
                              feedback="foreign-reference-feedback-secret")
        self.propose("matched-outcome", feedback_from=["foreign-reference", "baseline"])
        self.record("matched-child", 95, proposal="matched-outcome")
        row = self.history()["selection"][0]
        card = row["evidence"]["foreign-reference"]
        self.assertTrue(card["requires_revalidation"])
        self.assertNotIn("objective", card)
        self.assertNotIn("feedback", card)
        self.assertNotIn("987654321", json.dumps(row))
        self.assertNotIn("foreign-reference-feedback-secret", json.dumps(row))
        self.propose("transferred-outcome", ["baseline", "foreign-reference"])
        outcome = self.record("foreign-child", 888888, proposal="transferred-outcome", comparison=other,
                              feedback="foreign-outcome-feedback-secret", prediction="contradicted")
        row = self.history(related={outcome["implementation"]["fingerprint"]})["selection"][0]
        self.assertEqual(row["state"], "measured")
        self.assertFalse(row["outcome_comparison_matches"])
        self.assertIsNone(row["prediction_status"])
        self.assertIsNone(row["feedback"])
        self.assertIsNone(row["failure_mechanism"])
        self.assertEqual(row["objective_gain_vs_parents"], {"baseline": None, "foreign-reference": None})
        self.assertNotIn("objective", row["evidence"]["foreign-child"])
        self.assertNotIn("888888", json.dumps(row))
        self.assertNotIn("foreign-outcome-feedback-secret", json.dumps(row))
        self.assertEqual(self.history(comparison=foreign["comparison"])["available"], 0)
        self.assertEqual(trials.delivered_trials(self.packet(self.history())), ["matched-outcome", "transferred-outcome"])

    def test_only_selected_chains_are_hashed_and_selected_target_changes_are_rejected(self) -> None:
        for number in range(3):
            self.propose(f"trial-{number}")
            self.record(f"outcome-{number}", proposal=f"trial-{number}")
        untouched = self.entries["outcome-2"]
        Path(untouched["artifact_paths"]["source"]).unlink()
        Path(untouched["result"]["result_path"]).unlink()
        opened: set[Path] = set()
        read_bytes = Path.read_bytes
        def read(path: Path) -> bytes:
            opened.add(path.resolve())
            return read_bytes(path)
        with mock.patch.object(Path, "read_bytes", read):
            history = self.history()
        self.assertEqual([row["proposal_id"] for row in history["selection"]], ["trial-0", "trial-1"])
        expected = {self.path.resolve()}
        for name in ("baseline", "outcome-0", "outcome-1"):
            expected.add(Path(self.entries[name]["result"]["result_path"]))
            expected.add(Path(self.entries[name]["artifact_paths"]["source"]))
        self.assertEqual(opened, expected)
        target = Path(self.baseline["artifact_paths"]["source"])
        target.write_text("print('changed parent')\n", encoding="utf-8")
        with self.assertRaises(archive.ArchiveFailure):
            self.history()

    def test_delivery_accepts_bounded_prose_but_rejects_identity_or_reference_loss(self) -> None:
        self.propose("completed", prose="原始推测" * 3000)
        self.record("outcome", proposal="completed", feedback="实际反馈" * 3000)
        packet = self.packet(self.history())
        bounded = search.bound_packet(packet, budget=48 * 1024, mode="work")
        self.assertTrue(bounded["truncated_fields"])
        self.assertEqual(trials.delivered_trials(bounded), ["completed"])
        changes = [lambda p, t: p.update(archive_path=p["archive_path"] + ".other"),
                   lambda p, t: t["code_targets"][0].update(path=t["code_targets"][0]["path"] + ".other"),
                   lambda p, t: t["evidence"]["outcome"]["result"].update(result_sha256="0" * 64),
                   lambda p, t: t["evidence"].pop("baseline"),
                   lambda p, t: t.update(identity_checks={"code_targets": "not_recorded"})]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                mutated = copy.deepcopy(bounded)
                change(mutated, mutated["trial_history"]["selection"][0])
                self.assertEqual(trials.delivered_trials(mutated), [])
        self.assertEqual(trials.delivered_trials({"archive_path": str(self.path), "trial_history": None}), [])

    def test_oversized_trial_is_omitted_whole_and_long_result_path_is_preserved(self) -> None:
        long_id = "trial-" + "机制" * 10000
        self.propose(long_id)
        self.record("long-id-outcome", proposal=long_id)
        self.propose("long-result-trial")
        self.run_root = self.root / ("nested-" + "a" * 140) / ("nested-" + "b" * 140)
        self.record("long-result-outcome", proposal="long-result-trial")
        packet = self.packet(self.history())
        self.assertEqual(trials.delivered_trials(packet), [long_id, "long-result-trial"])
        bounded = search.bound_packet(packet, budget=48 * 1024, mode="work")
        self.assertLessEqual(len(archive.canonical(bounded)) + 1, 48 * 1024)
        self.assertEqual(trials.delivered_trials(bounded), ["long-result-trial"])
        kept = bounded["trial_history"]["selection"][0]
        original = packet["trial_history"]["selection"][1]
        self.assertEqual(kept["evidence"], original["evidence"])
        self.assertEqual(kept["retrieval_sha256"], original["retrieval_sha256"])
        self.assertIn("/trial_history/selection/omitted_items", bounded["truncated_fields"])


if __name__ == "__main__":
    unittest.main()
