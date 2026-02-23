"""Context builder — builds LLM context from all memory sources.

The expansion seam: one function the agent calls that grows richer across phases.
Phase 1: system prompt + recent conversations.
Phase 2: + facts, living user profile.
Phase 3: + vector retrieval, hybrid SQLite + ChromaDB.
"""
