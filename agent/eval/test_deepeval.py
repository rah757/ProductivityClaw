"""
ProductivityClaw LLM-as-Judge Quality Metrics

Custom eval using local MLX Qwen as judge. No DeepEval framework —
we handle retries, think-tag stripping, and JSON parsing ourselves.

Pre-recorded (input, context, output) pairs — no live agent needed.
Only the MLX server at localhost:8000 is required.

Run:
    pytest agent/eval/test_deepeval.py -v
    pytest agent/eval/test_deepeval.py -m deepeval -v
"""

import json
import re
import pytest

try:
    from langchain_openai import ChatOpenAI
    from agent.config import MLX_MODEL, MLX_BASE_URL
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False


pytestmark = [
    pytest.mark.deepeval,
    pytest.mark.flaky(reruns=2, reason="Qwen may return empty responses"),
]


# ---------------------------------------------------------------------------
# Judge helper
# ---------------------------------------------------------------------------

def _judge(prompt: str, retries: int = 5) -> str:
    """Send a prompt to MLX and return cleaned text. Retries on empty
    with increasing temperature to break out of empty-response loops."""
    temps = [0.0, 0.1, 0.3, 0.5, 0.7]
    for attempt in range(retries):
        llm = ChatOpenAI(
            base_url=MLX_BASE_URL,
            api_key="not-needed",
            model=MLX_MODEL,
            temperature=temps[min(attempt, len(temps) - 1)],
            max_tokens=2000,
        )
        resp = llm.invoke("/no_think\n" + prompt)
        content = resp.content or ""
        if isinstance(content, list):
            content = " ".join(
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in content
            )
        # Strip think tags
        clean = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL).strip()
        # If clean is empty, check reasoning field
        if not clean:
            ak = getattr(resp, "additional_kwargs", {}) or {}
            reasoning = ak.get("reasoning_content", "")
            if reasoning:
                clean = re.sub(r"<think>.*?</think>", "", str(reasoning), flags=re.DOTALL).strip()
        if clean:
            return clean
        print(f"  [judge] empty response (temp={temps[min(attempt, len(temps)-1)]}), retry {attempt + 1}/{retries}")
    return ""


def _judge_json(prompt: str, retries: int = 3) -> dict | list | None:
    """Send prompt, extract JSON from response."""
    text = _judge(prompt, retries=retries)
    if not text:
        return None
    # Find JSON object or array
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _mlx_available() -> bool:
    if not _LLM_AVAILABLE:
        return False
    try:
        import httpx
        r = httpx.get("http://localhost:8000/v1/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pre-recorded test data
# ---------------------------------------------------------------------------

SCHEDULE_QUERY = {
    "input": "What's on my schedule today?",
    "context": [
        "TODAY (Saturday, March 28):",
        "07:00 AM - 08:00 AM | Morning Workout [Personal] @ Campus Gym",
        "10:00 AM - 10:30 AM | 1:1 with Advisor [School] @ Professor's Office Room 412",
        "12:30 PM - 01:30 PM | Lunch with Alex [Personal] @ Chipotle on Main St",
        "03:00 PM - 04:00 PM | Sprint Planning [Work]",
    ],
    "output": (
        "Here's your schedule for today:\n\n"
        "- 7:00 AM - 8:00 AM: Morning Workout at Campus Gym\n"
        "- 10:00 AM - 10:30 AM: 1:1 with Advisor at Professor's Office Room 412\n"
        "- 12:30 PM - 1:30 PM: Lunch with Alex at Chipotle on Main St\n"
        "- 3:00 PM - 4:00 PM: Sprint Planning\n\n"
        "You have 4 events today."
    ),
}

EMPTY_SCHEDULE = {
    "input": "What's on my calendar today?",
    "context": ["TODAY: No events scheduled."],
    "output": "You don't have anything on your calendar today. Enjoy the free time!",
}

EMAIL_QUERY = {
    "input": "Do I have any important emails?",
    "context": [
        "HIGH: 'Deadline reminder: thesis draft due Monday' from advisor@university.edu",
        "LOW: 'Weekly newsletter' from news@techdigest.com",
        "NOISE: 'Sale: 50% off everything' from promo@store.com",
    ],
    "output": (
        "You have one important email:\n\n"
        "- **Deadline reminder: thesis draft due Monday** from your advisor\n\n"
        "There's also a tech newsletter and a promotional email, but nothing else urgent."
    ),
}

HALLUCINATED_OUTPUT = {
    "input": "What meetings do I have tomorrow?",
    "context": [
        "TOMORROW: Career Fair (All day) [School] @ Student Union Hall",
        "TOMORROW: 06:00 PM - 07:00 PM | Gym Session [Personal] @ Campus Gym",
    ],
    "output": (
        "Tomorrow you have:\n\n"
        "- Career Fair (all day) at Student Union Hall\n"
        "- Gym Session from 6:00 PM to 7:00 PM at Campus Gym\n"
        "- Team standup at 9:00 AM\n"  # HALLUCINATED
    ),
}

CONTEXT_STORE = {
    "input": "Remember that I prefer morning meetings before 11am",
    "context": [],
    "output": "Got it! I've saved that you prefer morning meetings before 11am.",
    "expected": "Acknowledged and stored the user's preference for morning meetings.",
}

TOOL_ROUTING = [
    ("What's on my schedule today?", "get_calendar_events"),
    ("Show me my emails", "get_emails"),
    ("Remember that I like dark mode", "store_context"),
    ("Add a meeting with John at 3pm tomorrow", "create_event"),
    ("Move my 3pm to 4pm", "move_event"),
    ("What did I store about Docker?", "get_stored_context"),
]


# ---------------------------------------------------------------------------
# Eval prompts (single LLM call per test, simple yes/no + score)
# ---------------------------------------------------------------------------

_RELEVANCY_PROMPT = """You are evaluating an AI assistant's response quality.

User question: {input}
Context provided: {context}
Assistant response: {output}

Rate how relevant the response is to the user's question on a scale of 1-5:
1 = Completely irrelevant
3 = Partially relevant
5 = Perfectly relevant and addresses the question

Respond ONLY with JSON: {{"score": <1-5>, "reason": "one line explanation"}}"""

_FAITHFULNESS_PROMPT = """You are checking if an AI assistant's response only uses information from the provided context.

User question: {input}
Context (ground truth): {context}
Assistant response: {output}

Does the response ONLY contain information present in the context? Rate 1-5:
1 = Contains significant fabricated information
3 = Mostly faithful with minor additions
5 = Completely faithful to the context

Respond ONLY with JSON: {{"score": <1-5>, "reason": "one line explanation"}}"""

_HALLUCINATION_PROMPT = """You are a hallucination detector. Check if the assistant's response contains ANY claims not supported by the context.

Context (ground truth):
{context}

Assistant response:
{output}

List every claim in the response and mark each as SUPPORTED or UNSUPPORTED.
Then give an overall score:
1 = Major hallucinations present
3 = Minor unsupported details
5 = No hallucinations, everything is supported

Respond ONLY with JSON: {{"score": <1-5>, "unsupported_claims": ["list", "of", "unsupported"], "reason": "one line"}}"""

_TOOL_ROUTING_PROMPT = """You are evaluating tool selection for an AI assistant.

Available tools:
- get_calendar_events: read calendar/schedule
- get_emails: read email inbox
- store_context: save user info/preferences/notes
- get_stored_context: retrieve previously stored info
- create_event: create a new calendar event
- move_event: reschedule an existing event

User message: "{input}"
Selected tool: "{tool}"

Is this the correct tool for the user's request?
Respond ONLY with JSON: {{"correct": true/false, "reason": "one line"}}"""

_CORRECTNESS_PROMPT = """You are evaluating if an AI response correctly handles the user's request.

User input: {input}
Expected behavior: {expected}
Actual response: {output}

Rate correctness 1-5:
1 = Wrong behavior
3 = Partially correct
5 = Exactly right

Respond ONLY with JSON: {{"score": <1-5>, "reason": "one line"}}"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _require_mlx():
    if not _mlx_available():
        pytest.skip("MLX server not running at localhost:8000")


class TestRelevancy:
    """Does the response actually answer the question?"""

    def _check(self, data):
        prompt = _RELEVANCY_PROMPT.format(
            input=data["input"],
            context="\n".join(data["context"]),
            output=data["output"],
        )
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        score = result.get("score", 0)
        assert score >= 4, f"Relevancy score {score}/5: {result.get('reason', '')}"

    def test_schedule_query(self):
        self._check(SCHEDULE_QUERY)

    def test_email_query(self):
        self._check(EMAIL_QUERY)

    def test_empty_schedule(self):
        self._check(EMPTY_SCHEDULE)


class TestFaithfulness:
    """Does the response stick to the provided context?"""

    def _check(self, data):
        prompt = _FAITHFULNESS_PROMPT.format(
            input=data["input"],
            context="\n".join(data["context"]),
            output=data["output"],
        )
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        score = result.get("score", 0)
        assert score >= 4, f"Faithfulness score {score}/5: {result.get('reason', '')}"

    def test_schedule_faithful(self):
        self._check(SCHEDULE_QUERY)

    def test_email_faithful(self):
        self._check(EMAIL_QUERY)


class TestHallucination:
    """Does the response avoid inventing information?"""

    def test_detects_hallucinated_event(self):
        """Output includes fake 'Team standup' — judge should flag it."""
        prompt = _HALLUCINATION_PROMPT.format(
            context="\n".join(HALLUCINATED_OUTPUT["context"]),
            output=HALLUCINATED_OUTPUT["output"],
        )
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        score = result.get("score", 5)
        unsupported = result.get("unsupported_claims", [])
        # Should score low (hallucination present)
        assert score <= 3, (
            f"Should detect hallucination but scored {score}/5. "
            f"Unsupported: {unsupported}"
        )

    def test_clean_output_passes(self):
        """Faithful schedule response should score well."""
        prompt = _HALLUCINATION_PROMPT.format(
            context="\n".join(SCHEDULE_QUERY["context"]),
            output=SCHEDULE_QUERY["output"],
        )
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        score = result.get("score", 0)
        assert score >= 4, f"Clean output scored {score}/5: {result.get('reason', '')}"


class TestToolRouting:
    """Does the agent pick the right tool for each query?"""

    @pytest.mark.parametrize("user_input,expected_tool", TOOL_ROUTING)
    def test_tool_selection(self, user_input, expected_tool):
        prompt = _TOOL_ROUTING_PROMPT.format(input=user_input, tool=expected_tool)
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        assert result.get("correct") is True, (
            f"Tool '{expected_tool}' not confirmed for '{user_input}': "
            f"{result.get('reason', '')}"
        )


class TestCorrectness:
    """General response correctness."""

    def test_context_store_acknowledgement(self):
        prompt = _CORRECTNESS_PROMPT.format(
            input=CONTEXT_STORE["input"],
            expected=CONTEXT_STORE["expected"],
            output=CONTEXT_STORE["output"],
        )
        result = _judge_json(prompt)
        assert result is not None, "Judge returned no JSON"
        score = result.get("score", 0)
        assert score >= 4, f"Correctness score {score}/5: {result.get('reason', '')}"
