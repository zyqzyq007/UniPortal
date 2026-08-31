"""
Lifecycle Hooks

Provides before_skill, after_skill, and on_error hooks that the
orchestrator calls around each skill execution.

Hooks are callables that receive (skill_name, context, result) and
can perform logging, tracing, metrics, or state manipulation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.skills.base import SkillContext, SkillResult
from utils.log_utils import log

__all__ = [
    "LifecycleHook",
    "HookType",
    "LifecycleManager",
]


class HookType:
    """Hook type constants."""

    BEFORE_SKILL = "before_skill"
    AFTER_SKILL = "after_skill"
    ON_ERROR = "on_error"


@dataclass
class LifecycleHook:
    """
    A registered lifecycle hook.

    Attributes:
        name: Human-readable name for the hook
        hook_type: One of 'before_skill', 'after_skill', 'on_error'
        callback: Callable to invoke
        priority: Lower values run first (default 100)
    """

    name: str
    hook_type: str
    callback: Callable
    priority: int = 100


class LifecycleManager:
    """
    Manages lifecycle hooks for the agent harness.

    Supports three hook points:
    - before_skill: Called before a skill executes
    - after_skill: Called after a skill succeeds
    - on_error: Called when a skill fails

    Example:
        >>> lm = LifecycleManager()
        >>> lm.on_before_skill(logging_hook)
        >>> lm.on_after_skill(metrics_hook)
        >>> lm.on_error(error_handler)
    """

    def __init__(self):
        self._hooks: dict[str, list[LifecycleHook]] = {
            HookType.BEFORE_SKILL: [],
            HookType.AFTER_SKILL: [],
            HookType.ON_ERROR: [],
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on_before_skill(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run before a skill executes.

        Callback signature:
            (skill_name: str, context: SkillContext) -> Optional[dict]

        A hook may optionally return a dict of state increments (e.g.
        ``{"shared_state": {"relevant_memories": [...]}}``) that the
        orchestrator merges into the graph state so downstream nodes see them.
        Returning ``None`` (the default) is a no-op.
        """
        self._hooks[HookType.BEFORE_SKILL].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.BEFORE_SKILL,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.BEFORE_SKILL].sort(key=lambda h: h.priority)

    def on_after_skill(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run after a skill executes successfully.

        Callback signature:
            (skill_name: str, context: SkillContext, result: SkillResult) -> None
        """
        self._hooks[HookType.AFTER_SKILL].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.AFTER_SKILL,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.AFTER_SKILL].sort(key=lambda h: h.priority)

    def on_error(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run when a skill fails.

        Callback signature:
            (skill_name: str, context: SkillContext, error: Exception) -> None
        """
        self._hooks[HookType.ON_ERROR].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.ON_ERROR,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.ON_ERROR].sort(key=lambda h: h.priority)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def fire_before_skill(
        self,
        skill_name: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        """
        Fire all before_skill hooks.

        A before-skill hook may optionally return a dict of ``shared_state``
        increments (and, in principle, any other state fields) that should be
        persisted into the graph state for downstream nodes to see. The
        orchestrator merges the collected increments into the node's state
        update. Returning ``None`` is equivalent to returning no increment.

        This is the mechanism that lets, e.g., the memory-enrichment hook
        populate ``shared_state["relevant_memories"]`` before the ``agent``
        node so the ``retrieve`` node (a separate node invocation) can read it.
        """
        increments: dict[str, Any] = {}
        for hook in self._hooks[HookType.BEFORE_SKILL]:
            try:
                ret = hook.callback(skill_name, context)
            except Exception as e:
                log.warning(f"Before-skill hook '{hook.name}' failed: {e}")
                continue
            if isinstance(ret, dict) and ret:
                # Shallow-merge each hook's increment; later hooks win per key.
                for key, value in ret.items():
                    if key == "shared_state" and isinstance(value, dict):
                        inc = increments.setdefault("shared_state", {})
                        inc.update(value)
                    else:
                        increments[key] = value
        return increments

    def fire_after_skill(
        self,
        skill_name: str,
        context: SkillContext,
        result: SkillResult,
    ) -> None:
        """Fire all after_skill hooks."""
        for hook in self._hooks[HookType.AFTER_SKILL]:
            try:
                hook.callback(skill_name, context, result)
            except Exception as e:
                log.warning(f"After-skill hook '{hook.name}' failed: {e}")

    def fire_on_error(
        self,
        skill_name: str,
        context: SkillContext,
        error: Exception,
    ) -> None:
        """Fire all on_error hooks."""
        for hook in self._hooks[HookType.ON_ERROR]:
            try:
                hook.callback(skill_name, context, error)
            except Exception as e:
                log.warning(f"Error hook '{hook.name}' failed: {e}")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all hooks."""
        for hook_type in self._hooks:
            self._hooks[hook_type].clear()

    def list_hooks(self) -> dict[str, list[str]]:
        """List all registered hook names by type."""
        return {hook_type: [h.name for h in hooks] for hook_type, hooks in self._hooks.items()}
