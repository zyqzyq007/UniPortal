"""
Intent Classification Module

Analyzes user queries to determine the appropriate processing route:
- RAG_QUERY: Requires knowledge base retrieval
- GENERAL_CHAT: General conversation
- DOCUMENT_UPLOAD: Document upload request
- SYSTEM_COMMAND: System administration commands
"""

from core.intent.classifier import IntentClassifier, IntentResult, IntentType

__all__ = [
    "IntentClassifier",
    "IntentType",
    "IntentResult",
]
