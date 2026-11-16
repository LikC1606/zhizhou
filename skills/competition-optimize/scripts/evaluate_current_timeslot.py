#!/usr/bin/env python3
"""Evaluate one C++ candidate against the local fixed-timeslot harness."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import pathlib
import platform
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from typing import Any

import timeslot_rules
import timeslot_workloads
from timeslot_workloads import SCENARIOS

CSV_FIELDS = ["seed", "scenario", "N", "Q", "uniformity", "stability", "operation_ms", "init_ms"]
COMPILER_FLAGS = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic"]
CORRECTNESS_MARKERS = [
    "grid length", "count mismatch", "unexpected service id", "invalid change count",
]


class EvaluationFailure(Exception):
    def __init__(self, kind: str, phase: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.phase = phase


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def runtime_environment() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def digest_contract(root: pathlib.Path, adapter_path: pathlib.Path, compiler_path: str,
                    compiler_version: str, environment: dict[str, str], stage: str, timeout: int,
                    rule_compiler: dict[str, Any] | None = None) -> str:
    included = [
        adapter_path,
        adapter_path.parent / "timeslot_workloads.py",
        adapter_path.parent / "timeslot_rules.py",
        root / "solution.h",
        root / "tests" / "benchmark.cpp",
        root / "tests" / "short_sequence.cpp",
        root / "tests" / "package_submission.py",
    ]
    digest = hashlib.sha256()
    for path in sorted(included, key=lambda item: str(item).lower()):
        if not path.is_file():
            raise EvaluationFailure("infrastructure_failure", "contract", f"Missing evaluator input: {path}")
        name = str(path.relative_to(root) if path.is_relative_to(root) else path.name)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    config = {
        "stage": stage,
        "compiler": compiler_path,
        "compiler_version": compiler_version,
        "runtime_environment": environment,
        "flags": COMPILER_FLAGS,
        "timeout_seconds": timeout,
        "workload": timeslot_workloads.seal(stage) if stage in {"smoke", "short", "full"} else None,
        "rule_compiler": rule_compiler,
        "package_entries": ["Solution.cpp", "solution.h"],
    }
    digest.update(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_process(command: list[str], cwd: pathlib.Path, timeout: int,
                stdout_path: pathlib.Path, stderr_path: pathlib.Path, phase: str) -> subprocess.CompletedProcess[str]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.touch(exist_ok=True)
    stderr_path.touch(exist_ok=True)
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(decode_output(exc.stdout), encoding="utf-8")
        stderr_path.write_text(decode_output(exc.stderr), encoding="utf-8")
        raise EvaluationFailure("timeout", phase, f"Exceeded {timeout}s: {pathlib.Path(command[0]).name}") from exc
    except OSError as exc:
        raise EvaluationFailure("infrastructure_failure", phase, str(exc)) from exc
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return result


def parse_rows(stdout: str, expected: int,
               expected_identity: dict[str, int] | None = None) -> list[dict[str, Any]]:
    try:
        rows = list(csv.DictReader(io.StringIO(stdout)))
        if not rows or list(rows[0].keys()) != CSV_FIELDS or len(rows) != expected:
            raise ValueError(f"Expected {expected} CSV rows with fields {CSV_FIELDS}; received {len(rows)}")
        parsed: list[dict[str, Any]] = []
        seen_scenarios: set[str] = set()
        for row in rows:
            if None in row:
                raise ValueError("CSV row contains extra columns")
            item: dict[str, Any] = {
                "seed": int(row["seed"]), "scenario": row["scenario"],
                "N": int(row["N"]), "Q": int(row["Q"]),
            }
            if item["N"] <= 0 or item["Q"] <= 0:
                raise ValueError("N and Q must be positive")
            if item["scenario"] not in SCENARIOS or item["scenario"] in seen_scenarios:
                raise ValueError(f"Unexpected or duplicate scenario: {item['scenario']}")
            seen_scenarios.add(item["scenario"])
            if expected_identity is not None:
                for field, value in expected_identity.items():
                    if item[field] != value:
                        raise ValueError(f"Expected {field}={value}; received {item[field]}")
            for key in ["uniformity", "stability", "operation_ms", "init_ms"]:
                value = float(row[key])
                if not math.isfinite(value):
                    raise ValueError(f"Non-finite metric: {key}")
                item[key] = value
            if not 0.0 <= item["uniformity"] <= 1.0 or not 0.0 <= item["stability"] <= 1.0:
                raise ValueError("Quality metrics must be in [0, 1]")
            if item["operation_ms"] < 0 or item["init_ms"] < 0:
                raise ValueError("Time metrics must be non-negative")
            item["quality_proxy"] = 0.55 * item["uniformity"] + 0.35 * item["stability"]
            parsed.append(item)
        if seen_scenarios != set(SCENARIOS):
            raise ValueError("Scenario rows do not match the evaluator scenario set")
        return parsed
    except (KeyError, TypeError, ValueError, csv.Error) as exc:
        raise EvaluationFailure("invalid_result", "parse_output", str(exc)) from exc


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["N"], row["Q"]), []).append(row)
    summary = []
    for (n, q), group in sorted(groups.items()):
        summary.append({
            "N": n, "Q": q, "cases": len(group),
            "uniformity_mean": sum(row["uniformity"] for row in group) / len(group),
            "stability_mean": sum(row["stability"] for row in group) / len(group),
            "quality_proxy_mean": sum(row["quality_proxy"] for row in group) / len(group),
            "operation_ms_mean": sum(row["operation_ms"] for row in group) / len(group),
            "operation_ms_max": max(row["operation_ms"] for row in group),
            "init_ms_mean": sum(row["init_ms"] for row in group) / len(group),
        })
    return summary


def classify_test_failure(stderr: str) -> str:
    if any(line.startswith("FAIL:") for line in stderr.splitlines()):
        return "correctness_failure"
    if any(marker in stderr for marker in CORRECTNESS_MARKERS):
        return "correctness_failure"
    return "runtime_failure"


def package_submission(source: bytes, source_path: pathlib.Path, header_path: pathlib.Path,
                       output_dir: pathlib.Path) -> dict[str, Any]:
    """Verify exact submission bytes, without claiming static or runtime validity."""
    archive_path = output_dir / "submission.zip"
    extracted = output_dir / "package-verified"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Solution.cpp", source)
        archive.writestr("solution.h", header_path.read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if names != ["Solution.cpp", "solution.h"] or archive.testzip() is not None:
            raise EvaluationFailure("package_failure", "package_verify", "ZIP entries or CRC check failed")
        if archive.read("Solution.cpp") != source or archive.read("solution.h") != header_path.read_bytes():
            raise EvaluationFailure("package_failure", "package_verify", "ZIP contents do not match selected inputs")
        archive.extractall(extracted)
    if ((extracted / "Solution.cpp").read_bytes() != source or
            (extracted / "solution.h").read_bytes() != header_path.read_bytes()):
        raise EvaluationFailure("package_failure", "package_verify", "Extracted files differ from selected inputs")
    return {
        "entries": names, "source_sha256": sha256_bytes(source),
        "header_sha256": file_digest(header_path), "zip_sha256": file_digest(archive_path),
        "zip_bytes": archive_path.stat().st_size, "source_name": source_path.name,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=pathlib.Path)
    parser.add_argument("--stage", required=True, choices=["smoke", "short", "full", "rules", "package"])
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--competition-root", type=pathlib.Path, default=os.environ.get("COMPETITION_ROOT"))
    parser.add_argument("--compiler", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--rule-compiler", default=os.environ.get("CLANGXX", "clang++"),
                        help="Clang C++ compiler for the rules stage; unavailable checks fail explicitly")
    parser.add_argument("--timeout", type=int, default=60,
                        help="timeout in seconds per compile or test process")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        print(json.dumps({"status": "failed", "error": {"type": "output_exists", "phase": "setup",
                                                          "message": f"Refusing to reuse output directory: {output_dir}"}}))
        return 2
    if args.competition_root is not None:
        try:
            tests_root = (pathlib.Path(args.competition_root).expanduser().resolve(strict=True) / "tests").resolve()
            output_dir.relative_to(tests_root)
        except (FileNotFoundError, ValueError):
            pass
        else:
            print(json.dumps({"status": "failed", "error": {"type": "unsafe_output_dir", "phase": "setup",
                                                              "message": "Output directory must be outside the competition tests directory"}}))
            return 2
    try:
        output_dir.mkdir(parents=True)
    except OSError as exc:
        print(json.dumps({"status": "failed", "error": {"type": "infrastructure_failure", "phase": "setup",
                                                          "message": str(exc)}}))
        return 2

    result: dict[str, Any] = {
        "schema_version": 3, "stage": args.stage, "status": "failed", "correct": None,
        "validity_scope": {"rules": "static_rule_subset", "package": "package_bytes"}.get(args.stage, "fixed_workload_correctness"),
        "unchecked_rules": ["static_rules", "all_other_official_rules", "official_score_and_hidden_test_performance"],
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime_environment": runtime_environment(),
        "candidate": str(args.candidate.expanduser().resolve()), "candidate_hash": None,
        "evaluator_hash": None, "compiler": {"command": args.compiler, "version": None},
        "metrics": {}, "artifacts": [], "error": None,
    }
    phase = "setup"
    started_clock = time.perf_counter()
    rows: list[dict[str, Any]] = []
    if args.stage in {"smoke", "short", "full"}:
        contract = timeslot_workloads.seal(args.stage)
        result["workload_hash"] = contract["workload_hash"]
        result["evaluation"] = {"workload_protocol": contract["workload_protocol"],
                                "expected_cases": contract["expected_cases"], "completed_cases": 0}
    elif args.stage == "package":
        result["unchecked_rules"].append("algorithm_correctness")
    try:
        candidate_path = args.candidate.expanduser().resolve(strict=True)
        if not candidate_path.is_file():
            raise EvaluationFailure("invalid_input", phase, "Candidate must be a source file")
        if args.timeout <= 0:
            raise EvaluationFailure("invalid_input", phase, "Timeout must be positive")
        if args.competition_root is None:
            raise EvaluationFailure("invalid_input", phase, "Set --competition-root or COMPETITION_ROOT")
        try:
            root = pathlib.Path(args.competition_root).expanduser().resolve(strict=True)
        except FileNotFoundError as exc:
            raise EvaluationFailure("invalid_input", phase, "Competition root does not exist") from exc
        if not root.is_dir():
            raise EvaluationFailure("invalid_input", phase, "Competition root must be a directory")
        for relative in ["solution.h", "tests/benchmark.cpp", "tests/short_sequence.cpp", "tests/package_submission.py"]:
            if not (root / relative).is_file():
                raise EvaluationFailure("infrastructure_failure", phase, f"Missing competition input: {relative}")

        source = candidate_path.read_bytes()
        result["candidate_hash"] = sha256_bytes(source)
        snapshot_dir = output_dir / "input"
        snapshot_dir.mkdir()
        snapshot = snapshot_dir / "candidate.cpp"
        snapshot.write_bytes(source)
        result["artifacts"].append(str(snapshot.relative_to(output_dir)))

        compiler, version = "not-used", "not-used"
        if args.stage in {"smoke", "short", "full"}:
            compiler = shutil.which(args.compiler)
            if compiler is None and pathlib.Path(args.compiler).is_file():
                compiler = str(pathlib.Path(args.compiler).resolve())
            if compiler is None:
                raise EvaluationFailure("infrastructure_failure", "compiler_check", f"Compiler not found: {args.compiler}")
            compiler = str(pathlib.Path(compiler).resolve())
            version_path = output_dir / "compiler-version.txt"
            result["artifacts"].extend(["compiler-version.txt", "compiler-version.stderr.txt"])
            version_result = run_process([compiler, "--version"], output_dir, args.timeout,
                                         version_path, output_dir / "compiler-version.stderr.txt", "compiler_check")
            if version_result.returncode != 0:
                raise EvaluationFailure("infrastructure_failure", "compiler_check", "Compiler --version failed")
            version_lines = version_result.stdout.splitlines()
            version = version_lines[0] if version_lines else "unknown"
            result["compiler"] = {"command": compiler, "version": version, "flags": COMPILER_FLAGS}
        else:
            result["compiler"] = {"command": None, "version": None, "flags": []}
        rule_compiler = timeslot_rules.compiler_identity(args.rule_compiler, args.timeout) if args.stage == "rules" else None
        adapter_path = pathlib.Path(__file__).resolve()
        environment = result["runtime_environment"]
        result["evaluator_hash"] = digest_contract(root, adapter_path, compiler, version,
                                                    environment, args.stage, args.timeout, rule_compiler)

        if args.stage == "package":
            phase = "package_verify"
            result["metrics"]["package"] = package_submission(source, candidate_path, root / "solution.h", output_dir)
            result["artifacts"].extend(["submission.zip", "package-verified/Solution.cpp", "package-verified/solution.h"])
        elif args.stage == "rules":
            phase = "rule_check"
            checked = timeslot_rules.check_rules(snapshot, root, rule_compiler, args.timeout)
            result["rule_check"] = checked
            result["unchecked_rules"] = checked["unchecked_rules"]
            (output_dir / "rule-check.json").write_text(json.dumps(checked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result["artifacts"].append("rule-check.json")
            if checked["status"] == "unavailable":
                raise EvaluationFailure("rule_check_unavailable", phase, checked["error"])
            if checked["status"] == "violation":
                raise EvaluationFailure("rule_violation", phase, f"Found {len(checked['violations'])} static rule findings; see rule-check.json")
        else:
            phase = "compile"
            harness = "tests/short_sequence.cpp" if args.stage in ["smoke", "short"] else "tests/benchmark.cpp"
            binary = output_dir / ("candidate.exe" if os.name == "nt" else "candidate")
            compile_log, compile_err = output_dir / "compile.stdout.txt", output_dir / "compile.stderr.txt"
            # MinGW on Windows can compile sources under a non-ASCII workspace but
            # does not reliably accept a non-ASCII absolute linker output path.
            command = [compiler, *COMPILER_FLAGS, "-I", str(root), str(snapshot), str(root / harness), "-o", binary.name]
            result["artifacts"].extend(["compile.stdout.txt", "compile.stderr.txt"])
            compiled = run_process(command, output_dir, args.timeout, compile_log, compile_err, phase)
            if compiled.returncode != 0:
                detail = compiled.stderr.strip().splitlines()
                raise EvaluationFailure("compilation_failure", phase,
                                         "\n".join(detail[-12:]) or "Compiler returned non-zero")
            result["artifacts"].append(binary.name)

            phase = "benchmark" if args.stage == "full" else "correctness_test"
            for n, q, seed in timeslot_workloads.invocations(args.stage):
                stem = ("smoke" if args.stage == "smoke" else f"full-n{n}-seed{seed}" if args.stage == "full"
                        else f"short-n{n}-q{q}-seed{seed}")
                result["artifacts"].extend([f"{stem}.stdout.txt", f"{stem}.stderr.txt"])
                arguments = [str(seed), str(n)] + ([] if args.stage == "full" else [str(q)])
                tested = run_process([str(binary), *arguments], output_dir, args.timeout,
                                     output_dir / f"{stem}.stdout.txt", output_dir / f"{stem}.stderr.txt", phase)
                if tested.returncode != 0:
                    detail = tested.stderr.strip().splitlines()
                    raise EvaluationFailure(classify_test_failure(tested.stderr), phase,
                                             f"N={n}, Q={q}, seed={seed}: " +
                                             ("\n".join(detail[-12:]) or f"Process exited {tested.returncode}"))
                rows.extend(parse_rows(tested.stdout, len(SCENARIOS), {"seed": seed, "N": n, "Q": q}))

            result["evaluation"]["completed_cases"] = len(rows)
            try:
                timeslot_workloads.validate_result(result, [(row["N"], row["Q"], row["seed"], row["scenario"]) for row in rows])
            except timeslot_workloads.WorkloadFailure as exc:
                raise EvaluationFailure("invalid_result", "workload_verify", str(exc)) from exc

            rows_path = output_dir / "metrics.csv"
            with rows_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS + ["quality_proxy"])
                writer.writeheader()
                writer.writerows(rows)
            result["artifacts"].append("metrics.csv")
            result["metrics"] = {
                "rows": rows, "summary": summarize(rows),
                "quality_proxy_definition": "0.55 * uniformity + 0.35 * stability; local proxy, not official total score",
            }
            result["correct"] = True

        if args.stage == "rules":
            rule_compiler = timeslot_rules.compiler_identity(args.rule_compiler, args.timeout)
        after_hash = digest_contract(root, adapter_path, compiler, version,
                                     environment, args.stage, args.timeout, rule_compiler)
        if after_hash != result["evaluator_hash"]:
            raise EvaluationFailure("contract_changed", phase, "Evaluator inputs changed while this run was executing")
        result["status"] = "success"
    except EvaluationFailure as exc:
        result["error"] = {"type": exc.kind, "phase": exc.phase, "message": str(exc)}
        if exc.kind in ["correctness_failure", "compilation_failure", "runtime_failure"]:
            result["correct"] = False
        if exc.kind == "timeout" and exc.phase in ["compile", "correctness_test", "benchmark"]:
            result["correct"] = False
        if exc.kind in ["contract_changed", "invalid_result"]:
            result["correct"] = None
    except FileNotFoundError as exc:
        result["error"] = {"type": "invalid_input", "phase": phase, "message": str(exc)}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        result["error"] = {"type": "infrastructure_failure", "phase": phase, "message": str(exc)}

    if "evaluation" in result:
        result["evaluation"]["completed_cases"] = len(rows)
    if result["status"] != "success" and rows:
        rows_path = output_dir / "metrics.csv"
        with rows_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS + ["quality_proxy"])
            writer.writeheader()
            writer.writerows(rows)
        result["artifacts"].append("metrics.csv")
        result["metrics"] = {
            "rows": rows,
            "summary": summarize(rows),
            "partial": True,
            "quality_proxy_definition": "0.55 * uniformity + 0.35 * stability; local proxy, not official total score",
        }
    result["elapsed_seconds"] = round(time.perf_counter() - started_clock, 6)
    result_path = output_dir / "result.json"
    result["artifacts"].append("result.json")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = result.get("metrics", {}).get("summary", [])
    console_result = {
        "schema_version": result["schema_version"],
        "stage": result["stage"],
        "status": result["status"],
        "correct": result["correct"],
        "validity_scope": result["validity_scope"],
        "unchecked_rules": result["unchecked_rules"],
        "rule_check": result.get("rule_check"),
        "workload_hash": result.get("workload_hash"),
        "evaluation": result.get("evaluation"),
        "candidate_hash": result["candidate_hash"],
        "evaluator_hash": result["evaluator_hash"],
        "metrics_summary": summary,
        "package": result.get("metrics", {}).get("package"),
        "result_file": str(result_path),
        "error": result["error"],
    }
    print(json.dumps(console_result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
