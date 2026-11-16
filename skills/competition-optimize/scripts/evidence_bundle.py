#!/usr/bin/env python3
"""Export explicitly selected evidence without rewriting archived identities."""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any

from candidate_evidence import ArchiveFailure, canonical, sha256
from evidence_files import ArtifactResolver, hash_path


def export_bundle(archive: pathlib.Path, output: pathlib.Path,
                  artifacts: list[pathlib.Path]) -> dict[str, Any]:
    """Copy raw archive bytes and named artifact roots into a new directory.

    No references are followed from the archive and no missing paths are guessed.
    Directory copies use the same file inventory as the existing directory hash.
    A failed export removes only this operation's newly created output directory.
    """
    archive = archive.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    paths = list(dict.fromkeys(path.expanduser().resolve(strict=True) for path in artifacts))
    if not archive.is_file():
        raise ArchiveFailure("invalid_archive", "Bundle archive must be a regular file")
    if output.exists():
        raise ArchiveFailure("output_exists", f"Refusing to overwrite evidence bundle: {output}")
    for path in paths:
        if not path.is_file() and not path.is_dir():
            raise ArchiveFailure("invalid_artifact", f"Artifact is neither a file nor directory: {path}")
        if path.is_dir() and output.is_relative_to(path):
            raise ArchiveFailure("invalid_bundle", "Bundle output cannot be inside an exported artifact directory")
    raw = archive.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    try:
        (output / "archive.jsonl").write_bytes(raw)
        manifest: dict[str, Any] = {
            "schema_version": 1, "kind": "competition_evidence_bundle",
            "archive": {"original_path": str(archive), "stored_path": "archive.jsonl",
                        "kind": "file", "sha256": sha256(raw)}, "artifacts": []}
        for index, path in enumerate(path for path in paths if path != archive):
            expected = hash_path(path)
            relative = pathlib.Path("artifacts") / f"{index:04d}"
            target = output / relative
            kind = "file" if path.is_file() else "directory"
            if kind == "file":
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            else:
                target.mkdir(parents=True)
                for member in sorted(path.rglob("*")):
                    if member.is_file():
                        destination = target / member.relative_to(path)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(member, destination)
            if hash_path(target) != expected or hash_path(path) != expected:
                raise ArchiveFailure("artifact_changed", f"Artifact changed while exporting: {path}")
            manifest["artifacts"].append({"original_path": str(path), "stored_path": relative.as_posix(),
                                          "kind": kind, "sha256": expected})
        (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return verify_bundle(output)
    except BaseException:
        shutil.rmtree(output)
        raise


def verify_bundle(bundle: pathlib.Path) -> dict[str, Any]:
    resolver = ArtifactResolver(bundle)
    return {"schema_version": 1, "status": "verified", "manifest": str(resolver.root / "manifest.json"),
            "archive": {"original_path": str(resolver.archive_original_path),
                        "resolved_path": str(resolver.archive_path), "sha256": resolver.archive_sha256},
            "artifacts": [{"original_path": row["original_path"],
                           "resolved_path": str(resolver.resolve_path(pathlib.Path(row["original_path"]))),
                           "kind": row["kind"], "sha256": row["sha256"]} for row in resolver.artifacts[1:]],
            "scope": "Explicitly exported bytes and path mapping only; archive semantics, unexported references and scientific conclusions are not certified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="copy an archive and explicitly named artifact roots")
    export.add_argument("--archive", type=pathlib.Path, required=True)
    export.add_argument("--output", type=pathlib.Path, required=True)
    export.add_argument("--artifact", type=pathlib.Path, action="append", default=[])
    verify = commands.add_parser("verify", help="verify a bundle and report its explicit path mapping")
    verify.add_argument("--bundle", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        result = (export_bundle(args.archive, args.output, args.artifact) if args.command == "export"
                  else verify_bundle(args.bundle))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ArchiveFailure, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": {"type": getattr(error, "kind", "bundle_io_error"),
                                                         "message": str(error)}}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
