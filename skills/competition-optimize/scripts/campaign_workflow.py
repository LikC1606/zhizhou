"""Freeze the actual instruction package used by future sealed turns.

Old in-flight prompts are never rewritten. A new checkpoint can adopt a new
installed version while older snapshots remain available at their original
paths. Workflow provenance is not part of a candidate's comparison identity.
"""
from __future__ import annotations

import pathlib
from typing import Any

from candidate_evidence import canonical, sha256
from campaign_runtime import CampaignError, atomic_bytes, file_hash


# A running manager retains its loaded code even if a later checkpoint adopts
# new instruction/tool files. Keep that identity separate from the new package.
MANAGER_SOURCE_SHA256 = file_hash(pathlib.Path(__file__).with_name("autonomous_campaign.py"))


def freeze_workflow(campaign: pathlib.Path, skill: pathlib.Path,
                    state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    paths = [skill / "SKILL.md", *sorted((skill / "references").rglob("*.md")),
             *sorted(path for path in (skill / "scripts").iterdir() if path.is_file())]
    contents = {str(path.relative_to(skill)): path.read_bytes() for path in paths}
    hashes = {name: sha256(raw) for name, raw in contents.items()}
    fingerprint = sha256(canonical(hashes))
    root = campaign / "workflow" / fingerprint
    protected = {}
    for name, raw in contents.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise CampaignError(f"Frozen workflow content was modified: {target}")
        else:
            atomic_bytes(target, raw)
        protected[str(target)] = hashes[name]
    manifest = root / "manifest.json"
    manifest_bytes = canonical({"schema_version": 1, "package_sha256": fingerprint, "files": hashes}) + b"\n"
    if manifest.exists():
        if manifest.read_bytes() != manifest_bytes:
            raise CampaignError("Frozen workflow manifest was modified")
    else:
        atomic_bytes(manifest, manifest_bytes)
    protected[str(manifest)] = file_hash(manifest)
    snapshot = {"schema_version": 1, "skill_root": str(root), "skill_path": str(root / "SKILL.md"),
                "manifest_path": str(manifest), "package_sha256": fingerprint}
    provenance = {"schema_version": 1, "package_sha256": fingerprint,
                  "skill_sha256": hashes["SKILL.md"], "runner_sha256": MANAGER_SOURCE_SHA256,
                  "tool_runner_sha256": hashes.get("scripts/autonomous_campaign.py"),
                  "cli_path": state["agent_bin"], "cli_version": "unknown",
                  "requested_model": state["model"] or "unknown", "resolved_model": "unknown"}
    if state["turn_number"] and not state.get("instruction_snapshot"):
        provenance["legacy_instructions"] = "Previous live instruction contents were not sealed; not reconstructed"
    return snapshot, protected, provenance
