from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import candidate_archive as archive
import campaign_search as search
import measurement_plans


class MeasurementPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "archive.jsonl"
        self.sources = {name: self.root / f"{name}.py" for name in ("leader", "challenger", "other")}
        for name, source in self.sources.items():
            source.write_text("import os\n"
                              "if os.environ.get('FAIL') == '1': raise RuntimeError('planned execution failed')\n"
                              "print(os.environ['SCORE'])\n# " + name + "\n")
        self.record("leader-first", "leader", 100)
        self.record("challenger-first", "challenger", 60)
        self.record("leader-repeat", "leader", 10)
        records = archive.read_records(self.path)
        evidence = archive.ComparisonEvidence(
            records, eligible=lambda entry: archive._observed_snapshot(
                entry, archive.implementation_identity(entry)))
        self.conflict = evidence.for_candidate("leader-first").ranking_conflict()
        self.assertIsNotNone(self.conflict)
        self.comparison = archive.candidate_index(records)["leader-first"]["comparison"]

    def record(self, name: str, source_name: str, score: int, *, plan_id: str | None = None,
               run_id: str = "pair-a", seeds: list[int] | None = None, repetitions: int = 1,
               valid: bool = True, config_hash: str | None = None, failed: bool = False) -> dict:
        source = self.sources[source_name]
        run = subprocess.run(["/usr/bin/python3", str(source)], capture_output=True, text=True,
                             env={"SCORE": str(score), "FAIL": "1" if failed else "0"})
        self.assertEqual(run.returncode != 0, failed, run.stderr)
        outcome = {"status": "failed" if failed else "success", "valid": valid and not failed,
                   "candidate_hash": archive.hash_path(source),
                   "candidate_scope": "program_source", "evaluator_hash": "evaluator-1",
                   "workload_hash": "workload-1", "score_model_hash": "score-1", "stage": "development",
                   "score": {"kind": "proxy", "metric": "quality", "direction": "maximize"}}
        if failed:
            outcome["error"] = {"type": "runtime_failure", "phase": "candidate_execution",
                                "message": run.stderr}
        else:
            outcome["score"]["value"] = int(run.stdout)
        if plan_id is not None:
            outcome["evaluation"] = {"measurement_plan_id": plan_id, "measurement_run_id": run_id,
                                     "seeds": [11] if seeds is None else seeds,
                                     "repetitions": repetitions}
        if config_hash is not None:
            outcome.setdefault("evaluation", {})["config_hash"] = config_hash
        result_path = self.root / f"{name}.json"
        result_path.write_text(json.dumps(outcome) + "\n")
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--source", str(source), "--result", str(result_path), "--route", "repeat",
                "--mechanism", "paired execution", "--status", "promising"]
        if source_name in ("leader", "challenger") and name not in ("leader-first", "challenger-first"):
            args += ["--reuse-reason", "Independent planned measurement" if plan_id else "Independent conflict witness"]
        return archive.record_candidate(archive.parser().parse_args(args))

    def plan(self, *, plan_id: str = "frozen-1", signature: str | None = None,
             prefix: str = "") -> dict:
        records = archive.read_records(self.path)
        leader = archive.candidate_index(records)[prefix + "leader-first"]
        conflict = archive.ComparisonEvidence(records, eligible=search.observed_implementation).for_candidate(
            leader["candidate_id"]).ranking_conflict()
        authored = {"plan_id": plan_id, "conflict_signature": signature or conflict["signature"],
                    "comparison": leader["comparison"], "leader_candidate": leader["candidate_id"],
                    "challenger_candidate": prefix + "challenger-first", "witness_candidate": prefix + "leader-repeat",
                    "runs": [{"run_id": "pair-a", "seeds": [11], "repetitions": 1},
                             {"run_id": "pair-b", "seeds": [12], "repetitions": 1}],
                    "decision_rule": "Compare both prespecified paired runs; retain raw scores and review feasibility."}
        path = self.root / f"{plan_id}.json"
        path.write_text(json.dumps(authored) + "\n")
        return archive.record_measurement_plan(archive.parser().parse_args(
            ["measure-plan", "--archive", str(self.path), "--plan", str(path)]))

    def status(self, plan_id: str = "frozen-1") -> dict:
        records = archive.read_records(self.path)
        plan = next(entry for entry in records if entry["event"] == "measurement_plan"
                    and entry["plan_id"] == plan_id)
        return measurement_plans.status(plan, records)

    def stop(self, *, plan_id: str = "frozen-1",
             reason: str = "The frozen recipe repeatedly fails; the planned comparison remains unresolved.",
             next_action: str = "Execute a viable repaired implementation as ordinary development.") -> dict:
        return archive.record_measurement_stop(archive.parser().parse_args(
            ["measure-stop", "--archive", str(self.path), "--plan-id", plan_id,
             "--reason", reason, "--next-action", next_action]))

    def handoff(self) -> dict:
        records = archive.read_records(self.path)
        return search.handoff_packet(
            self.path, records, {"size": self.path.stat().st_size,
                                 "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)

    def decide(self, *, conclusion: str = "Pairwise scores favor the challenger",
               plan_id: str = "frozen-1") -> dict:
        path = self.root / "decision.json"
        path.write_text(json.dumps({"plan_id": plan_id, "conclusion": conclusion,
                                    "reason": "Both predeclared paired runs favored the challenger under the fixed metric.",
                                    "next_action": "Review the task-specific promotion threshold and confirmation policy."}))
        return archive.record_measurement_decision(archive.parser().parse_args(
            ["measure-decide", "--archive", str(self.path), "--decision", str(path)]))

    def finish_plan(self, *, prefix: str = "", plan_id: str = "frozen-1",
                    config_hash: str | None = None) -> dict:
        self.plan(prefix=prefix, plan_id=plan_id)
        for run_id, seed in (("pair-a", 11), ("pair-b", 12)):
            for name, score in (("leader", 55), ("challenger", 65)):
                self.record(prefix + name + "-" + run_id, name, score, plan_id=plan_id,
                            run_id=run_id, seeds=[seed], config_hash=config_hash)
        return self.decide(plan_id=plan_id, conclusion="Paired conclusion for " + plan_id)

    def rejects(self, operation, kind: str) -> None:
        prior = self.path.read_bytes()
        with self.assertRaises(archive.ArchiveFailure) as error:
            operation()
        self.assertEqual(error.exception.kind, kind)
        self.assertEqual(self.path.read_bytes(), prior)

    def test_plan_validation_and_status_use_archived_values_without_files(self) -> None:
        before = archive.read_records(self.path)
        plan = self.plan()
        records = archive.read_records(self.path)
        expected = self.status()
        for path in self.sources.values():
            path.unlink()
        for entry in records:
            if entry["event"] == "candidate":
                Path(entry["result"]["result_path"]).unlink()

        script = """
import json
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
import measurement_plans
records = [json.loads(line) for line in pathlib.Path(sys.argv[2]).read_text().splitlines()]
plan = next(entry for entry in records if entry["event"] == "measurement_plan")
measurement_plans.validate_plan(plan, records[:records.index(plan)])
view = measurement_plans.status(plan, records)
assert measurement_plans.first_pending(records) == view
print(json.dumps({"status": view,
                  "pairs_sha256": measurement_plans.evidence_sha256(view),
                  "stop_sha256": measurement_plans.stop_evidence_sha256(view),
                  "loaded_archive": "candidate_archive" in sys.modules}))
"""
        result = subprocess.run(["/usr/bin/python3", "-c", script, str(SCRIPTS), str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "status": expected, "pairs_sha256": measurement_plans.evidence_sha256(expected),
            "stop_sha256": measurement_plans.stop_evidence_sha256(expected), "loaded_archive": False})
        measurement_plans.validate_plan(plan, before)
        with self.assertRaises(OSError):
            measurement_plans.verify_stop_evidence(expected, records)

    def test_plan_precedes_matching_pairs_and_only_complete_pairs_close_it(self) -> None:
        self.rejects(lambda: self.record("premature", "leader", 52, plan_id="frozen-1"),
                     "unplanned_measurement")
        plan = self.plan()
        self.assertEqual(archive.read_records(self.path)[-1], plan)
        self.assertFalse(self.status()["complete"])
        self.rejects(self.decide, "incomplete_measurement_plan")
        self.record("leader-pair-a-invalid", "leader", 55, plan_id="frozen-1", valid=False)
        self.assertIsNone(self.status()["runs"][0]["leader"])
        self.record("leader-pair-a", "leader", 56, plan_id="frozen-1")
        self.assertEqual(self.status()["runs"][0]["leader"]["value"], 56)
        self.rejects(lambda: self.record("leader-pair-a-again", "leader", 58, plan_id="frozen-1"),
                     "duplicate_measurement_slot")
        self.record("challenger-pair-a", "challenger", 61, plan_id="frozen-1")
        self.record("leader-pair-b", "leader", 57, plan_id="frozen-1", run_id="pair-b", seeds=[12])
        self.assertFalse(self.status()["complete"])
        self.record("challenger-pair-b", "challenger", 62, plan_id="frozen-1", run_id="pair-b", seeds=[12])
        self.assertTrue(self.status()["complete"])
        self.assertEqual(measurement_plans.first_pending(archive.read_records(self.path))["plan_id"],
                         "frozen-1")
        self.assertEqual(self.status()["runs"][1]["challenger"]["value"], 62)
        decision = self.decide()
        self.assertEqual(self.status()["decision"]["evidence_sha256"], decision["evidence_sha256"])
        self.assertIsNone(measurement_plans.first_pending(archive.read_records(self.path)))
        self.rejects(self.decide, "duplicate_measurement_decision")
        self.rejects(lambda: self.record("late-invalid", "leader", 56, plan_id="frozen-1", valid=False),
                     "closed_measurement_plan")
        self.assertEqual(self.path.read_bytes().count(b'"event": "measurement_plan"'), 1)

    def test_partial_failed_plan_stops_without_inventing_completion_gain_or_execution_health(self) -> None:
        self.plan()
        invalid = self.record("leader-invalid", "leader", 55, plan_id="frozen-1", valid=False)
        measured = self.record("challenger-measured", "challenger", 65, plan_id="frozen-1")
        failed = self.record("leader-failed", "leader", 55, plan_id="frozen-1", failed=True)
        before = archive.read_records(self.path)
        progress = search.objective_progress(before)
        health = search.execution_health(before)
        self.assertTrue(health["needs_attention"])
        prefix = self.path.read_bytes()

        stopped = self.stop()
        self.assertTrue(self.path.read_bytes().startswith(prefix))
        self.assertEqual(stopped["event"], "measurement_stop")
        self.assertEqual(stopped["plan_id"], "frozen-1")
        self.assertRegex(stopped["evidence_sha256"], r"^[0-9a-f]{64}$")
        records = archive.read_records(self.path)
        self.assertEqual(records[-1], stopped)
        view = self.status()
        self.assertEqual(view["state"], "stopped_unresolved")
        self.assertEqual(view["stop"], stopped)
        self.assertFalse(view["complete"])
        self.assertIsNone(view["decision"])
        self.assertIsNone(view["runs"][0]["leader"])
        self.assertEqual(view["runs"][0]["challenger"]["candidate_id"], measured["candidate_id"])
        self.assertIsNone(measurement_plans.first_pending(records))
        self.assertEqual(search.objective_progress(records), progress)
        self.assertEqual(progress["best_candidate"], "leader-first")
        self.assertEqual(search.execution_health(records), health)

        attempts = {entry["candidate_id"]: entry for entry in view["attempts"]}
        self.assertEqual(list(attempts), [invalid["candidate_id"], measured["candidate_id"], failed["candidate_id"]])
        for entry, implementation, observed in ((invalid, "leader", False), (measured, "challenger", True),
                                                  (failed, "leader", False)):
            attempt = attempts[entry["candidate_id"]]
            self.assertEqual(attempt["run_id"], "pair-a")
            self.assertEqual(attempt["implementation"], implementation)
            self.assertEqual(attempt["implementation_fingerprint"],
                             archive.implementation_identity(entry)["fingerprint"])
            self.assertEqual(attempt["result_sha256"], entry["result"]["result_sha256"])
            self.assertEqual(attempt["execution_status"], entry["result"]["execution_status"])
            self.assertEqual(attempt["valid"], entry["valid"])
            self.assertEqual(attempt["observed"], observed)
        self.assertIsNone(attempts[failed["candidate_id"]]["value"])
        self.assertEqual(attempts[measured["candidate_id"]]["value"], 65)
        packet = self.handoff()
        self.assertIsNone(packet["measurement_plan"])
        self.assertIsNone(packet["measurement_decision"])
        carried = packet["measurement_stop"]
        self.assertEqual((carried["remaining_slots"], carried["attempts"], carried["failed_attempts"]), (3, 3, 2))
        self.assertEqual(carried["reason"], stopped["reason"])
        self.assertEqual(carried["next_action"], stopped["next_action"])

    def test_stopped_plan_rejects_unknown_or_repeated_close_late_results_and_replacement_plan(self) -> None:
        self.rejects(lambda: self.stop(plan_id="unknown"), "unknown_measurement_plan")
        self.plan()
        self.record("failed-before-stop", "leader", 55, plan_id="frozen-1", failed=True)
        self.stop()
        self.rejects(self.stop, "closed_measurement_plan")
        self.rejects(self.decide, "closed_measurement_plan")
        self.rejects(lambda: self.record("late-measurement", "leader", 56, plan_id="frozen-1"),
                     "closed_measurement_plan")
        self.rejects(lambda: self.record("late-failure", "leader", 56, plan_id="frozen-1", failed=True),
                     "closed_measurement_plan")
        self.rejects(lambda: self.plan(plan_id="replacement"), "duplicate_measurement_plan")
        self.assertEqual(self.path.read_bytes().count(b'"event": "measurement_stop"'), 1)

    def test_decided_plan_cannot_be_stopped(self) -> None:
        self.finish_plan()
        self.rejects(self.stop, "closed_measurement_plan")
        self.assertIsNone(self.handoff()["measurement_stop"])

    def test_stop_replay_binds_summary_frozen_protocol_and_failed_attempt_metadata(self) -> None:
        self.plan()
        failed = self.record("failed-before-stop", "leader", 55, plan_id="frozen-1", failed=True)
        self.record("measured-before-stop", "challenger", 65, plan_id="frozen-1")
        stopped = self.stop()
        original = self.path.read_bytes()
        for changed in ("summary", "frozen protocol", "failed attempt"):
            with self.subTest(changed=changed):
                rows = [json.loads(line) for line in original.decode().splitlines()]
                if changed == "summary":
                    rows[-1]["evidence_sha256"] = "0" * 64
                elif changed == "frozen protocol":
                    plan = next(entry for entry in rows if entry["event"] == "measurement_plan")
                    plan["decision_rule"] += " An altered interpretation is not the frozen protocol."
                else:
                    entry = next(entry for entry in rows if entry.get("candidate_id") == failed["candidate_id"])
                    entry["result"]["result_sha256"] = "0" * 64
                self.path.write_text("\n".join(json.dumps(entry) for entry in rows) + "\n")
                try:
                    with self.assertRaises(archive.ArchiveFailure) as error:
                        archive.read_records(self.path)
                    self.assertEqual(error.exception.kind, "measurement_evidence_changed")
                finally:
                    self.path.write_bytes(original)
        self.assertEqual(archive.read_records(self.path)[-1], stopped)

    def test_stop_and_handoff_recheck_each_attempt_result_and_source_bytes(self) -> None:
        self.plan()
        original_sources = dict(self.sources)
        for name in ("leader", "challenger"):
            self.sources[name] = self.root / f"stopped-{name}.py"
            self.sources[name].write_bytes(original_sources[name].read_bytes())
        try:
            attempts = [self.record("old-failed", "leader", 55, plan_id="frozen-1", failed=True),
                        self.record("old-measured", "challenger", 65, plan_id="frozen-1")]
        finally:
            self.sources = original_sources

        for entry in attempts:
            for path, kind in ((Path(entry["result"]["result_path"]), "result_changed"),
                               (Path(entry["artifact_paths"]["source"]), "parent_artifact_changed")):
                with self.subTest(stage="stop", candidate=entry["candidate_id"], path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original + b" ")
                    try:
                        self.rejects(self.stop, kind)
                    finally:
                        path.write_bytes(original)
        stopped = self.stop()
        # An old failed measurement remains a useful failure card on its own
        # contract. Switch contracts so only the historical stop retrieves it.
        self.record("other-contract-after-stop", "leader", 55, config_hash="later-evaluation")
        packet = self.handoff()
        for entry in attempts:
            self.assertNotIn(entry["candidate_id"], packet["development_brief"]["candidates"])
        self.assertFalse(packet["execution_health"]["needs_attention"])
        self.assertFalse(packet["measurement_stop"]["comparison_matches_active"])
        self.assertEqual(packet["measurement_stop"]["evidence_sha256"], stopped["evidence_sha256"])
        for entry in attempts:
            for path, kind in ((Path(entry["result"]["result_path"]), "result_changed"),
                               (Path(entry["artifact_paths"]["source"]), "parent_artifact_changed")):
                with self.subTest(stage="handoff", candidate=entry["candidate_id"], path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original + b" ")
                    try:
                        with self.assertRaises(archive.ArchiveFailure) as error:
                            self.handoff()
                        self.assertEqual(error.exception.kind, kind)
                    finally:
                        path.write_bytes(original)
        self.assertEqual(self.handoff()["measurement_stop"]["evidence_sha256"], stopped["evidence_sha256"])

    def test_active_comparison_stop_survives_newer_foreign_stop_and_falls_back_for_unseen_contract(self) -> None:
        self.plan()
        self.record("first-failed", "leader", 55, plan_id="frozen-1", failed=True)
        first = self.stop(reason="Original contract's frozen execution fails.")
        self.record("other-leader-first", "leader", 100, config_hash="other-evaluation")
        self.record("other-challenger-first", "challenger", 60, config_hash="other-evaluation")
        self.record("other-leader-repeat", "leader", 10, config_hash="other-evaluation")
        self.plan(prefix="other-", plan_id="frozen-2")
        self.record("other-failed", "leader", 55, plan_id="frozen-2", failed=True,
                    config_hash="other-evaluation")
        second = self.stop(plan_id="frozen-2", reason="Other contract's frozen execution also fails.")

        self.record("return-to-original-after-stop", "leader", 50)
        packet = self.handoff()
        carried = packet["measurement_stop"]
        self.assertEqual(carried["plan_id"], first["plan_id"])
        self.assertEqual(carried["evidence_sha256"], first["evidence_sha256"])
        self.assertEqual(carried["reason"], first["reason"])
        self.assertTrue(carried["comparison_matches_active"])
        self.assertEqual(carried["comparison_key"], packet["objective_progress"]["comparison_key"])
        self.assertEqual(packet["objective_progress"]["best_candidate"], "leader-first")

        self.record("return-to-other-after-stop", "leader", 50, config_hash="other-evaluation")
        carried = self.handoff()["measurement_stop"]
        self.assertEqual(carried["plan_id"], second["plan_id"])
        self.assertTrue(carried["comparison_matches_active"])

        self.record("third-contract-after-stop", "leader", 50, config_hash="unreviewed-evaluation")
        packet = self.handoff()
        carried = packet["measurement_stop"]
        self.assertEqual(carried["plan_id"], second["plan_id"])
        self.assertEqual(carried["evidence_sha256"], second["evidence_sha256"])
        self.assertFalse(carried["comparison_matches_active"])
        self.assertNotEqual(carried["comparison_key"], packet["objective_progress"]["comparison_key"])
        self.assertIsNone(packet["measurement_plan"])

    def test_decision_evidence_hash_detects_rewritten_paired_results(self) -> None:
        self.plan()
        for run_id, seed in (("pair-a", 11), ("pair-b", 12)):
            self.record("leader-" + run_id, "leader", 55, plan_id="frozen-1", run_id=run_id, seeds=[seed])
            self.record("challenger-" + run_id, "challenger", 65, plan_id="frozen-1", run_id=run_id, seeds=[seed])
        self.decide()
        lines = self.path.read_text().splitlines()
        decision = json.loads(lines[-1])
        decision["evidence_sha256"] = "0" * 64
        lines[-1] = json.dumps(decision)
        self.path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(archive.ArchiveFailure) as error:
            archive.read_records(self.path)
        self.assertEqual(error.exception.kind, "measurement_evidence_changed")

    def test_handoff_rechecks_paired_result_and_source_bytes(self) -> None:
        self.plan()
        original_leader = self.sources["leader"]
        self.sources["leader"] = self.root / "paired-leader.py"
        self.sources["leader"].write_bytes(original_leader.read_bytes())
        for run_id, seed in (("pair-a", 11), ("pair-b", 12)):
            self.record("leader-" + run_id, "leader", 55, plan_id="frozen-1",
                        run_id=run_id, seeds=[seed])
            self.record("challenger-" + run_id, "challenger", 65, plan_id="frozen-1",
                        run_id=run_id, seeds=[seed])
        self.decide()
        self.sources["leader"] = original_leader
        for i in range(6):
            self.record("later-" + str(i), "leader", 55)
        records = archive.read_records(self.path)
        decision = next(entry for entry in records if entry["event"] == "measurement_decision")
        pair = archive.candidate_index(records)["leader-pair-a"]
        packet = search.handoff_packet(self.path, records,
                                       {"size": self.path.stat().st_size,
                                        "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertNotIn(pair["candidate_id"], packet["development_brief"]["candidates"])
        result_path = Path(pair["result"]["result_path"])
        original = result_path.read_bytes()
        result_path.write_bytes(original + b" ")
        with self.assertRaises(archive.ArchiveFailure) as error:
            search.handoff_packet(self.path, records,
                                  {"size": self.path.stat().st_size,
                                   "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertEqual(error.exception.kind, "result_changed")
        result_path.write_bytes(original)
        source_path = Path(pair["artifact_paths"]["source"])
        source = source_path.read_bytes()
        source_path.write_bytes(source + b" ")
        with self.assertRaises(archive.ArchiveFailure) as error:
            search.handoff_packet(self.path, records,
                                  {"size": self.path.stat().st_size,
                                   "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertEqual(error.exception.kind, "parent_artifact_changed")
        source_path.write_bytes(source)
        carried = search.handoff_packet(self.path, records,
                                        {"size": self.path.stat().st_size,
                                         "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertEqual(carried["measurement_decision"]["evidence_sha256"], decision["evidence_sha256"])

    def test_wrong_contract_recipe_seed_run_or_replacement_plan_is_rejected(self) -> None:
        self.plan()
        cases = (
            ("wrong-seed", "leader", {"seeds": [99]}),
            ("boolean-seed", "leader", {"seeds": [True]}),
            ("wrong-run", "leader", {"run_id": "pair-c"}),
            ("wrong-repeat", "leader", {"repetitions": 2}),
            ("boolean-repeat", "leader", {"repetitions": True}),
            ("wrong-contract", "leader", {"config_hash": "other"}),
            ("wrong-recipe", "other", {}),
        )
        for name, source, kw in cases:
            with self.subTest(name=name):
                self.rejects(lambda name=name, source=source, kw=kw: self.record(
                    name, source, 50, plan_id="frozen-1", **kw), "unplanned_measurement")
        self.rejects(lambda: self.plan(plan_id="replacement"), "duplicate_measurement_plan")
        self.assertEqual(len(archive.read_records(self.path)), 4)

    def test_plan_identity_cannot_be_forged_and_replay_detects_protocol_edit(self) -> None:
        self.rejects(lambda: self.plan(signature="other-signature"), "invalid_measurement_plan")
        self.plan()
        self.record("leader-pair-a", "leader", 56, plan_id="frozen-1")
        lines = self.path.read_text().splitlines()
        plan = json.loads(lines[3])
        plan["runs"][0]["seeds"] = [1000]
        lines[3] = json.dumps(plan)
        self.path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(archive.ArchiveFailure) as error:
            archive.read_records(self.path)
        self.assertEqual(error.exception.kind, "unplanned_measurement")

    def test_pending_plan_remains_visible_after_another_contract_becomes_active(self) -> None:
        self.plan()
        self.record("other-comparison", "other", 90, config_hash="other-evaluation")
        records = archive.read_records(self.path)
        packet = search.handoff_packet(
            self.path, records, {"size": self.path.stat().st_size,
                                 "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertEqual(packet["objective_progress"]["anchor_candidate"], "other-comparison")
        self.assertEqual(packet["measurement_plan"]["plan_id"], "frozen-1")
        self.assertEqual(packet["measurement_plan"]["remaining_slots"], 4)
        self.assertNotEqual(packet["measurement_plan"]["comparison_key"],
                            packet["objective_progress"]["comparison_key"])

    def test_decision_handoff_preserves_scope_after_comparison_changes(self) -> None:
        self.plan()
        for run_id, seed in (("pair-a", 11), ("pair-b", 12)):
            self.record("leader-" + run_id, "leader", 55, plan_id="frozen-1",
                        run_id=run_id, seeds=[seed])
            self.record("challenger-" + run_id, "challenger", 65, plan_id="frozen-1",
                        run_id=run_id, seeds=[seed])
        decision = self.decide()

        def handoff() -> dict:
            records = archive.read_records(self.path)
            return search.handoff_packet(
                self.path, records, {"size": self.path.stat().st_size,
                                     "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)

        packet = handoff()
        carried = packet["measurement_decision"]
        self.assertIsNone(packet["measurement_plan"])
        self.assertTrue(carried["comparison_matches_active"])
        self.assertEqual(carried["comparison_key"], packet["objective_progress"]["comparison_key"])
        self.assertEqual(carried["evidence_sha256"], decision["evidence_sha256"])
        self.assertEqual(carried["conclusion"], decision["conclusion"])
        self.assertEqual(packet["objective_progress"]["best_candidate"], "leader-first")

        self.record("other-comparison", "other", 90, config_hash="other-evaluation")
        packet = handoff()
        carried = packet["measurement_decision"]
        self.assertFalse(carried["comparison_matches_active"])
        self.assertNotEqual(carried["comparison_key"], packet["objective_progress"]["comparison_key"])
        self.assertEqual(carried["evidence_sha256"], decision["evidence_sha256"])
        self.assertEqual(packet["objective_progress"]["best_candidate"], "other-comparison")

    def test_active_comparison_decision_survives_a_newer_foreign_decision(self) -> None:
        first = self.finish_plan()
        self.record("other-leader-first", "leader", 100, config_hash="other-evaluation")
        self.record("other-challenger-first", "challenger", 60, config_hash="other-evaluation")
        self.record("other-leader-repeat", "leader", 10, config_hash="other-evaluation")
        second = self.finish_plan(prefix="other-", plan_id="frozen-2", config_hash="other-evaluation")
        self.record("return-to-original-comparison", "leader", 50)
        records = archive.read_records(self.path)
        packet = search.handoff_packet(
            self.path, records, {"size": self.path.stat().st_size,
                                 "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        carried = packet["measurement_decision"]
        self.assertEqual(carried["plan_id"], first["plan_id"])
        self.assertEqual(carried["evidence_sha256"], first["evidence_sha256"])
        self.assertTrue(carried["comparison_matches_active"])
        self.assertEqual(packet["objective_progress"]["best_candidate"], "leader-first")

        self.record("return-to-other-comparison", "leader", 50, config_hash="other-evaluation")
        records = archive.read_records(self.path)
        packet = search.handoff_packet(
            self.path, records, {"size": self.path.stat().st_size,
                                 "sha256": archive.sha256(self.path.read_bytes())}, "t" * 64)
        self.assertEqual(packet["measurement_decision"]["plan_id"], second["plan_id"])
        self.assertTrue(packet["measurement_decision"]["comparison_matches_active"])


if __name__ == "__main__":
    unittest.main()
