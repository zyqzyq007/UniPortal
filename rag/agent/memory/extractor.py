from __future__ import annotations

import re
import uuid

from agent.memory.types import MemoryEntry, MemoryType
from utils.log_utils import log


def _fact_sections() -> list[str]:
    """Sections to capture as long-term facts, from the active domain profile.

    Defaults to the first two sections of the profile's ``section_template``
    (conclusion + causes for aviation; empty for the general profile, which
    has no structured output). Returns [] when the profile defines no
    sections — free-form answers yield no section-keyed facts.
    """
    from core.prompts.domain_profile import get_active_profile

    return list(get_active_profile().section_template[:2])


class MemoryExtractor:
    def extract_facts(self, question: str, answer: str) -> list[MemoryEntry]:
        entries = []

        for section in _fact_sections():
            if section in answer:
                content = self._extract_between_markers(answer, section)
                if content:
                    entries.append(
                        MemoryEntry(
                            id=str(uuid.uuid4()),
                            memory_type=MemoryType.FACT,
                            content=f"{section}: {content.strip()}",
                            metadata={"source_query": question},
                        )
                    )

        if entries:
            log.debug(f"MemoryExtractor: extracted {len(entries)} facts from answer")
        return entries

    def extract_correction(self, original: str, correction: str) -> MemoryEntry:
        return MemoryEntry(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.CORRECTION,
            content=correction,
            metadata={"original_answer": original},
        )

    def _extract_between_markers(self, text: str, section: str) -> str:
        patterns = [
            rf"【{re.escape(section)}】(.*?)(?=【|$)",
            rf"{re.escape(section)}[：:](.*?)(?=【|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""
