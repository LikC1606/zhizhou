#!/usr/bin/env python3
"""Portable Markdown memory and skill installation; Python standard library only."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- lzh-memory:begin -->"
END = "<!-- lzh-memory:end -->"
EXCLUDED = {".git", "__pycache__", "node_modules", ".DS_Store"}
TOOLS = ("codex", "claude", "cursor", "gemini", "agents")
CORE = (
    "memory/working-agreements.md",
    "memory/maintenance.md",
    "memory/projects/theorem-os.md",
)


class MemoryError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".lzh-memory-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def skill_files(directory):
    """Follow source links while preventing loops; ignore only build/cache metadata."""
    def walk(current, relative, ancestors):
        real = current.resolve(strict=True)
        if real in ancestors:
            raise MemoryError(f"Skill symlink cycle: {current}")
        if current.is_dir():
            for child in sorted(current.iterdir()):
                if child.name not in EXCLUDED and not child.name.endswith((".pyc", ".pyo")):
                    yield from walk(child, relative / child.name, ancestors | {real})
        elif current.is_file():
            yield relative, current
        else:
            raise MemoryError(f"Unsupported skill entry: {current}")
    yield from walk(directory, Path(), set())


def tree_digest(directory, *, filtered=True):
    h = hashlib.sha256()
    # Installation targets must include unexpected local files in their digest.
    # Source-only cache filtering must not hide edits in an installed copy.
    if filtered:
        files = skill_files(directory)
    else:
        files = ((p.relative_to(directory), p) for p in sorted(directory.rglob("*"))
                 if p.is_file() or p.is_symlink())
    for relative, file in files:
        if not filtered and file.is_symlink():
            h.update(b"symlink\0" + relative.as_posix().encode() + b"\0"
                     + os.readlink(file).encode() + b"\0")
            continue
        h.update(relative.as_posix().encode() + b"\0")
        h.update(str(stat.S_IMODE(file.stat().st_mode) & 0o111).encode() + b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def copy_skill(source, target):
    """Stage the full payload before replacing a previously managed directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".lzh-memory-", dir=target.parent) as tmp:
        temporary = Path(tmp)
        payload = temporary / "payload"
        payload.mkdir()
        for relative, file in skill_files(source):
            dest = payload / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)
        previous = temporary / "previous"
        existed = target.exists()
        if existed:
            target.rename(previous)
        try:
            payload.rename(target)
        except BaseException:
            if existed:
                previous.rename(target)
            raise


def skills():
    directory = ROOT / "skills"
    if not directory.is_dir():
        return []
    return [p for p in sorted(directory.iterdir())
            if not p.name.startswith(".") and (p / "SKILL.md").is_file()]


def memory_body(home, machine):
    paths = {
        "projects": str(home / "workspace/projects"),
        "outputs": str(home / "workspace/outputs"),
        "downloads": str(home / "Downloads"),
        "temporary": str(home / ".cache/lzh-memory/tmp"),
    }
    if machine:
        supplied = read_json(machine, None)
        if not isinstance(supplied, dict) or set(supplied) != set(paths):
            raise MemoryError("Machine profile needs projects, outputs, downloads, temporary.")
        for key, value in supplied.items():
            if not isinstance(value, str) or not value.strip():
                raise MemoryError(f"Invalid machine path: {key}")
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                raise MemoryError(f"Machine path must be absolute: {key}")
            paths[key] = str(candidate)
    sections = [
        "# lzh-memory\n\n"
        f"个人工作知识库：`{ROOT}`。任务开始时读取 `{ROOT / 'memory/INDEX.md'}`；"
        "按任务范围读取 memory/notes/ 中 status 为 confirmed 的相关记录。"
        "pending 记录是待讨论建议，不作为用户规则。项目当前的指令和研究记录应结合阅读；"
        "projects/ 中的历史快照不自动成为当前项目的运行配置。\n\n"
        "你明确表达的长期偏好、纠正和已确认结论，应按本库 maintenance 约定继续记录。"
        "修改本库核心规则或 skills 后，用安装命令预览并更新工具副本。"
    ]
    for name in CORE:
        path = ROOT / name
        if not path.is_file():
            raise MemoryError(f"Missing core memory: {name}")
        sections.append(path.read_text(encoding="utf-8").strip())
    sections.append(
        "## 本机存储位置\n\n"
        f"- 新项目：`{paths['projects']}`。\n"
        f"- 大体积输出和实验产物：`{paths['outputs']}`。\n"
        f"- 下载：`{paths['downloads']}`。\n"
        f"- 临时文件优先使用 `$TMPDIR`；未设置时使用 `{paths['temporary']}`。\n"
        "- 已有项目继续使用原路径，不为改变存储位置重启正在运行的任务。\n"
        "- 历史 skill 若写有原服务器的临时路径，按这里的本机约定解析；迁移不改写原始快照。"
    )
    return "\n\n".join(sections) + "\n"


def managed_section(text):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise MemoryError("Unbalanced or repeated lzh-memory markers")
    if BEGIN not in text:
        return None
    start = text.index(BEGIN)
    finish = text.index(END)
    if finish < start:
        raise MemoryError("Reversed lzh-memory markers")
    return text[start:finish + len(END)]


@dataclass
class Operation:
    path: Path
    action: str
    kind: str
    digest: str = ""
    text: str = ""
    source: Path = None
    reason: str = ""


def text_operation(path, body, entries, *, cursor=False):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return Operation(path, "conflict", "instructions", reason="Existing path is not a regular file")
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    section = BEGIN + "\n" + body.rstrip() + "\n" + END
    old_section = managed_section(current)
    old = entries.get(str(path), {})
    if old_section is not None:
        if old_section != section and old.get("digest") != digest_text(old_section):
            return Operation(path, "conflict", "instructions",
                             reason="Managed section has local edits or unknown ownership")
        desired = current.replace(old_section, section, 1)
    else:
        if cursor and current:
            return Operation(path, "conflict", "instructions",
                             reason="Existing Cursor rule has no managed section")
        prefix = "---\ndescription: lzh personal working memory\nalwaysApply: true\n---\n\n" if cursor else ""
        desired = current + ("\n\n" if current and not current.endswith("\n\n") else "") + prefix + section + "\n"
    return Operation(path, "unchanged" if desired == current else "write", "instructions",
                     digest=digest_text(section), text=desired)


def skill_operation(target, source, entries):
    desired = tree_digest(source)
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        return Operation(target, "conflict", "skill", reason="Existing skill is a link or non-directory; preserve its owner")
    if not target.exists():
        return Operation(target, "copy", "skill", digest=desired, source=source)
    current = tree_digest(target, filtered=False)
    if current == desired:
        return Operation(target, "unchanged", "skill", digest=desired, source=source)
    previous = entries.get(str(target), {}).get("digest")
    if current != previous:
        return Operation(target, "conflict", "skill", reason="Skill differs from source and has no unchanged installed baseline")
    return Operation(target, "update", "skill", digest=desired, source=source)


def report_operations(operations, apply):
    counts = Counter(op.action for op in operations)
    print(("Apply" if apply else "Preview") + ": " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    for op in operations:
        if op.kind == "instructions" or op.action == "conflict":
            print(f"  {op.action}: {op.path}" + (f" — {op.reason}" if op.reason else ""))
    skill_roots = sorted({str(op.path.parent) for op in operations if op.kind == "skill"})
    for path in skill_roots:
        print(f"  skills: {path}")
    if any(op.action == "conflict" for op in operations):
        raise MemoryError("Conflicts found; no changes applied. Merge into the repository or resolve the target first.")


def apply_operations(operations):
    for op in operations:
        if op.action == "write":
            atomic_text(op.path, op.text)
        elif op.action in {"copy", "update"}:
            copy_skill(op.source, op.path)


def install(args):
    project = args.project.expanduser().absolute() if args.project else None
    home = args.home.expanduser().absolute() if args.home else Path.home()
    destination = project or home
    selected = set(args.tools) - {"all"}
    if "all" in args.tools:
        selected.update(TOOLS if project else TOOLS[:4])
    if "agents" in selected and not project:
        raise MemoryError("The generic agents adapter is project-scoped; pass --project.")
    if args.codex_home and project:
        raise MemoryError("--codex-home applies to home installation only.")
    state_file = destination / ".lzh-memory/install-state.json"
    state = read_json(state_file, {"version": 1, "entries": {}})
    if state.get("version") != 1 or not isinstance(state.get("entries"), dict):
        raise MemoryError(f"Unsupported installation state: {state_file}")
    entries = state["entries"]
    body = memory_body(home, args.machine)
    instruction_paths = {}
    skill_roots = set()
    if "codex" in selected or "agents" in selected:
        if project:
            instruction_paths[project / "AGENTS.md"] = False
        else:
            configured = args.codex_home or (Path(os.environ["CODEX_HOME"]) if not args.home and os.environ.get("CODEX_HOME") else home / ".codex")
            instruction_paths[configured.expanduser().absolute() / "AGENTS.md"] = False
        skill_roots.add(destination / ".agents/skills")
    if "claude" in selected:
        instruction_paths[destination / ("CLAUDE.md" if project else ".claude/CLAUDE.md")] = False
        skill_roots.add(destination / ".claude/skills")
    if "gemini" in selected:
        instruction_paths[destination / ("GEMINI.md" if project else ".gemini/GEMINI.md")] = False
        skill_roots.add(destination / ".agents/skills")
    if "cursor" in selected:
        path = destination / (".cursor/rules/lzh-memory.mdc" if project else ".lzh-memory/cursor-user-rules.md")
        instruction_paths[path] = bool(project)
        skill_roots.add(destination / ".agents/skills")
    operations = [text_operation(path, body, entries, cursor=cursor)
                  for path, cursor in sorted(instruction_paths.items())]
    source_skills = skills()
    for directory in sorted(skill_roots):
        for source in source_skills:
            operations.append(skill_operation(directory / source.name, source, entries))
    report_operations(operations, args.apply)
    print(f"  {len(source_skills)} canonical skills; source: {ROOT}")
    if args.apply:
        apply_operations(operations)
        for op in operations:
            entries[str(op.path)] = {"kind": op.kind, "digest": op.digest}
        state.update({"repository": str(ROOT), "updated_at": timestamp()})
        write_json(state_file, state)
        ignore = destination / ".lzh-memory/.gitignore"
        if not ignore.exists():
            atomic_text(ignore, "*\n")
        print("Installed. Start a new tool session to load updated instructions and skills.")
    else:
        print("No files changed. Add --apply to install this plan.")
    if "cursor" in selected and not project:
        print("Cursor User Rules: paste the exported Markdown into Settings → Rules → User Rules.")


def import_skills(args):
    manifest_file = ROOT / "sources/skill-imports.json"
    manifest = read_json(manifest_file, {"version": 1, "skills": {}})
    if manifest.get("version") != 1 or not isinstance(manifest.get("skills"), dict):
        raise MemoryError("Unsupported skill import manifest")
    records = manifest["skills"]
    entries = {str(ROOT / "skills" / name): {"digest": record["digest"]}
               for name, record in records.items()}
    sources = {}
    for root in args.paths:
        root = root.expanduser().absolute()
        if not root.is_dir():
            raise MemoryError(f"Skill source directory not found: {root}")
        candidates = [root] if (root / "SKILL.md").is_file() else sorted(root.iterdir())
        for source in candidates:
            if source.name.startswith(".") or not (source / "SKILL.md").is_file():
                continue
            previous = sources.get(source.name)
            if previous and tree_digest(previous) != tree_digest(source):
                raise MemoryError(f"Two different source skills share the name {source.name}")
            sources[source.name] = source
    if not sources:
        raise MemoryError("No SKILL.md directories found in the supplied paths")
    operations = [skill_operation(ROOT / "skills" / name, source, entries)
                  for name, source in sorted(sources.items())]
    report_operations(operations, args.apply)
    print(f"  Importing {len(operations)} full skill directories, following source links.")
    if args.apply:
        apply_operations(operations)
        for name, source in sources.items():
            records[name] = {"source": str(source), "resolved_source": str(source.resolve()),
                             "captured_at": timestamp(), "digest": tree_digest(source),
                             "origin": records.get(name, {}).get("origin", "unknown; retained local installation")}
        write_json(manifest_file, manifest)
    else:
        print("No files changed. Add --apply to import this plan.")


def read_note(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise MemoryError(f"Note has no metadata: {path}")
    metadata, body = text[4:].split("\n---\n", 1)
    data = {}
    for line in metadata.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise MemoryError(f"Invalid note metadata: {path}")
        value = value.strip()
        try:
            data[key] = json.loads(value)
        except json.JSONDecodeError:
            data[key] = value
    for field in ("title", "scope", "status", "source", "recorded_at"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise MemoryError(f"Note is missing {field}: {path}")
    if data["status"] not in {"confirmed", "pending", "superseded"}:
        raise MemoryError(f"Invalid note status: {path}")
    if not re.fullmatch(r"global|research|project:[\w-]+", data["scope"]):
        raise MemoryError(f"Invalid note scope: {path}")
    if not body.strip():
        raise MemoryError(f"Empty note body: {path}")
    return data, body


def note(args):
    if not re.fullmatch(r"global|research|project:[\w-]+", args.scope):
        raise MemoryError("Scope must be global, research, or project:<id>")
    if not all(value.strip() for value in (args.title, args.source, args.body)):
        raise MemoryError("Title, source and body must be nonempty")
    recorded = timestamp()
    slug = re.sub(r"[^\w-]+", "-", args.title.strip().lower()).strip("-")[:64] or "note"
    directory = ROOT / "memory/notes"
    directory.mkdir(parents=True, exist_ok=True)
    stem = recorded[:10] + "-" + slug
    path = directory / f"{stem}.md"
    index = 2
    while path.exists():
        path = directory / f"{stem}-{index}.md"
        index += 1
    data = {"title": args.title, "scope": args.scope, "status": args.status,
            "source": args.source, "recorded_at": recorded}
    content = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in data.items()) + "\n---\n\n" + args.body.strip() + "\n"
    atomic_text(path, content)
    print(f"Recorded {args.status}: {path}")


def check(args):
    for name in (*CORE, "memory/INDEX.md"):
        if not (ROOT / name).is_file():
            raise MemoryError(f"Missing core file: {name}")
    imported = read_json(ROOT / "sources/skill-imports.json", {"skills": {}})
    source_skills = skills()
    if not source_skills:
        raise MemoryError("No canonical skills")
    missing = set(imported["skills"]) - {source.name for source in source_skills}
    if missing:
        raise MemoryError("Missing imported skill entry: " + ", ".join(sorted(missing)))
    changed = []
    total_files = total_bytes = 0
    for source in source_skills:
        content = (source / "SKILL.md").read_text(encoding="utf-8")
        if not content.startswith("---\n") or not re.search(r"^name:\s*\S", content, re.M) or not re.search(r"^description:\s*\S", content, re.M):
            raise MemoryError(f"Skill needs name and description frontmatter: {source.name}")
        for _, path in skill_files(source):
            total_files += 1
            total_bytes += path.stat().st_size
        baseline = imported["skills"].get(source.name, {}).get("digest")
        if baseline and tree_digest(source) != baseline:
            changed.append(source.name)
    notes = list((ROOT / "memory/notes").glob("*.md"))
    states = Counter(read_note(path)[0]["status"] for path in notes)
    print(f"OK: {len(source_skills)} skills, {total_files} files, {total_bytes / 1024**2:.1f} MiB; {len(notes)} notes {dict(states)}")
    if changed:
        print("Canonical edits since import (retained): " + ", ".join(changed))
    print("Checked local content structure; client loading and external skill dependencies are separate.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("check", help="Check canonical memory, skills and notes")
    cmd.set_defaults(run=check)
    cmd = commands.add_parser("install", help="Preview or install tool instructions and skills")
    target = cmd.add_mutually_exclusive_group()
    target.add_argument("--home", type=Path, help="Target user home (default: current home)")
    target.add_argument("--project", type=Path, help="Target project directory")
    cmd.add_argument("--tools", nargs="+", choices=(*TOOLS, "all"), default=list(TOOLS[:4]))
    cmd.add_argument("--machine", type=Path, help="JSON machine paths; defaults are relative to target home")
    cmd.add_argument("--codex-home", type=Path, help="Override Codex configuration directory")
    cmd.add_argument("--apply", action="store_true")
    cmd.set_defaults(run=install)
    cmd = commands.add_parser("import-skills", help="Import complete local skill directories")
    cmd.add_argument("paths", type=Path, nargs="+")
    cmd.add_argument("--apply", action="store_true")
    cmd.set_defaults(run=import_skills)
    cmd = commands.add_parser("note", help="Record a sourced memory (pending unless confirmed)")
    cmd.add_argument("title")
    cmd.add_argument("--scope", required=True)
    cmd.add_argument("--source", required=True)
    cmd.add_argument("--body", required=True)
    cmd.add_argument("--status", choices=("confirmed", "pending"), default="pending")
    cmd.set_defaults(run=note)
    args = parser.parse_args()
    try:
        args.run(args)
    except (MemoryError, OSError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
