"""Local JSON storage for skills."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Skill

DEFAULT_SKILLS_DIR = Path("~/.ai_radar/skills").expanduser()


def resolve_skills_dir(path: str | os.PathLike | None = None) -> Path:
    """Resolve and create the configured skills directory."""
    chosen = path or os.getenv("AI_RADAR_SKILLS_DIR") or DEFAULT_SKILLS_DIR
    resolved = Path(chosen).expanduser()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


class SkillStorage:
    """Persist skills as one JSON file per skill."""

    def __init__(self, base_dir: str | os.PathLike | None = None) -> None:
        self.base_dir = resolve_skills_dir(base_dir)

    def path_for(self, skill_id: str) -> Path:
        """Return the file path for a skill id."""
        return self.base_dir / f"{skill_id}.json"

    def save(self, skill: Skill) -> Path:
        """Write one skill to disk."""
        path = self.path_for(skill.skill_id)
        path.write_text(
            json.dumps(skill.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, skill_id: str) -> Skill:
        """Read one skill from disk."""
        path = self.path_for(skill_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Skill.from_dict(payload)

    def load_all(self) -> list[Skill]:
        """Load all skills from disk in stable path order."""
        skills: list[Skill] = []
        for path in sorted(self.base_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            skills.append(Skill.from_dict(payload))
        return skills
