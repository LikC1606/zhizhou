"""Check a declared subset of fixed-timeslot C++ rules with Clang's AST.

This checks active candidate-source syntax, including expanded macros. Header
implementation bodies and other compilation configurations are outside the
check. Packaging and behavioral correctness are separate operations.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
from typing import Any


FLAGS = ("-std=c++17", "-fsyntax-only", "-Xclang", "-ast-dump=json")
COVERAGE = [
    "candidate-source AST in the active C++17 configuration, including expanded macros",
    "builtin binary *, /, %, *=, /=, %= and resolved overloaded operator-expression forms",
    "float/double types, including aliases desugared by Clang",
    "main declarations and references to sqrt/pow/sin/cos/tan/log/exp/fmod/cin/cout/printf/scanf/fopen/clock",
    "std::chrono types visible in candidate-source AST nodes",
]
UNCHECKED_RULES = [
    "algorithm_correctness_and_official_scoring", "resource_limits_and_runtime_behavior",
    "included_header_implementation_bodies", "inactive_preprocessor_branches_and_unexpanded_macros",
    "indirect_or_explicit_operator_function_calls_and_unresolved_template_semantics",
    "other_io_math_timing_APIs_and_all_other_official_rules",
]
ARITHMETIC = {"*", "/", "%", "*=", "/=", "%="}
FORBIDDEN_REFERENCES = {"sqrt", "pow", "sin", "cos", "tan", "log", "exp", "fmod",
                        "cin", "cout", "printf", "scanf", "fopen", "clock"}


def compiler_identity(command: str, timeout: int) -> dict[str, Any]:
    """Resolve the actual Clang binary; absence is actionable evidence, not a pass."""
    identity: dict[str, Any] = {"requested": command, "command": None, "version": None,
                                "sha256": None, "flags": list(FLAGS), "available": False}
    resolved = shutil.which(command)
    if resolved is None:
        identity["error"] = f"Clang not found: {command}. Install Clang and set --rule-compiler or CLANGXX."
        return identity
    path = pathlib.Path(resolved).resolve()
    identity["command"] = str(path)
    try:
        version = subprocess.run([str(path), "--version"], text=True, capture_output=True,
                                 timeout=timeout, check=False)
        if version.returncode != 0 or "clang" not in version.stdout.lower():
            identity["error"] = "Rule checking requires Clang; set --rule-compiler or CLANGXX to clang++."
            return identity
        identity.update(version=version.stdout.strip(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        available=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        identity["error"] = f"Cannot inspect Clang: {exc}. Check --rule-compiler or CLANGXX."
    return identity


def _source_location(node: dict[str, Any], source_path: pathlib.Path) -> dict[str, Any] | None:
    location = node.get("loc") or node.get("range", {}).get("begin", {})
    location = location.get("expansionLoc", location)
    # Clang omits repeated file names, but retains includedFrom on header locations.
    if "offset" not in location or "includedFrom" in location:
        return None
    filename = location.get("file")
    if filename and pathlib.Path(filename).resolve() != source_path:
        return None
    return location


def _operator_name(node: dict[str, Any]) -> str | None:
    if node.get("kind") == "DeclRefExpr":
        return node.get("referencedDecl", {}).get("name")
    for child in node.get("inner", []):
        name = _operator_name(child)
        if name:
            return name
    return None


def check_rules(source_path: pathlib.Path, include_dir: pathlib.Path,
                compiler: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Return passed/violation/unavailable with the exact static checking scope."""
    result: dict[str, Any] = {"status": "unavailable", "all_rules_verified": False,
                              "compiler": compiler, "coverage": list(COVERAGE),
                              "unchecked_rules": list(UNCHECKED_RULES), "violations": []}
    if not compiler.get("available"):
        result["error"] = compiler.get("error", "Clang unavailable; set --rule-compiler or CLANGXX.")
        return result
    source_path = source_path.resolve()
    try:
        source = source_path.read_bytes()
        source.decode("utf-8")
        command = [compiler["command"], *FLAGS, "-I", str(include_dir), str(source_path)]
        checked = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False,
                                 cwd=source_path.parent)
        if checked.returncode != 0:
            result["error"] = "Clang could not parse the candidate; rule checking is unavailable. " + "\n".join(checked.stderr.splitlines()[-12:])
            return result
        tree = json.loads(checked.stdout)
        if not isinstance(tree, dict) or tree.get("kind") != "TranslationUnitDecl":
            raise ValueError("Clang did not return a translation-unit AST")
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"Could not complete Clang AST checking: {exc}"
        return result

    violations: dict[tuple[str, int, str], dict[str, Any]] = {}
    pending = [tree]
    while pending:
        node = pending.pop()
        children = node.get("inner", [])
        pending.extend(children)
        location = _source_location(node, source_path)
        if location is None:
            continue
        offset = location["offset"]
        kind = node.get("kind")
        findings = []
        if kind in {"BinaryOperator", "CompoundAssignOperator"} and node.get("opcode") in ARITHMETIC:
            findings.append(("arithmetic", node["opcode"]))
        if kind == "CXXOperatorCallExpr" and len(children) == 3:
            name = _operator_name(children[0])
            if name and name.removeprefix("operator") in ARITHMETIC:
                findings.append(("arithmetic", name))
        types = node.get("type", {})
        type_name = types.get("desugaredQualType", types.get("qualType", ""))
        if re.search(r"\b(float|double)\b", type_name):
            findings.append(("floating_type", type_name))
        if re.search(r"\bstd::chrono::", type_name):
            findings.append(("chrono_type", type_name))
        if kind == "FunctionDecl" and node.get("name") == "main":
            findings.append(("main", "main declaration"))
        if kind == "DeclRefExpr":
            name = node.get("referencedDecl", {}).get("name")
            if name in FORBIDDEN_REFERENCES:
                findings.append(("forbidden_reference", name))
        for rule, detail in findings:
            prefix = source[:offset]
            violations[rule, offset, detail] = {
                "rule": rule, "detail": detail, "line": prefix.count(b"\n") + 1,
                "column": offset - prefix.rfind(b"\n"),
            }
    result["violations"] = [value for _, value in sorted(violations.items())]
    result["status"] = "violation" if violations else "passed"
    return result
