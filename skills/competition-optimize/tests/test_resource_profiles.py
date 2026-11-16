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
search = importlib.import_module("campaign_search")
campaign_archive = importlib.import_module("campaign_archive")
resources = importlib.import_module("resource_profiles")
fixtures = importlib.import_module("test_optimization_brief")


class ResourceProfileTests(unittest.TestCase):
    setUp = fixtures.OptimizationBriefTests.setUp
    record = fixtures.OptimizationBriefTests.record
    brief = fixtures.OptimizationBriefTests.brief
    propose = fixtures.OptimizationBriefTests.propose

    def profile_record(self, name: str, quality: float | None, cost: float | None, *,
                       profile: dict | None = None, **kwargs) -> dict:
        receipt = dict(kwargs.pop("receipt_fields", {}))
        if cost is not None:
            receipt["resource_profile"] = {"metric": "latency", "unit": "seconds",
                                           "scope": "candidate_inference", "protocol_sha256": "a" * 64,
                                           "value": cost, **(profile or {})}
        return self.record(name, quality, receipt_fields=receipt, **kwargs)

    def view(self, anchor: str = "best") -> dict:
        return self.brief("--anchor", anchor, "--recent", "1", "--routes", "1", "--frontier", "0")

    def test_hidden_fast_parent_survives_context_and_can_supply_actual_proposal_targets(self) -> None:
        fast = self.profile_record("old-fast", 80, 1, route="fast", feedback="Observed tradeoff. " * 5000)
        best = self.profile_record("best", 100, 10)
        self.profile_record("interior", 90, 5, route="middle")
        self.profile_record("dominated", 70, 6, route="bad")
        for i in range(6):
            self.profile_record(f"recent-{i}", 50, 20)
        value = self.view("recent-5")
        tradeoff = value["resource_tradeoffs"]
        self.assertEqual(value["best_development"], "best")
        self.assertEqual(tradeoff["reference_candidate_id"], "best")
        self.assertEqual(tradeoff["available"], 3)
        self.assertEqual(tradeoff["omitted"], 1)
        self.assertEqual([p["candidate_id"] for p in tradeoff["selection"]], ["old-fast", "best"])
        self.assertNotIn("old-fast", value["recent_current"])
        self.assertEqual(value["candidates"]["old-fast"]["artifact_paths"], fast["artifact_paths"])
        packet = search.handoff_packet(self.path, archive.read_records(self.path),
                                       {"size": self.path.stat().st_size, "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertLessEqual(len(archive.canonical(packet)) + 1, search.HANDOFF_BYTES)
        self.assertEqual(packet["development_brief"]["resource_tradeoffs"]["selection"], tradeoff["selection"])
        self.assertEqual(packet["development_brief"]["candidates"]["best"]["result"]["result_sha256"],
                         best["result"]["result_sha256"])
        proposal = self.propose("combine", "best", parents=["best", "old-fast"], feedback=["old-fast"])
        self.assertEqual({t["path"] for t in proposal["code_targets"]},
                         {best["artifact_paths"]["source"], fast["artifact_paths"]["source"]})

    def test_protocols_comparisons_and_unmeasured_costs_are_never_inferred_or_mixed(self) -> None:
        self.profile_record("fast", 80, 1)
        self.profile_record("best", 100, 10)
        for i, changes in enumerate([{"metric": "memory"}, {"unit": "ms"}, {"scope": "training"},
                                     {"protocol_sha256": "b" * 64}]):
            self.profile_record(f"other-protocol-{i}", 90, 0, profile=changes)
        for i, comparison in enumerate([{"evaluator_hash": "other"}, {"workload_hash": "other"},
                                         {"score_model_hash": "other"}, {"stage": "short"},
                                         {"config_hash": "other"}, {"runtime_environment": {"python": "other"}}]):
            self.profile_record(f"foreign-{i}", 1000, 0, comparison=comparison)
        self.profile_record("unprofiled", 99, None, receipt_fields={"elapsed_seconds": 0})
        value = self.view()
        self.assertEqual(value["resource_tradeoffs"]["profiled_implementations"], 2)
        self.assertEqual(value["resource_tradeoffs"]["protocol_groups"], 5)
        self.assertEqual([p["candidate_id"] for p in value["resource_tradeoffs"]["selection"]], ["fast", "best"])
        for card in value["candidates"].values():
            self.assertNotEqual(card["objective"]["value"], 1000)
        fresh = self.profile_record("unprofiled-new-contract", 1, None,
                                    comparison={"workload_hash": "empty"})
        empty = self.view(fresh["candidate_id"])["resource_tradeoffs"]
        self.assertIsNone(empty["protocol"])
        self.assertEqual(empty["selection"], [])

    def test_minimization_equal_points_and_dominance_have_stable_correct_endpoints(self) -> None:
        self.profile_record("fast-low-quality", 10, 1, direction="minimize")
        self.profile_record("equal-later", 10, 1, direction="minimize")
        self.profile_record("same-cost-better", 8, 1, direction="minimize")
        self.profile_record("same-quality-slower", 8, 2, direction="minimize")
        self.profile_record("best", 2, 10, direction="minimize")
        points = self.view()["resource_tradeoffs"]
        self.assertEqual(points["available"], 2)
        self.assertEqual([p["candidate_id"] for p in points["selection"]], ["same-cost-better", "best"])
        self.profile_record("dominates-all", 1, 0, direction="minimize")
        single = self.view("dominates-all")["resource_tradeoffs"]
        self.assertEqual(single["available"], 1)
        self.assertEqual(single["selection"][0]["endpoint"], "fastest_and_highest_quality")

    def test_repeat_uses_same_observation_for_quality_and_resource_not_best_or_fastest_alias(self) -> None:
        self.profile_record("best-no-profile", 100, None)
        self.profile_record("best-first-profile", 90, 9, reuse="best-no-profile")
        self.profile_record("best-lucky-profile", 1000, 0, reuse="best-no-profile")
        self.profile_record("fast-first", 80, 1)
        self.profile_record("fast-lucky", 95, 0, reuse="fast-first")
        value = self.view("best-lucky-profile")
        tradeoff = value["resource_tradeoffs"]
        self.assertEqual(value["best_development"], "best-no-profile")
        self.assertEqual(tradeoff["reference_candidate_id"], "best-first-profile")
        self.assertEqual([p["candidate_id"] for p in tradeoff["selection"]], ["fast-first", "best-first-profile"])
        self.assertEqual(tradeoff["selection"][1]["objective"]["value"], 90)
        self.assertEqual(tradeoff["selection"][1]["resource_profile"]["value"], 9)

    def test_missing_best_profile_falls_back_only_to_explicit_anchor_implementation(self) -> None:
        self.profile_record("old-profile", 80, 1)
        self.profile_record("best", 100, None)
        self.profile_record("anchor", 90, 10, profile={"protocol_sha256": "b" * 64})
        value = self.view("anchor")["resource_tradeoffs"]
        self.assertEqual(value["reference_reason"], "anchor_implementation_first_profile")
        self.assertEqual(value["protocol_groups"], 2)
        self.assertEqual(value["selection"][0]["candidate_id"], "anchor")
        unavailable = self.view("best")["resource_tradeoffs"]
        self.assertIsNone(unavailable["protocol"])
        self.assertEqual(unavailable["protocol_groups"], 2)

    def test_confirmation_diagnostic_failed_partial_manual_output_only_and_missing_code_are_excluded(self) -> None:
        self.profile_record("best", 100, 10)
        self.profile_record("fast", 80, 1)
        confirmation = self.profile_record("confirmation", 10000, 0, role="confirmation")
        self.profile_record("diagnostic", 10000, 0, role="diagnostic", parent="best", status="promising")
        self.profile_record("failed", 90, 0, valid=False, status="rejected")
        self.profile_record("manual", 90, 0, result=False)
        self.profile_record("output-only", 90, 0, receipt_fields={"candidate_scope": "prediction_csv"})
        self.profile_record("missing-source", 90, 0, snapshot=False)
        self.profile_record("partial", 90, 0, status="rejected", receipt_fields={
            "evaluation": {"config_hash": "c" * 64, "runtime_environment": {"python": "fixture"},
                           "expected_cases": 4, "completed_cases": 3}})
        Path(confirmation["artifact_paths"]["source"]).unlink()
        Path(confirmation["result"]["result_path"]).unlink()
        view = self.view()
        self.assertEqual(view["resource_tradeoffs"]["profiled_implementations"], 2)
        self.assertEqual(view["best_development"], "best")

    def test_selected_source_result_and_archived_profile_changes_are_rejected(self) -> None:
        fast = self.profile_record("fast", 80, 1)
        self.profile_record("best", 100, 10)
        for path, expected in [(Path(fast["artifact_paths"]["source"]), "parent_artifact_changed"),
                               (Path(fast["result"]["result_path"]), "result_changed")]:
            raw = path.read_bytes()
            path.write_bytes(raw + b" ")
            with self.assertRaises(archive.ArchiveFailure) as caught:
                self.view()
            self.assertEqual(caught.exception.kind, expected)
            path.write_bytes(raw)
        records = archive.read_records(self.path)
        records[0]["result"]["resource_profile"]["value"] = 0
        with self.assertRaises(archive.ArchiveFailure) as caught:
            archive.optimization_brief(archive.parser().parse_args(["brief", "--archive", str(self.path)]), records)
        self.assertEqual(caught.exception.kind, "invalid_resource_profile")

    def test_schema_validation_and_legacy_result_revalidation(self) -> None:
        profile = {"metric": "latency", "unit": "seconds", "scope": "candidate_inference",
                   "protocol_sha256": "a" * 64, "value": 1}
        invalid = [None, [], {}, {**profile, "extra": 1}]
        invalid += [{**profile, key: value} for key, value in [
            ("metric", ""), ("unit", " "), ("scope", "x" * 129), ("protocol_sha256", "bad"),
            ("value", True), ("value", -1), ("value", float("inf")), ("value", float("nan")),
            ("value", 10 ** 1000)]]
        for value in invalid:
            with self.subTest(value=str(value)[:70]), self.assertRaises(resources.ResourceFailure):
                resources.describe(value)
        self.assertEqual(resources.describe({**profile, "value": 0})["value"], 0)
        candidate = self.profile_record("best", 100, 10)
        self.assertEqual(campaign_archive.CampaignArchive(self.path).verified().evidence.records[0]["result"], candidate["result"])
        old = copy.deepcopy(candidate)
        old["result"].pop("resource_profile")
        self.path.write_bytes(archive.canonical(old) + b"\n")
        self.assertEqual(campaign_archive.CampaignArchive(self.path).verified().evidence.records[0]["result"], old["result"])
        self.assertEqual(self.view()["resource_tradeoffs"]["selection"], [])
        result_path = Path(candidate["result"]["result_path"])
        result = json.loads(result_path.read_text())
        result["resource_profile"]["value"] = -1
        result_path.write_text(json.dumps(result))
        with self.assertRaises(archive.ArchiveFailure) as caught:
            archive.result_metadata(result_path)
        self.assertEqual(caught.exception.kind, "invalid_resource_profile")


if __name__ == "__main__":
    unittest.main()
