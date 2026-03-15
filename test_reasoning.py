"""Quick test: reasoning=True vs reasoning=False with Qwen 3.5"""

import time
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

MODEL = "qwen3.5:35b-a3b"

TESTS = [
    "Hi, how are you?",
    "What day is March 20, 2026?",
    "If I have meetings at 9am, 11am, and 2pm, when is the best 1-hour slot for a gym session?",
]

def run_test(reasoning: bool):
    label = "ON" if reasoning else "OFF"
    print(f"\n{'='*60}")
    print(f"  REASONING = {label}")
    print(f"{'='*60}")

    llm = ChatOllama(model=MODEL, temperature=0.1, reasoning=reasoning)

    for msg in TESTS:
        print(f"\n  User: {msg}")
        t0 = time.perf_counter()
        resp = llm.invoke([HumanMessage(content=msg)])
        ms = int((time.perf_counter() - t0) * 1000)

        reasoning_content = resp.additional_kwargs.get("reasoning_content", "")
        r_len = len(reasoning_content) if reasoning_content else 0
        has_think_tags = "<think>" in (resp.content or "")

        print(f"  Response ({ms}ms): {resp.content[:200]}")
        print(f"  Reasoning chars: {r_len}")
        print(f"  <think> tags in content: {has_think_tags}")
        if reasoning_content:
            print(f"  Reasoning preview: {reasoning_content[:150]}...")


if __name__ == "__main__":
    run_test(reasoning=True)
    run_test(reasoning=False)
