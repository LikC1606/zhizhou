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
evaluator = importlib.import_module("evaluate_predictions")


class ImplementationIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "archive.jsonl"
        self.truth = self.root / "truth.csv"
        self.truth.write_text("id,target\na,1\nb,4\nc,9\n", encoding="utf-8")
        self.entries: dict[str, dict] = {}

    def record(self, name: str, predictions: list[float], recipe: str | None = "fit_declared_stochastic_pipeline()",
               parent: str | None = None, route: str = "model", status: str = "runner_up", role: str | None = None,
               proposal: str | None = None, feedback: str | None = None, stage: str = "development",
               candidate_scope: str | None = None, split_id: str = "fixed", parents: list[str] | None = None) -> dict:
        folder = self.root / name
        folder.mkdir()
        source = folder / "predictions.csv"
        source.write_text("id,prediction\n" + "".join(f"{i},{v}\n" for i, v in zip("abc", predictions)), encoding="utf-8")
        pipeline = folder / "pipeline"
        if recipe is not None:
            pipeline.mkdir()
            (pipeline / "train.py").write_text(recipe + "\n", encoding="utf-8")
        output = folder / "evaluation"
        output.mkdir()
        args = evaluator.make_parser().parse_args(["--truth", str(self.truth), "--predictions", str(source),
                                                  "--metric", "rmse", "--stage", stage, "--split-id", split_id,
                                                  "--output-dir", str(output)])
        result = evaluator.evaluate(args, output)
        if candidate_scope is not None:
            result["candidate_scope"] = candidate_scope
        result_path = output / "result.json"
        result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        arguments = ["record", "--archive", str(self.path), "--candidate-id", name, "--source", str(source),
                     "--result", str(result_path), "--route", route, "--mechanism", name, "--status", status]
        if recipe is not None:
            arguments += ["--configuration", str(pipeline)]
        for parent_id in parents or ([parent] if parent else []):
            arguments += ["--parent", parent_id]
        if role:
            arguments += ["--role", role]
        if feedback:
            arguments += ["--feedback", feedback]
        if proposal:
            arguments += ["--proposal-id", proposal, "--prediction-status", "supported"]
        entry = archive.record_candidate(archive.parser().parse_args(arguments))
        self.entries[name] = entry
        return entry

    def brief(self, *args: str) -> dict:
        return archive.optimization_brief(archive.parser().parse_args(["brief", "--archive", str(self.path), *args]))

    def decide(self) -> dict:
        return archive.route_decision(archive.parser().parse_args(["decide", "--archive", str(self.path)]))

    def propose(self, name: str, parent: str, target: Path | None = None, parents: list[str] | None = None) -> dict:
        entry = self.entries[parent]
        if target is None:
            root = Path(entry["artifact_paths"].get("configuration", entry["artifact_paths"]["source"]))
            target = root / "train.py" if root.is_dir() else root
        value = {"proposal_id": name, "parent_ids": parents or [parent], "feedback_from": parents or [parent], "route": entry["route"],
                 "code_targets": [str(target)], "basis": "Code and matched development result support a replacement",
                 "change": "Replace the score-affecting implementation", "expected_observation": "Improved full objective",
                 "validation": "Unchanged development contract", "stop_condition": "Reserve or failed mechanism"}
        path = self.root / (name + "-proposal.json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return archive.propose_candidate(archive.parser().parse_args(["propose", "--archive", str(self.path), "--proposal", str(path)]))

    def algorithm(self, name: str, source_text: str, parent: str | None = None, proposal: str | None = None) -> dict:
        folder = self.root / name
        folder.mkdir()
        source = folder / "solve.py"
        source.write_text(source_text, encoding="utf-8")
        configuration = folder / "configuration.json"
        configuration.write_text('{"capacity":2}\n', encoding="utf-8")
        result = {"status": "success", "valid": True, "candidate_scope": "program_source",
                  "validity_scope": "program_and_fixture_checks", "candidate_hash": archive.hash_path(source),
                  "evaluator_hash": "e" * 64, "workload_hash": "w" * 64, "score_model_hash": "s" * 64,
                  "stage": "development", "score": {"kind": "official_metric", "metric": "sum", "direction": "maximize", "value": 2}}
        result_path = folder / "result.json"
        result_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        args = ["record", "--archive", str(self.path), "--candidate-id", name, "--source", str(source),
                "--configuration", str(configuration), "--result", str(result_path), "--route", "algorithm",
                "--mechanism", name, "--status", "runner_up"]
        if parent:
            args += ["--parent", parent]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", "supported", "--feedback", "Executed changed source"]
        entry = archive.record_candidate(archive.parser().parse_args(args))
        self.entries[name] = entry
        return entry

    def test_new_predictions_from_same_pipeline_do_not_create_route_progress(self) -> None:
        self.record("baseline", [1, 2, 3])
        self.record("lucky-repeat", [1, 4, 9], parent="baseline")
        decision = self.decide()
        self.assertEqual(decision["recent_valid_candidates"], 1)
        self.assertEqual(decision["progress_candidates"], [])

    def test_new_predictions_from_same_pipeline_cannot_replace_best_representative(self) -> None:
        baseline = self.record("baseline", [1, 2, 3])
        repeat = self.record("lucky-repeat", [1, 4, 9], parent="baseline")
        self.assertNotEqual(baseline["fingerprint"], repeat["fingerprint"])
        value = self.brief()
        self.assertEqual(value["best_development"], "baseline")
        self.assertEqual(value["routes"][0]["distinct_implementations"], 1)
        self.assertEqual(value["candidates"]["lucky-repeat"]["objective"]["value"], 0)
        self.assertIsNone(value["candidates"]["lucky-repeat"]["objective_gain_vs_best"])

    def test_algorithm_code_can_change_with_unchanged_configuration(self) -> None:
        self.algorithm("parent", "def solve(values, k): return values[:k]\n")
        self.propose("change-code", "parent", Path(self.entries["parent"]["artifact_paths"]["source"]))
        child = self.algorithm("child", "def solve(values, k): return sorted(values, reverse=True)[:k]\n",
                               parent="parent", proposal="change-code")
        self.assertNotEqual(child["fingerprint"], self.entries["parent"]["fingerprint"])
        self.assertEqual(archive.iteration_trace(archive.read_records(self.path))[0]["state"], "evaluated_valid")

    def test_prediction_artifact_does_not_supply_a_code_target(self) -> None:
        self.record("baseline", [1, 2, 3])
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.propose("edit-output", "baseline", Path(self.entries["baseline"]["artifact_paths"]["source"]))
        self.assertEqual(caught.exception.kind, "unbound_code_target")

    def test_missing_training_snapshot_cannot_support_an_implementation_proposal(self) -> None:
        self.record("outputs-only", [1, 2, 3], recipe=None)
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.propose("missing-code", "outputs-only")
        self.assertEqual(caught.exception.kind, "missing_implementation_snapshot")

    def test_repeat_identity_and_all_measurement_bytes_are_preserved(self) -> None:
        first = self.record("first", [1, 2, 3])
        second = self.record("second", [1, 4, 9])
        self.assertEqual(first["implementation"], second["implementation"])
        self.assertEqual(second["reused_implementation_from"], ["first"])
        self.assertEqual(first["reused_implementation_from"], [])
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        value = self.brief()
        self.assertEqual(value["candidates"]["first"]["reused_implementation_from"], [])
        self.assertEqual(value["candidates"]["second"]["reused_implementation_from"], ["first"])
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_changed_recipe_can_share_identical_predictions(self) -> None:
        first = self.record("first", [1, 2, 3])
        second = self.record("second", [1, 2, 3], recipe="fit_different_representation()")
        self.assertNotEqual(first["implementation"], second["implementation"])
        self.assertEqual(self.brief()["routes"][0]["distinct_implementations"], 2)

    def test_legacy_recipe_identity_is_derived_without_rewriting_history(self) -> None:
        self.record("first", [1, 2, 3])
        self.record("second", [1, 4, 9])
        records = archive.read_records(self.path)
        for entry in records:
            entry.pop("implementation", None)
            entry.pop("reused_implementation_from", None)
            entry["result"].pop("candidate_scope", None)
        self.path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in records))
        old_bytes = self.path.read_bytes()
        self.assertEqual(self.brief()["best_development"], "first")
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)
        self.assertEqual(self.path.read_bytes(), old_bytes)

    def test_legacy_prediction_only_links_keep_their_original_evidence_scope(self) -> None:
        self.record("first", [1, 2, 3])
        self.propose("change", "first")
        self.record("second", [1, 4, 9], recipe="fit_changed_representation()", parent="first", proposal="change", feedback="New result")
        records = archive.read_records(self.path)
        for entry in records:
            if entry["event"] == "candidate":
                entry["artifacts"].pop("configuration")
                entry["artifact_paths"].pop("configuration")
                entry["fingerprint"] = archive.sha256(archive.canonical(entry["artifacts"]))
                entry.pop("implementation")
                entry.pop("reused_implementation_from", None)
                entry["result"].pop("candidate_scope")
            elif entry["event"] == "proposal":
                path = self.entries["first"]["artifact_paths"]["source"]
                entry["code_targets"] = [{"path": path, "sha256": archive.hash_path(Path(path))}]
        self.path.write_bytes(b"".join(archive.canonical(entry) + b"\n" for entry in records))
        old_bytes = self.path.read_bytes()
        trace = archive.iteration_trace(archive.read_records(self.path))
        self.assertEqual(trace[0]["state"], "evaluated_valid")
        self.assertEqual(trace[0]["evidence"]["implementation"]["scope"], "prediction_artifact_only")
        self.assertEqual(self.path.read_bytes(), old_bytes)

    def test_prediction_only_scores_do_not_invent_an_implementation_count(self) -> None:
        self.record("first", [1, 2, 3], recipe=None)
        self.record("second", [1, 4, 9], recipe=None)
        value = self.brief()
        self.assertIsNone(value["routes"][0]["distinct_implementations"])
        self.assertEqual(value["routes"][0]["distinct_artifact_fingerprints"], 2)
        self.assertEqual(value["candidates"]["second"]["implementation"]["scope"], "prediction_artifact_only")
        self.assertEqual(value["candidates"]["second"]["objective"]["value"], 0)
        self.assertEqual(self.decide()["action"], "diagnose")

    def test_repeat_does_not_close_an_unresolved_implementation_opportunity(self) -> None:
        self.record("first", [1, 2, 3], status="promising", feedback="Residual pattern needs a different representation")
        self.record("second", [1, 4, 9], parent="first")
        self.assertEqual(self.brief()["routes"][0]["unresolved"], "first")
        self.assertIn("first", self.decide()["unresolved_candidates"])

    def test_renamed_route_repeat_does_not_become_an_alternative_best(self) -> None:
        self.record("first", [1, 2, 3])
        self.record("second", [1, 4, 9], route="renamed")
        value = self.brief()
        self.assertEqual(value["best_development"], "first")
        self.assertIsNone(value["routes"][0]["best"])
        self.assertEqual(self.decide()["recent_valid_candidates"], 0)

    def test_failed_observation_does_not_hide_first_valid_pipeline_measurement(self) -> None:
        self.record("failed", [1, 2, 3], status="rejected")
        entries = archive.read_records(self.path)
        entries[0]["valid"] = False
        self.path.write_bytes(archive.canonical(entries[0]) + b"\n")
        self.record("valid-repeat", [1, 4, 9])
        value = self.brief()
        self.assertEqual(value["best_development"], "valid-repeat")
        self.assertEqual(value["routes"][0]["distinct_implementations"], 1)
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)

    def test_confirmation_does_not_change_recipe_grouping_or_route_review(self) -> None:
        self.record("first", [1, 2, 3])
        before = self.brief(), self.decide()
        self.record("confirmation", [1, 4, 9], role="confirmation", route="confirmation-only")
        self.assertEqual((self.brief(), self.decide()), before)

    def test_same_recipe_on_a_new_comparison_has_its_own_first_measurement(self) -> None:
        self.record("other-split", [1, 2, 3], split_id="other")
        self.record("full", [1, 4, 9])
        value = self.brief()
        self.assertEqual(value["best_development"], "full")
        self.assertEqual(value["candidates"]["full"]["reused_implementation_from"], [])
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)

    def test_unknown_old_recipes_do_not_inflate_current_route_evidence(self) -> None:
        self.record("old-outputs", [1, 2, 3], recipe=None)
        self.record("known-recipe", [1, 2, 3])
        decision = self.decide()
        self.assertEqual(decision["recent_valid_candidates"], 1)
        self.assertEqual(decision["evidence_candidates"], ["known-recipe"])
        self.assertEqual(decision["progress_candidates"], [])

    def test_declared_generated_artifacts_share_execution_pipeline_identity(self) -> None:
        self.record("first", [1, 2, 3], candidate_scope="generated_artifact")
        second = self.record("second", [1, 4, 9], candidate_scope="generated_artifact")
        self.assertEqual(second["implementation"]["scope"], "execution_pipeline")
        self.assertEqual(second["reused_implementation_from"], ["first"])
        self.assertEqual(self.brief()["best_development"], "first")
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)

    def test_declared_generated_output_without_recipe_keeps_identity_gap_visible(self) -> None:
        self.record("output", [1, 2, 3], recipe=None, candidate_scope="generated_artifact")
        value = self.brief()
        self.assertEqual(value["candidates"]["output"]["implementation"]["scope"], "generated_artifact_only")
        self.assertIsNone(value["routes"][0]["distinct_implementations"])
        self.assertEqual(self.decide()["action"], "diagnose")

    def test_output_scope_label_change_does_not_create_a_new_recipe(self) -> None:
        self.record("first", [1, 2, 3])
        second = self.record("second", [1, 4, 9], candidate_scope="generated_artifact")
        self.assertEqual(second["reused_implementation_from"], ["first"])
        self.assertEqual(self.brief()["best_development"], "first")
        self.assertEqual(self.decide()["recent_valid_candidates"], 1)

    def test_multi_parent_proposal_cannot_reuse_one_parent_recipe_as_a_combination(self) -> None:
        self.record("first", [1, 2, 3])
        self.record("second", [1, 4, 8], recipe="fit_different_representation()")
        self.propose("combine", "first", parents=["first", "second"])
        # Same recipe as first, with fresh output bytes; this is no new combination.
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.record("child", [1, 3, 8], parents=["first", "second"], feedback="Claimed combination", proposal="combine")
        self.assertEqual(caught.exception.kind, "unchanged_pipeline")
        self.assertEqual(archive.iteration_trace(archive.read_records(self.path))[0]["state"], "pending")

    def test_unchanged_recipe_cannot_complete_a_code_change_proposal(self) -> None:
        self.record("first", [1, 2, 3])
        self.propose("change", "first")
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.record("second", [1, 4, 9], parent="first", proposal="change", feedback="Lucky new predictions")
        self.assertEqual(caught.exception.kind, "unchanged_pipeline")
        self.assertEqual(archive.iteration_trace(archive.read_records(self.path))[0]["state"], "pending")

    def test_dropping_recipe_cannot_complete_a_code_change_proposal(self) -> None:
        self.record("first", [1, 2, 3])
        self.propose("change", "first")
        with self.assertRaises(archive.ArchiveFailure) as caught:
            self.record("second", [1, 4, 9], recipe=None, parent="first", proposal="change", feedback="Missing recipe")
        self.assertEqual(caught.exception.kind, "unchanged_pipeline")

    def test_tampered_implementation_identity_is_rejected(self) -> None:
        self.record("first", [1, 2, 3])
        records = archive.read_records(self.path)
        records[0]["implementation"]["fingerprint"] = "0" * 64
        self.path.write_bytes(archive.canonical(records[0]) + b"\n")
        with self.assertRaises(archive.ArchiveFailure) as caught:
            archive.read_records(self.path)
        self.assertEqual(caught.exception.kind, "invalid_archive")


if __name__ == "__main__":
    unittest.main()
