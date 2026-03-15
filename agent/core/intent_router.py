"""
Intent router: classifies user messages before the main LLM call.

Current approach: bind ALL tools, let the main LLM decide.
With ~6 tools, the model handles tool selection perfectly fine
without any pre-filtering. This is the OpenClaw approach.

When the tool count grows past ~15, re-enable the LLM classifier
to narrow down tools for ambiguous messages. Code is preserved below.

Returns:
    {
        "tools": None,     # None = bind all tools
        "think": False,
    }
"""

from agent.core.registry import load_skills


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(user_message: str) -> dict:
    """Classify intent of a user message.

    Currently: always bind all tools, let the main LLM decide.
    The LLM is the best fuzzy matcher we have — no keyword rules
    can match its ability to understand natural language.

    Returns dict with keys:
        tools  (list[str] | None): None = bind all tools
        think  (bool):             whether reasoning mode should be enabled
    """
    print(f"  [router] all-tools (main LLM decides)")
    return {"tools": None, "think": False}
