"""Behavior checks for portable installs, conflict handling, and memory capture.

Every command runs against a disposable repository and an explicit target home
or project. These tests never install into the current user's configuration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- lzh-memory:begin -->"
END = "<!-- lzh-memory:end -->"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def snapshot(root: Path) -> dict[str, bytes | str]:
    """Compare contents, including links, without depending on timestamps."""
    if not root.exists():
        return {}
    result: dict[str, bytes | str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            result[str(path.relative_to(root))] = os.readlink(path)
        elif path.is_file():
            result[str(path.relative_to(root))] = path.read_bytes()
    return result


class MemoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="lzh-memory-tests-")
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.repo = self.base / "memory repository"
        self.home = self.base / "target home"
        self.project = self.base / "target project"
        self.repo.mkdir()
        (self.repo / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/memory.py", self.repo / "scripts/memory.py")
        write(
            self.repo / "memory/working-agreements.md",
            "# Working agreements\n\nKeep user changes intact.\n",
        )
        write(
            self.repo / "memory/maintenance.md",
            "# Memory maintenance\n\nRead memory/INDEX.md for relevant records.\n",
        )
        write(self.repo / "memory/INDEX.md", "# Memory index\n\nRead notes on demand.\n")
        write(
            self.repo / "memory/projects/theorem-os.md",
            "# TheoremOS boundary\n\nPreserve ongoing solver runs.\n",
        )
        (self.repo / "memory/notes").mkdir()
        write(
            self.repo / "skills/demo/SKILL.md",
            "---\nname: demo\ndescription: A disposable example skill.\n---\n\n"
            "Read references/method.md when relevant.\n",
        )
        write(self.repo / "skills/demo/references/method.md", "Original method.\n")
        write(self.repo / "sources/skill-imports.json", '{"version": 1, "skills": {}}\n')

    def cli(self, *args: str, repo: Path | None = None) -> subprocess.CompletedProcess[str]:
        fixture = repo or self.repo
        return subprocess.run(
            [sys.executable, str(fixture / "scripts/memory.py"), *map(str, args)],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=30,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def install_home(self, *extra: str, tools: str = "all") -> subprocess.CompletedProcess[str]:
        return self.cli("install", "--home", str(self.home), "--tools", tools, *extra)

    def test_preview_does_not_create_home_or_change_repository(self) -> None:
        before = snapshot(self.repo)
        self.assert_success(self.install_home())
        self.assertFalse(self.home.exists(), "An install preview must not create target directories")
        self.assertEqual(snapshot(self.repo), before)

    def test_install_preserves_existing_rules_and_repeated_install_is_stable(self) -> None:
        rules = self.home / ".codex/AGENTS.md"
        unmanaged = "# Existing preferences\n\nUse my existing formatter.\n"
        write(rules, unmanaged)
        self.assert_success(self.install_home("--apply"))
        installed = rules.read_text()
        self.assertTrue(installed.startswith(unmanaged))
        self.assertEqual(installed.count(BEGIN), 1)
        self.assertEqual(installed.count(END), 1)
        self.assertIn("Keep user changes intact.", installed)
        self.assertTrue((self.home / ".agents/skills/demo/SKILL.md").is_file())
        self.assertTrue((self.home / ".claude/skills/demo/references/method.md").is_file())
        self.assertTrue((self.home / ".lzh-memory/cursor-user-rules.md").is_file())
        self.assertTrue((self.home / ".lzh-memory/install-state.json").is_file())
        first = snapshot(self.home)
        state_name = ".lzh-memory/install-state.json"
        first_state = json.loads(first.pop(state_name))
        first_state.pop("updated_at", None)
        self.assert_success(self.install_home("--apply"))
        repeated = snapshot(self.home)
        repeated_state = json.loads(repeated.pop(state_name))
        repeated_state.pop("updated_at", None)
        self.assertEqual(repeated, first)
        self.assertEqual(repeated_state, first_state)

    def test_unmanaged_skill_conflict_rejects_entire_plan(self) -> None:
        write(self.home / ".agents/skills/demo/SKILL.md", "An independently maintained skill.\n")
        write(self.home / ".codex/AGENTS.md", "My existing rules.\n")
        before = snapshot(self.home)
        for flags in [(), ("--apply",)]:
            with self.subTest(flags=flags):
                result = self.install_home(*flags)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(snapshot(self.home), before, "A conflict must prevent every planned write")
        self.assertFalse((self.home / ".claude").exists())

    def test_managed_skill_updates_without_duplicate_rules(self) -> None:
        self.assert_success(self.install_home("--apply", tools="codex"))
        write(self.repo / "skills/demo/references/method.md", "Updated method.\n")
        write(self.repo / "skills/demo/references/new.md", "New supporting evidence.\n")
        self.assert_success(self.install_home("--apply", tools="codex"))
        installed = self.home / ".agents/skills/demo"
        self.assertEqual((installed / "references/method.md").read_text(), "Updated method.\n")
        self.assertEqual((installed / "references/new.md").read_text(), "New supporting evidence.\n")
        rules = (self.home / ".codex/AGENTS.md").read_text()
        self.assertEqual(rules.count(BEGIN), 1)
        self.assertEqual(rules.count(END), 1)

    def test_local_skill_edits_are_preserved_when_source_changes(self) -> None:
        self.assert_success(self.install_home("--apply", tools="codex"))
        installed = self.home / ".agents/skills/demo/references/method.md"
        write(installed, "Locally corrected method; do not discard.\n")
        write(self.repo / "skills/demo/references/method.md", "Another upstream method.\n")
        before = snapshot(self.home)
        result = self.install_home("--apply", tools="codex")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), before)

    def test_rule_updates_preserve_external_notes_and_reject_edited_managed_section(self) -> None:
        self.assert_success(self.install_home("--apply", tools="codex"))
        rules = self.home / ".codex/AGENTS.md"
        local_note = "\n# Local instructions\n\nUse this server's formatter configuration.\n"
        write(rules, rules.read_text() + local_note)
        working = self.repo / "memory/working-agreements.md"
        write(working, working.read_text() + "\nNew agreed preference.\n")
        self.assert_success(self.install_home("--apply", tools="codex"))
        updated = rules.read_text()
        self.assertTrue(updated.endswith(local_note))
        self.assertIn("New agreed preference.", updated)

        write(rules, updated.replace("New agreed preference.", "Local conflicting preference.", 1))
        write(working, working.read_text() + "\nAnother agreed preference.\n")
        write(self.repo / "skills/demo/references/method.md", "A newer shared method.\n")
        before = snapshot(self.home)
        result = self.install_home("--apply", tools="codex")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), before)

    def test_project_cursor_rule_has_mdc_frontmatter(self) -> None:
        self.assert_success(
            self.cli("install", "--project", str(self.project), "--tools", "all", "--apply")
        )
        cursor_rule = self.project / ".cursor/rules/lzh-memory.mdc"
        content = cursor_rule.read_text()
        self.assertTrue(content.startswith("---\n"), content)
        self.assertRegex(content, r"(?m)^alwaysApply:\s*true\s*$")
        self.assertTrue((self.project / "AGENTS.md").is_file())
        self.assertTrue((self.project / "CLAUDE.md").is_file())
        self.assertTrue((self.project / "GEMINI.md").is_file())
        self.assertTrue((self.project / ".agents/skills/demo/SKILL.md").is_file())
        self.assertTrue((self.project / ".claude/skills/demo/SKILL.md").is_file())
        self.assertFalse((self.project / ".cursor/rules/lzh-memory.md").exists())

    def test_reinstall_after_repository_move_refreshes_paths(self) -> None:
        self.assert_success(self.install_home("--apply", tools="codex"))
        old_repo = self.repo
        moved = self.base / "moved memory repository"
        shutil.move(str(old_repo), moved)
        self.repo = moved
        self.assert_success(self.install_home("--apply", tools="codex"))
        rules = (self.home / ".codex/AGENTS.md").read_text()
        self.assertIn(str(moved), rules)
        self.assertNotIn(str(old_repo), rules)
        self.assertEqual(rules.count(BEGIN), 1)

    def make_import_source(self) -> tuple[Path, Path]:
        source = self.base / "incoming"
        payload = self.base / "original skill"
        write(
            payload / "SKILL.md",
            "---\nname: imported\ndescription: Imported example.\n---\n\n"
            "Read references/procedure.md.\n",
        )
        write(payload / "references/procedure.md", "A complete procedure.\n")
        write(payload / "scripts/helper.py", "print('helper')\n")
        write(payload / ".git/config", "ignored git state\n")
        write(payload / "scripts/__pycache__/helper.pyc", "ignored bytecode\n")
        write(payload / "node_modules/package/index.js", "ignored dependency\n")
        source.mkdir()
        (source / "imported").symlink_to(payload, target_is_directory=True)
        return source, payload

    def test_import_follows_source_link_and_keeps_payload_without_caches(self) -> None:
        source, payload = self.make_import_source()
        self.assert_success(self.cli("import-skills", str(source)))
        self.assertFalse((self.repo / "skills/imported").exists())
        self.assert_success(self.cli("import-skills", str(source), "--apply"))
        imported = self.repo / "skills/imported"
        self.assertFalse(imported.is_symlink(), "A portable snapshot must survive removal of the source")
        self.assertEqual((imported / "SKILL.md").read_bytes(), (payload / "SKILL.md").read_bytes())
        self.assertEqual((imported / "references/procedure.md").read_text(), "A complete procedure.\n")
        self.assertEqual((imported / "scripts/helper.py").read_text(), "print('helper')\n")
        for excluded in [".git", "scripts/__pycache__", "node_modules"]:
            self.assertFalse((imported / excluded).exists(), excluded)
        registry = json.loads((self.repo / "sources/skill-imports.json").read_text())
        self.assertIn("imported", json.dumps(registry))

    def test_import_does_not_overwrite_locally_edited_canonical_skill(self) -> None:
        source, payload = self.make_import_source()
        self.assert_success(self.cli("import-skills", str(source), "--apply"))
        canonical = self.repo / "skills/imported/references/procedure.md"
        write(canonical, "A locally reviewed correction.\n")
        write(payload / "references/procedure.md", "A changed source procedure.\n")
        before = snapshot(self.repo)
        result = self.cli("import-skills", str(source), "--apply")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.repo), before)

    def test_note_defaults_to_pending_and_is_not_promoted_to_global_instructions(self) -> None:
        marker = "UNCONFIRMED_SCIENTIFIC_ASSUMPTION_482"
        self.assert_success(
            self.cli(
                "note", "待确认的方法", "--scope", "research", "--source", "Current discussion",
                "--body", marker,
            )
        )
        notes = list((self.repo / "memory/notes").glob("*.md"))
        self.assertEqual(len(notes), 1)
        note = notes[0].read_text()
        self.assertRegex(note, r"(?m)^status:\s*[\"']?pending[\"']?\s*$")
        self.assertIn(marker, note)
        self.assertIn("Current discussion", note)
        self.assert_success(self.install_home("--apply", tools="codex"))
        self.assertNotIn(marker, (self.home / ".codex/AGENTS.md").read_text())

    def test_check_rejects_a_missing_skill_entry(self) -> None:
        self.assert_success(self.cli("check"))
        (self.repo / "skills/demo/SKILL.md").unlink()
        result = self.cli("check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_rejects_registered_missing_entry_when_another_skill_is_valid(self) -> None:
        write(
            self.repo / "skills/second/SKILL.md",
            "---\nname: second\ndescription: Another valid example skill.\n---\n\n"
            "Follow this independent procedure.\n",
        )
        write(
            self.repo / "sources/skill-imports.json",
            json.dumps({"version": 1, "skills": {"demo": {"digest": "0" * 64}}}) + "\n",
        )
        self.assert_success(self.cli("check"))
        (self.repo / "skills/demo/SKILL.md").unlink()
        result = self.cli("check")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
