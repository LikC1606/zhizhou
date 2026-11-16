"""Bind an agent's implementation-fidelity report to its executed snapshot.

Byte checks establish which code was reviewed, not semantic correctness. A
faithfulness report never changes the adapter's score or candidate validity.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Any, Callable


class ReviewFailure(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _roots(entry: dict[str, Any], identity: dict[str, Any]) -> list[pathlib.Path]:
    keys = (["configuration"] if identity["scope"] in {"training_pipeline", "execution_pipeline"}
            else list(identity["artifacts"]))
    return [pathlib.Path(entry["artifact_paths"][key]) for key in keys]


def _bound(path: pathlib.Path, roots: list[pathlib.Path]) -> bool:
    return path.is_absolute() and all(part != ".." for part in path.parts) and any(
        path == root or path.is_relative_to(root) for root in roots)


def _body(value: Any) -> None:
    if (not isinstance(value, dict) or value.get("fidelity") not in ("yes", "partial", "no", "unknown")
            or not _text(value.get("actual_mechanism"))
            or not isinstance(value.get("missing_components"), list)
            or any(not _text(item) for item in value["missing_components"])
            or not isinstance(value.get("code_evidence"), list) or not value["code_evidence"]):
        raise ReviewFailure("Review requires fidelity, actual_mechanism, missing_components and code_evidence")
    if ((value["fidelity"] == "yes" and value["missing_components"])
            or (value["fidelity"] in {"partial", "no"} and not value["missing_components"])):
        raise ReviewFailure("Partial/no fidelity requires missing components; yes requires none")


def validate(value: Any, entry: dict[str, Any], identity: dict[str, Any]) -> None:
    _body(value)
    if (entry["role"] not in {"development", "diagnostic"}
            or not entry.get("proposal_id") or value.get("proposal_id") != entry["proposal_id"]
            or value.get("assessment_kind") != "agent_report"
            or value.get("implementation_fingerprint") != identity["fingerprint"]
            or not _sha(value.get("input_sha256"))
            or not entry["result"].get("result_path")
            or not entry["result"].get("result_sha256") or not entry["result"].get("execution_status")
            or identity["scope"] in {"prediction_artifact_only", "generated_artifact_only"}
            or not set(identity["artifacts"]) <= entry["artifact_paths"].keys()):
        raise ReviewFailure("Review must bind a prospective development/diagnostic execution and its code/recipe identity")
    roots = _roots(entry, identity)
    for item in value["code_evidence"]:
        if (not isinstance(item, dict) or not _text(item.get("path"))
                or not _text(item.get("detail")) or not _sha(item.get("sha256"))
                or not _bound(pathlib.Path(item["path"]), roots)):
            raise ReviewFailure("Code evidence must bind files inside the evaluated successor's executable snapshot")


def normalize(value: Any, raw: bytes, entry: dict[str, Any], identity: dict[str, Any],
              hash_path: Callable[[pathlib.Path], str]) -> dict[str, Any]:
    _body(value)
    evidence = []
    for item in value["code_evidence"]:
        if not isinstance(item, dict) or not _text(item.get("path")) or not _text(item.get("detail")):
            raise ReviewFailure("Code evidence requires a path and detail")
        path = pathlib.Path(item["path"]).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ReviewFailure("Code evidence must name a file")
        evidence.append({"path": str(path), "sha256": hash_path(path), "detail": item["detail"]})
    review = {"assessment_kind": "agent_report", "proposal_id": entry.get("proposal_id"),
              "implementation_fingerprint": identity["fingerprint"],
              "input_sha256": hashlib.sha256(raw).hexdigest(),
              **{key: value[key] for key in ("fidelity", "actual_mechanism", "missing_components")},
              "code_evidence": evidence}
    validate(review, entry, identity)
    return review


def verify(value: dict[str, Any], entry: dict[str, Any], identity: dict[str, Any],
           hash_path: Callable[[pathlib.Path], str], *,
           resolve_path: Callable[[pathlib.Path], pathlib.Path] | None = None) -> None:
    validate(value, entry, identity)
    resolve = resolve_path if resolve_path is not None else lambda path: path.resolve(strict=True)
    roots = [resolve(root) for root in _roots(entry, identity)]
    for item in value["code_evidence"]:
        path = resolve(pathlib.Path(item["path"]))
        if not path.is_file() or not _bound(path, roots) or hash_path(path) != item["sha256"]:
            raise ReviewFailure("Reviewed code evidence changed or left the evaluated snapshot")
