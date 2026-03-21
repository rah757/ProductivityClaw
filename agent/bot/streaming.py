"""Telegram streaming — edit a single message in-place as tokens arrive.

Tiered flush intervals to feel snappy early, then back off:
  0.3s  for the first 5 edits
  0.5s  for the next 5
  1.2s  for the next 5
  3.3s  from there on
Caps at ~30 edits/min (Telegram's rate limit)."""

import re
import time
import asyncio

_TIERS = [
    (5, 0.3),    # first 5 edits: 0.3s apart
    (5, 0.5),    # next 5: 0.5s
    (5, 1.2),    # next 5: 1.2s
    (999, 3.3),  # rest: 3.3s
]


def _get_flush_interval(edit_count: int) -> float:
    """Return the flush interval for the current edit number."""
    cumulative = 0
    for count, interval in _TIERS:
        cumulative += count
        if edit_count < cumulative:
            return interval
    return _TIERS[-1][1]


def _snap_to_sentence(text: str) -> str:
    """Snap to last sentence boundary for cleaner reads.
    Returns text up to last sentence-ending punctuation, or full text if none found."""
    # Find last sentence boundary (. ! ? followed by space or end)
    match = list(re.finditer(r'[.!?]\s', text))
    if match:
        return text[:match[-1].end()]
    # Also check if text ends with punctuation
    if text and text[-1] in '.!?\n':
        return text
    return text


async def stream_to_telegram(
    chat_id: int,
    bot,
    token_generator,
    parse_mode: str = "HTML",
    format_fn=None,
):
    """Stream LLM tokens into a Telegram message by editing in-place.

    Args:
        chat_id: Telegram chat ID to send to.
        bot: telegram.Bot instance.
        token_generator: Iterator/generator yielding token strings.
        parse_mode: "HTML" or "Markdown". Default "HTML".
        format_fn: Optional function to format accumulated text before sending.
                   E.g. _md_to_tg_html. If None, sends raw text.

    Returns:
        (final_text, message) — the complete raw text and the Telegram Message object.
    """
    accumulated = ""
    message = None
    edit_count = 0
    last_flush = 0.0
    flushed_text = ""

    for token in token_generator:
        accumulated += token

        # Skip think tags in-flight
        if "<think>" in accumulated and "</think>" not in accumulated:
            continue

        # Strip completed think tags
        clean = re.sub(r"<think>.*?</think>", "", accumulated, flags=re.DOTALL).strip()
        if not clean:
            continue

        now = time.time()
        interval = _get_flush_interval(edit_count)

        if now - last_flush < interval:
            continue

        # Snap to sentence boundary for cleaner display
        display = _snap_to_sentence(clean)
        if not display or display == flushed_text:
            continue

        formatted = format_fn(display) if format_fn else display

        try:
            if message is None:
                # First flush: send new message
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=formatted + " ▍",
                    parse_mode=parse_mode,
                )
            else:
                # Subsequent flushes: edit in place
                await message.edit_text(
                    text=formatted + " ▍",
                    parse_mode=parse_mode,
                )
            edit_count += 1
            last_flush = now
            flushed_text = display
        except Exception as e:
            # Telegram rate limit or message unchanged — skip this flush
            if "message is not modified" not in str(e).lower():
                print(f"  [stream] edit error: {e}")

    # Final edit: remove cursor, show complete text
    final_clean = re.sub(r"<think>.*?</think>", "", accumulated, flags=re.DOTALL).strip()

    if final_clean:
        formatted = format_fn(final_clean) if format_fn else final_clean
        try:
            if message is None:
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=formatted,
                    parse_mode=parse_mode,
                )
            else:
                await message.edit_text(
                    text=formatted,
                    parse_mode=parse_mode,
                )
        except Exception:
            pass

    return final_clean, message
