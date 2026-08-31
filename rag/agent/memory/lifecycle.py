from __future__ import annotations

from collections.abc import Callable

from agent.memory.extractor import MemoryExtractor
from agent.memory.store import get_memory_store
from agent.skills.base import SkillContext, SkillResult
from utils.log_utils import log

_extractor = MemoryExtractor()


def create_memory_store_hook() -> Callable:
    def after_generate(skill_name: str, context: SkillContext, result: SkillResult):
        if skill_name != "generate":
            return
        try:
            question = context.question
            answer = ""
            if result.messages:
                answer = result.messages[-1].content if result.messages else ""
            if not question or not answer:
                return
            entries = _extractor.extract_facts(question, answer)
            store = get_memory_store()
            for entry in entries:
                store.store(entry)
        except Exception as e:
            log.warning(f"Memory store hook failed: {e}")

    return after_generate


def create_memory_enrichment_hook() -> Callable:
    def before_agent(skill_name: str, context: SkillContext):
        if skill_name != "agent":
            return None
        try:
            from agent.memory.types import MemoryQuery

            question = context.question
            if not question:
                return None
            store = get_memory_store()
            query = MemoryQuery(query=question, limit=5)
            memories = store.retrieve(query)
            if memories:
                relevant = [
                    {"id": m.id, "content": m.content, "type": m.memory_type.value}
                    for m in memories
                ]
                # Make visible to the current (agent) node immediately.
                context.shared_state["relevant_memories"] = relevant
                log.debug(f"Memory enrichment: injected {len(memories)} memories")
                # Return an increment so the orchestrator persists it into the
                # graph state and downstream nodes (e.g. retrieve) can read it.
                # This relies on AgentState.shared_state being a merged field.
                return {"shared_state": {"relevant_memories": relevant}}
        except Exception as e:
            log.warning(f"Memory enrichment hook failed: {e}")
        return None

    return before_agent
