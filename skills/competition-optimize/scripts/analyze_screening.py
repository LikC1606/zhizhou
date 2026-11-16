#!/usr/bin/env python3
"""Check observed rank preservation of a cheap screen against full development scores."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import pathlib
import sys
from itertools import combinations
from typing import Any


class ScreeningFailure(Exception):
    pass


def read_scores(raw: bytes) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = reader.fieldnames
        if (not header or len(set(header)) != len(header) or any(not key.strip() for key in header)
                or not {"candidate", "screen_score", "full_score"} <= set(header)):
            raise ValueError("Need unique named columns including candidate, screen_score, full_score")
        rows, names = [], set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed score row")
            name = row["candidate"]
            if not name.strip() or name in names:
                raise ValueError("Candidate IDs must be non-empty and unique")
            names.add(name)
            scores = {key: float(row[key]) for key in ["screen_score", "full_score"]}
            if not all(math.isfinite(value) for value in scores.values()):
                raise ValueError("Every reference needs finite successful screen and full scores")
            rows.append({"candidate": name, **scores})
        if len(rows) < 2:
            raise ValueError("Need at least two paired reference candidates")
        return rows
    except (UnicodeError, ValueError, csv.Error) as exc:
        raise ScreeningFailure(str(exc)) from exc


def preference(left: float, right: float, direction: str, epsilon: float) -> int:
    if abs(left - right) <= epsilon:
        return 0
    return -1 if (left < right if direction == "minimize" else left > right) else 1


def analyze_rows(rows: list[dict[str, Any]], keep: int, screen_direction: str,
                 full_direction: str, screen_epsilon: float, full_epsilon: float) -> dict[str, Any]:
    if type(keep) is not int or not 1 <= keep <= len(rows):
        raise ScreeningFailure("Keep count must be from 1 to the number of references")
    if screen_direction not in {"minimize", "maximize"} or full_direction not in {"minimize", "maximize"}:
        raise ScreeningFailure("Score directions must be minimize or maximize")
    if any(not math.isfinite(value) or value < 0 for value in [screen_epsilon, full_epsilon]):
        raise ScreeningFailure("Tie epsilons must be finite and non-negative, in each score's units")
    screen_order = sorted(rows, key=lambda row: (
        row["screen_score"] * (1 if screen_direction == "minimize" else -1), row["candidate"]))
    full_order = sorted(rows, key=lambda row: (
        row["full_score"] * (1 if full_direction == "minimize" else -1), row["candidate"]))
    cutoff, best = screen_order[keep - 1]["screen_score"], full_order[0]["full_score"]
    retained = [row["candidate"] for row in screen_order
                if preference(row["screen_score"], cutoff, screen_direction, screen_epsilon) <= 0]
    full_best = [row["candidate"] for row in full_order
                 if preference(row["full_score"], best, full_direction, full_epsilon) == 0]
    counts = {"concordant": 0, "inverted": 0, "screen_tied_only": 0, "full_tied_only": 0, "both_tied": 0}
    examples = []
    for left, right in combinations(sorted(rows, key=lambda row: row["candidate"]), 2):
        screen = preference(left["screen_score"], right["screen_score"], screen_direction, screen_epsilon)
        full = preference(left["full_score"], right["full_score"], full_direction, full_epsilon)
        if not screen or not full:
            kind = "both_tied" if not screen and not full else "screen_tied_only" if not screen else "full_tied_only"
        else:
            kind = "concordant" if screen == full else "inverted"
        counts[kind] += 1
        if kind == "inverted" and len(examples) < 10:
            examples.append({"candidates": [left["candidate"], right["candidate"]],
                             "screen_preference": left["candidate"] if screen < 0 else right["candidate"],
                             "full_preference": left["candidate"] if full < 0 else right["candidate"]})
    decisive = counts["concordant"] + counts["inverted"]
    return {
        "reference_count": len(rows), "nominal_keep_count": keep, "actual_keep_count": len(retained),
        "screen_cutoff_score": cutoff, "screen_order": [row["candidate"] for row in screen_order],
        "full_order": [row["candidate"] for row in full_order], "screen_survivors": retained,
        "full_best_candidates": full_best, "full_best_retained": [name for name in full_best if name in retained],
        "full_best_missed": [name for name in full_best if name not in retained],
        "at_least_one_full_best_retained": any(name in retained for name in full_best),
        "pair_counts": counts, "decisive_pairs": decisive,
        "decisive_pair_agreement": counts["concordant"] / decisive if decisive else None,
        "inversion_examples": examples, "reference_scores": sorted(rows, key=lambda row: row["candidate"]),
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    path = args.scores.expanduser().resolve(strict=True)
    raw = path.read_bytes()
    report = analyze_rows(read_scores(raw), args.keep_count, args.screen_direction, args.full_direction,
                          args.screen_tie_epsilon, args.full_tie_epsilon)
    if path.read_bytes() != raw:
        raise ScreeningFailure("Reference score bytes changed during analysis")
    return {
        "schema_version": 1, "status": "analyzed", "selection_scope": "development_screen_calibration_only",
        "input": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()},
        "analyzer_hash": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        "configuration": {"screen_direction": args.screen_direction, "full_direction": args.full_direction,
                          "screen_tie_epsilon": args.screen_tie_epsilon, "full_tie_epsilon": args.full_tie_epsilon,
                          "keep_count": args.keep_count, "cutoff_policy": "retain_cutoff_ties"},
        **report,
        "note": "Descriptive evidence on supplied valid references; no guarantee for future candidates. "
                "The adapter must verify candidate pairing, score provenance, stage, and hard rules. "
                "No candidate promotion, budget expansion, or confirmation selection.",
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", required=True, type=pathlib.Path)
    parser.add_argument("--screen-direction", required=True, choices=["minimize", "maximize"])
    parser.add_argument("--full-direction", required=True, choices=["minimize", "maximize"])
    parser.add_argument("--keep-count", required=True, type=int, help="planned survivor count; cutoff ties also survive")
    parser.add_argument("--screen-tie-epsilon", type=float, default=0)
    parser.add_argument("--full-tie-epsilon", type=float, default=0)
    parser.add_argument("--output", required=True, type=pathlib.Path, help="new report; never overwritten")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        report = analyze(args)
        with args.output.expanduser().resolve().open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    except (OSError, ScreeningFailure, ValueError, OverflowError) as exc:
        print(json.dumps({"schema_version": 1, "status": "failed", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
