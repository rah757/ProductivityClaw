"""
ProductivityClaw DeepEval Quality Metrics

Uses DeepEval's LLM-as-a-judge metrics to evaluate agent response quality.
Runs against pre-recorded (input, context, output) pairs so you don't need
the MLX server running to *execute* these evals — only the judge model is needed.

The judge model is the same local MLX Qwen instance (localhost:8000).

Run:
    pytest agent/eval/test_deepeval.py -v
    pytest agent/eval/test_deepeval.py -m deepeval -v
"""

import pytest

try:
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        HallucinationMetric,
        GEval,
    )
    from deepeval.test_case import LLMTestCaseParams
    from deepeval.models.base_model import DeepEvalBaseLLM
    DEEPEVAL_AVAILABLE = True
except ImportError:
    DEEPEVAL_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DEEPEVAL_AVAILABLE,
    reason="deepeval not installed -- pip install deepeval",
)


# ---------------------------------------------------------------------------
# Custom MLX Judge Model
# ---------------------------------------------------------------------------

if DEEPEVAL_AVAILABLE:
    import re as _re

    def _clean_llm_output(content) -> str:
        """Extract usable text from MLX response: handle list content,
        strip <think> tags, and find JSON if present."""
        if isinstance(content, list):
            text = " ".join(
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in content
            )
        else:
            text = str(content or "")

        full_text = text
        # Strip think tags
        clean = _re.sub(r"<think>.*?</think>", "", full_text, flags=_re.DOTALL).strip()

        # If clean text is empty but full text has content, search full text for JSON
        if not clean and full_text:
            json_match = _re.search(r"[\[{].*[\]}]", full_text, _re.DOTALL)
            if json_match:
                return json_match.group()

        return clean if clean else full_text

    class MLXJudge(DeepEvalBaseLLM):
        """Use the local MLX server as the DeepEval judge model."""

        def __init__(self):
            import httpx
            from langchain_openai import ChatOpenAI
            from agent.config import MLX_MODEL, MLX_BASE_URL
            self._model = ChatOpenAI(
                base_url=MLX_BASE_URL,
                api_key="not-needed",
                model=MLX_MODEL,
                temperature=0.1,
                max_tokens=4000,
                timeout=300,
                http_client=httpx.Client(timeout=300),
                http_async_client=httpx.AsyncClient(timeout=300),
            )

        def load_model(self):
            return self._model

        def _extract_content(self, response) -> str:
            """Extract text from response, checking all possible fields."""
            content = response.content
            # Check for reasoning content in additional_kwargs
            ak = getattr(response, "additional_kwargs", {}) or {}
            reasoning = ak.get("reasoning_content", "")
            print(f"\n[JUDGE-DEBUG] content type={type(content).__name__} len={len(str(content))}")
            print(f"[JUDGE-DEBUG] content={repr(str(content)[:200])}")
            print(f"[JUDGE-DEBUG] reasoning len={len(str(reasoning))}")
            if reasoning:
                print(f"[JUDGE-DEBUG] reasoning={repr(str(reasoning)[:200])}")
            print(f"[JUDGE-DEBUG] additional_kwargs keys={list(ak.keys())}")

            # If content is empty, try reasoning field
            result = _clean_llm_output(content)
            if not result and reasoning:
                result = _clean_llm_output(reasoning)
            return result

        def generate(self, prompt: str) -> str:
            response = self._model.invoke("/no_think\n" + prompt)
            return self._extract_content(response)

        async def a_generate(self, prompt: str) -> str:
            response = await self._model.ainvoke("/no_think\n" + prompt)
            return self._extract_content(response)

        def get_model_name(self):
            return "MLX-Qwen3.5-35B-A3B"


# ---------------------------------------------------------------------------
# Pre-recorded test data (input, retrieval_context, actual_output)
# ---------------------------------------------------------------------------

SCHEDULE_QUERY = {
    "input": "What's on my schedule today?",
    "retrieval_context": [
        "TODAY (Saturday, March 28):",
        "07:00 AM - 08:00 AM | Morning Workout [Personal] @ Campus Gym",
        "10:00 AM - 10:30 AM | 1:1 with Advisor [School] @ Professor's Office Room 412",
        "12:30 PM - 01:30 PM | Lunch with Alex [Personal] @ Chipotle on Main St",
        "03:00 PM - 04:00 PM | Sprint Planning [Work]",
    ],
    "actual_output": (
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
    "retrieval_context": [
        "TODAY: No events scheduled.",
    ],
    "actual_output": "You don't have anything on your calendar today. Enjoy the free time!",
}

EMAIL_QUERY = {
    "input": "Do I have any important emails?",
    "retrieval_context": [
        "HIGH: 'Deadline reminder: thesis draft due Monday' from advisor@university.edu",
        "LOW: 'Weekly newsletter' from news@techdigest.com",
        "NOISE: 'Sale: 50% off everything' from promo@store.com",
    ],
    "actual_output": (
        "You have one important email:\n\n"
        "- **Deadline reminder: thesis draft due Monday** from your advisor\n\n"
        "There's also a tech newsletter and a promotional email, but nothing else urgent."
    ),
}

HALLUCINATION_TEST = {
    "input": "What meetings do I have tomorrow?",
    "retrieval_context": [
        "TOMORROW: Career Fair (All day) [School] @ Student Union Hall",
        "TOMORROW: 06:00 PM - 07:00 PM | Gym Session [Personal] @ Campus Gym",
    ],
    "actual_output": (
        "Tomorrow you have:\n\n"
        "- Career Fair (all day) at Student Union Hall\n"
        "- Gym Session from 6:00 PM to 7:00 PM at Campus Gym\n"
        "- Team standup at 9:00 AM\n"  # HALLUCINATED — not in context
    ),
}

CONTEXT_STORE_QUERY = {
    "input": "Remember that I prefer morning meetings before 11am",
    "retrieval_context": [],
    "actual_output": "Got it! I've saved that you prefer morning meetings before 11am.",
    "expected_output": "Acknowledged and stored the user's preference for morning meetings.",
}

TOOL_ACCURACY_CASES = [
    {
        "input": "What's on my schedule today?",
        "expected_tools": ["get_calendar_events"],
        "description": "Schedule query should call calendar tool",
    },
    {
        "input": "Show me my emails",
        "expected_tools": ["get_emails"],
        "description": "Email query should call email tool",
    },
    {
        "input": "Remember that I like dark mode",
        "expected_tools": ["store_context"],
        "description": "Memory request should call store_context",
    },
    {
        "input": "Add a meeting with John at 3pm tomorrow",
        "expected_tools": ["create_event"],
        "description": "Event creation should call create_event",
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _get_judge():
    """Lazy-init the judge to avoid import errors when deepeval is missing."""
    return MLXJudge()


@pytest.mark.deepeval
class TestAnswerRelevancy:
    """Does the agent's response actually answer the question?"""

    def test_schedule_query_relevancy(self):
        metric = AnswerRelevancyMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=SCHEDULE_QUERY["input"],
            actual_output=SCHEDULE_QUERY["actual_output"],
            retrieval_context=SCHEDULE_QUERY["retrieval_context"],
        )
        assert_test(test_case, [metric])

    def test_email_query_relevancy(self):
        metric = AnswerRelevancyMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=EMAIL_QUERY["input"],
            actual_output=EMAIL_QUERY["actual_output"],
            retrieval_context=EMAIL_QUERY["retrieval_context"],
        )
        assert_test(test_case, [metric])

    def test_empty_schedule_relevancy(self):
        metric = AnswerRelevancyMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=EMPTY_SCHEDULE["input"],
            actual_output=EMPTY_SCHEDULE["actual_output"],
            retrieval_context=EMPTY_SCHEDULE["retrieval_context"],
        )
        assert_test(test_case, [metric])


@pytest.mark.deepeval
class TestFaithfulness:
    """Does the agent only use information from the provided context?"""

    def test_schedule_faithful_to_calendar(self):
        metric = FaithfulnessMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=SCHEDULE_QUERY["input"],
            actual_output=SCHEDULE_QUERY["actual_output"],
            retrieval_context=SCHEDULE_QUERY["retrieval_context"],
        )
        assert_test(test_case, [metric])

    def test_email_faithful_to_inbox(self):
        metric = FaithfulnessMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=EMAIL_QUERY["input"],
            actual_output=EMAIL_QUERY["actual_output"],
            retrieval_context=EMAIL_QUERY["retrieval_context"],
        )
        assert_test(test_case, [metric])


@pytest.mark.deepeval
class TestHallucination:
    """Does the agent avoid inventing information not in the context?"""

    def test_detects_hallucinated_event(self):
        """The HALLUCINATION_TEST output includes a fake 'Team standup' -- should fail."""
        metric = HallucinationMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=HALLUCINATION_TEST["input"],
            actual_output=HALLUCINATION_TEST["actual_output"],
            context=HALLUCINATION_TEST["retrieval_context"],
        )
        # We EXPECT this to fail (score < threshold) because output has hallucination
        metric.measure(test_case)
        assert metric.score < 0.5, (
            f"Hallucination metric should flag invented 'Team standup' but scored {metric.score}"
        )

    def test_clean_output_passes(self):
        """A faithful schedule response should score well on hallucination."""
        metric = HallucinationMetric(model=_get_judge(), threshold=0.5)
        test_case = LLMTestCase(
            input=SCHEDULE_QUERY["input"],
            actual_output=SCHEDULE_QUERY["actual_output"],
            context=SCHEDULE_QUERY["retrieval_context"],
        )
        assert_test(test_case, [metric])


@pytest.mark.deepeval
class TestToolAccuracy:
    """Does the agent call the right tool for each query type?

    Uses GEval to judge whether the expected tool would be appropriate
    for the given user input.
    """

    def test_tool_routing_correctness(self):
        tool_correctness = GEval(
            name="Tool Routing",
            criteria=(
                "Given the user's input, determine if the expected tool is the correct one "
                "to call. The available tools are: get_calendar_events (for schedule queries), "
                "get_emails (for email queries), store_context (for remembering user info), "
                "update_profile (for updating user preferences), create_event (for creating "
                "calendar events), move_event (for rescheduling events)."
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            model=_get_judge(),
            threshold=0.5,
        )

        for case in TOOL_ACCURACY_CASES:
            test_case = LLMTestCase(
                input=case["input"],
                actual_output=", ".join(case["expected_tools"]),
                expected_output=", ".join(case["expected_tools"]),
            )
            tool_correctness.measure(test_case)
            assert tool_correctness.score >= 0.5, (
                f"Tool routing failed for '{case['description']}': "
                f"score={tool_correctness.score}, reason={tool_correctness.reason}"
            )


@pytest.mark.deepeval
class TestResponseCorrectness:
    """General correctness using GEval."""

    def test_context_store_acknowledgement(self):
        correctness = GEval(
            name="Correctness",
            criteria=(
                "Determine if the actual output correctly acknowledges and confirms "
                "that the user's preference has been saved."
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            model=_get_judge(),
            threshold=0.5,
        )
        test_case = LLMTestCase(
            input=CONTEXT_STORE_QUERY["input"],
            actual_output=CONTEXT_STORE_QUERY["actual_output"],
            expected_output=CONTEXT_STORE_QUERY["expected_output"],
        )
        assert_test(test_case, [correctness])
