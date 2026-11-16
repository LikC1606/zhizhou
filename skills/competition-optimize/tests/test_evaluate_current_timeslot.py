from __future__ import annotations

import csv
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
evaluate = importlib.import_module("evaluate_current_timeslot")
CLANG = shutil.which(os.environ.get("CLANGXX", "clang++"))


def metric_rows() -> list[dict[str, str]]:
    return [
        {
            "seed": "7",
            "scenario": scenario,
            "N": "400",
            "Q": "100",
            "uniformity": "0.5",
            "stability": "0.4",
            "operation_ms": "3.5",
            "init_ms": "1.25",
        }
        for scenario in evaluate.SCENARIOS
    ]


def csv_output(rows: list[dict[str, str]]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=evaluate.CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class ParseRowsTests(unittest.TestCase):
    def test_accepts_complete_rows_for_the_requested_workload(self) -> None:
        parsed = evaluate.parse_rows(
            csv_output(metric_rows()), len(evaluate.SCENARIOS),
            {"seed": 7, "N": 400, "Q": 100},
        )

        self.assertEqual(len(parsed), len(evaluate.SCENARIOS))
        self.assertAlmostEqual(parsed[0]["quality_proxy"], 0.415)

    def test_rejects_rows_that_do_not_match_invocation_identity(self) -> None:
        for expected, message in [({"N": 10000}, "Expected N=10000"),
                                  ({"Q": 1000}, "Expected Q=1000")]:
            with self.subTest(expected=expected), self.assertRaisesRegex(evaluate.EvaluationFailure, message):
                evaluate.parse_rows(csv_output(metric_rows()), len(evaluate.SCENARIOS), expected)

    def test_rejects_missing_duplicate_or_unknown_scenarios(self) -> None:
        duplicate = metric_rows()
        duplicate[-1]["scenario"] = duplicate[0]["scenario"]
        unknown = metric_rows()
        unknown[-1]["scenario"] = "unknown"
        missing = metric_rows()[:-1]

        for rows in [duplicate, unknown, missing]:
            with self.subTest(scenarios=[row["scenario"] for row in rows]):
                with self.assertRaises(evaluate.EvaluationFailure):
                    evaluate.parse_rows(csv_output(rows), len(evaluate.SCENARIOS))

    def test_rejects_extra_csv_columns(self) -> None:
        lines = csv_output(metric_rows()).splitlines()
        lines[2] += ",unexpected"
        with self.assertRaisesRegex(evaluate.EvaluationFailure, "extra columns"):
            evaluate.parse_rows("\n".join(lines) + "\n", len(evaluate.SCENARIOS))

    def test_rejects_invalid_dimensions_quality_and_time(self) -> None:
        for field, value in [("N", "0"), ("Q", "-1"), ("uniformity", "1.01"),
                             ("stability", "-0.01"), ("operation_ms", "-1"), ("init_ms", "NaN")]:
            with self.subTest(field=field, value=value):
                rows = metric_rows()
                rows[0][field] = value
                with self.assertRaises(evaluate.EvaluationFailure):
                    evaluate.parse_rows(csv_output(rows), len(evaluate.SCENARIOS))


@unittest.skipUnless(CLANG, "Clang is required for real C++ AST regression tests; set CLANGXX")
class RuleChecksTests(unittest.TestCase):
    def check(self, source: str) -> dict:
        rules = importlib.import_module("timeslot_rules")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "candidate.cpp"
            source_path.write_text(source, encoding="utf-8")
            identity = rules.compiler_identity(CLANG, 30)
            return rules.check_rules(source_path, root, identity, 30)

    def test_multiplication_cannot_pass_via_a_whitelisted_variable_name(self) -> None:
        checked = self.check("int f(int current) { return 2 * current; }")
        self.assertEqual(checked["status"], "violation")
        self.assertTrue(any(item["rule"] == "arithmetic" for item in checked["violations"]))

    def test_pointer_declarations_and_dereferences_are_accepted(self) -> None:
        checked = self.check("int f(int* p) { int **q = &p; return **q + *(p + 1); }")
        self.assertEqual(checked["status"], "passed", checked)

    def test_comments_and_string_literals_are_not_cpp_operations(self) -> None:
        checked = self.check('const char* text = R"(float double main() */% // printf)";\n'
                             '// 2 * current; printf("bad");\n/* / % double */\nint f() { return 1; }')
        self.assertEqual(checked["status"], "passed", checked)

    def test_compound_operations_and_expanded_macros_are_checked(self) -> None:
        for expression in ["n *= 2", "n /= 2", "n %= 2", "n = n / 2", "n = n % 2"]:
            with self.subTest(expression=expression):
                self.assertEqual(self.check(f"int f(int n) {{ {expression}; return n; }}")["status"], "violation")
        checked = self.check("#define MUL(x) ((x) * (x))\nint f(int n) { return MUL(n); }")
        self.assertEqual(checked["status"], "violation")

    def test_standard_library_iterator_dereference_is_accepted(self) -> None:
        checked = self.check("#include <set>\nint f(std::set<int>& s) { return *s.begin(); }")
        self.assertEqual(checked["status"], "passed", checked)

    def test_overloaded_unary_dereference_and_binary_multiplication_are_distinguished(self) -> None:
        pointer = "struct P { int operator*() const { return 1; } }; int f(P p) { return *p; }"
        multiply = "struct V { V operator*(const V&) const { return *this; } }; V f(V a, V b) { return a * b; }"
        self.assertEqual(self.check(pointer)["status"], "passed")
        self.assertEqual(self.check(multiply)["status"], "violation")

    def test_float_aliases_main_and_named_forbidden_references_are_reported(self) -> None:
        for source in ["using Real = double; Real f() { return 0; }", "int main() { return 0; }",
                       '#include <cstdio>\nint f() { return std::printf("x"); }']:
            with self.subTest(source=source):
                self.assertEqual(self.check(source)["status"], "violation")

    def test_invalid_cpp_is_unavailable_and_never_passes(self) -> None:
        checked = self.check("int f( { broken;")
        self.assertEqual(checked["status"], "unavailable")

    def test_report_does_not_claim_inactive_preprocessor_code_was_checked(self) -> None:
        checked = self.check("#if 0\nint f(int x) { return x * x; }\n#endif\nint f(int x) { return x; }")
        self.assertEqual(checked["status"], "passed")
        self.assertIs(checked["all_rules_verified"], False)
        self.assertIn("inactive_preprocessor_branches_and_unexpanded_macros", checked["unchecked_rules"])


class AdapterStageTests(unittest.TestCase):
    def run_stage(self, stage: str, source: str, extra: list[str] | None = None,
                  expected_returncode: int = 0, harness: str = "// fixture\n") -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            competition = root / "competition"
            (competition / "tests").mkdir(parents=True)
            for name in ["solution.h", "tests/benchmark.cpp", "tests/short_sequence.cpp", "tests/package_submission.py"]:
                (competition / name).write_text("// fixture\n", encoding="utf-8")
            for name in ["tests/benchmark.cpp", "tests/short_sequence.cpp"]:
                (competition / name).write_text(harness, encoding="utf-8")
            candidate = root / "Solution.cpp"
            candidate.write_text(source, encoding="utf-8")
            output = root / "run"
            process = subprocess.run([sys.executable, str(SCRIPT_DIR / "evaluate_current_timeslot.py"),
                                      "--candidate", str(candidate), "--stage", stage,
                                      "--competition-root", str(competition), "--output-dir", str(output),
                                      *(extra or [])], text=True, capture_output=True, check=False)
            self.assertEqual(process.returncode, expected_returncode, process.stdout + process.stderr)
            value = json.loads((output / "result.json").read_text())
            if stage == "package":
                self.assertEqual(process.returncode, 0, process.stdout)
                with zipfile.ZipFile(output / "submission.zip") as archive:
                    self.assertEqual(archive.namelist(), ["Solution.cpp", "solution.h"])
                    self.assertEqual(archive.read("Solution.cpp"), candidate.read_bytes())
                    self.assertEqual(archive.read("solution.h"), (competition / "solution.h").read_bytes())
            return value

    def test_package_checks_exact_bytes_without_claiming_algorithm_or_rule_correctness(self) -> None:
        value = self.run_stage("package", "int f(int current) { return 2 * current; }")
        self.assertEqual(value["status"], "success")
        self.assertIsNone(value["correct"])
        self.assertEqual(value["validity_scope"], "package_bytes")
        self.assertIn("static_rules", value["unchecked_rules"])

    def test_missing_rule_compiler_is_explicitly_unavailable(self) -> None:
        value = self.run_stage("rules", "int f() { return 1; }", ["--rule-compiler", "/missing/clang++"],
                               expected_returncode=1)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["rule_check"]["status"], "unavailable")
        self.assertIsNone(value["correct"])
        self.assertIn("--rule-compiler", value["error"]["message"])

    @unittest.skipUnless(CLANG, "Clang is required; set CLANGXX")
    def test_rules_cli_reports_scope_and_cannot_claim_algorithm_correctness(self) -> None:
        for source, status, exit_code in [("int f(int* p) { return *p; }", "passed", 0),
                                          ("int f(int current) { return 2 * current; }", "violation", 1)]:
            with self.subTest(status=status):
                value = self.run_stage("rules", source, ["--rule-compiler", CLANG], expected_returncode=exit_code)
                self.assertEqual(value["rule_check"]["status"], status)
                self.assertEqual(value["validity_scope"], "static_rule_subset")
                self.assertIsNone(value["correct"])
                self.assertFalse(value["rule_check"]["all_rules_verified"])
                self.assertTrue(value["rule_check"]["compiler"]["sha256"])
                self.assertNotIn("submission.zip", value["artifacts"])

    @unittest.skipUnless(shutil.which("g++"), "g++ is required for the disposable harness fixture")
    def test_runner_and_reader_agree_on_complete_fixed_protocol(self) -> None:
        harness = r'''
#include <iostream>
int main(int argc, char** argv) {
    if (argc < 3) return 2;
    const char* q = argc > 3 ? argv[3] : "1000";
    const char* scenarios[] = {"mixed", "sparse", "dense", "single", "bulk", "many-types", "dominant", "uneven", "fresh-id"};
    std::cout << "seed,scenario,N,Q,uniformity,stability,operation_ms,init_ms\n";
    for (const char* scenario : scenarios)
        std::cout << argv[1] << ',' << scenario << ',' << argv[2] << ',' << q << ",0.5,0.4,3.5,1.25\n";
}
'''
        comparator = importlib.import_module("compare_timeslot_results")
        for stage, count in [("smoke", 9), ("short", 405), ("full", 90)]:
            with self.subTest(stage=stage):
                value = self.run_stage(stage, "int candidate() { return 1; }", ["--compiler", shutil.which("g++")],
                                       harness=harness)
                self.assertEqual(value["schema_version"], 3)
                self.assertEqual(value["evaluation"]["expected_cases"], count)
                self.assertEqual(value["evaluation"]["completed_cases"], count)
                self.assertEqual(len(value["metrics"]["rows"]), count)
                if stage != "smoke":
                    compared = comparator.compare(value, Path("base.json"), value, Path("candidate.json"))
                    self.assertEqual(compared["workload_count"], count)
                    self.assertEqual(compared["workload_hash"], value["workload_hash"])

    def test_contract_covers_workload_checker_and_rule_compiler_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tests").mkdir()
            adapter = root / "adapter"
            adapter.mkdir()
            for name in ["solution.h", "tests/benchmark.cpp", "tests/short_sequence.cpp", "tests/package_submission.py",
                         "adapter/evaluate.py", "adapter/timeslot_workloads.py", "adapter/timeslot_rules.py"]:
                (root / name).write_text("fixture", encoding="utf-8")
            def digest(identity: dict) -> str:
                return evaluate.digest_contract(root, adapter / "evaluate.py", "not-used", "not-used", {},
                                                "rules", 60, identity)
            identity = {"command": "clang++", "version": "test-18", "sha256": "a" * 64}
            original = digest(identity)
            for name in ["timeslot_workloads.py", "timeslot_rules.py"]:
                (adapter / name).write_text("changed", encoding="utf-8")
                self.assertNotEqual(digest(identity), original)
                (adapter / name).write_text("fixture", encoding="utf-8")
            for field in identity:
                self.assertNotEqual(digest({**identity, field: "changed"}), original)


if __name__ == "__main__":
    unittest.main()
