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


class ScopedLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "archive.jsonl"
        self.entries: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.sequence = 0
        self.control = self.record("control", 100)

    def arguments(self, name: str, score: int = 90, *, proposal: str | None = None,
                  learning: dict | None = None, role: str = "development",
                  comparison: dict | None = None, failed: bool = False,
                  executed: bool = True, scope: str = "program_source",
                  scored: bool = True, snapshot: bool = True, reuse: str | None = None):
        self.sequence += 1
        folder = self.root / str(self.sequence)
        folder.mkdir()
        source = folder / "solution.py"
        source.write_text(f"# {name}\n" + ("raise RuntimeError('actual failure')\n" if failed else f"print({score})\n"), encoding="utf-8")
        if reuse:
            source.write_bytes(Path(self.entries[reuse]["artifact_paths"]["source"]).read_bytes())
        run = subprocess.run(["/usr/bin/python3", str(source)], capture_output=True, text=True)
        receipt = {"status": "failed" if failed else "success", "valid": not failed,
                   "candidate_hash": archive.hash_path(source), "candidate_scope": scope,
                   "evaluator_hash": "e" * 64, "workload_hash": "w" * 64,
                   "score_model_hash": "m" * 64, "stage": "development"}
        if scored:
            receipt["score"] = {"kind": "official_metric", "metric": "quality",
                                "direction": "maximize", "value": score if failed else int(run.stdout)}
        receipt.update(comparison or {})
        result = folder / "result.json"
        result.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        args = ["record", "--archive", str(self.path), "--candidate-id", name,
                "--route", "main", "--mechanism", name, "--role", role,
                "--status", "rejected" if failed else "unresolved" if role == "diagnostic" else "runner_up",
                "--feedback", "Measured the actual successor"]
        if snapshot:
            args += ["--source", str(source)]
        if executed:
            args += ["--result", str(result)]
        if not executed or not scored:
            args += ["--valid", "--objective-value", str(score), "--objective-direction", "maximize",
                     "--objective-kind", "official_metric", "--objective-name", "quality"]
            if not executed:
                args += ["--evaluator-hash", "e" * 64, "--workload-hash", "w" * 64,
                         "--score-model-hash", "m" * 64, "--stage", "development"]
        if proposal:
            args += ["--proposal-id", proposal, "--prediction-status", "supported"]
            for parent_id in self.proposals[proposal]["parent_ids"]:
                args += ["--parent", parent_id]
        if reuse:
            args += ["--reuse-reason", "A genuine repeated execution for evidence"]
        learning_path = folder / "learning.json"
        if learning is not None:
            learning_path.write_text(json.dumps(learning), encoding="utf-8")
            args += ["--learning", str(learning_path)]
        return archive.parser().parse_args(args), learning_path

    def record(self, name: str, score: int = 90, **kwargs) -> dict:
        args, _ = self.arguments(name, score, **kwargs)
        entry = archive.record_candidate(args)
        self.entries[name] = entry
        return entry

    def propose(self, name: str, *, parent: str = "control", learning_from: list | None = None) -> dict:
        value = {"proposal_id": name, "parent_ids": [parent], "feedback_from": [parent],
                 "route": "main", "code_targets": [self.entries[parent]["artifact_paths"]["source"]],
                 "basis": "Use measured evidence under matching conditions", "change": "Implement the next mechanism",
                 "expected_observation": "The target residual decreases", "validation": "Fixed development adapter",
                 "stop_condition": "Record the actual measured result"}
        if learning_from is not None:
            value["learning_from"] = learning_from
        self.sequence += 1
        path = self.root / f"proposal-{self.sequence}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        entry = archive.propose_candidate(archive.parser().parse_args(
            ["propose", "--archive", str(self.path), "--proposal", str(path)]))
        self.proposals[name] = entry
        return entry

    @staticmethod
    def lesson(key: str = "representation", *, evidence: list[str] | None = None,
               revises: str | None = None, text: str = "The joint representation reduced the measured residual") -> dict:
        value = {"key": key, "lesson": text, "conditions": "The fixed small integer workload",
                 "next_action": "Test the same mechanism under the stated condition",
                 "limitations": "One measured development observation does not establish causality",
                 "evidence_from": [] if evidence is None else evidence}
        if revises is not None:
            value["revises"] = revises
        return value

    def learned(self, name: str = "first", *, lesson: dict | None = None, **kwargs) -> dict:
        self.propose(name + "-proposal")
        return self.record(name, proposal=name + "-proposal", learning=lesson or self.lesson(), **kwargs)

    def brief(self, anchor: str = "control") -> dict:
        return archive.optimization_brief(archive.parser().parse_args(
            ["brief", "--archive", str(self.path), "--anchor", anchor]))

    def packet(self) -> dict:
        return search.handoff_packet(self.path, archive.read_records(self.path),
                                     {"sha256": "a" * 64, "size": 1}, "t" * 64)

    def test_measured_learning_revision_keeps_old_bytes_and_current_head(self) -> None:
        self.propose("first-proposal")
        args, raw = self.arguments("first", proposal="first-proposal", learning=self.lesson())
        raw_hash = archive.sha256(raw.read_bytes())
        first = archive.record_candidate(args)
        self.entries["first"] = first
        report = first["learning"]
        self.assertEqual(report["assessment_kind"], "agent_report")
        self.assertEqual(report["evidence_from"], ["first"])
        self.assertEqual(report["input_sha256"], raw_hash)
        raw.unlink()
        old = self.path.read_bytes()
        self.propose("revise-proposal", learning_from=["first"])
        revised = self.record("revision", 95, proposal="revise-proposal",
                              learning=self.lesson(evidence=["first"], revises="first", text="The mechanism has a narrower useful condition"))
        self.assertTrue(self.path.read_bytes().startswith(old))
        self.assertEqual(revised["learning_from"], ["first"])
        self.assertEqual(revised["learning"]["evidence_from"], ["first", "revision"])
        current = self.brief()["scoped_learning"]
        self.assertEqual(current["available"], 1)
        self.assertEqual([row["candidate_id"] for row in current["selection"]], ["revision"])
        self.assertEqual(current["selection"][0]["learning"]["revises"], "first")
        self.assertEqual(self.entries["first"]["learning"], report)
        self.learned("newer-key", lesson=self.lesson(key="newer-key"))
        self.learned("latest-key", lesson=self.lesson(key="latest-key"))
        selected = self.brief("revision")["scoped_learning"]
        self.assertEqual((selected["available"], selected["omitted"]), (3, 1))
        self.assertEqual([row["candidate_id"] for row in selected["selection"]], ["revision", "latest-key"])

    def test_stale_foreign_and_unmeasured_sources_are_rejected(self) -> None:
        self.learned()
        self.propose("revise")
        self.record("head", 95, proposal="revise", learning=self.lesson(evidence=["first"], revises="first"))
        self.learned("foreign", comparison={"workload_hash": "other-workload"})
        for references in (["first"], ["foreign"], ["control"], [], ["head", "head"]):
            before = self.path.read_bytes()
            with self.subTest(references=references), self.assertRaises(archive.ArchiveFailure):
                self.propose("invalid-reference-" + str(len(before)), learning_from=references)
            self.assertEqual(self.path.read_bytes(), before)
        sources = [("confirmation", {"role": "confirmation"}), ("failed", {"failed": True}),
                   ("manual", {"executed": False}), ("output", {"scope": "prediction_csv"}),
                   ("foreign-evidence", {"comparison": {"workload_hash": "foreign"}})]
        for name, options in sources:
            self.record(name, **options)
            self.propose(name + "-probe")
            before = self.path.read_bytes()
            args, _ = self.arguments(name + "-outcome", proposal=name + "-probe",
                                      learning=self.lesson(key=name, evidence=[name]))
            with self.subTest(source=name), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
            self.assertEqual(self.path.read_bytes(), before)

    def test_only_scored_executed_prospective_outcomes_can_report_learning(self) -> None:
        cases = [("failed", {"failed": True}), ("manual", {"executed": False}),
                 ("confirmation", {"role": "confirmation"}), ("output-only", {"scope": "prediction_csv"}),
                 ("unscored", {"scored": False}), ("no-snapshot", {"snapshot": False})]
        for name, options in cases:
            self.propose(name + "-proposal")
            before = self.path.read_bytes()
            args, _ = self.arguments(name, proposal=name + "-proposal", learning=self.lesson(key=name), **options)
            with self.subTest(outcome=name), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
            self.assertEqual(self.path.read_bytes(), before)
        args, _ = self.arguments("unlinked", learning=self.lesson())
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(args)
        diagnostic = self.learned("diagnostic", role="diagnostic")
        self.assertEqual(diagnostic["learning"]["candidate_id"], "diagnostic")
        self.assertEqual(self.brief()["best_development"], "control")

    def test_revision_must_name_and_retain_the_current_head(self) -> None:
        self.learned()
        self.propose("revision")
        invalid = [self.lesson(), self.lesson(revises="first"),
                   self.lesson(evidence=["first"], revises="control"),
                   self.lesson(key="new-key", evidence=["first"], revises="first"),
                   self.lesson(key="missing-source", evidence=["unknown"])]
        for index, report in enumerate(invalid):
            args, _ = self.arguments("bad-" + str(index), proposal="revision", learning=report)
            before = self.path.read_bytes()
            with self.subTest(index=index), self.assertRaises(archive.ArchiveFailure):
                archive.record_candidate(args)
            self.assertEqual(self.path.read_bytes(), before)
        self.record("head", 95, proposal="revision", learning=self.lesson(evidence=["first"], revises="first"))
        self.propose("stale-revision")
        args, _ = self.arguments("stale", proposal="stale-revision",
                                  learning=self.lesson(evidence=["first"], revises="first"))
        with self.assertRaises(archive.ArchiveFailure):
            archive.record_candidate(args)

    def test_changed_cited_bytes_fail_at_retrieval_and_application(self) -> None:
        self.learned(lesson=self.lesson(evidence=["control"]))
        source = Path(self.control["artifact_paths"]["source"])
        original = source.read_bytes()
        source.write_bytes(original + b"# changed evidence\n")
        with self.assertRaises(archive.ArchiveFailure):
            self.brief()
        with self.assertRaises(archive.ArchiveFailure):
            self.propose("changed-evidence", parent="first", learning_from=["first"])
        source.write_bytes(original)
        self.assertEqual(self.brief()["scoped_learning"]["available"], 1)
        result = Path(self.control["result"]["result_path"])
        result.write_bytes(result.read_bytes() + b" ")
        with self.assertRaises(archive.ArchiveFailure):
            self.propose("changed-result", parent="first", learning_from=["first"])

    def test_old_report_trace_and_card_verify_its_independently_cited_evidence(self) -> None:
        source = self.record("separate-evidence", 10)
        first = self.learned(lesson=self.lesson(evidence=["separate-evidence"]))
        self.propose("revision")
        self.record("head", 95, proposal="revision",
                    learning=self.lesson(evidence=["first"], revises="first"))
        self.record("later-one", 20)
        self.record("later-two", 30)
        brief = self.brief()
        self.assertNotIn("separate-evidence", brief["candidates"])
        self.assertEqual(brief["candidates"]["first"]["learning"], first["learning"])
        self.assertEqual([row["candidate_id"] for row in brief["scoped_learning"]["selection"]], ["head"])
        trace_args = archive.parser().parse_args(
            ["trace", "--archive", str(self.path), "--proposal-id", "first-proposal"])
        trace = archive.trace_report(trace_args)["iterations"][0]
        self.assertNotIn("separate-evidence", trace["parent_ids"] + trace["feedback_from"]
                         + trace.get("learning_from", []))
        self.assertEqual(trace["evidence"]["learning"], first["learning"])
        for target, kind in ((source["artifact_paths"]["source"], "parent_artifact_changed"),
                             (source["result"]["result_path"], "result_changed")):
            path = Path(target)
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            try:
                for consumer in (lambda: archive.trace_report(trace_args), self.brief):
                    with self.subTest(target=target, consumer=consumer):
                        with self.assertRaises(archive.ArchiveFailure) as caught:
                            consumer()
                        self.assertEqual(caught.exception.kind, kind)
            finally:
                path.write_bytes(original)

    def test_learning_application_and_bounded_trial_require_intact_reports(self) -> None:
        legacy = self.path.read_bytes()
        self.assertNotIn("learning", self.brief()["candidates"]["control"])
        self.assertEqual(self.brief()["scoped_learning"]["selection"], [])
        first = self.learned()
        self.propose("apply", learning_from=["first"])
        brief = self.brief()
        self.assertEqual(brief["pending_details"][0]["learning_from"], ["first"])
        self.assertEqual(brief["candidates"]["first"]["learning"], first["learning"])
        pending = self.packet()
        self.assertEqual(search.delivered_exposures(pending)["proposals"], ["apply"])
        self.record("application", 105, proposal="apply")
        trace = archive.iteration_trace(archive.read_records(self.path), proposal_id="apply")[0]
        self.assertEqual(trace["learning_from"], ["first"])
        self.assertEqual(trace["learning_evidence"], {"first": first["learning"]})
        self.assertEqual(trace["evidence"]["learning_from"], ["first"])
        packet = self.packet()
        rows = packet["trial_history"]["selection"]
        apply_index = next(i for i, row in enumerate(rows) if row["proposal_id"] == "apply")
        self.assertEqual(rows[apply_index]["evidence"]["first"]["learning"], first["learning"])
        self.assertIn("apply", trials.delivered_trials(packet))
        for mutation in (lambda row: row.pop("learning_from"),
                         lambda row: row["evidence"]["first"]["learning"].update(lesson="changed claim")):
            changed = copy.deepcopy(packet)
            mutation(changed["trial_history"]["selection"][apply_index])
            self.assertNotIn("apply", trials.delivered_trials(changed))
        bounded = bounded_packet(packet)
        self.assertIn("apply", trials.delivered_trials(bounded))
        self.assertTrue(self.path.read_bytes().startswith(legacy))
        self.propose("long-report")
        self.record("long", proposal="long-report", learning=self.lesson(key="long", text="Measured conditional explanation " * 4000))
        history = trials.trial_history(self.path, archive.read_records(self.path), self.control["comparison"], set(),
                                       seen={"first-proposal": 1, "apply": 1})
        packet = {"archive_path": str(self.path), "trial_history": history}
        self.assertIn("long-report", trials.delivered_trials(packet))
        self.assertNotIn("long-report", trials.delivered_trials(bounded_packet(packet)))

    def test_standalone_learning_reads_revision_and_delivery_without_archive_module(self) -> None:
        self.learned(lesson=self.lesson(evidence=["control"]))
        self.propose("revision", learning_from=["first"])
        head = self.record("head", 95, proposal="revision",
                           learning=self.lesson(evidence=["first"], revises="first"))
        program = r'''
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import scoped_learning as learning
from candidate_evidence import implementation_identity
from evidence_files import EvidenceReads

path = Path(sys.argv[2])
records = [json.loads(line) for line in path.read_text().splitlines()]
candidates = {}
for entry in records:
    if entry["event"] != "candidate":
        continue
    if "learning" in entry:
        learning.validate(entry["learning"], entry, candidates)
    candidates[entry["candidate_id"]] = entry
head = candidates["head"]
history = learning.retrieve(candidates, head["comparison"],
                            {implementation_identity(head)["fingerprint"]}, 2,
                            reads=EvidenceReads(), seen={}, archive_path=path)
packet = {"archive_path": str(path), "development_brief": {
    "comparison": head["comparison"], "scoped_learning": history}}
assert "candidate_archive" not in sys.modules
print(json.dumps({"history": history, "delivered": learning.delivered(packet)}))
'''
        run = subprocess.run(["/usr/bin/python3", "-c", program, str(SCRIPTS), str(self.path)],
                             check=True, capture_output=True, text=True)
        result = json.loads(run.stdout)
        self.assertEqual(result["delivered"], ["head"])
        rows = result["history"]["selection"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["learning"], head["learning"])
        self.assertEqual(set(rows[0]["evidence"]), {"first", "head"})


if __name__ == "__main__":
    unittest.main()
