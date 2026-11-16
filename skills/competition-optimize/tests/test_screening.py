from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
screening = importlib.import_module("analyze_screening")


class ScreeningTests(unittest.TestCase):
    def rows(self, screen, full):
        return [{"candidate": name, "screen_score": before, "full_score": after}
                for name, before, after in zip("abcd", screen, full)]

    def test_opposite_score_directions_preserve_order(self):
        report = screening.analyze_rows(self.rows([1, 2, 3], [30, 20, 10]), 1, "minimize", "maximize", 0, 0)
        self.assertEqual(report["pair_counts"]["concordant"], 3)
        self.assertEqual(report["decisive_pair_agreement"], 1)
        self.assertEqual(report["screen_survivors"], ["a"])
        self.assertEqual(report["full_best_retained"], ["a"])

    def test_inverted_screen_reports_missed_full_winner(self):
        report = screening.analyze_rows(self.rows([1, 2, 3], [30, 20, 10]), 1, "minimize", "minimize", 0, 0)
        self.assertEqual(report["pair_counts"]["inverted"], 3)
        self.assertEqual(report["decisive_pair_agreement"], 0)
        self.assertFalse(report["at_least_one_full_best_retained"])
        self.assertEqual(report["full_best_missed"], ["c"])
        self.assertEqual(report["inversion_examples"][0]["screen_preference"], "a")
        self.assertEqual(report["inversion_examples"][0]["full_preference"], "b")

    def test_cutoff_ties_expand_survivors_and_epsilon_uses_score_units(self):
        rows = self.rows([1, 2, 2.25, 3], [9, 7, 7.1, 8])
        report = screening.analyze_rows(rows, 2, "minimize", "minimize", .25, .1)
        self.assertEqual(report["screen_survivors"], ["a", "b", "c"])
        self.assertEqual(report["actual_keep_count"], 3)
        self.assertEqual(report["full_best_candidates"], ["b", "c"])
        # Maximizing screens retain ties on the lower side of the cutoff too.
        report = screening.analyze_rows(rows, 2, "maximize", "minimize", .25, 0)
        self.assertEqual(report["screen_survivors"], ["d", "c", "b"])

    def test_all_ties_do_not_claim_perfect_pair_agreement(self):
        report = screening.analyze_rows(self.rows([1, 1, 1], [2, 2, 2]), 1, "maximize", "minimize", 0, 0)
        self.assertEqual(report["pair_counts"]["both_tied"], 3)
        self.assertIsNone(report["decisive_pair_agreement"])
        self.assertEqual(report["screen_survivors"], ["a", "b", "c"])
        self.assertEqual(report["full_best_missed"], [])

    def test_single_side_ties_are_separate_from_decisive_pairs(self):
        report = screening.analyze_rows(self.rows([1, 1, 2], [3, 2, 2]), 2, "minimize", "minimize", 0, 0)
        self.assertEqual(report["pair_counts"], {"concordant": 0, "inverted": 1,
                                                "screen_tied_only": 1, "full_tied_only": 1, "both_tied": 0})

    def test_input_order_does_not_change_analysis_and_keep_all_drops_nothing(self):
        rows = self.rows([1, 2, 3], [3, 2, 1])
        first = screening.analyze_rows(rows, 3, "minimize", "minimize", 0, 0)
        self.assertEqual(first, screening.analyze_rows(list(reversed(rows)), 3, "minimize", "minimize", 0, 0))
        self.assertEqual(first["full_best_missed"], [])

    def test_finite_extreme_scores_do_not_overflow_output(self):
        report = screening.analyze_rows(self.rows([-1e308, 1e308], [1e308, -1e308]),
                                        1, "minimize", "minimize", 1e308, 1e308)
        self.assertEqual(report["screen_survivors"], ["a"])
        self.assertEqual(report["full_best_missed"], ["b"])
        json.dumps(report, allow_nan=False)

    def test_invalid_configuration_and_score_tables_fail(self):
        rows = self.rows([1, 2], [1, 2])
        for keep, screen, full, eps in [(0, "minimize", "minimize", 0), (3, "minimize", "minimize", 0),
                                      (True, "minimize", "minimize", 0), (1, "other", "minimize", 0),
                                      (1, "minimize", "other", 0), (1, "minimize", "minimize", -1),
                                      (1, "minimize", "minimize", math.inf)]:
            with self.subTest(keep=keep, eps=eps), self.assertRaises(screening.ScreeningFailure):
                screening.analyze_rows(rows, keep, screen, full, eps, 0)
        for raw in [b'candidate,screen_score,full_score\na,1,nan\nb,2,1\n',
                    b'candidate,screen_score,full_score\na,1,2\na,2,1\n',
                    b'candidate,screen_score,full_score\n ,1,2\nb,2,1\n',
                    b'candidate,screen_score,full_score\na,1\nb,2,1\n',
                    b'candidate,screen_score,full_score\na,1,2,x\nb,2,1\n',
                    b'candidate,screen_score,full_score\na,1,2\n',
                    b'candidate,screen_score,full_score,full_score\na,1,2,2\nb,2,1,1\n',
                    b'candidate,screen_score\na,1\nb,2\n', b'\xff']:
            with self.subTest(raw=raw), self.assertRaises(screening.ScreeningFailure):
                screening.read_scores(raw)

    def test_bom_and_extra_named_columns_keep_exact_candidate_ids(self):
        rows = screening.read_scores(b'\xef\xbb\xbfcandidate,screen_score,full_score,note\n001,1,2,a\n1,2,1,b\n')
        self.assertEqual([row["candidate"] for row in rows], ["001", "1"])

    def test_cli_reports_inversions_without_error_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scores, output = root / "scores.csv", root / "report.json"
            scores.write_text("candidate,screen_score,full_score\na,1,2\nb,2,1\n", encoding="utf-8")
            command = [sys.executable, str(SCRIPT_DIR / "analyze_screening.py"), "--scores", str(scores),
                       "--screen-direction", "minimize", "--full-direction", "minimize",
                       "--keep-count", "1", "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["full_best_missed"], ["b"])
            saved = output.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(output.read_bytes(), saved)
            args = screening.make_parser().parse_args(command[2:])
            read = Path.read_bytes
            calls = 0
            def changed(path):
                nonlocal calls
                raw = read(path)
                if path == scores:
                    calls += 1
                    return raw if calls == 1 else raw + b" "
                return raw
            with patch.object(Path, "read_bytes", changed), self.assertRaises(screening.ScreeningFailure):
                screening.analyze(args)


if __name__ == "__main__":
    unittest.main()
