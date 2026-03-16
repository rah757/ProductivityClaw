"""Quick test — calls heartbeat tick directly without waiting 30 min.
Requires mlx_lm.server running on port 8000."""

import time

# Test 1: heartbeat tick (LLM decides whether to message)
print("=" * 50)
print("TEST 1: Heartbeat tick")
print("=" * 50)

from agent.scheduler.briefing import _heartbeat_tick, set_send_fn

# Mock send function — just prints instead of sending to Telegram
sent_messages = []
async def mock_send(text: str):
    sent_messages.append(text)
    print(f"  [MOCK SEND] {text}")

set_send_fn(mock_send)

t0 = time.time()
_heartbeat_tick()
elapsed = time.time() - t0

print(f"\n  Elapsed: {elapsed:.1f}s")
if sent_messages:
    print(f"  Result: SENT message ({len(sent_messages[0])} chars)")
else:
    print(f"  Result: SKIPPED (nothing to report)")

# Test 2: verify full_sync runs (check logs for [sync] before [heartbeat])
print("\n" + "=" * 50)
print("TEST 2: Context building")
print("=" * 50)

from agent.scheduler.briefing import _build_heartbeat_context
context = _build_heartbeat_context()
print(context)

# Test 3: HTML rendering on heartbeat send
print("\n" + "=" * 50)
print("TEST 3: HTML rendering")
print("=" * 50)

from agent.bot.telegram_handler import _md_to_tg_html

test_cases = [
    "**Morning briefing:** You have 3 events today.",
    "Next meeting: *Sprint Planning* in 15 minutes.",
    "No events today. `HEARTBEAT_SKIP`",
    "🫀 **Today:** 2 meetings, 1 reminder.",
]

for tc in test_cases:
    print(f"  IN:  {tc}")
    print(f"  OUT: {_md_to_tg_html(tc)}")
    print()

print("Done.")
