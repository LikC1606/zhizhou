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
search = importlib.import_module("campaign_search")


class CampaignSearchTests(unittest.TestCase):
    """Exercise search decisions with evidence accepted by the real archive API."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "candidates.jsonl"
        self.entries: dict[str, dict] = {}
        self.sequence = 0

    def record(self, name: str, score: float | None = 10, *, route: str = "current",
               direction: str = "maximize", kind: str = "official_metric",
               metric: str = "quality", valid: bool = True, status: str = "runner_up",
               role: str = "development", parent: str | None = None, feedback: str = "",
               failure: str = "", comparison: dict | None = None,
               reuse: str | None = None, scope: str = "program_source",
               recipe: str | None = None, executed: bool = True,
               snapshot: bool = True, result_score: bool = True,
               execution_status: str | None = None, result_error: dict | str | None = None,
               result_artifacts: list | None = None, partial: bool = False,
               result_reference: str | None = None, objective_flags: bool = True) -> dict:
        self.sequence += 1
        folder = self.root / str(self.sequence)
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"def solve(): return {name!r}\n", encoding="utf-8")
        if reuse is not None:
            source.write_bytes(Path(self.entries[reuse]["artifact_paths"]["source"]).read_bytes())
        result = {
            "status": execution_status or ("success" if valid else "failed"), "valid": valid,
            "candidate_hash": archive.hash_path(source), "candidate_scope": scope,
            "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
            "score_model_hash": "m" * 64, "stage": "development",
            "score": {"kind": kind, "metric": metric, "direction": direction, "value": score},
        }
        for key, value in (comparison or {}).items():
            if key == "config_hash":
                result.setdefault("evaluation", {})[key] = value
            else:
                result[key] = value
        if not result_score:
            result.pop("score")
        if result_error is not None:
            result["error"] = result_error
        if result_artifacts is not None:
            result["artifacts"] = result_artifacts
        if partial:
            result["metrics"] = {"partial": True}
        result_path = folder / "result.json"
        result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        if result_reference is not None:
            result_path = Path(self.entries[result_reference]["result"]["result_path"])
        arguments = ["record", "--archive", str(self.path), "--candidate-id", name,
                     "--route", route, "--mechanism", "fixture implementation",
                     "--status", status, "--role", role]
        if snapshot:
            arguments += ["--source", str(source)]
        if recipe is not None:
            pipeline = folder / "pipeline.py"
            pipeline.write_text(recipe + "\n", encoding="utf-8")
            arguments += ["--configuration", str(pipeline)]
        if executed:
            arguments += ["--result", str(result_path)]
            if not result_score and objective_flags:
                arguments += ["--objective-direction", direction, "--objective-kind", kind,
                              "--objective-name", metric]
                if score is not None:
                    arguments += ["--objective-value", str(score)]
        else:
            arguments += ["--valid" if valid else "--invalid",
                          "--objective-direction", direction, "--objective-kind", kind,
                          "--objective-name", metric, "--evaluator-hash", result["evaluator_hash"],
                          "--workload-hash", result["workload_hash"],
                          "--score-model-hash", result["score_model_hash"], "--stage", result["stage"]]
            if score is not None:
                arguments += ["--objective-value", str(score)]
        if parent is not None:
            arguments += ["--parent", parent]
        if feedback:
            arguments += ["--feedback", feedback]
        if failure:
            arguments += ["--failure", failure]
        if reuse is not None:
            arguments += ["--reuse-reason", "matched repeated measurement"]
        entry = archive.record_candidate(archive.parser().parse_args(arguments))
        self.entries[name] = entry
        return entry

    def records(self) -> list[dict]:
        return archive.read_records(self.path)

    def propose(self, name: str, parent: str, *, feedback: list[str] | None = None) -> None:
        proposal = {"proposal_id": name, "parent_ids": [parent], "feedback_from": feedback or [parent],
                    "route": "next", "code_targets": [self.entries[parent]["artifact_paths"]["source"]],
                    "basis": "Inspect the archived implementation and observed issue",
                    "change": "Implement a complete successor", "expected_observation": "Recover a usable observation",
                    "validation": "Fixed development adapter", "stop_condition": "Record a tested outcome or a concrete stop reason"}
        path = self.root / (name + ".json")
        path.write_text(json.dumps(proposal), encoding="utf-8")
        archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))

    def progress(self) -> dict:
        return search.objective_progress(self.records())

    def health(self) -> dict:
        return search.execution_health(self.records())

    def recovery(self) -> dict | None:
        records = self.records()
        return search.recovery_evidence(records, search.execution_health(records))

    def packet(self, **kwargs) -> dict:
        # The caller owns these control identities. They stay fixed here so a
        # confirmation record cannot leak indirectly through changed metadata.
        return search.handoff_packet(self.path, self.records(), {"sha256": "a" * 64, "size": 1}, "t" * 64, **kwargs)

    def test_empty_archive_has_no_objective_and_cannot_trigger_review(self) -> None:
        progress = self.progress()
        self.assertIsNone(progress["best_candidate"])
        self.assertEqual(progress["comparable_implementations"], 0)
        self.assertFalse(search.review_due(progress, None, 1))
        self.assertIsNone(self.packet()["development_brief"])

    def test_first_measurement_is_a_baseline_not_an_improvement_or_failure(self) -> None:
        self.record("baseline", 10)
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["best_value"], 10)
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertEqual(progress["implementations_since_best"], 0)
        self.assertEqual(progress["improvement_candidates"], [])
        self.assertEqual(progress["nonimproving_candidates"], [])
        self.assertFalse(search.review_due(progress, None, 1))

    def test_maximize_replays_historical_best_instead_of_latest_score(self) -> None:
        self.record("baseline", 10)
        self.record("first-gain", 12)
        self.record("regression", 8)
        self.record("rebound", 11)
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "first-gain")
        self.assertEqual(progress["best_value"], 12)
        self.assertEqual(progress["implementations_since_best"], 2)
        self.assertEqual(progress["improvement_candidates"], ["first-gain"])
        self.assertEqual(progress["nonimproving_candidates"], ["regression", "rebound"])
        self.record("new-high", 13)
        self.assertEqual(self.progress()["best_candidate"], "new-high")
        self.assertEqual(self.progress()["implementations_since_best"], 0)

    def test_minimize_reverses_gain_and_plateau_direction(self) -> None:
        self.record("baseline", 10, direction="minimize")
        self.record("regression", 14, direction="minimize")
        self.record("rebound", 11, direction="minimize")
        self.assertEqual(self.progress()["best_candidate"], "baseline")
        self.assertEqual(self.progress()["implementations_since_best"], 2)
        self.record("new-low", 9, direction="minimize")
        self.assertEqual(self.progress()["best_value"], 9)
        self.assertEqual(self.progress()["improvement_candidates"], ["new-low"])
        self.assertEqual(self.progress()["implementations_since_best"], 0)

    def test_route_rename_rebound_and_unresolved_labels_do_not_reset_plateau(self) -> None:
        self.record("baseline", 10, route="old")
        self.record("weak", 6, route="old")
        self.record("renamed", 8, route="new", status="promising", feedback="An untested opportunity")
        self.record("unresolved", 9, route="newer", status="unresolved", feedback="Still worth pursuing")
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["implementations_since_best"], 3)
        self.assertTrue(search.review_due(progress, None, 3))

    def test_equal_score_is_not_a_new_best(self) -> None:
        self.record("baseline", 10)
        self.record("tie", 10)
        self.assertEqual(self.progress()["best_candidate"], "baseline")
        self.assertEqual(self.progress()["implementations_since_best"], 1)
        self.assertEqual(self.progress()["improvement_candidates"], [])

    def test_repeated_implementation_lucky_measurement_cannot_replace_best(self) -> None:
        self.record("baseline", 10)
        self.record("weak", 8)
        self.record("lucky-repeat", 100, reuse="weak")
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 2)
        self.assertEqual(progress["implementations_since_best"], 1)
        self.assertEqual(progress["nonimproving_candidates"], ["weak"])

    def test_comparison_evidence_surfaces_first_measurement_conflict_without_reranking(self) -> None:
        self.record("a-first", 100)
        self.record("b-first", 60)
        self.record("a-repeat-one", 10, reuse="a-first")
        self.record("a-repeat-two", 10, reuse="a-first")
        self.record("b-repeat", 60, reuse="b-first")
        evidence = archive.ComparisonEvidence(self.records(), eligible=search.observed_implementation)
        view = evidence.for_candidate("b-repeat")
        self.assertEqual([entry["candidate_id"] for entry in view.representatives], ["a-first", "b-first"])
        self.assertEqual(len(evidence.first_observations()), 2)
        self.assertEqual(self.progress()["best_candidate"], "a-first")
        conflict = view.ranking_conflict()
        self.assertEqual((conflict["leader_candidate"], conflict["challenger_candidate"],
                          conflict["witness_candidate"], conflict["reason"]),
                         ("a-first", "b-first", "a-repeat-one", "leader_repeat_below_challenger_first"))
        packet = self.packet()
        self.assertEqual(packet["repeat_conflict"]["signature"], conflict["signature"])
        self.assertTrue(search.delivered_repeat_conflict(packet))
        self.assertEqual(packet["development_brief"]["best_development"], "a-first")
        altered = json.loads(json.dumps(packet))
        altered["repeat_conflict"]["cards"]["witness"]["result_path"] = "[truncated]"
        self.assertFalse(search.delivered_repeat_conflict(altered))

    def test_conflict_requires_real_repeated_result_under_the_same_comparison(self) -> None:
        self.record("leader", 100)
        self.record("challenger", 60)
        self.record("other-contract", 10, reuse="leader", comparison={"config_hash": "other"})
        view = archive.ComparisonEvidence(self.records(), eligible=search.observed_implementation).for_candidate("leader")
        self.assertIsNone(view.ranking_conflict())
        self.record("repeat", 10, reuse="leader")
        self.assertIsNotNone(self.packet()["repeat_conflict"])

    def test_repeat_conflict_respects_minimize_direction(self) -> None:
        self.record("leader", 1, direction="minimize")
        self.record("challenger", 5, direction="minimize")
        self.record("leader-repeat", 10, direction="minimize", reuse="leader")
        conflict = self.packet()["repeat_conflict"]
        self.assertEqual((conflict["leader_candidate"], conflict["witness_candidate"]),
                         ("leader", "leader-repeat"))

    def test_new_output_bytes_from_same_recipe_are_not_new_implementations(self) -> None:
        self.record("baseline", 10, scope="prediction_csv", recipe="fit_declared_pipeline()")
        self.record("lucky-output", 100, scope="prediction_csv", recipe="fit_declared_pipeline()")
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertEqual(progress["implementations_since_best"], 0)

    def test_confirmation_cannot_change_progress_review_or_handoff(self) -> None:
        self.record("baseline", 10)
        self.record("weak", 8, feedback="Observed failure")
        before_progress, before_packet = self.progress(), self.packet()
        confirmation = self.record("secret-confirmation-id", 987654321,
                                   role="confirmation", route="secret-confirmation-route",
                                   feedback="secret-confirmation-feedback")
        Path(confirmation["artifact_paths"]["source"]).unlink()
        Path(confirmation["result"]["result_path"]).unlink()
        self.assertEqual(self.progress(), before_progress)
        self.assertEqual(self.packet(), before_packet)
        self.assertNotIn("secret-confirmation", json.dumps(self.packet()))

    def test_output_only_results_do_not_create_quality_observations(self) -> None:
        self.record("baseline", 10)
        for number, scope in enumerate(("prediction_csv", "generated_artifact")):
            with self.subTest(scope=scope):
                self.record(f"output-only-{number}", 100, scope=scope)
                progress = self.progress()
                self.assertEqual(progress["best_candidate"], "baseline")
                self.assertEqual(progress["comparable_implementations"], 1)
                self.assertEqual(progress["implementations_since_best"], 0)
                self.assertFalse(progress["latest_eligible"])
                self.assertFalse(search.review_due(progress, None, 1))

    def test_manual_score_without_execution_cannot_count_as_measured_progress(self) -> None:
        self.record("baseline", 10)
        manual = self.record("manual-score", 100, executed=False)
        self.assertTrue(archive.measurable(manual))
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertFalse(progress["latest_eligible"])

    def test_result_without_source_snapshot_cannot_supply_executed_implementation(self) -> None:
        self.record("baseline", 10)
        self.record("unsnapshotted", 100, snapshot=False)
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertFalse(progress["latest_eligible"])

    def test_manual_objective_flags_cannot_invent_a_missing_adapter_score(self) -> None:
        self.record("baseline", 10)
        claimed = self.record("claimed-gain", 100, result_score=False)
        self.assertTrue(archive.measurable(claimed))
        self.assertTrue(search.executed_implementation(claimed))
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertFalse(progress["latest_eligible"])

    def test_failed_first_attempt_does_not_poison_first_valid_observation_of_same_code(self) -> None:
        self.record("baseline", 10)
        self.record("failed", 100, valid=False, status="rejected")
        self.record("repaired-environment", 11, reuse="failed")
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "repaired-environment")
        self.assertEqual(progress["comparable_implementations"], 2)
        self.assertEqual(progress["improvement_candidates"], ["repaired-environment"])

    def test_failed_and_unknown_measurements_do_not_invent_quality_samples(self) -> None:
        self.record("baseline", 10)
        self.record("failed", 100, valid=False, status="rejected", failure="Capacity violation")
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertFalse(progress["latest_eligible"])
        self.record("unknown", None, kind="unknown")
        self.assertEqual(self.progress()["comparable_implementations"], 0)
        self.assertFalse(search.review_due(self.progress(), None, 1))

    def test_entire_comparison_identity_isolated_in_both_directions(self) -> None:
        self.record("baseline", 10)
        self.record("original-weak", 8)
        original = self.progress()
        changes = [
            {"comparison": {"evaluator_hash": "different-evaluator"}},
            {"comparison": {"workload_hash": "different-workload"}},
            {"comparison": {"score_model_hash": "different-score-model"}},
            {"comparison": {"config_hash": "different-config"}},
            {"comparison": {"runtime_environment": {"python": "different-runtime"}}},
            {"comparison": {"stage": "screening"}},
            {"kind": "proxy"}, {"metric": "different-metric"}, {"direction": "minimize"},
        ]
        for number, change in enumerate(changes):
            with self.subTest(change=change):
                name = f"other-comparison-{number}"
                self.record(name, 1000, **change)
                progress = self.progress()
                self.assertNotEqual(progress["comparison_key"], original["comparison_key"])
                self.assertEqual(progress["best_candidate"], name)
                self.assertEqual(progress["comparable_implementations"], 1)
                self.assertEqual(progress["implementations_since_best"], 0)
                self.assertEqual(progress["improvement_candidates"], [])
        self.record("back-to-original", 9)
        progress = self.progress()
        self.assertEqual(progress["comparison_key"], original["comparison_key"])
        self.assertEqual(progress["best_candidate"], "baseline")
        self.assertEqual(progress["comparable_implementations"], 3)
        self.assertEqual(progress["implementations_since_best"], 2)

    def test_same_code_under_new_comparison_becomes_only_its_own_baseline(self) -> None:
        self.record("baseline", 10)
        self.record("other-data", 100, reuse="baseline", comparison={"workload_hash": "other-data"})
        progress = self.progress()
        self.assertEqual(progress["best_candidate"], "other-data")
        self.assertEqual(progress["comparable_implementations"], 1)
        self.assertEqual(progress["improvement_candidates"], [])

    def test_paired_smoke_cannot_hide_four_contracts_without_other_implementations(self) -> None:
        self.record("smoke-baseline", comparison={"stage": "smoke"})
        self.record("smoke-candidate", comparison={"stage": "smoke"})
        for number in range(4):
            self.record(f"full-{number}", comparison={"config_hash": f"full-{number}"})
            self.record(f"smoke-repeat-{number}", reuse="smoke-candidate", comparison={"stage": "smoke"})
        continuity = search.comparison_continuity(self.records())
        self.assertEqual(continuity["distinct_observations"], 6)
        self.assertEqual(continuity["unpaired_contracts"], 4)
        self.assertEqual(continuity["new_unpaired_contracts"], 4)
        self.assertEqual(continuity["recent_unpaired_candidates"], [f"full-{i}" for i in range(4)])
        self.assertEqual(continuity["latest_unpaired_candidate"], "full-3")
        self.assertTrue(search.comparison_review_due(continuity, 4))
        self.assertEqual(search.comparison_recovery(self.records(), continuity)["target"]["candidate_id"], "full-3")
        self.assertFalse(search.review_due(self.progress(), None, 4))

    def test_smoke_to_full_and_promptly_paired_new_contracts_need_no_measurement_review(self) -> None:
        smoke = {"stage": "smoke"}
        self.record("smoke-baseline", comparison=smoke)
        for number in range(5):
            full = {"config_hash": f"full-fidelity-{number}"}
            self.record(f"full-baseline-{number}", comparison=full)
            self.assertFalse(search.comparison_review_due(search.comparison_continuity(self.records()), 4))
            self.record(f"full-candidate-{number}", comparison=full)
            self.assertFalse(search.comparison_review_due(search.comparison_continuity(self.records()), 4))
        self.record("smoke-candidate", comparison=smoke)
        continuity = search.comparison_continuity(self.records())
        self.assertEqual(continuity["distinct_observations"], 12)
        self.assertEqual(continuity["unpaired_contracts"], 0)
        self.assertEqual(continuity["new_unpaired_contracts"], 0)
        self.assertIsNone(continuity["latest_unpaired_candidate"])
        self.assertIsNone(search.comparison_recovery(self.records(), continuity))

    def test_same_code_reruns_do_not_pair_but_old_code_under_new_contract_does(self) -> None:
        self.record("old-code")
        other = {"workload_hash": "other-workload"}
        self.record("new-code", comparison=other)
        before = search.comparison_continuity(self.records())
        self.record("lucky-rerun", 1000, reuse="new-code", comparison=other)
        self.assertEqual(search.comparison_continuity(self.records()), before)
        self.record("old-code-on-other", reuse="old-code", comparison=other)
        continuity = search.comparison_continuity(self.records())
        self.assertEqual(continuity["distinct_observations"], 3)
        self.assertEqual(continuity["unpaired_contracts"], 1)
        self.assertEqual(continuity["recent_unpaired_candidates"], ["old-code"])
        self.record("new-code-on-original", reuse="new-code")
        continuity = search.comparison_continuity(self.records())
        self.assertEqual(continuity["distinct_observations"], 4)
        self.assertEqual(continuity["unpaired_contracts"], 0)

    def test_measurement_checkpoint_only_acknowledges_earlier_remaining_singletons(self) -> None:
        self.record("old-singleton", comparison={"config_hash": "old"})
        checkpoint = {"distinct_observations": search.comparison_continuity(self.records())["distinct_observations"]}
        self.assertEqual(search.comparison_continuity(self.records(), checkpoint)["unpaired_contracts"], 1)
        self.assertEqual(search.comparison_continuity(self.records(), checkpoint)["new_unpaired_contracts"], 0)
        for number in range(3):
            self.record(f"new-singleton-{number}", comparison={"config_hash": f"new-{number}"})
        continuity = search.comparison_continuity(self.records(), checkpoint)
        self.assertEqual(continuity["unpaired_contracts"], 4)
        self.assertEqual(continuity["new_unpaired_contracts"], 3)
        self.assertFalse(search.comparison_review_due(continuity, 4))
        self.record("repeat-old", reuse="old-singleton", comparison={"config_hash": "old"})
        self.assertEqual(search.comparison_continuity(self.records(), checkpoint), continuity)
        self.record("new-singleton-3", comparison={"config_hash": "new-3"})
        self.assertTrue(search.comparison_review_due(search.comparison_continuity(self.records(), checkpoint), 4))
        self.record("paired-new-zero", reuse="old-singleton", comparison={"config_hash": "new-0"})
        continuity = search.comparison_continuity(self.records(), checkpoint)
        self.assertEqual(continuity["unpaired_contracts"], 4)
        self.assertEqual(continuity["new_unpaired_contracts"], 3)
        self.assertFalse(search.comparison_review_due(continuity, 4))

    def test_unobserved_and_confirmation_records_cannot_change_comparison_continuity(self) -> None:
        self.record("real-singleton")
        before = search.comparison_continuity(self.records())
        cases = [("failed", {"valid": False, "status": "rejected"}),
                 ("partial", {"valid": False, "partial": True, "status": "rejected"}),
                 ("unknown", {"score": None, "kind": "unknown"}),
                 ("manual", {"executed": False}),
                 ("without-snapshot", {"snapshot": False}),
                 ("output-only", {"scope": "prediction_csv"}),
                 ("claimed-score", {"result_score": False}),
                 ("confirmation", {"role": "confirmation"})]
        for name, options in cases:
            with self.subTest(name=name):
                self.record(name, **options)
                self.assertEqual(search.comparison_continuity(self.records()), before)

    def test_comparison_recovery_prefers_different_implementation_ancestor_without_foreign_scores(self) -> None:
        original = {"workload_hash": "original-workload", "config_hash": "original-config"}
        ancestor = self.record("reference-ancestor", 987654321, comparison=original,
                               feedback="foreign-reference-feedback")
        self.record("same-code-parent", parent="reference-ancestor",
                    comparison={"workload_hash": "intermediate-workload"})
        self.record("unrelated-newer", comparison=original)
        target = self.record("unpaired-target", reuse="same-code-parent", parent="same-code-parent",
                             comparison={"workload_hash": "target-workload", "config_hash": "target-config"},
                             feedback="target-observation-is-not-in-the-identity-card")
        records = self.records()
        recovery = search.comparison_recovery(records, search.comparison_continuity(records))
        self.assertEqual(recovery["reference"]["candidate_id"], "reference-ancestor")
        self.assertEqual(recovery["target"]["candidate_id"], "unpaired-target")
        self.assertEqual(recovery["changed_fields"], ["config_hash", "workload_hash"])
        for label, entry in (("reference", ancestor), ("target", target)):
            card = recovery[label]
            self.assertEqual(card["implementation"]["fingerprint"], entry["implementation"]["fingerprint"])
            self.assertEqual(card["comparison"], entry["comparison"])
            self.assertEqual(card["result_sha256"], entry["result"]["result_sha256"])
            self.assertTrue(card["requires_revalidation"])
            self.assertNotIn("objective", card)
            self.assertNotIn("feedback", card)
        serialized = json.dumps(recovery)
        self.assertNotIn("987654321", serialized)
        self.assertNotIn("foreign-reference-feedback", serialized)
        self.assertNotIn("target-observation-is-not", serialized)

    def test_fallback_comparison_reference_and_handoff_ignore_confirmation_artifacts(self) -> None:
        self.record("earlier-reference")
        self.propose("historical-proposal", "earlier-reference")
        self.record("same-target-code-earlier")
        self.record("target", reuse="same-target-code-earlier", comparison={"workload_hash": "target-workload"})
        records = self.records()
        continuity = search.comparison_continuity(records)
        recovery = search.comparison_recovery(records, continuity)
        self.assertEqual(recovery["reference"]["candidate_id"], "earlier-reference")
        before_packet = self.packet(continuity=continuity)
        self.assertEqual(before_packet["comparison_continuity"], continuity)
        self.assertEqual({key: value for key, value in before_packet["comparison_recovery"].items()
                          if key != "retrieval_sha256"}, recovery)
        secret = self.record("secret-confirmation", 987654321, role="confirmation", feedback="secret-feedback")
        Path(secret["artifact_paths"]["source"]).unlink()
        Path(secret["result"]["result_path"]).unlink()
        self.assertEqual(search.comparison_continuity(self.records()), continuity)
        self.assertEqual(search.comparison_recovery(self.records(), continuity), recovery)
        self.assertEqual(self.packet(continuity=continuity), before_packet)

    def test_comparison_recovery_bounds_history_and_packet_with_large_runtime_metadata(self) -> None:
        for number in range(9):
            self.record(f"isolated-{number}", comparison={"config_hash": f"config-{number}"})
        metadata = {f"package-{number}": {f"field-{field}": "版本信息" * 300 for field in range(8)}
                    for number in range(80)}
        self.record("isolated-9", comparison={"config_hash": "config-9", "runtime_environment": metadata})
        records = self.records()
        continuity = search.comparison_continuity(records)
        self.assertEqual(continuity["recent_unpaired_candidates"], [f"isolated-{i}" for i in range(2, 10)])
        recovery = search.comparison_recovery(records, continuity)
        self.assertEqual([card["candidate_id"] for card in recovery["unpaired_examples"]],
                         [f"isolated-{i}" for i in range(6, 10)])
        self.assertEqual(recovery["examples_omitted"], 6)
        for card in recovery["unpaired_examples"]:
            self.assertNotIn("comparison", card)
            self.assertNotIn("objective", card)
            self.assertNotIn("feedback", card)
            self.assertTrue(card["comparison_sha256"])
            self.assertTrue(card["implementation_fingerprint"])
            self.assertTrue(card["result_path"])
        packet = self.packet(continuity=continuity)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False).encode("utf-8")), search.HANDOFF_BYTES)
        self.assertTrue(packet["truncated_fields"])
        self.assertEqual(packet["archive_path"], str(self.path))
        self.assertEqual(packet["comparison_continuity"]["unpaired_contracts"], 10)
        self.assertEqual(packet["comparison_recovery"]["target"]["candidate_id"], "isolated-9")
        self.assertEqual(self.records()[-1]["comparison"]["runtime_environment"], metadata)

    def test_measurement_review_delivery_requires_full_pointers_after_bounding_and_compaction(self) -> None:
        self.record("reference")
        self.record("normal-target", parent="reference", comparison={"workload_hash": "normal"})
        self.assertTrue(search.delivered_comparison_review(self.packet()))
        metadata = {f"package-{number}": {f"field-{field}": "版本信息" * 300 for field in range(8)}
                    for number in range(80)}
        self.record("compact-target", parent="reference",
                    comparison={"workload_hash": "compact", "runtime_environment": metadata})
        compact = self.packet()
        self.assertIn("details_omitted", compact["comparison_recovery"])
        self.assertRegex(compact["comparison_recovery"]["retrieval_sha256"], r"^[0-9a-f]{64}$")
        self.assertLessEqual(len(archive.canonical(compact)) + 1, search.HANDOFF_BYTES)
        self.assertTrue(search.delivered_comparison_review(compact))
        compact["comparison_recovery"]["target"]["result_path"] += ".different-result"
        self.assertFalse(search.delivered_comparison_review(compact))
        for label, key in (("long-id", "candidate_id"), ("long-result", "result_path")):
            with self.subTest(pointer=key):
                name = "target-" + "候选" * 1000 if label == "long-id" else "long-result-target"
                if label == "long-result":
                    self.root = self.root / ("result-" + "a" * 140) / ("nested-" + "b" * 140)
                    self.root.mkdir(parents=True)
                entry = self.record(name, parent="reference",
                                    comparison={"workload_hash": label, "runtime_environment": metadata})
                actual_pointer = entry["candidate_id"] if key == "candidate_id" else entry["result"]["result_path"]
                bounded = self.packet()
                self.assertIn("details_omitted", bounded["comparison_recovery"])
                # Whole-card selection preserves identities even when ordinary
                # descriptive metadata needs compaction.
                self.assertEqual(bounded["comparison_recovery"]["target"][key], actual_pointer)
                self.assertTrue(search.delivered_comparison_review(bounded))

    def test_review_requires_a_new_nonimproving_window_after_each_review(self) -> None:
        self.record("baseline", 10)
        for number in range(4):
            self.record(f"first-window-{number}", 9)
        reviewed = self.progress()
        self.assertTrue(search.review_due(reviewed, None, 4))
        self.assertFalse(search.review_due(reviewed, reviewed, 4))
        self.record("repeat", 999, reuse="first-window-3")
        self.assertFalse(search.review_due(self.progress(), reviewed, 4))
        for number in range(3):
            self.record(f"next-window-{number}", 8)
            self.assertFalse(search.review_due(self.progress(), reviewed, 4))
        self.record("next-window-3", 8)
        self.assertTrue(search.review_due(self.progress(), reviewed, 4))

    def test_improvement_after_review_starts_a_new_quality_window(self) -> None:
        self.record("baseline", 10)
        for number in range(2):
            self.record(f"old-weak-{number}", 9)
        reviewed = self.progress()
        self.record("improved", 11)
        self.assertFalse(search.review_due(self.progress(), reviewed, 2))
        self.record("new-weak-0", 10)
        self.assertFalse(search.review_due(self.progress(), reviewed, 2))
        self.record("new-weak-1", 10)
        self.assertTrue(search.review_due(self.progress(), reviewed, 2))

    def test_review_requires_actual_valid_latest_measurement(self) -> None:
        self.record("baseline", 10)
        self.record("weak-0", 9)
        self.record("weak-1", 8)
        self.assertTrue(search.review_due(self.progress(), None, 2))
        for name, change in (("failed", {"valid": False, "status": "rejected"}),
                             ("manual", {"executed": False}),
                             ("unsnapshotted", {"snapshot": False}),
                             ("only-output", {"scope": "prediction_csv"})):
            with self.subTest(name=name):
                self.record(name, 100, **change)
                self.assertFalse(search.review_due(self.progress(), None, 2))

    def test_handoff_retains_cross_route_best_failure_and_unresolved_with_source_evidence(self) -> None:
        self.record("current-best", 10)
        self.record("alternative-best", 12, route="alternative")
        self.record("alternative-failure", 3, route="alternative", status="rejected",
                    feedback="Measured negative result", failure="Construction ignores an ordering constraint")
        self.record("opportunity", 11, route="opportunity", status="unresolved",
                    feedback="Residuals suggest a different representation")
        self.record("current-latest", 9, parent="current-best", feedback="Local patch regressed")
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        packet = self.packet()
        self.assertEqual(packet["objective_progress"]["best_candidate"], "alternative-best")
        brief = packet["development_brief"]
        self.assertEqual(brief["best_development"], "alternative-best")
        routes = {entry["route"]: entry for entry in brief["routes"]}
        self.assertEqual(routes["current"]["best"], "current-best")
        self.assertEqual(routes["alternative"]["latest_failure"], "alternative-failure")
        self.assertEqual(routes["opportunity"]["unresolved"], "opportunity")
        latest = brief["candidates"]["current-latest"]
        self.assertEqual(latest["objective_gain_vs_parents"]["current-best"], -1)
        self.assertEqual(latest["artifact_paths"]["source"], self.entries["current-latest"]["artifact_paths"]["source"])
        self.assertEqual(latest["result"]["result_path"], self.entries["current-latest"]["result"]["result_path"])
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_handoff_parent_gains_respect_direction_and_reject_cross_comparison_gain(self) -> None:
        self.record("parent", 10, direction="minimize")
        self.record("improved", 8, direction="minimize", parent="parent")
        self.assertEqual(self.packet()["development_brief"]["candidates"]["improved"]
                         ["objective_gain_vs_parents"]["parent"], 2)
        self.record("changed-contract", 1, direction="minimize", parent="improved",
                    comparison={"workload_hash": "other-data"})
        card = self.packet()["development_brief"]["candidates"]["changed-contract"]
        self.assertIsNone(card["objective_gain_vs_parents"]["improved"])

    def test_handoff_best_requires_the_same_real_scored_execution_as_progress(self) -> None:
        self.record("baseline", 10)
        for name, change in (("manual-high", {"executed": False}),
                             ("outputs-high", {"scope": "prediction_csv"}),
                             ("flags-high", {"result_score": False}),
                             ("unsnapshotted-high", {"snapshot": False})):
            with self.subTest(name=name):
                self.record(name, 1000, **change)
                packet = self.packet()
                self.assertEqual(packet["objective_progress"]["best_candidate"], "baseline")
                self.assertEqual(packet["development_brief"]["best_development"], "baseline")
                self.assertIn(name, packet["development_brief"]["candidates"])

    def test_handoff_omits_foreign_comparison_scores_and_caps_route_context(self) -> None:
        self.record("foreign-secret-id", 123456, route="foreign",
                    comparison={"runtime_environment": {"identity": "foreign-runtime"}},
                    feedback="foreign-secret-feedback")
        for number in range(8):
            self.record(f"alternative-{number}", number + 1, route=f"route-{number}")
        self.record("current", 10)
        packet = self.packet()
        brief = packet["development_brief"]
        self.assertLessEqual(len(brief["routes"]), 4)
        self.assertNotIn("foreign-secret-id", brief["candidates"])
        self.assertNotIn("foreign-secret-feedback", json.dumps(packet))
        self.assertNotIn("123456", json.dumps(packet))
        self.assertGreater(brief["omitted"]["other_development_comparisons"], 0)

    def test_handoff_pending_work_in_other_comparisons_is_not_the_active_task_list(self) -> None:
        def propose(name: str, parent: str) -> None:
            entry = self.entries[parent]
            proposal = {"proposal_id": name, "parent_ids": [parent], "feedback_from": [parent],
                        "route": entry["route"], "code_targets": [entry["artifact_paths"]["source"]],
                        "basis": "Measured implementation leaves a residual error",
                        "change": "Replace the representation", "expected_observation": "Lower residual error",
                        "validation": "Matched development evaluation", "stop_condition": "Contradicted mechanism"}
            path = self.root / (name + ".json")
            path.write_text(json.dumps(proposal), encoding="utf-8")
            archive.propose_candidate(archive.parser().parse_args(
                ["propose", "--archive", str(self.path), "--proposal", str(path)]))

        self.record("foreign-parent", 1000, comparison={"workload_hash": "foreign-workload"})
        propose("foreign-pending", "foreign-parent")
        self.record("current-parent", 10)
        propose("current-pending", "current-parent")
        packet = self.packet()
        brief = packet["development_brief"]
        self.assertEqual(brief["pending_proposals"], ["current-pending"])
        self.assertNotIn("foreign-pending", json.dumps(packet))
        self.assertGreater(brief["omitted"]["pending_details"], 0)

    def test_handoff_keeps_active_pending_ids_beyond_rotating_details(self) -> None:
        self.record("parent", 10)
        for number in range(7):
            self.propose(f"p{number}", "parent")
        packet = self.packet(pending_seen={})
        brief = packet["development_brief"]
        self.assertEqual(brief["pending_proposals"], [f"p{i}" for i in range(7)])
        self.assertEqual(search.delivered_exposures(packet)["proposals"], ["p0", "p1", "p2", "p3"])
        again = self.packet(pending_seen=dict.fromkeys(["p0", "p1", "p2", "p3"], 1))
        self.assertEqual(search.delivered_exposures(again)["proposals"], ["p4", "p5", "p6", "p0"])
        self.assertEqual(again["development_brief"]["pending_summary"]["available"], 7)

    def test_repair_proposal_retains_cross_contract_identity_without_score_or_feedback(self) -> None:
        good = self.record("good", 123456, feedback="foreign-feedback-must-not-guide-this-contract")
        self.record("failed", None, valid=False, status="rejected", parent="good",
                    result_score=False, objective_flags=False, result_error={"phase": "run", "message": "IndexError"})
        self.propose("repair", "failed", feedback=["good", "failed"])
        packet = self.packet(pending_seen={})
        brief = packet["development_brief"]
        self.assertEqual(brief["pending_proposals"], ["repair"])
        self.assertNotIn("good", brief["candidates"])
        reference = brief["pending_references"]["good"]
        self.assertTrue(reference["requires_revalidation"])
        self.assertEqual(reference["implementation"]["fingerprint"], good["implementation"]["fingerprint"])
        self.assertEqual(reference["result"]["result_sha256"], good["result"]["result_sha256"])
        self.assertNotIn("123456", json.dumps(packet))
        self.assertNotIn("foreign-feedback-must-not", json.dumps(packet))
        self.assertEqual(search.delivered_exposures(packet)["proposals"], ["repair"])
        brief["pending_references"].pop("good")
        self.assertEqual(search.delivered_exposures(packet)["proposals"], [])

    def test_pending_exposure_requires_complete_targets_but_not_full_feedback_prose(self) -> None:
        self.record("parent", 10)
        self.propose("p0", "parent")
        packet = self.packet(pending_seen={})
        self.assertEqual(search.delivered_exposures(packet)["proposals"], ["p0"])
        packet["truncated_fields"]["/development_brief/candidates/parent/feedback"] = 100
        self.assertEqual(search.delivered_exposures(packet)["proposals"], ["p0"])
        packet["truncated_fields"]["/development_brief/pending_details/0/code_targets/0/path"] = 100
        self.assertEqual(search.delivered_exposures(packet)["proposals"], [])

    def test_handoff_large_feedback_is_bounded_and_points_back_to_evidence(self) -> None:
        self.record("baseline", 10)
        self.record("verbose-failure", 9, status="rejected", feedback="实测失败原因" * 20000,
                    failure="Constraint violation " * 10000)
        packet = self.packet()
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False).encode("utf-8")), search.HANDOFF_BYTES)
        self.assertTrue(packet["truncated_fields"])
        self.assertEqual(packet["archive_path"], str(self.path))
        self.assertEqual(packet["task_sha256"], "t" * 64)
        self.assertEqual(self.records()[-1]["feedback"], "实测失败原因" * 20000)

    def test_handoff_hard_byte_bound_survives_oversized_unicode_identifiers(self) -> None:
        self.record("候选" * 20000, 10, feedback="证据" * 20000)
        packet = self.packet()
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False).encode("utf-8")), search.HANDOFF_BYTES)
        self.assertTrue(packet["truncated_fields"])
        self.assertEqual(packet["archive_path"], str(self.path))

    def test_empty_execution_history_needs_no_repair_or_review(self) -> None:
        health = self.health()
        self.assertEqual(health["execution_attempts"], 0)
        self.assertEqual(health["attempts_without_observation"], 0)
        self.assertIsNone(health["anchor_candidate"])
        self.assertIsNone(health["last_scored_candidate"])
        self.assertFalse(health["needs_attention"])
        self.assertFalse(search.execution_review_due(health, None, 1))
        self.assertIsNone(self.recovery())

    def test_unscored_failures_remain_continuous_across_changed_comparison_contracts(self) -> None:
        baseline = self.record("healthy-baseline", 10)
        first = self.record("compile-failure", None, valid=False, status="rejected",
                            result_score=False, objective_flags=False,
                            result_error={"type": "compilation_failure", "phase": "compile",
                                          "message": "missing semicolon"})
        self.assertNotEqual(first["comparison"], baseline["comparison"])
        second = self.record("renamed-route-failure", None, valid=False, status="rejected",
                             route="renamed", result_score=False, objective_flags=False,
                             comparison={"evaluator_hash": None, "workload_hash": "other-workload"})
        self.assertNotEqual(second["comparison"], first["comparison"])
        health = self.health()
        self.assertEqual(health["execution_attempts"], 3)
        self.assertEqual(health["attempts_without_observation"], 2)
        self.assertEqual(health["last_scored_candidate"], "healthy-baseline")
        self.assertEqual(health["recent_unmeasured_candidates"],
                         ["compile-failure", "renamed-route-failure"])
        self.assertEqual(health["issue"], "failed_or_invalid_execution")
        self.assertTrue(search.execution_review_due(health, None, 2))
        # Operational recovery does not turn these records into low scores.
        self.assertEqual(self.progress()["comparable_implementations"], 0)
        self.assertFalse(search.review_due(self.progress(), None, 1))

    def test_success_without_a_usable_metric_requests_observation_repair_not_low_score(self) -> None:
        self.record("baseline", 10)
        cases = [("unknown-metric", {"kind": "unknown", "score": 999}),
                 ("null-metric", {"score": None}),
                 ("missing-metric", {"score": None, "result_score": False, "objective_flags": False}),
                 ("claimed-metric", {"score": 999, "result_score": False})]
        for number, (name, options) in enumerate(cases, 1):
            with self.subTest(name=name):
                self.record(name, **options)
                health = self.health()
                self.assertTrue(health["needs_attention"])
                self.assertEqual(health["issue"], "unusable_objective")
                self.assertEqual(health["attempts_without_observation"], number)
                self.assertEqual(health["last_scored_candidate"], "baseline")
                self.assertFalse(search.review_due(self.progress(), None, 1))
                self.assertIn("not evidence against its algorithm", self.recovery()["scope"])

    def test_partial_or_invalid_success_is_an_execution_issue(self) -> None:
        self.record("baseline", 10)
        for name, options in (("invalid-output", {}), ("partial-evaluation", {"partial": True})):
            with self.subTest(name=name):
                self.record(name, 1000, valid=False, status="rejected", execution_status="success", **options)
                self.assertEqual(self.health()["issue"], "failed_or_invalid_execution")
                self.assertEqual(self.progress()["best_candidate"], "baseline")
                self.assertEqual(self.progress()["comparable_implementations"], 1)
        self.assertTrue(self.recovery()["target"]["diagnostic"]["partial"])

    def test_real_scored_success_recovers_health_even_with_a_lower_score(self) -> None:
        self.record("baseline", 10)
        self.record("failed", None, valid=False, status="rejected", result_score=False, objective_flags=False)
        self.record("unmeasured", None)
        self.assertEqual(self.health()["attempts_without_observation"], 2)
        self.record("recovered", 8)
        health = self.health()
        self.assertEqual(health["execution_attempts"], 4)
        self.assertEqual(health["last_scored_candidate"], "recovered")
        self.assertEqual(health["attempts_without_observation"], 0)
        self.assertEqual(health["recent_unmeasured_candidates"], [])
        self.assertFalse(health["needs_attention"])
        self.assertIsNone(health["issue"])
        self.assertIsNone(self.recovery())
        self.assertEqual(self.progress()["best_candidate"], "baseline")
        self.assertIsNone(self.packet()["execution_recovery"])

    def test_repeated_code_with_new_execution_is_an_attempt_but_result_alias_is_not(self) -> None:
        self.record("baseline", 10)
        first = self.record("failed", None, valid=False, status="rejected", result_score=False,
                            objective_flags=False)
        repeat = self.record("repeated-failure", None, valid=False, status="rejected", reuse="failed",
                             result_score=False, objective_flags=False)
        self.assertEqual(search.executed_implementation(first), search.executed_implementation(repeat))
        self.assertNotEqual(first["result"]["result_path"], repeat["result"]["result_path"])
        # Identical JSON bytes at a new execution path still identify a new run.
        self.assertEqual(first["result"]["result_sha256"], repeat["result"]["result_sha256"])
        before = self.health()
        self.assertEqual(before["attempts_without_observation"], 2)
        self.record("alias-of-finished-result", None, valid=False, status="rejected", reuse="failed",
                    result_reference="failed", result_score=False, objective_flags=False)
        self.assertEqual(self.health(), before)
        self.assertEqual(self.recovery()["target"]["candidate_id"], "repeated-failure")

    def test_failed_code_can_recover_from_a_successful_rerun_without_becoming_a_new_implementation(self) -> None:
        first = self.record("failed", None, valid=False, status="rejected", result_score=False,
                            objective_flags=False)
        success = self.record("environment-recovered", 11, reuse="failed")
        self.assertEqual(search.executed_implementation(first), search.executed_implementation(success))
        self.assertEqual(self.health()["execution_attempts"], 2)
        self.assertEqual(self.health()["last_scored_candidate"], "environment-recovered")
        self.assertFalse(self.health()["needs_attention"])

    def test_confirmation_manual_unsnapshotted_and_output_only_records_cannot_change_health(self) -> None:
        self.record("baseline", 10)
        self.record("active-failure", None, valid=False, status="rejected", result_score=False,
                    objective_flags=False)
        before = self.health()
        cases = [("confirmation", {"role": "confirmation"}),
                 ("manual", {"executed": False}),
                 ("without-snapshot", {"snapshot": False}),
                 ("predictions-only", {"scope": "prediction_csv"}),
                 ("generated-only", {"scope": "generated_artifact"})]
        for name, options in cases:
            with self.subTest(name=name):
                entry = self.record(name, None, valid=False, status="rejected", result_score=False,
                                    objective_flags=False, **options)
                if name == "confirmation":
                    Path(entry["result"]["result_path"]).unlink()
                    Path(entry["artifact_paths"]["source"]).unlink()
                self.assertEqual(self.health(), before)
                self.assertEqual(self.recovery()["target"]["candidate_id"], "active-failure")

    def test_execution_review_requires_new_attempts_after_review_and_resets_after_recovery(self) -> None:
        self.record("baseline", 10)
        for number in range(3):
            self.record(f"failed-{number}", None, valid=False, status="rejected", result_score=False,
                        objective_flags=False)
        reviewed = self.health()
        self.assertTrue(search.execution_review_due(reviewed, None, 3))
        self.assertFalse(search.execution_review_due(reviewed, reviewed, 3))
        for number in range(2):
            self.record(f"more-failed-{number}", None, valid=False, status="rejected", result_score=False,
                        objective_flags=False)
            self.assertFalse(search.execution_review_due(self.health(), reviewed, 3))
        self.record("more-failed-2", None, valid=False, status="rejected", result_score=False,
                    objective_flags=False)
        self.assertTrue(search.execution_review_due(self.health(), reviewed, 3))
        self.record("recovered", 8)
        self.assertFalse(search.execution_review_due(self.health(), reviewed, 3))
        for number in range(3):
            self.record(f"new-failed-{number}", None, valid=False, status="rejected", result_score=False,
                        objective_flags=False)
            self.assertEqual(search.execution_review_due(self.health(), reviewed, 3), number == 2)

    def test_recovery_prefers_actual_scored_ancestor_over_newer_unrelated_observation(self) -> None:
        self.record("ancestor", 10, comparison={"workload_hash": "ancestor-workload"})
        self.record("newer-unrelated", 20)
        self.record("failed-parent", None, parent="ancestor", valid=False, status="rejected",
                    result_score=False, objective_flags=False)
        self.record("failed-target", None, parent="failed-parent", valid=False, status="rejected",
                    result_score=False, objective_flags=False)
        self.assertEqual(self.health()["last_scored_candidate"], "newer-unrelated")
        recovery = self.recovery()
        self.assertEqual(recovery["target"]["candidate_id"], "failed-target")
        self.assertEqual(recovery["reference"]["candidate_id"], "ancestor")
        self.assertEqual(recovery["reference_relationship"], "scored_ancestor")
        self.assertFalse(recovery["reference_comparison_matches"])
        self.assertIn("another contract", recovery["scope"])
        self.assertIn("must be revalidated", recovery["scope"])
        self.assertEqual(recovery["reference"]["identity_checks"],
                         {"result_bytes": "checked", "snapshot_bytes": "checked"})

    def test_recovery_follows_diagnostic_to_ordinary_control_instead_of_using_intervention_as_reference(self) -> None:
        self.record("control", 10)
        self.record("intervention", 10000, role="diagnostic", status="unresolved", parent="control")
        self.record("failed-child", None, parent="intervention", valid=False, status="rejected",
                    result_score=False, objective_flags=False)
        self.assertEqual(self.health()["last_scored_candidate"], "intervention")
        recovery = self.recovery()
        self.assertEqual(recovery["target"]["role"], "development")
        self.assertEqual(recovery["reference"]["candidate_id"], "control")
        self.assertEqual(recovery["reference"]["role"], "development")
        self.assertEqual(recovery["reference_relationship"], "scored_ancestor")

    def test_recovery_confirmation_ancestor_is_a_barrier_and_cannot_supply_feedback(self) -> None:
        self.record("behind-confirmation", 9)
        confirmation = self.record("secret-confirmation", 3141592653, role="confirmation",
                                   parent="behind-confirmation", feedback="hidden-feedback-only")
        self.record("available-development", 10)
        self.record("failed-target", None, parent="secret-confirmation", valid=False, status="rejected",
                    result_score=False, objective_flags=False)
        Path(confirmation["result"]["result_path"]).unlink()
        Path(confirmation["artifact_paths"]["source"]).unlink()
        recovery = self.recovery()
        self.assertEqual(recovery["reference"]["candidate_id"], "available-development")
        self.assertEqual(recovery["reference_relationship"], "earlier_development_observation")
        packet = self.packet()
        self.assertNotIn("3141592653", json.dumps(packet))
        self.assertNotIn("hidden-feedback-only", json.dumps(packet))
        self.assertNotIn("secret-confirmation", packet["development_brief"]["candidates"])

    def test_recovery_without_any_development_observation_has_no_reference(self) -> None:
        self.record("first-failure", None, valid=False, status="rejected", result_score=False,
                    objective_flags=False)
        recovery = self.recovery()
        self.assertEqual(recovery["target"]["candidate_id"], "first-failure")
        self.assertIsNone(recovery["reference"])
        self.assertIsNone(recovery["reference_relationship"])
        self.assertIsNone(recovery["reference_comparison_matches"])

    def test_recovery_diagnostic_comes_from_hashed_result_not_agent_failure_claim(self) -> None:
        self.record("baseline", 10)
        error = {"type": "infrastructure_failure", "phase": "compiler_check",
                 "message": "Compiler not found", "unrelated_control_field": "do not forward"}
        entry = self.record("failed", None, valid=False, status="rejected", result_score=False,
                            objective_flags=False, failure="UNVERIFIED_ALGORITHM_IS_BAD",
                            result_error=error,
                            result_artifacts=["compiler.stderr.txt", 123, {"untrusted": "value"}])
        recovery = self.recovery()
        self.assertEqual(recovery["target"]["diagnostic"], {
            "error": {"type": "infrastructure_failure", "phase": "compiler_check", "message": "Compiler not found"},
            "partial": False, "artifacts": ["compiler.stderr.txt"]})
        self.assertNotIn("UNVERIFIED_ALGORITHM_IS_BAD", json.dumps(recovery))
        self.assertNotIn("unrelated_control_field", json.dumps(recovery))
        self.assertEqual(recovery["target"]["result_sha256"], entry["result"]["result_sha256"])
        self.assertEqual(self.packet()["execution_recovery"], recovery)

    def test_recovery_rejects_changed_target_or_reference_result(self) -> None:
        self.record("baseline", 10)
        self.record("failed", None, parent="baseline", valid=False, status="rejected", result_score=False,
                    objective_flags=False, result_error="actual error")
        for name in ("failed", "baseline"):
            with self.subTest(name=name):
                path = Path(self.entries[name]["result"]["result_path"])
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b" ")
                    with self.assertRaises(archive.ArchiveFailure) as raised:
                        self.recovery()
                    self.assertEqual(raised.exception.kind, "result_changed")
                    with self.assertRaises(archive.ArchiveFailure):
                        self.packet()
                finally:
                    path.write_bytes(original)

    def test_recovery_handoff_bounds_large_unicode_errors_and_retains_original_result(self) -> None:
        self.record("baseline", 10)
        message = "编译失败证据" * 20000
        entry = self.record("failed", None, parent="baseline", valid=False, status="rejected",
                            result_score=False, objective_flags=False,
                            result_error={"type": "compilation_failure", "phase": "compile", "message": message},
                            result_artifacts=[f"日志-{number}-" + "证据" * 2000 for number in range(60)])
        path = Path(entry["result"]["result_path"])
        original = path.read_bytes()
        packet = self.packet()
        self.assertLessEqual(len(archive.canonical(packet)) + 1, search.HANDOFF_BYTES)
        self.assertIn("/execution_recovery/target/diagnostic/error/message", packet["truncated_fields"])
        self.assertEqual(packet["execution_recovery"]["target"]["result_path"], str(path))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(original)["error"]["message"], message)
        self.assertEqual(len(json.loads(original)["artifacts"]), 60)

    def test_recovery_handoff_hard_byte_bound_also_covers_nested_runtime_metadata(self) -> None:
        self.record("baseline", 10)
        runtime = {f"package-group-{group}": {f"package-{package}": "版本证据" * 400
                                              for package in range(30)}
                   for group in range(30)}
        entry = self.record("failed", None, parent="baseline", valid=False, status="rejected",
                            result_score=False, objective_flags=False,
                            comparison={"runtime_environment": runtime}, result_error="actual failure")
        original = Path(entry["result"]["result_path"]).read_bytes()
        packet = self.packet()
        self.assertLessEqual(len(archive.canonical(packet)) + 1, search.HANDOFF_BYTES)
        self.assertTrue(packet["truncated_fields"])
        self.assertEqual(packet["archive_path"], str(self.path))
        recovery = packet["execution_recovery"]
        self.assertEqual(recovery["target"]["candidate_id"], "failed")
        self.assertEqual(recovery["target"]["result_sha256"], entry["result"]["result_sha256"])
        self.assertEqual(recovery["target"]["result_path"], entry["result"]["result_path"])
        self.assertEqual(recovery["target"]["diagnostic"]["error"], "actual failure")
        self.assertEqual(recovery["reference"]["candidate_id"], "baseline")
        self.assertEqual(recovery["target"]["comparison_sha256"], archive.sha256(archive.canonical(entry["comparison"])))
        self.assertIn("details_omitted", recovery)
        self.assertEqual(Path(entry["result"]["result_path"]).read_bytes(), original)

    def test_progress_reconstructed_from_same_archive_is_deterministic(self) -> None:
        self.record("baseline", 10)
        self.record("improved", 11)
        self.record("weak", 9)
        self.record("lucky-repeat", 100, reuse="weak")
        first = self.progress()
        reloaded_records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(search.objective_progress(reloaded_records), first)


if __name__ == "__main__":
    unittest.main()
