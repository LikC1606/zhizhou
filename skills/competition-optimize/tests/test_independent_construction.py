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
search = importlib.import_module("campaign_search")
trials = importlib.import_module("campaign_trials")


class IndependentConstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "archive.jsonl"
        self.entries: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.sequence = 0
        self.control = self.record("control", 100, status="unresolved")

    def arguments(self, name: str, score: int = 90, *, proposal: str | None = None,
                  role: str = "development", status: str = "runner_up",
                  comparison: dict | None = None, executed: bool = True,
                  scope: str = "program_source", recipe: bool = False,
                  reuse: str | None = None, same_recipe: str | None = None,
                  prediction: str = "supported", review: bool = False):
        self.sequence += 1
        folder = self.root / str(self.sequence)
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"# Actual construction {name}\nprint({score})\n", encoding="utf-8")
        if reuse:
            source.write_bytes(Path(self.entries[reuse]["artifact_paths"]["source"]).read_bytes())
        run = subprocess.run(["/usr/bin/python3", str(source)], capture_output=True, text=True, check=True)
        receipt = {"status": "success", "valid": True, "candidate_hash": archive.hash_path(source),
                   "candidate_scope": scope, "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
                   "score_model_hash": "m" * 64, "stage": "development",
                   "score": {"kind": "official_metric", "metric": "profit",
                             "direction": "maximize", "value": int(run.stdout)}}
        receipt.update(comparison or {})
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--source", str(source), "--route", "main", "--mechanism", name,
                "--status", status, "--role", role, "--feedback", "Measured construction and actual mechanism"]
        if recipe:
            configuration = folder / "recipe"
            configuration.mkdir()
            target = configuration / "train.py"
            target.write_text(f"# Recipe {name}\nprint({score})\n", encoding="utf-8")
            if same_recipe:
                target.write_bytes((Path(self.entries[same_recipe]["artifact_paths"]["configuration"]) / "train.py").read_bytes())
            args += ["--configuration", str(configuration)]
        if executed:
            args += ["--result", str(result)]
        else:
            args += ["--valid", "--objective-value", str(score), "--objective-direction", "maximize",
                     "--objective-kind", "official_metric", "--objective-name", "profit",
                     "--evaluator-hash", "e" * 64, "--workload-hash", "w" * 64,
                     "--score-model-hash", "m" * 64, "--stage", "development"]
        if reuse:
            args += ["--reuse-reason", "A genuine repeated execution under the requested construction"]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", prediction]
            for parent_id in self.proposals[proposal]["parent_ids"]:
                args += ["--parent", parent_id]
        if review:
            report = {"fidelity": "yes", "actual_mechanism": "New independent representation",
                      "missing_components": [],
                      "code_evidence": [{"path": str(source), "detail": "The representation is in the executed entry"}]}
            report_path = folder / "implementation-review.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            args += ["--implementation-review", str(report_path)]
        return archive.parser().parse_args(args)

    def record(self, name: str, score: int = 90, **kwargs) -> dict:
        entry = archive.record_candidate(self.arguments(name, score, **kwargs))
        self.entries[name] = entry
        return entry

    def proposal_input(self, name: str, *, mode: object = "independent",
                       parents: list[str] | None = None, feedback: list[str] | None = None,
                       targets: list[str] | None = None) -> dict:
        parent_ids = ["control"] if parents is None else parents
        value = {"proposal_id": name, "parent_ids": parent_ids,
                 "feedback_from": parent_ids if feedback is None else feedback,
                 "route": "main", "code_targets": [] if targets is None else targets,
                 "basis": "Measured parent is the comparison control",
                 "change": "Construct a different representation from the task and evidence",
                 "expected_observation": "The independent construction improves the measured score",
                 "validation": "Fixed development adapter",
                 "stop_condition": "Record a real successor and inspect the observation"}
        if mode is not None:
            value["construction_mode"] = mode
        return value

    def propose_value(self, value: dict) -> dict:
        self.sequence += 1
        path = self.root / f"proposal-{self.sequence}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        entry = archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.proposals[entry["proposal_id"]] = entry
        return entry

    def propose(self, name: str, **kwargs) -> dict:
        return self.propose_value(self.proposal_input(name, **kwargs))

    def brief(self, anchor: str = "control") -> dict:
        return archive.optimization_brief(archive.parser().parse_args(
            ["brief", "--archive", str(self.path), "--anchor", anchor]))

    def packet(self) -> dict:
        return search.handoff_packet(self.path, archive.read_records(self.path),
                                     {"sha256": "a" * 64, "size": 1}, "t" * 64)

    def test_opt_in_and_legacy_target_contract_keep_old_bytes(self) -> None:
        legacy_bytes = self.path.read_bytes()
        target = self.control["artifact_paths"]["source"]
        legacy = self.propose("legacy", mode=None, targets=[target])
        explicit = self.propose("refinement", mode="refinement", targets=[target])
        independent = self.propose("independent")
        self.assertNotIn("construction_mode", legacy)
        self.assertEqual(explicit["construction_mode"], "refinement")
        self.assertEqual(independent["code_targets"], [])
        self.assertEqual(independent["parent_ids"], ["control"])
        self.assertTrue(self.path.read_bytes().startswith(legacy_bytes))
        before = self.path.read_bytes()
        invalid = [self.proposal_input("bad-mode", mode="fresh"),
                   self.proposal_input("list-mode", mode=[]),
                   self.proposal_input("dict-mode", mode={}),
                   self.proposal_input("targeted-independent", targets=[target]),
                   self.proposal_input("empty-refinement", mode="refinement"),
                   self.proposal_input("empty-legacy", mode=None),
                   self.proposal_input("no-control", parents=[]),
                   self.proposal_input("no-feedback", feedback=[])]
        for value in invalid:
            with self.subTest(proposal=value["proposal_id"]), self.assertRaises(archive.ArchiveFailure):
                self.propose_value(value)
            self.assertEqual(self.path.read_bytes(), before)
        old_child = self.record("legacy-child", 101, proposal="legacy")
        explicit_child = self.record("refinement-child", 102, proposal="refinement")
        self.assertNotIn("construction_mode", old_child)
        self.assertEqual(explicit_child["construction_mode"], "refinement")
        legacy_trace = archive.iteration_trace(archive.read_records(self.path), proposal_id="legacy")[0]
        self.assertNotIn("construction_mode", legacy_trace)
        self.assertEqual(legacy_trace["identity_checks"], {"code_targets": "checked"})
        self.assertNotIn("construction_mode", self.brief()["candidates"]["legacy-child"])
        self.assertTrue(self.path.read_bytes().startswith(legacy_bytes))

    def test_independent_execution_preserves_comparison_and_mode_in_all_views(self) -> None:
        proposal = self.propose("new-representation")
        pending = self.brief()["pending_details"][0]
        checks = {"code_targets": "not_applicable", "construction_mode": "independent"}
        self.assertEqual(pending["identity_checks"], checks)
        child = self.record("independent-child", 110, proposal="new-representation")
        self.assertEqual(child["construction_mode"], "independent")
        self.assertEqual(child["parent_ids"], proposal["parent_ids"])
        self.assertNotEqual(child["implementation"]["fingerprint"], self.control["implementation"]["fingerprint"])
        self.assertEqual(child["objective"]["value"], 110)
        self.assertEqual(self.brief()["best_development"], "independent-child")
        self.assertEqual(self.brief()["candidates"]["independent-child"]["construction_mode"], "independent")
        trace = archive.iteration_trace(archive.read_records(self.path), proposal_id="new-representation")[0]
        self.assertEqual(trace["construction_mode"], "independent")
        self.assertEqual(trace["identity_checks"], checks)
        self.assertEqual(trace["evidence"]["construction_mode"], "independent")
        packet = self.packet()
        trial = packet["trial_history"]["selection"][0]
        self.assertEqual(trial["construction_mode"], "independent")
        self.assertEqual(trial["identity_checks"], checks)
        self.assertEqual(trial["objective_gain_vs_parents"], {"control": 10})
        self.assertEqual(trials.delivered_trials(packet), ["new-representation"])

    def test_role_execution_unchanged_and_parent_integrity_guards_still_apply(self) -> None:
        self.propose("guarded")
        for name, options in (("manual", {"executed": False}),
                              ("confirmation", {"role": "confirmation"}),
                              ("output-only", {"scope": "prediction_csv"}),
                              ("unchanged", {"reuse": "control"})):
            with self.subTest(name=name), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(self.arguments(name, proposal="guarded", **options))
        no_snapshot = self.arguments("missing-source-snapshot", proposal="guarded")
        no_snapshot.source = None
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(no_snapshot)
        self.record("pipeline", scope="prediction_csv", recipe=True)
        self.propose("pipeline-independent", parents=["pipeline"])
        with self.assertRaises(archive.ArchiveFailure):
            self.record("same-recipe-output", 111, proposal="pipeline-independent",
                        scope="prediction_csv", recipe=True, same_recipe="pipeline")
        self.record("confirmation-parent", role="confirmation")
        self.record("output-parent", scope="prediction_csv")
        for parent in ("confirmation-parent", "output-parent"):
            with self.subTest(parent=parent), self.assertRaises(archive.ArchiveFailure):
                self.propose("bad-parent-" + parent, parents=[parent])
        source = Path(self.control["artifact_paths"]["source"])
        original = source.read_bytes()
        source.write_bytes(original + b"# Mutation after archived execution\n")
        with self.assertRaises(archive.ArchiveFailure):
            self.propose("changed-control")
        source.write_bytes(original)
        result = Path(self.control["result"]["result_path"])
        result.write_bytes(result.read_bytes() + b" ")
        with self.assertRaises(archive.ArchiveFailure):
            self.propose("changed-result")

    def test_independent_comparison_does_not_consume_refinement_opportunity(self) -> None:
        self.propose("independent")
        self.record("independent-result", 120, proposal="independent")
        frontier = self.brief()["review_frontier"]["selection"]
        self.assertEqual(len(frontier), 1)
        self.assertEqual(frontier[0]["candidate_id"], "control")
        self.assertEqual(frontier[0]["successor_implementations"], 0)
        self.assertEqual(frontier[0]["measured_successor_implementations"], 0)
        self.assertIsNone(frontier[0]["latest_successor"])
        self.propose("refine", mode="refinement", targets=[self.control["artifact_paths"]["source"]])
        self.record("refine-result", 105, proposal="refine", prediction="unresolved")
        frontier = self.brief()["review_frontier"]["selection"][0]
        self.assertEqual(frontier["successor_implementations"], 1)
        self.assertEqual(frontier["measured_successor_implementations"], 1)
        self.assertEqual(frontier["latest_successor"], "refine-result")
        self.assertEqual(self.brief()["best_development"], "independent-result")

    def test_cross_contract_references_remain_identity_only(self) -> None:
        self.record("new-control", 90, comparison={"workload_hash": "new-workload"})
        self.propose("new-context", parents=["new-control"], feedback=["control"])
        brief = self.brief("new-control")
        self.assertEqual([row["proposal_id"] for row in brief["pending_details"]], ["new-context"])
        reference = brief["pending_references"]["control"]
        self.assertTrue(reference["requires_revalidation"])
        self.assertNotIn("objective", reference)
        self.assertNotIn("feedback", reference)
        self.assertEqual(self.brief()["pending_details"], [])
        self.record("new-context-result", 99, proposal="new-context", comparison={"workload_hash": "new-workload"})
        row = self.packet()["trial_history"]["selection"][0]
        self.assertEqual(row["construction_mode"], "independent")
        self.assertEqual(row["objective_gain_vs_parents"], {"new-control": 9})
        self.assertNotIn("objective", row["evidence"]["control"])
        self.assertTrue(row["evidence"]["control"]["requires_revalidation"])
        self.assertEqual(self.brief()["pending_details"], [])

    def test_pending_and_completed_bounded_delivery_requires_intact_mode_and_checks(self) -> None:
        self.propose("sealed-independent")
        packet = self.packet()
        self.assertEqual(search.delivered_exposures(packet)["proposals"], ["sealed-independent"])
        changes = [lambda row: row.pop("construction_mode"),
                   lambda row: row.update(construction_mode="refinement"),
                   lambda row: row.update(identity_checks={"code_targets": "checked"})]
        for index, change in enumerate(changes):
            changed = copy.deepcopy(packet)
            change(changed["development_brief"]["pending_details"][0])
            with self.subTest(pending=index):
                self.assertEqual(search.delivered_exposures(changed)["proposals"], [])
        self.record("sealed-result", 110, proposal="sealed-independent", review=True)
        packet = self.packet()
        bounded = bounded_packet(packet)
        self.assertEqual(trials.delivered_trials(bounded), ["sealed-independent"])
        self.assertEqual(bounded["development_brief"]["candidates"]["sealed-result"]["construction_mode"], "independent")
        self.assertEqual(bounded["development_brief"]["candidates"]["sealed-result"]["implementation_review"]["fidelity"], "yes")
        self.assertLessEqual(len(archive.canonical(bounded)) + 1, search.HANDOFF_BYTES)
        for index, change in enumerate(changes):
            changed = copy.deepcopy(bounded)
            change(changed["trial_history"]["selection"][0])
            with self.subTest(completed=index):
                self.assertEqual(trials.delivered_trials(changed), [])
        before = self.path.read_bytes()
        records = archive.read_records(self.path)
        next(row for row in records if row.get("candidate_id") == "sealed-result")["construction_mode"] = "refinement"
        with self.assertRaises(archive.ArchiveFailure):
            archive.validate_successor(records[-1], self.proposals["sealed-independent"], records[:-1])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
