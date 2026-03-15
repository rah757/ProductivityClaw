from agent.memory.context_store import store_context_dump

# trace_id is injected at call time by graph_agent (via partial or kwarg).
# If not provided, stored without a trace.
_current_trace_id = None


def execute(text: str) -> str:
    """Save context the user shared to persistent storage."""
    tid = _current_trace_id or "untraced"
    store_context_dump(trace_id=tid, content=text)
    print(f"  [store_context] saved {len(text)} chars (trace={tid})")
    return "Stored."
