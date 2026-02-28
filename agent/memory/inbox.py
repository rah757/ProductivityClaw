"""Inbox — message queue for incoming user input.

SQLite-backed. Telegram, webhook, Siri, etc. all write here.
Agent (or message processor) polls for pending messages and processes them.
CRUD + polling logic. The backbone of the architecture.
"""
