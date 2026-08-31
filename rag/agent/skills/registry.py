"""
Skill Registry

Dynamic registry for skills. The Harness uses this to build
LangGraph nodes and look up skills at runtime.

Supports:
- Explicit register() / unregister()
- auto_discover() to scan skill directories
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from agent.skills.base import BaseSkill
from utils.log_utils import log

__all__ = ["SkillRegistry"]

_SKILLS_DIR = Path(__file__).parent


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> SkillRegistry:
        self._skills[skill.name] = skill
        log.info(f"Skill registered: {skill.name}")
        return self

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> BaseSkill | None:
        return self._skills.get(name)

    def require(self, name: str) -> BaseSkill:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"Skill '{name}' not registered")
        return skill

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())

    def get_all(self) -> dict[str, BaseSkill]:
        return dict(self._skills)

    def health_check(self) -> dict[str, Any]:
        return {name: skill.health_check() for name, skill in self._skills.items()}

    def auto_discover(self, **skill_kwargs) -> SkillRegistry:
        """
        Scan agent/skills/ subdirectories for skill.py modules
        and register any BaseSkill instances they export.

        Each skill directory should contain:
            skill.py   -- must expose a skill class (BaseSkill subclass)
            config.yaml -- optional configuration overrides

        Args:
            **skill_kwargs: Extra keyword args passed to skill constructors
                           (e.g. llm=...)

        Returns:
            self for chaining
        """
        for child in sorted(_SKILLS_DIR.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(("_", ".")):
                continue
            skill_file = child / "skill.py"
            if not skill_file.exists():
                continue

            module_name = f"agent.skills.{child.name}.skill"
            try:
                mod = importlib.import_module(module_name)
            except Exception as e:
                log.warning(f"auto_discover: failed to import {module_name}: {e}")
                continue

            # Find BaseSkill subclass in the module
            skill_cls = None
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                    and attr.__module__ == module_name
                ):
                    skill_cls = attr
                    break

            if skill_cls is None:
                log.debug(f"auto_discover: no BaseSkill found in {module_name}")
                continue

            try:
                instance = skill_cls(**skill_kwargs)
                self.register(instance)
            except Exception as e:
                log.warning(f"auto_discover: failed to instantiate {skill_cls.__name__}: {e}")

        return self
