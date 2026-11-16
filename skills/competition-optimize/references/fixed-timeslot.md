# Fixed Timeslot Adapter

Use this reference for the Huawei Cloud fixed-timeslot C++ case. Invoke the bundled adapter by absolute path. Set `COMPETITION_ROOT` to the directory containing `solution.h` and `tests/`, or pass it explicitly. `CXX` selects the compiler; the default is `g++`.

```powershell
python <skill-dir>/scripts/evaluate_current_timeslot.py `
  --candidate <candidate.cpp> `
  --stage smoke `
  --competition-root <competition-root> `
  --output-dir <new-run-dir>
```

Stages are `smoke` (9 cases: seed 17, N 100, Q 1), `short` (405 cases: N 100/400/10000, Q 1/10/100, five seeds and nine scenarios), `full` (90 cases: N 400/10000, Q 1000, five seeds and nine scenarios), `rules` (the declared Clang AST static-check subset), and `package` (exact ZIP verification). The five seeds are 1/7/17/31/101. Use a new output directory outside the competition `tests/` tree. Stdout gives a compact JSON summary and `result.json` is the source of truth. Compile and per-process timeout default to 60 seconds and can be set with `--timeout`. Failed evaluations may retain partial metrics for diagnosis; only successful complete short/full results can be compared.

New results use schema 3 and bind the fixed workload protocol in `workload_hash` and `evaluation.workload_protocol/expected_cases/completed_cases`. The runner and reader share the workload definition, and each independently verifies all expected keys. The reader still accepts genuinely complete schema-2 short/full results against the known legacy protocol. Missing, extra, duplicate, or wrong-stage cases fail even when both compared files have the same defect; incomplete legacy evidence cannot be relabeled as a complete evaluation. New and legacy results still need identical evaluator hashes and runtime environments to be compared.

Run static checks and package creation as separate operations on the same candidate:

```powershell
python <skill-dir>/scripts/evaluate_current_timeslot.py `
  --candidate <candidate.cpp> --stage rules `
  --rule-compiler <clang++> `
  --competition-root <competition-root> --output-dir <new-rule-run-dir>

python <skill-dir>/scripts/evaluate_current_timeslot.py `
  --candidate <candidate.cpp> --stage package `
  --competition-root <competition-root> --output-dir <new-package-run-dir>
```

The `rules` stage needs a working Clang C++ toolchain with standard-library headers; use `--rule-compiler` or `CLANGXX` (default `clang++`). It performs syntax checking only and does not execute candidate code. A missing compiler, parse failure, or timeout produces `rule_check.status=unavailable` and a nonzero exit; it never counts as a pass. Rules reported as violations also return nonzero. The result records the actual compiler command, version, executable hash, checking coverage, and unchecked rules. The evaluator hash covers this compiler identity and the workload/checker module sources.

The checked subset is active candidate-source AST syntax: builtin `*`, `/`, `%` and their compound assignments, resolved overloaded operator expressions, `float`/`double` types including desugared aliases, `main` declarations, listed math/I/O/time symbol references, and visible `std::chrono` types. Clang distinguishes unary pointer or iterator dereferences from binary multiplication; comments and strings are not operations. Expanded macros are checked at their candidate-source expansion location. Header implementation bodies, inactive branches, unexpanded macros, unresolved template semantics, indirect or explicit operator-function calls, other APIs, runtime/resource behavior, and other official rules remain unchecked. See `rule-check.json` for the exact catalog; `all_rules_verified` always remains false.

The existing `--stage package` command remains available without Clang. It now verifies only the ZIP entries, CRC, extracted bytes, and hashes of `Solution.cpp` and `solution.h`; it does not run static checks. Both package and rules results keep `correct=null`, with `validity_scope=package_bytes` or `static_rule_subset`. Their success is not correctness evaluation, a complete rule audit, or comparable measurement evidence. Before submission, retain behavioral evaluation, the static-check report, manual review of unchecked rules, and the package report for the same candidate hash.

The official per-testcase score is `0.55 * Scoreuniformity + 0.35 * Scorevariance + 0.10 * Scorespeed`. Speed is 1 when measured time `t <= tfast`, 0 when `t >= tslow`, and otherwise `1 - ln(t / tfast) / ln(tslow / tfast)`. The published problem statement does not provide numeric `tfast` and `tslow`; the adapter therefore reports the local quality proxy `0.55 * uniformity + 0.35 * stability` and operation/init timing separately. It does not calculate the official total score. Do not infer the missing speed contribution or official test aggregation.

For a different scheduling method, validate counts, interface behavior and score calculations independently; its valid grid may differ from the incumbent. Exact-grid equality is appropriate for a deliberately equivalent speed optimization, not a default restriction on score search. Preserve quality/runtime tradeoffs when speed parameters are unknown: a self-chosen slowdown ceiling cannot prove a net official-score loss. Prioritize credible time-limit risks with the timing boundary and hardware scope stated, rather than repeatedly polishing equivalent grids while feasibility remains unresolved.

The adapter snapshots the candidate and writes binaries, logs, CSV, JSON, and package artifacts only under the requested output directory. It reuses the competition harness and is not a sandbox; only run candidate code you are authorized to execute. The candidate is a single UTF-8 C++ source file using the provided `solution.h` interface and standard library.

Compare completed runs with:

```powershell
python <skill-dir>/scripts/compare_timeslot_results.py `
  --baseline <baseline-result.json> `
  --candidate <candidate-result.json> `
  --output <new-comparison.json>
```

The comparator requires successful, complete results with matching evaluator hashes and runtime environments, and exact coverage of the fixed stage protocol. Matching environment metadata alone does not establish timing comparability under concurrent load. Use [timing recovery](plateau-recovery.md#make-timing-interpretable) for consequential comparisons; preserve valid deterministic quality evidence and remeasure affected resource items separately. Timing deltas remain local and need matched repeat confirmation before selection. Do not mark an incompatible result comparable to bypass the tool's checks.
