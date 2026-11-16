from __future__ import annotations

import copy
import importlib
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
replay = importlib.import_module("replay_inference_votes")


def samples(answers, *, seconds=None):
    return [{"id": str(i), "status": "completed" if answer is not None else "invalid",
             "answer": answer, "elapsed_seconds": seconds}
            for i, answer in enumerate(answers)]


def trace(cases):
    return {"schema_version": 1, "stage": "development",
            "generation": {key: char * 64 for key, char in
                           [("recipe_sha256", "a"), ("workload_sha256", "b"), ("answer_parser_sha256", "c")]},
            "cases": [{"id": name, "target": target, "samples": rows} for name, target, rows in cases]}


class InferenceVoteReplayTests(unittest.TestCase):
    def test_irreversible_stop_preserves_answer_and_sums_only_selected_sample_costs(self):
        data = trace([("q", "A", samples(["A", "A", "A", "B", "B"], seconds=2))])
        report = replay.analyze_cases(data, 5)
        self.assertEqual(report["full_budget"]["samples_used"], 5)
        self.assertEqual(report["early_stop"]["samples_used"], 3)
        self.assertEqual(report["early_stop"]["cached_sample_seconds"], 6)
        self.assertEqual(report["full_budget"]["cached_sample_seconds"], 10)
        self.assertEqual(report["skipped_sample_slots"], 2)
        self.assertEqual(report["early_stop"]["exact_match_accuracy"], 1)
        self.assertTrue(report["answers_unchanged"])

    def test_observed_majority_is_not_enough_to_stop(self):
        # A leads the first two votes but B wins the fixed budget.
        outcome = replay.replay_case(samples(["A", "A", "B", "B", "B"]))
        self.assertEqual(outcome["answer"], "B")
        self.assertEqual(outcome["samples_used"], 5)
        self.assertEqual(outcome["stop_reason"], "sample_limit")

    def test_plurality_can_be_irreversible_without_an_absolute_majority(self):
        outcome = replay.replay_case(samples(["A", "B", "C", "A", "D", "A", "E"]))
        self.assertEqual(outcome["answer"], "A")
        self.assertEqual(outcome["samples_used"], 6)

    def test_fixed_first_seen_tie_rule_and_exact_strings(self):
        outcome = replay.replay_case(samples(["Z", "A", "A", "Z"]))
        self.assertEqual(outcome["answer"], "Z")
        self.assertEqual(outcome["samples_used"], 4)
        data = trace([("001", "001", samples(["1", "1", "001"]))])
        report = replay.analyze_cases(data, 3)
        self.assertEqual(report["full_budget"]["correct_count"], 0)
        self.assertEqual(report["cases_with_correct_sample"], 1)

    def test_failures_consume_slots_and_all_failed_cases_stay_in_accuracy(self):
        failed = samples([None] * 5)
        failed[1]["status"] = "timeout"
        failed[2]["status"] = "failed"
        data = trace([("all-failed", "A", failed),
                      ("partial", "B", samples([None, "B", "B", None, None]))])
        report = replay.analyze_cases(data, 5)
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["full_budget"]["no_answer_count"], 1)
        self.assertEqual(report["full_budget"]["exact_match_accuracy"], .5)
        self.assertEqual(sum(report["full_budget"]["failure_counts"].values()), 8)
        # The fourth, failed slot makes B's lead irreversible; it is still consumed.
        self.assertEqual(report["cases"][1]["early_stop"]["samples_used"], 4)

    def test_targets_do_not_select_answers_and_budget_does_not_use_later_samples(self):
        data = trace([("q", "A", samples(["B", "B", "B", "A", "A"]))])
        before = replay.analyze_cases(data, 3)
        data["cases"][0]["target"] = "B"
        after = replay.analyze_cases(data, 3)
        self.assertEqual(before["cases"][0]["early_stop"]["answer"], "B")
        self.assertEqual(after["cases"][0]["early_stop"]["answer"], "B")
        self.assertEqual(before["cases_with_correct_sample"], 0)
        self.assertEqual(after["cases_with_correct_sample"], 1)

    def test_unknown_cost_stays_unknown(self):
        rows = samples(["A"] * 5, seconds=1)
        rows[-1].pop("elapsed_seconds")
        report = replay.analyze_cases(trace([("q", "A", rows)]), 5)
        self.assertIsNone(report["full_budget"]["cached_sample_seconds"])
        self.assertEqual(report["early_stop"]["cached_sample_seconds"], 3)

    def test_exhaustive_ordered_answer_pools_never_change_final_plurality(self):
        # Independent full-vote oracle covers ties, multiple labels and failed slots.
        for count in range(1, 7):
            for answers in itertools.product(("A", "B", "C", None), repeat=count):
                valid = [answer for answer in answers if answer is not None]
                expected = max(valid, key=valid.count) if valid else None
                outcome = replay.replay_case(samples(answers))
                self.assertEqual(outcome["answer"], expected, answers)

    def test_trace_validation_rejects_stage_identity_duplicates_and_invalid_samples(self):
        good = trace([("q", "A", samples(["A"] * 3))])
        mutations = []
        for key, value in [("stage", "confirmation"), ("stage", "test"), ("schema_version", True),
                           ("cases", []), ("generation", {})]:
            bad = copy.deepcopy(good)
            bad[key] = value
            mutations.append(bad)
        bad = copy.deepcopy(good)
        bad["cases"].append(copy.deepcopy(bad["cases"][0]))
        mutations.append(bad)
        for key, value in [("id", "1"), ("status", "unknown"), ("answer", None),
                           ("answer", 1), ("elapsed_seconds", True), ("elapsed_seconds", -1)]:
            bad = copy.deepcopy(good)
            bad["cases"][0]["samples"][0][key] = value
            mutations.append(bad)
        bad = copy.deepcopy(good)
        bad["cases"][0]["samples"][0]["status"] = "failed"
        mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(replay.ReplayFailure):
                replay.read_trace(json.dumps(bad).encode())
        for raw in [b'{"stage":"development","stage":"confirmation"}', b'{"n":NaN}', b'{"n":1e999}']:
            with self.subTest(raw=raw), self.assertRaises(replay.evidence.ArchiveFailure):
                replay.read_trace(raw)

    def test_missing_budget_slots_are_not_silent_exclusions(self):
        data = trace([("q", "A", samples(["A"]))])
        for limit in [0, True, 2]:
            with self.subTest(limit=limit), self.assertRaises(replay.ReplayFailure):
                replay.analyze_cases(data, limit)

    def test_cli_preserves_inputs_report_identity_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache, output = root / "trace.json", root / "report.json"
            raw = json.dumps(trace([("q", "A", samples(["A"] * 5))])).encode()
            cache.write_bytes(raw)
            command = [sys.executable, str(SCRIPT_DIR / "replay_inference_votes.py"),
                       "--trace", str(cache), "--max-samples", "5", "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(json.loads(result.stdout), report)
            self.assertEqual(report["input"]["sha256"], replay.evidence.sha256(raw))
            self.assertEqual(report["configuration_sha256"],
                             replay.evidence.sha256(replay.evidence.canonical(report["configuration"])))
            self.assertEqual(report["selection_scope"], "cached_inference_votes_only")
            self.assertTrue({"candidate_hash", "valid", "score"}.isdisjoint(report))
            self.assertEqual(cache.read_bytes(), raw)
            saved = output.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(output.read_bytes(), saved)
            args = replay.make_parser().parse_args(command[2:])
            read = Path.read_bytes
            calls = 0

            def changed(path):
                nonlocal calls
                value = read(path)
                if path == cache:
                    calls += 1
                    return value if calls == 1 else value + b" "
                return value

            with patch.object(Path, "read_bytes", changed), self.assertRaises(replay.ReplayFailure):
                replay.analyze(args)


if __name__ == "__main__":
    unittest.main()
