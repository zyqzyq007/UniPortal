"""
Skill Configuration Loader

Loads config.yaml from a skill directory and merges values onto
a Python dataclass. Falls back to dataclass defaults if YAML
is absent or malformed.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

from utils.log_utils import log

__all__ = ["load_skill_config"]

T = TypeVar("T")


def load_skill_config(skill_dir: str | Path, config_cls: type[T]) -> T:
    """
    Load skill configuration from config.yaml, merging onto dataclass defaults.

    Args:
        skill_dir: Path to the skill directory (containing config.yaml)
        config_cls: The dataclass type to instantiate

    Returns:
        A populated config_cls instance
    """
    yaml_path = Path(skill_dir) / "config.yaml"
    if not yaml_path.exists():
        return config_cls()

    try:
        import yaml
    except ImportError:
        log.debug("PyYAML not installed, using dataclass defaults")
        return config_cls()

    try:
        with open(yaml_path, encoding="utf-8") as f:
            overrides: dict[str, Any] = yaml.safe_load(f) or {}

        defaults = asdict(config_cls())
        for key in overrides:
            if key in defaults:
                defaults[key] = overrides[key]

        return config_cls(**defaults)

    except Exception as e:
        log.warning(f"Failed to load {yaml_path}: {e}, using defaults")
        return config_cls()
