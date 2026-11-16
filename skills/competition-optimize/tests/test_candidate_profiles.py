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
fixtures = importlib.import_module("test_optimization_brief")


class CandidateProfileTests(unittest.TestCase):
    # Reuse only fixture operations, without inheriting its unrelated tests.
    setUp = fixtures.OptimizationBriefTests.setUp
    record = fixtures.OptimizationBriefTests.record
    brief = fixtures.OptimizationBriefTests.brief
    propose = fixtures.OptimizationBriefTests.propose

    def profile_record(self, name: str, score: float | None, cases: dict | None, *,
                       metric: str = "case-profit", profile_direction: str = "maximize", **kwargs) -> dict:
        receipt = dict(kwargs.pop("receipt_fields", {}))
        if cases is not None:
            receipt["case_profile"] = {"metric": metric, "direction": profile_direction, "cases": cases}
            receipt.setdefault("evaluation", {
                "config_hash": "c" * 64, "runtime_environment": {"python": "fixture"},
                "expected_cases": len(cases), "completed_cases": len(cases),
            })
        return self.record(name, score, receipt_fields=receipt, **kwargs)

    def complement(self, anchor: str = "best") -> dict:
        return self.brief("--anchor", anchor, "--recent", "1", "--routes", "1", "--frontier", "0")

    def packet(self) -> dict:
        return search.handoff_packet(self.path, archive.read_records(self.path),
                                     {"size": self.path.stat().st_size, "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)

    def test_old_lower_score_specialist_survives_bounded_context_and_can_supply_a_real_parent(self) -> None:
        specialist = self.profile_record("old-specialist", 80, {"001": 12, "1": 8, "c": 10, "d": 10},
                                         feedback="Measured local strength and regression. " * 5000)
        best = self.profile_record("best", 100, {"001": 10, "1": 10, "c": 10, "d": 10})
        for number in range(6):
            self.profile_record(f"recent-{number}", 50, {"001": 9, "1": 9, "c": 9, "d": 9})
        value = self.complement("recent-5")
        evidence = value["complementary_evidence"]
        self.assertEqual(value["best_development"], "best")
        self.assertEqual(evidence["best_candidate_id"], "best")
        self.assertEqual(evidence["reference_candidate_id"], "best")
        self.assertEqual(evidence["available"], 1)
        self.assertEqual(evidence["selection"], [{
            "candidate_id": "old-specialist", "wins": 1, "losses": 1, "ties": 2, "additional_wins": 1,
            "winning_cases": [{"case_id": "001", "reference": 10, "candidate": 12}],
            "losing_cases": [{"case_id": "1", "reference": 10, "candidate": 8}],
        }])
        self.assertNotIn("old-specialist", value["recent_current"])
        card = value["candidates"]["old-specialist"]
        self.assertEqual(card["artifact_paths"], specialist["artifact_paths"])
        self.assertEqual(card["result"]["result_sha256"], specialist["result"]["result_sha256"])
        descriptor = card["result"]["case_profile"]
        self.assertEqual(set(descriptor), {"metric", "direction", "case_count", "case_keys_sha256", "profile_sha256"})
        self.assertEqual(descriptor["case_count"], 4)
        for key in ["case_keys_sha256", "profile_sha256"]:
            self.assertRegex(descriptor[key], r"^[0-9a-f]{64}$")

        packet = self.packet()
        self.assertLessEqual(len(archive.canonical(packet)) + 1, search.HANDOFF_BYTES)
        self.assertTrue(packet["truncated_fields"])
        self.assertEqual(packet["objective_progress"]["best_candidate"], "best")
        retrieved = packet["development_brief"]
        self.assertEqual(retrieved["complementary_evidence"]["selection"], evidence["selection"])
        self.assertEqual(retrieved["candidates"]["old-specialist"]["artifact_paths"], specialist["artifact_paths"])
        self.assertEqual(retrieved["candidates"]["best"]["result"]["result_sha256"], best["result"]["result_sha256"])
        proposal = self.propose("combine", "best", parents=["best", "old-specialist"],
                                feedback=["best", "old-specialist"])
        self.assertEqual(proposal["parent_ids"], ["best", "old-specialist"])
        self.assertEqual({item["path"] for item in proposal["code_targets"]},
                         {best["artifact_paths"]["source"], specialist["artifact_paths"]["source"]})

    def test_second_parent_adds_winning_case_coverage_before_scalar_score_and_archive_order(self) -> None:
        self.profile_record("best", 100, dict.fromkeys("abcd", 10))
        self.profile_record("same-cases-lower-score", 90, {"a": 12, "b": 12, "c": 9, "d": 10})
        self.profile_record("two-wins", 95, {"a": 11, "b": 11, "c": 8, "d": 9})
        self.profile_record("same-cases-later-tie", 95, {"a": 11, "b": 11, "c": 8, "d": 9})
        self.profile_record("new-case", 99, {"a": 9, "b": 9, "c": 12, "d": 10})
        value = self.complement()
        evidence = value["complementary_evidence"]
        self.assertEqual(value["best_development"], "best")
        self.assertEqual(evidence["available"], 4)
        self.assertEqual([item["candidate_id"] for item in evidence["selection"]], ["two-wins", "new-case"])
        self.assertEqual([item["wins"] for item in evidence["selection"]], [2, 1])
        self.assertEqual([item["additional_wins"] for item in evidence["selection"]], [2, 1])
        self.assertEqual(evidence["selection"][1]["winning_cases"], [{"case_id": "c", "reference": 10, "candidate": 12}])

    def test_dominated_confirmation_diagnostic_failed_manual_partial_and_output_only_are_not_donors(self) -> None:
        self.profile_record("best", 100, dict.fromkeys("abcd", 10))
        self.profile_record("dominated", 99, {"a": 10, "b": 9, "c": 8, "d": 7})
        self.profile_record("eligible", 80, {"a": 11, "b": 8, "c": 10, "d": 10})
        cases = dict.fromkeys("abcd", 20)
        confirmation = self.profile_record("confirmation", 10000, cases, role="confirmation")
        self.profile_record("diagnostic", 10000, cases, role="diagnostic", parent="best", status="promising")
        self.profile_record("failed", 90, cases, valid=False, status="rejected")
        self.profile_record("manual", 90, cases, result=False)
        self.profile_record("output-only", 90, cases, receipt_fields={"candidate_scope": "prediction_csv"})
        self.profile_record("missing-source", 90, cases, snapshot=False)
        self.profile_record("partial", 90, cases, status="rejected", receipt_fields={
            "evaluation": {"config_hash": "c" * 64, "runtime_environment": {"python": "fixture"},
                           "expected_cases": 4, "completed_cases": 3},
        })
        Path(confirmation["result"]["result_path"]).unlink()
        Path(confirmation["artifact_paths"]["source"]).unlink()
        value = self.complement()
        evidence = value["complementary_evidence"]
        self.assertEqual(value["best_development"], "best")
        self.assertEqual(evidence["available"], 1)
        self.assertEqual([item["candidate_id"] for item in evidence["selection"]], ["eligible"])
        packet = self.packet()
        self.assertEqual(packet["objective_progress"]["best_candidate"], "best")
        self.assertEqual(packet["development_brief"]["complementary_evidence"]["selection"], evidence["selection"])

    def test_complete_comparison_and_profile_metric_direction_and_case_ids_are_isolated(self) -> None:
        self.profile_record("best", 100, dict.fromkeys("abcd", 10))
        self.profile_record("eligible", 80, {"a": 11, "b": 8, "c": 10, "d": 10})
        for number, comparison in enumerate([
            {"evaluator_hash": "other"}, {"workload_hash": "other"}, {"score_model_hash": "other"},
            {"config_hash": "other"}, {"stage": "short"}, {"runtime_environment": {"python": "other"}},
        ]):
            self.profile_record(f"other-contract-{number}", 90, dict.fromkeys("abcd", 20), comparison=comparison)
        self.profile_record("other-profile-metric", 90, dict.fromkeys("abcd", 20), metric="another-profit")
        self.profile_record("other-profile-direction", 90, dict.fromkeys("abcd", 0), profile_direction="minimize")
        self.profile_record("other-profile-ids", 90, {"a": 20, "b": 20, "c": 20, "different": 20})
        self.profile_record("other-objective-name", 90, dict.fromkeys("abcd", 20), score_fields={"metric": "other"})
        self.profile_record("other-objective-kind", 90, dict.fromkeys("abcd", 20), score_fields={"kind": "proxy"})
        self.profile_record("other-objective-direction", 90, dict.fromkeys("abcd", 20), direction="minimize")
        value = self.complement()
        self.assertEqual(value["best_development"], "best")
        self.assertEqual(value["complementary_evidence"]["available"], 1)
        self.assertEqual([item["candidate_id"] for item in value["complementary_evidence"]["selection"]], ["eligible"])

        for name, scalar, cases in [
            ("loss-best", 1, dict.fromkeys("abcd", 1)),
            ("loss-specialist", 2, {"a": 0, "b": 2, "c": 1, "d": 1}),
        ]:
            self.profile_record(name, scalar, cases, metric="squared_error", profile_direction="minimize",
                                direction="minimize", comparison={"workload_hash": "loss-workload"})
        losses = self.complement("loss-best")["complementary_evidence"]
        self.assertEqual(losses["best_candidate_id"], "loss-best")
        self.assertEqual([item["candidate_id"] for item in losses["selection"]], ["loss-specialist"])
        self.assertEqual(losses["selection"][0]["winning_cases"], [{"case_id": "a", "reference": 1, "candidate": 0}])
        self.assertEqual(losses["selection"][0]["losing_cases"], [{"case_id": "b", "reference": 1, "candidate": 2}])

    def test_first_valid_matching_profile_is_kept_instead_of_lucky_remeasurement(self) -> None:
        self.profile_record("best-no-profile", 100, None)
        self.profile_record("best-first-profile", 100, dict.fromkeys("abcd", 10), reuse="best-no-profile")
        self.profile_record("best-lucky-repeat", 1000, dict.fromkeys("abcd", 5), reuse="best-no-profile")
        self.profile_record("donor-no-profile", 80, None)
        self.profile_record("donor-invalid-profile", None, dict.fromkeys("abcd", 99), reuse="donor-no-profile",
                            valid=False, status="rejected")
        self.profile_record("donor-foreign-profile", 800, dict.fromkeys("abcd", 40), reuse="donor-no-profile",
                            comparison={"workload_hash": "other"})
        self.profile_record("donor-first-profile", 80, {"a": 12, "b": 8, "c": 10, "d": 10}, reuse="donor-no-profile")
        self.profile_record("donor-lucky-repeat", 900, dict.fromkeys("abcd", 50), reuse="donor-no-profile")
        value = self.complement("best-no-profile")
        evidence = value["complementary_evidence"]
        self.assertEqual(value["best_development"], "best-no-profile")
        self.assertEqual(evidence["best_candidate_id"], "best-no-profile")
        self.assertEqual(evidence["reference_candidate_id"], "best-first-profile")
        self.assertIn("best-first-profile", value["candidates"])
        self.assertEqual([item["candidate_id"] for item in evidence["selection"]], ["donor-first-profile"])
        self.assertEqual(evidence["selection"][0]["wins"], 1)
        self.assertEqual(evidence["selection"][0]["winning_cases"], [{"case_id": "a", "reference": 10, "candidate": 12}])

    def test_changed_raw_profile_and_invalid_case_values_are_rejected(self) -> None:
        self.profile_record("best", 100, dict.fromkeys("abcd", 10))
        donor = self.profile_record("old-donor", 80, {"a": 12, "b": 8, "c": 10, "d": 10})
        path = Path(donor["result"]["result_path"])
        raw = path.read_bytes()
        changed = json.loads(raw)
        changed["case_profile"]["cases"]["a"] = 1000
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.complement()
        self.assertEqual(caught.exception.kind, "result_changed")
        with self.assertRaises(archive.ArchiveFailure) as caught:
            campaign_archive.CampaignArchive(self.path).verified().evidence.records
        self.assertEqual(caught.exception.kind, "result_changed")
        path.write_bytes(raw)
        for number, cases in enumerate([{}, {"a": True}, {"a": "12"}, {" ": 1}]):
            with self.subTest(cases=cases), self.assertRaises(archive.ArchiveFailure) as caught:
                self.profile_record(f"invalid-profile-{number}", 90, cases)
            self.assertEqual(caught.exception.kind, "invalid_case_profile")

    def test_campaign_archive_verifies_legacy_metadata_without_upgrading_or_rewriting_recorded_bytes(self) -> None:
        entry = self.profile_record("legacy", 100, dict.fromkeys("abcd", 10))
        result_path = Path(entry["result"]["result_path"])
        raw_result = result_path.read_bytes()
        self.assertIn("case_profile", archive.result_metadata(result_path))
        legacy = copy.deepcopy(entry)
        legacy["result"] = archive.result_metadata(result_path, include_case_profile=False)
        self.assertNotIn("case_profile", legacy["result"])
        self.path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        raw_archive = self.path.read_bytes()
        verified = campaign_archive.CampaignArchive(self.path).verified().evidence.records
        self.assertEqual(verified, [legacy])
        self.assertEqual(self.path.read_bytes(), raw_archive)
        self.assertEqual(result_path.read_bytes(), raw_result)


if __name__ == "__main__":
    unittest.main()
