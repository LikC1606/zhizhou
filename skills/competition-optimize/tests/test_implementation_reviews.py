from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from handoff_fixtures import bounded_packet
archive = importlib.import_module("candidate_archive")
trials = importlib.import_module("campaign_trials")
search = importlib.import_module("campaign_search")


class ImplementationReviewTests(unittest.TestCase):
    """Keep agent fidelity reports bound to the code that actually executed."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "archive.jsonl"
        self.entries: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.counter = 0
        self.parent = self.record("parent", 100)

    def arguments(self, name: str, score: int = 90, *, proposal: str | None = None,
                  review: dict | None = None, role: str = "development", valid: bool = True,
                  executed: bool = True, scope: str = "program_source", recipe: bool = False,
                  comparison: dict | None = None, prediction: str = "contradicted"):
        self.counter += 1
        folder = self.root / f"run-{self.counter}"
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"# Implementation {name}\nprint({score})\n", encoding="utf-8")
        measured = subprocess.run(["/usr/bin/python3", str(source)], capture_output=True,
                                  text=True, check=True)
        receipt = {"status": "success" if valid else "failed", "valid": valid,
                   "candidate_hash": archive.hash_path(source), "candidate_scope": scope,
                   "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
                   "score_model_hash": "m" * 64, "stage": "development",
                   "score": {"kind": "official_metric", "metric": "profit",
                             "direction": "maximize", "value": int(measured.stdout)}}
        receipt.update(comparison or {})
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--source", str(source), "--route", "main", "--mechanism", name,
                "--status", "rejected" if not valid else "unresolved" if role == "diagnostic" else "runner_up",
                "--role", role, "--feedback", "Actual code and measured outcome inspected"]
        evidence_path = source
        if recipe:
            configuration = folder / "recipe"
            configuration.mkdir()
            evidence_path = configuration / "train.py"
            evidence_path.write_text(f"# Executed recipe for {name}\nprint({score})\n", encoding="utf-8")
            args += ["--configuration", str(configuration)]
        if executed:
            args += ["--result", str(result)]
        else:
            args += ["--valid", "--objective-value", str(score), "--objective-direction", "maximize",
                     "--objective-kind", "official_metric", "--objective-name", "profit",
                     "--evaluator-hash", "e" * 64, "--workload-hash", "w" * 64,
                     "--score-model-hash", "m" * 64, "--stage", "development"]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", prediction]
            for parent_id in self.proposals[proposal]["parent_ids"]:
                args += ["--parent", parent_id]
        review_path = folder / "review.json"
        if review is not None:
            value = copy.deepcopy(review)
            for evidence in value.get("code_evidence", []):
                if evidence.get("path") == "$actual":
                    evidence["path"] = str(evidence_path)
                elif evidence.get("path") == "$output":
                    evidence["path"] = str(source)
            review_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            args += ["--implementation-review", str(review_path)]
        return archive.parser().parse_args(args), review_path

    def record(self, name: str, score: int = 90, **kwargs) -> dict:
        args, _ = self.arguments(name, score, **kwargs)
        entry = archive.record_candidate(args)
        self.entries[name] = entry
        return entry

    def propose(self, name: str, parent: str = "parent") -> dict:
        roots = self.entries[parent]["artifact_paths"]
        target = Path(roots.get("configuration", roots["source"]))
        if target.is_dir():
            target = target / "train.py"
        proposal = {"proposal_id": name, "parent_ids": [parent], "feedback_from": [parent],
                    "route": "main", "code_targets": [str(target)],
                    "basis": "Measured residual suggests a coupled construction",
                    "change": "Implement the construction and its representation together",
                    "expected_observation": "The target score improves", "validation": "Fixed development adapter",
                    "stop_condition": "Record and inspect the actual executed outcome"}
        path = self.root / f"proposal-{len(self.proposals)}.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        event = archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.proposals[name] = event
        return event

    @staticmethod
    def review(fidelity: str = "yes", detail: str = "The construction is present at solve entry") -> dict:
        return {"fidelity": fidelity, "actual_mechanism": "Capacity-aware construction",
                "missing_components": [] if fidelity == "yes" else ["Joint representation update"],
                "code_evidence": [{"path": "$actual", "detail": detail}]}

    def brief(self, anchor: str | None = None) -> dict:
        args = ["brief", "--archive", str(self.path)]
        if anchor:
            args += ["--anchor", anchor]
        return archive.optimization_brief(archive.parser().parse_args(args))

    def history(self, comparison: dict | None = None) -> dict:
        return trials.trial_history(self.path, archive.read_records(self.path),
                                    comparison or self.parent["comparison"], set())

    def test_review_is_bound_to_successor_and_survives_raw_input_removal(self) -> None:
        self.propose("coupled")
        args, raw = self.arguments("child", proposal="coupled", review=self.review("partial"))
        input_hash = archive.sha256(raw.read_bytes())
        child = archive.record_candidate(args)
        self.entries["child"] = child
        review = child["implementation_review"]
        self.assertEqual(review["assessment_kind"], "agent_report")
        self.assertEqual(review["proposal_id"], "coupled")
        self.assertEqual(review["implementation_fingerprint"], child["implementation"]["fingerprint"])
        self.assertEqual(review["input_sha256"], input_hash)
        evidence = review["code_evidence"][0]
        self.assertEqual(evidence["path"], child["artifact_paths"]["source"])
        self.assertEqual(evidence["sha256"], archive.hash_path(Path(evidence["path"])))
        raw.unlink()
        self.assertEqual(self.brief()["candidates"]["child"]["implementation_review"], review)
        trace = archive.trace_report(archive.parser().parse_args(
            ["trace", "--archive", str(self.path), "--proposal-id", "coupled"]))
        self.assertEqual(trace["iterations"][0]["evidence"]["implementation_review"], review)
        self.assertEqual(self.history()["selection"][0]["evidence"]["child"]["implementation_review"], review)
        packet = search.handoff_packet(self.path, archive.read_records(self.path),
                                       {"sha256": "a" * 64, "size": 1}, "t" * 64)
        self.assertEqual(packet["development_brief"]["candidates"]["child"]["implementation_review"], review)
        self.assertEqual(trials.delivered_trials(packet), ["coupled"])
        source = Path(child["artifact_paths"]["source"])
        source.write_text(source.read_text() + "# Changed after execution\n", encoding="utf-8")
        with self.assertRaises(archive.ArchiveFailure):
            self.history()

    def test_malformed_or_unbound_reports_fail_without_appending(self) -> None:
        self.propose("review-me")
        mutations = [lambda v: v.update(fidelity="maybe"),
                     lambda v: v.update(fidelity=[]),
                     lambda v: v.update(fidelity={}),
                     lambda v: v.update(actual_mechanism=""),
                     lambda v: v.update(missing_components=["Missing joint update"]),
                     lambda v: v.update(code_evidence=[]),
                     lambda v: v["code_evidence"][0].update(detail=""),
                     lambda v: v["code_evidence"][0].update(path=self.parent["artifact_paths"]["source"])]
        before = self.path.read_bytes()
        for index, mutate in enumerate(mutations):
            value = self.review()
            mutate(value)
            args, _ = self.arguments(f"bad-{index}", proposal="review-me", review=value)
            with self.subTest(index=index), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
            self.assertEqual(self.path.read_bytes(), before)
        for fidelity in ("partial", "no"):
            value = self.review(fidelity)
            value["missing_components"] = []
            args, _ = self.arguments("empty-" + fidelity, proposal="review-me", review=value)
            with self.subTest(fidelity=fidelity), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
        args, _ = self.arguments("unlinked", review=self.review())
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(args)

    def test_execution_role_and_recipe_define_the_eligible_code_roots(self) -> None:
        self.propose("role-check")
        for name, options in (("manual", {"executed": False}),
                              ("confirmation", {"role": "confirmation"}),
                              ("output-only", {"scope": "prediction_csv"})):
            args, _ = self.arguments(name, proposal="role-check", review=self.review(), **options)
            with self.subTest(name=name), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
        self.propose("diagnostic-check")
        diagnostic = self.record("failed-probe", proposal="diagnostic-check", review=self.review("no"),
                                 role="diagnostic", valid=False)
        self.assertFalse(diagnostic["valid"])
        self.assertEqual(diagnostic["implementation_review"]["fidelity"], "no")
        self.propose("recipe-check")
        bad = self.review()
        bad["code_evidence"][0]["path"] = "$output"
        args, _ = self.arguments("output-as-code", proposal="recipe-check", review=bad,
                                 scope="prediction_csv", recipe=True)
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(args)
        child = self.record("recipe-child", proposal="recipe-check", review=self.review(),
                            scope="prediction_csv", recipe=True)
        self.assertEqual(child["implementation"]["scope"], "training_pipeline")
        evidence = child["implementation_review"]["code_evidence"][0]
        self.assertTrue(Path(evidence["path"]).is_relative_to(child["artifact_paths"]["configuration"]))

    def test_fidelity_does_not_replace_prediction_or_measured_score(self) -> None:
        self.propose("deviated")
        no = self.record("improved-deviation", 110, proposal="deviated", review=self.review("no"), prediction="supported")
        self.propose("faithful", parent="improved-deviation")
        yes = self.record("faithful-regression", 80, proposal="faithful", review=self.review(), prediction="contradicted")
        brief = self.brief()
        self.assertEqual(brief["best_development"], no["candidate_id"])
        self.assertEqual(brief["candidates"][no["candidate_id"]]["prediction_status"], "supported")
        self.assertEqual(brief["candidates"][yes["candidate_id"]]["prediction_status"], "contradicted")
        self.assertEqual(brief["candidates"][yes["candidate_id"]]["objective_gain_vs_best"], -30)
        self.assertEqual(no["implementation_review"]["fidelity"], "no")
        self.assertEqual(search.objective_progress(archive.read_records(self.path))["best_candidate"], no["candidate_id"])

    def test_foreign_outcome_does_not_deliver_review_judgment(self) -> None:
        self.propose("foreign-outcome")
        foreign = self.record("foreign", 999, proposal="foreign-outcome", review=self.review("partial"),
                              comparison={"workload_hash": "different"})
        row = self.history()["selection"][0]
        self.assertFalse(row["outcome_comparison_matches"])
        self.assertNotIn("implementation_review", row["evidence"]["foreign"])
        self.assertIsNone(row["prediction_status"])
        self.assertEqual(row["objective_gain_vs_parents"], {"parent": None})
        self.assertNotIn("foreign", self.brief("parent")["candidates"])
        trace = archive.iteration_trace(archive.read_records(self.path), proposal_id="foreign-outcome")
        self.assertEqual(trace[0]["evidence"]["implementation_review"], foreign["implementation_review"])

    def test_legacy_bytes_and_bounded_review_identity_remain_explicit(self) -> None:
        legacy = self.path.read_bytes()
        self.assertNotIn("implementation_review", self.brief()["candidates"]["parent"])
        self.assertEqual(self.path.read_bytes(), legacy)
        self.propose("bounded")
        self.record("bounded-child", proposal="bounded", review=self.review())
        packet = {"archive_path": str(self.path), "trial_history": self.history()}
        bounded = bounded_packet(packet)
        self.assertEqual(trials.delivered_trials(bounded), ["bounded"])
        for field, value in (("fidelity", "no"), ("implementation_fingerprint", "0" * 64)):
            changed = copy.deepcopy(bounded)
            changed["trial_history"]["selection"][0]["evidence"]["bounded-child"]["implementation_review"][field] = value
            with self.subTest(field=field):
                self.assertEqual(trials.delivered_trials(changed), [])
        self.assertTrue(self.path.read_bytes().startswith(legacy))
        self.propose("long-review")
        self.record("long-child", proposal="long-review", review=self.review(detail="Observed source mechanism " * 4000))
        packet = {"archive_path": str(self.path), "trial_history": self.history()}
        bounded = bounded_packet(packet)
        self.assertEqual(trials.delivered_trials(bounded), ["bounded"])


if __name__ == "__main__":
    unittest.main()
