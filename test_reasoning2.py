"""Direct Ollama HTTP API test — raw think parameter"""

import time
import requests
import json

MODEL = "qwen3.5:35b-a3b"

TESTS = [
    "Hi, how are you?",
    "What day is March 20, 2026?",
]

def test(think: bool):
    label = "ON" if think else "OFF"
    print(f"\n{'='*50}")
    print(f"  think={think}")
    print(f"{'='*50}")

    for msg in TESTS:
        print(f"\n  User: {msg}")
        t0 = time.perf_counter()
        resp = requests.post("http://localhost:11434/api/chat", json={
            "model": MODEL,
            "messages": [{"role": "user", "content": msg}],
            "think": think,
            "stream": False,
        })
        ms = int((time.perf_counter() - t0) * 1000)
        data = resp.json()

        content = data["message"]["content"]
        thinking = data["message"].get("thinking", "")
        t_len = len(thinking) if thinking else 0

        print(f"  Response ({ms}ms): {content[:200]}")
        print(f"  Thinking chars: {t_len}")
        if thinking:
            print(f"  Thinking preview: {thinking[:150]}...")

if __name__ == "__main__":
    test(think=False)
    test(think=True)
