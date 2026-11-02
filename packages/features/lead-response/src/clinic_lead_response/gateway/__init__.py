"""The messaging gateway: one place that decides whether a text may go out, sends it once, and records what happened.

The rules (keywords, consent and quiet hours, retries, status) are pure modules with no database and no network.
The provider is an interface (``SmsProvider``), Twilio is one implementation, and nothing here runs a loop:
re-firing a retry is the jobs worker's job (a later chunk).
"""
