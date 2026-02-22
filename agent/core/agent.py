"""LangGraph agent definition.

Defines the stateful agent graph:
  START → Build Context → LLM Reason → (tool call?) → Execute Tool → LLM Respond → Log + Output → END

The agent pulls from the inbox, processes through the graph, and writes to the outbox.
"""
