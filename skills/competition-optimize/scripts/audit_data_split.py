#!/usr/bin/env python3
"""Check declared partition IDs and optional group/time boundaries before fitting."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import combinations
from typing import Any


class SplitFailure(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate partition: {key}")
        result[key] = value
    return result


def read_splits(raw: bytes) -> dict[str, set[str]]:
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
        if not isinstance(value, dict) or not 2 <= len(value) <= 64:
            raise ValueError("Expected an object with 2-64 disjoint partitions")
        result = {}
        for name, ids in value.items():
            if not name.strip() or not isinstance(ids, list) or not ids:
                raise ValueError("Partition names and ID lists must be non-empty")
            if any(not isinstance(item, str) or not item.strip() for item in ids):
                raise ValueError(f"{name}: IDs must be non-empty strings")
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name}: duplicate IDs")
            result[name] = set(ids)
        return result
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SplitFailure("invalid_splits", str(exc)) from exc


def read_metadata(raw: bytes, columns: list[str], id_column: str) -> dict[str, dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = reader.fieldnames
        if (not header or any(not name.strip() for name in header)
                or len(set(header)) != len(header) or not set(columns) <= set(header)):
            raise ValueError("Metadata needs unique named columns, including all requested columns")
        rows = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed metadata row")
            if any(not row[column].strip() for column in columns):
                raise ValueError("Requested metadata values must be non-empty")
            sample_id = row[id_column]
            if sample_id in rows:
                raise ValueError(f"Duplicate metadata ID: {sample_id}")
            rows[sample_id] = row
        if not rows:
            raise ValueError("Metadata has no rows")
        return rows
    except (UnicodeError, ValueError, csv.Error) as exc:
        raise SplitFailure("invalid_metadata", str(exc)) from exc


def number(value: str) -> Fraction:
    try:
        parsed = Decimal(value)
        # Keep exact comparisons while bounding pathological exponents/coefficients.
        if not parsed.is_finite() or len(value) > 128 or abs(parsed.as_tuple().exponent) > 1000:
            raise ValueError("Expected a finite decimal of at most 128 characters and exponent +/-1000")
        return Fraction(parsed)
    except (ValueError, InvalidOperation) as exc:
        raise SplitFailure("invalid_number", str(exc)) from exc


def timestamp(value: str, time_format: str) -> Fraction:
    if time_format == "number":
        return number(value)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
                            r"(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("Use YYYY-MM-DDTHH:MM:SS[.ffffff] with Z or +/-HH:MM timezone")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("ISO-8601 timestamps must include a timezone")
        delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return Fraction((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds, 1000000)
    except (ValueError, OverflowError) as exc:
        raise SplitFailure("invalid_time", str(exc)) from exc


def audit(args: argparse.Namespace) -> dict[str, Any]:
    groups = args.group_column or []
    if not args.id_column.strip() or any(not column.strip() for column in groups):
        raise SplitFailure("invalid_config", "Column names must be non-empty")
    if len(set(groups)) != len(groups):
        raise SplitFailure("invalid_config", "Group columns must be distinct")
    gap = number(args.minimum_time_gap)
    if gap < 0:
        raise SplitFailure("invalid_config", "Minimum time gap must be non-negative")
    time_options = args.time_order or args.time_format or args.available_time_column or gap
    if time_options and not args.time_column:
        raise SplitFailure("invalid_config", "Time options require --time-column")
    if args.time_column and (not args.time_column.strip() or not args.time_order or not args.time_format):
        raise SplitFailure("invalid_config", "Time checks require --time-order and --time-format")
    if args.available_time_column is not None and not args.available_time_column.strip():
        raise SplitFailure("invalid_config", "Available-time column must be non-empty")
    if (groups or args.time_column) and args.metadata is None:
        raise SplitFailure("invalid_config", "Group/time checks require --metadata")

    split_path = args.splits.expanduser().resolve(strict=True)
    split_raw = split_path.read_bytes()
    splits = read_splits(split_raw)
    if args.time_column and (len(args.time_order) != len(splits) or set(args.time_order) != set(splits)):
        raise SplitFailure("invalid_config", "Time order must name every partition exactly once")
    ids = set().union(*splits.values())
    checks = []
    for left, right in combinations(splits, 2):
        common = splits[left] & splits[right]
        checks.append({"kind": "id_disjointness", "partitions": [left, right],
                       "passed": not common, "overlap_count": len(common), "examples": sorted(common)[:5]})

    sources = {"splits": {"path": str(split_path), "sha256": digest(split_raw)}}
    metadata_path, metadata_raw = None, None
    if args.metadata is not None:
        metadata_path = args.metadata.expanduser().resolve(strict=True)
        if metadata_path == split_path:
            raise SplitFailure("invalid_config", "Splits and metadata must be separate files")
        metadata_raw = metadata_path.read_bytes()
        columns = [args.id_column, *groups]
        if args.time_column:
            columns.append(args.time_column)
        if args.available_time_column:
            columns.append(args.available_time_column)
        rows = read_metadata(metadata_raw, columns, args.id_column)
        sources["metadata"] = {"path": str(metadata_path), "sha256": digest(metadata_raw)}
        missing, extra = ids - rows.keys(), rows.keys() - ids
        checks.append({"kind": "metadata_coverage", "passed": not missing and not extra,
                       "missing_count": len(missing), "extra_count": len(extra),
                       "missing_examples": sorted(missing)[:5], "extra_examples": sorted(extra)[:5]})
        if not missing:
            for column in groups:
                units = {name: {rows[key][column] for key in keys} for name, keys in splits.items()}
                for left, right in combinations(splits, 2):
                    common = units[left] & units[right]
                    checks.append({"kind": "group_disjointness", "column": column,
                                   "partitions": [left, right], "passed": not common,
                                   "overlap_count": len(common), "examples": sorted(common)[:5]})
            if args.time_column:
                times = {key: timestamp(rows[key][args.time_column], args.time_format) for key in ids}
                available = ({key: timestamp(rows[key][args.available_time_column], args.time_format)
                              for key in ids} if args.available_time_column else times)
                for left, right in zip(args.time_order, args.time_order[1:]):
                    latest_event = max(times[key] for key in splits[left])
                    latest_label = max(available[key] for key in splits[left])
                    earliest = min(times[key] for key in splits[right])
                    latest = max(latest_event, latest_label)
                    checks.append({"kind": "forward_time_boundary", "partitions": [left, right],
                                   "passed": earliest > latest and earliest - latest >= gap,
                                   "latest_event_time": str(latest_event),
                                   "latest_available_time": str(latest_label),
                                   "earliest_next_time": str(earliest),
                                   "gap": str(earliest - latest)})

    if split_path.read_bytes() != split_raw or (metadata_path is not None
                                              and metadata_path.read_bytes() != metadata_raw):
        raise SplitFailure("source_changed", "Split/metadata bytes changed during the audit")
    return {
        "schema_version": 1, "status": "passed" if all(check["passed"] for check in checks) else "rejected",
        "validity_scope": "declared_partition_metadata_only", "sources": sources,
        "checker_hash": digest(pathlib.Path(__file__).read_bytes()),
        "python_version": sys.version,
        "configuration": {"id_column": args.id_column, "group_columns": groups,
                          "time_column": args.time_column, "available_time_column": args.available_time_column,
                          "time_format": args.time_format, "time_order": args.time_order,
                          "minimum_time_gap": str(gap),
                          "time_unit": ("seconds" if args.time_format == "iso8601" else
                                        "metadata_units" if args.time_column else None)},
        "partition_counts": {name: len(keys) for name, keys in splits.items()},
        "unique_ids": len(ids), "checks": checks,
        "unchecked": ["actual_fitting_rows", "learned_preprocessing", "loader_or_cached_feature_leakage",
                      "statistical_independence", "prior_holdout_exposure", "competition_rules", "resource_limits"],
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", required=True, type=pathlib.Path, help="JSON object: partition -> exact string IDs")
    parser.add_argument("--metadata", type=pathlib.Path, help="CSV covering exactly the audited IDs")
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--group-column", action="append", help="Repeat for multiple required group boundaries")
    parser.add_argument("--time-column", help="Prediction/event timestamp")
    parser.add_argument("--available-time-column", help="Optional timestamp when each label becomes available")
    parser.add_argument("--time-format", choices=["number", "iso8601"])
    parser.add_argument("--time-order", nargs="+", help="Earlier to later; names every partition once")
    parser.add_argument("--minimum-time-gap", default="0", help="Non-negative decimal: metadata units or ISO seconds")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="New receipt file; never overwritten")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        report = audit(args)
        output = args.output.expanduser().resolve()
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    except (OSError, SplitFailure, ValueError) as exc:
        error = {"schema_version": 1, "status": "error", "validity_scope": "declared_partition_metadata_only",
                 "error": {"type": exc.kind if isinstance(exc, SplitFailure) else "invalid_input", "message": str(exc)}}
        print(json.dumps(error, ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
