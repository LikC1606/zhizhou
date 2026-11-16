"""Read and verify candidate result and snapshot bytes within one operation.

File digests may be reused only in an explicit EvidenceReads view. Directories
are enumerated afresh; every use checks the current file identity. No archive,
measurement plan or learning module is imported.
"""

from __future__ import annotations

import pathlib
import time
from typing import Any

import implementation_reviews
from candidate_evidence import ArchiveFailure, canonical, implementation_identity, load_json, sha256


class ArtifactResolver:
    """Resolve only explicitly exported paths from a verified evidence bundle.

    Original archive/seal strings remain unchanged. A manifest is a content and
    location contract, not an assertion that its evidence is scientifically valid.
    Unmapped references fail instead of searching the host or silently falling
    back to an original file that happens to exist.
    """

    def __init__(self, manifest_path: pathlib.Path) -> None:
        manifest_path = manifest_path.expanduser().resolve(strict=True)
        if manifest_path.is_dir():
            manifest_path = manifest_path / "manifest.json"
        self.root = manifest_path.parent
        manifest = load_json(manifest_path.read_bytes(), str(manifest_path))
        if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
                or manifest.get("schema_version") != 1
                or manifest.get("kind") != "competition_evidence_bundle"
                or not isinstance(manifest.get("archive"), dict)
                or not isinstance(manifest.get("artifacts"), list)):
            raise ArchiveFailure("invalid_bundle", "Expected a schema-1 evidence bundle manifest")
        self._entries: list[tuple[pathlib.Path, pathlib.Path, str]] = []
        self.artifacts: list[dict[str, str]] = []
        seen: set[pathlib.Path] = set()
        for position, entry in enumerate([manifest["archive"], *manifest["artifacts"]]):
            if not isinstance(entry, dict):
                raise ArchiveFailure("invalid_bundle", "Bundle entries must be objects")
            original, stored, digest, kind = (entry.get(key) for key in
                                               ("original_path", "stored_path", "sha256", "kind"))
            if (not isinstance(original, str) or not pathlib.Path(original).is_absolute()
                    or ".." in pathlib.Path(original).parts or not isinstance(digest, str)
                    or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or kind not in ("file", "directory") or position == 0 and kind != "file"):
                raise ArchiveFailure("invalid_bundle", "Malformed bundle identity or artifact kind")
            source = pathlib.Path(original)
            if source in seen:
                raise ArchiveFailure("invalid_bundle", "Bundle contains duplicate original paths")
            target = self._stored_path(stored)
            if (target.is_file() if kind == "file" else target.is_dir()) is not True:
                raise ArchiveFailure("invalid_bundle", "Bundle artifact kind differs from its manifest")
            if kind == "directory" and any(not member.resolve(strict=True).is_relative_to(target)
                                            for member in target.rglob("*") if member.is_file()):
                raise ArchiveFailure("invalid_bundle", "Bundle member leaves its exported directory")
            if hash_path(target) != digest:
                raise ArchiveFailure("bundle_artifact_changed", f"Bundle bytes differ from the manifest: {original}")
            seen.add(source)
            self._entries.append((source, target, kind))
            self.artifacts.append(dict(entry))
            if position == 0:
                self.archive_original_path = source
                self.archive_path = target
                self.archive_sha256 = digest
        self._entries.sort(key=lambda entry: len(entry[0].parts), reverse=True)

    def _stored_path(self, value: Any) -> pathlib.Path:
        if (not isinstance(value, str) or not value or pathlib.Path(value).is_absolute()
                or ".." in pathlib.Path(value).parts):
            raise ArchiveFailure("invalid_bundle", "Bundle locations must be relative paths inside the bundle")
        path = (self.root / value).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ArchiveFailure("invalid_bundle", "Bundle location leaves its root")
        return path

    def resolve_path(self, path: pathlib.Path) -> pathlib.Path:
        path = path.expanduser()
        if not path.is_absolute() or ".." in path.parts:
            raise ArchiveFailure("unmapped_artifact", f"Bundle requires an explicitly mapped absolute path: {path}")
        for original, target, kind in self._entries:
            if path == original:
                resolved = target.resolve(strict=True)
                if not resolved.is_relative_to(self.root):
                    raise ArchiveFailure("invalid_bundle", "Mapped artifact leaves its bundle")
                return resolved
            if kind == "directory" and path.is_relative_to(original):
                mapped = (target / path.relative_to(original)).resolve(strict=True)
                if not mapped.is_relative_to(target):
                    raise ArchiveFailure("invalid_bundle", "Mapped artifact leaves its exported directory")
                return mapped
        # Directory verification enumerates physical members after resolving the
        # declared root. These paths must still belong to an exported artifact.
        for _, target, kind in self._entries:
            if path == target or kind == "directory" and path.is_relative_to(target):
                resolved = path.resolve(strict=True)
                if resolved == target or kind == "directory" and resolved.is_relative_to(target):
                    return resolved
        raise ArchiveFailure("unmapped_artifact", f"Artifact was not explicitly exported: {path}")


class EvidenceReads:
    """Reuse file digests within one evidence view, never across requests.

    Recheck file identity on every use. Directories are deliberately not cached:
    their inventories and each member's current identity must still be visited.
    Only digests are retained, not model/data/result bytes.
    """

    def __init__(self, resolver: ArtifactResolver | None = None) -> None:
        self._resolver = resolver
        self._files: dict[pathlib.Path, tuple[tuple[int, ...], str]] = {}
        # Same-size writes can share a filesystem timestamp tick. Recent files
        # are always reread; archived snapshots older than this view can reuse
        # digests after their full identity is checked again. No waiting.
        self._stable_before_ns = time.time_ns() - 1_000_000_000

    def resolve_path(self, path: pathlib.Path) -> pathlib.Path:
        return (self._resolver.resolve_path(path) if self._resolver is not None else
                path.expanduser().resolve(strict=True))

    def archive_name(self, path: pathlib.Path) -> str:
        """Keep a bundle's original archive identity independent of host paths."""
        if self._resolver is None:
            return str(path.expanduser().resolve())
        if path.expanduser() not in (self._resolver.archive_original_path, self._resolver.archive_path):
            raise ArchiveFailure("invalid_bundle", "Query archive differs from the explicit bundle archive")
        return str(self._resolver.archive_original_path)

    @staticmethod
    def _identity(path: pathlib.Path) -> tuple[int, ...]:
        info = path.stat()
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)

    def digest(self, path: pathlib.Path) -> str:
        path = self.resolve_path(path)
        identity = self._identity(path)
        previous = self._files.get(path)
        if (previous is not None and previous[0] == identity
                and max(identity[-2:]) < self._stable_before_ns):
            return previous[1]
        return self._read(path, identity)[1]

    def _read(self, path: pathlib.Path, identity: tuple[int, ...]) -> tuple[bytes, str]:
        raw = path.read_bytes()
        digest = sha256(raw)
        if self._identity(path) == identity:
            self._files[path] = (identity, digest)
        return raw, digest

    def read_bytes(self, path: pathlib.Path) -> bytes:
        """Read required contents and share their digest with later checks."""
        path = self.resolve_path(path)
        return self._read(path, self._identity(path))[0]


def hash_path(path: pathlib.Path, *, reads: EvidenceReads | None = None) -> str:
    """Hash a file or a deterministic directory listing."""
    path = reads.resolve_path(path) if reads is not None else path.expanduser().resolve(strict=True)
    if path.is_file():
        return reads.digest(path) if reads is not None else sha256(path.read_bytes())
    if not path.is_dir():
        raise ArchiveFailure("invalid_artifact", f"Artifact is neither a file nor directory: {path}")
    members: list[dict[str, str]] = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            relative = item.relative_to(path).as_posix()
            members.append({"path": relative, "sha256": reads.digest(item) if reads is not None else sha256(item.read_bytes())})
    return sha256(canonical({"kind": "directory", "members": members}))


def verify_result(entry: dict[str, Any], *, reads: EvidenceReads | None = None) -> None:
    result = entry["result"]
    if result.get("result_path"):
        path = pathlib.Path(result["result_path"])
        digest = reads.digest(path) if reads is not None else sha256(path.read_bytes())
        if digest != result["result_sha256"]:
            raise ArchiveFailure("result_changed", f"Result bytes changed for {entry['candidate_id']}")


def verify_artifacts(entry: dict[str, Any], *, reads: EvidenceReads | None = None) -> list[pathlib.Path]:
    roots = []
    for key, name in entry["artifact_paths"].items():
        original = pathlib.Path(name)
        path = reads.resolve_path(original) if reads is not None else original.resolve(strict=True)
        if hash_path(path, reads=reads) != entry["artifacts"][key]:
            raise ArchiveFailure("parent_artifact_changed", f"Archived artifact changed for {entry['candidate_id']}: {key}")
        roots.append(path)
    if "implementation_review" in entry:
        try:
            implementation_reviews.verify(entry["implementation_review"], entry, implementation_identity(entry),
                                          lambda path: hash_path(path, reads=reads),
                                          resolve_path=reads.resolve_path if reads is not None else None)
        except implementation_reviews.ReviewFailure as exc:
            raise ArchiveFailure("invalid_implementation_review", str(exc)) from exc
    return roots


def verify_proposal_targets(proposal: dict[str, Any], checked: set[tuple[str, str]], *,
                             reads: EvidenceReads | None = None) -> None:
    for target in proposal["code_targets"]:
        identity = (target["path"], target["sha256"])
        if identity not in checked:
            if hash_path(pathlib.Path(target["path"]), reads=reads) != target["sha256"]:
                raise ArchiveFailure("parent_artifact_changed", f"Pending code target changed: {target['path']}")
            checked.add(identity)
