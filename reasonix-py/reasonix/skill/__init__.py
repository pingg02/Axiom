"""Progressive-disclosure skill discovery for Axiom agents."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: str
    scope: str


def discover_skills(workspace: str | Path) -> list[SkillInfo]:
    """Discover project and user SKILL.md files without loading their bodies."""
    project = Path(workspace).resolve()
    roots: list[tuple[Path, str]] = [
        (project / ".axiom" / "skills", "project"),
        (project / ".reasonix" / "skills", "project"),
        (project / ".agents" / "skills", "project"),
        (project / ".codex" / "skills", "project"),
    ]
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", "~/.config")).expanduser()
        roots.append((appdata / "axiom-desktop" / "skills", "user"))
    roots.extend(
        [
            (Path.home() / ".agents" / "skills", "user"),
            (Path.home() / ".codex" / "skills", "user"),
        ]
    )

    discovered: dict[str, SkillInfo] = {}
    for root, scope in roots:
        if not root.is_dir():
            continue
        candidates = [root / "SKILL.md"]
        candidates.extend(path / "SKILL.md" for path in root.iterdir() if path.is_dir())
        for path in candidates:
            if not path.is_file():
                continue
            info = _read_skill_info(path, scope)
            key = info.name.casefold()
            if key not in discovered:
                discovered[key] = info
    return sorted(discovered.values(), key=lambda item: item.name.casefold())


def format_skill_catalog(skills: list[SkillInfo]) -> str:
    if not skills:
        return ""
    lines = [
        "## Skills",
        "",
        "Skills are progressive instructions. When a request matches a skill, "
        "read its SKILL.md with the read_file tool before acting; do not load "
        "unrelated skills.",
        "",
    ]
    lines.extend(
        f"- {skill.name}: {skill.description or 'No description'} "
        f"(SKILL.md: {skill.path})"
        for skill in skills
    )
    return "\n".join(lines)


def _read_skill_info(path: Path, scope: str) -> SkillInfo:
    text = path.read_text(encoding="utf-8", errors="replace")[:32768]
    metadata: dict[str, str] = {}
    if text.startswith("---"):
        frontmatter, separator, remainder = text[3:].partition("---")
        if separator:
            for raw_line in frontmatter.splitlines():
                key, marker, value = raw_line.partition(":")
                if marker and key.strip() in {"name", "description"}:
                    metadata[key.strip()] = value.strip().strip("'\"")
            text = remainder
    name = str(metadata.get("name", "")).strip() or path.parent.name
    description = str(metadata.get("description", "")).strip()
    if not description:
        description = _first_description_line(text)
    return SkillInfo(
        name=name,
        description=description,
        path=str(path.resolve()),
        scope=scope,
    )


def _first_description_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            return line[:240]
    return ""


__all__ = ["SkillInfo", "discover_skills", "format_skill_catalog"]
