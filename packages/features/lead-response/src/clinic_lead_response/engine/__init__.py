"""The engine: turns the jobs that intake writes into a task, an acknowledgement, a holding message and an escalation.

The ``jobs`` table is the queue of record. Nothing here runs by itself: a scheduled tick (and a fast path after an
inbound text is committed) call into it, and only while ``LEAD_RESPONSE_ENGINE_ENABLED`` is on.
"""
