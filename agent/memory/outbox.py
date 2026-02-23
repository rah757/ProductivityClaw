"""Outbox — message queue for agent responses.

Agent writes responses here. Dispatcher polls and routes to Telegram, webhook
callbacks, etc. CRUD + dispatching logic. Paired with inbox as the backbone.
"""
