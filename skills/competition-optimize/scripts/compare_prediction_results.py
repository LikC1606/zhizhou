#!/usr/bin/env python3
"""Compare local prediction scores under the same split and metric contract."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from typing import Any

from prediction_core import (
    ComparisonFailure, compare, load_result, metric_preference, byte_hash, object_hash,
    PredictionFailure,
)
from prediction_evidence import EvidenceFailure, load_pair


def compare_verified(baseline: pathlib.Path, candidate: pathlib.Path,
                     truth: pathlib.Path, epsilon: float) -> dict[str, Any]:
    if not math.isfinite(epsilon) or epsilon < 0:
        raise ComparisonFailure("Tie epsilon must be finite and non-negative")
    try:
        pair = load_pair(baseline, candidate, truth)
    except (EvidenceFailure, PredictionFailure) as exc:
        raise ComparisonFailure(str(exc)) from exc
    result = pair.comparison
    result["tie_epsilon"] = epsilon
    result["metric_preference"] = metric_preference(result["objective_improvement"], epsilon)
    result["score_verification"] = {
        "status": "passed", "scope": "saved_scores_recomputed_on_recorded_metric_inputs",
        "truth": str(pair.paths["truth"]), "input_hashes": pair.input_hashes,
        "verification_hash": object_hash({name: byte_hash(pathlib.Path(__file__).with_name(name).read_bytes())
                                          for name in ["compare_prediction_results.py", "prediction_evidence.py", "prediction_core.py"]}),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=pathlib.Path)
    parser.add_argument("--candidate", required=True, type=pathlib.Path)
    parser.add_argument("--tie-epsilon", type=float, default=1e-12)
    parser.add_argument("--truth", type=pathlib.Path,
                        help="optional frozen truth CSV: recompute saved scores with the installed evaluator")
    parser.add_argument("--output", type=pathlib.Path, help="optional new comparison JSON; never overwrite")
    args = parser.parse_args()
    try:
        baseline_path = args.baseline.expanduser().resolve(strict=True)
        candidate_path = args.candidate.expanduser().resolve(strict=True)
        result = (compare_verified(baseline_path, candidate_path, args.truth, args.tie_epsilon)
                  if args.truth is not None else
                  compare(load_result(baseline_path), load_result(candidate_path), args.tie_epsilon))
        result["baseline"]["result"] = str(baseline_path)
        result["candidate"]["result"] = str(candidate_path)
        if args.output is not None:
            with args.output.expanduser().open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    except (OSError, ComparisonFailure, ValueError, TypeError, OverflowError) as exc:
        print(json.dumps({"status": "failed", "error": {"type": "comparison_invalid", "message": str(exc)}},
                         ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
