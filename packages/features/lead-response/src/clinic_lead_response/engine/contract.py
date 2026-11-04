"""What the engine relies on from the staff side. The reply and task API (a later chunk) must keep to this contract,
because the engine reads the database, not a message from the API, to learn that staff have answered.

A STAFF REPLY is a row in ``lead_response.messages`` with ``direction = 'outbound'`` and ``sender_kind = 'staff'``,
created by sending through ``Gateway.send`` with ``Purpose.STAFF_REPLY`` (the gateway writes that sender kind itself, so
a reply sent any other way would not count). Its ``created_at`` is when the engine considers the lead answered.

"MARK HANDLED" is ``tasks.status = 'handled'`` (with ``handled_at`` and ``handled_by_staff_id``).

What the engine does with them, every time a holding message or an escalation is about to fire:
  * a staff reply after the wait began: the pending holding and escalation jobs are cancelled (reason ``staff_reply``)
    and ``tasks.first_staff_reply_at`` is filled in if the API has not;
  * a task that is no longer open: the same jobs are cancelled (reason ``handled``, or ``task_closed`` for any other
    closed status);
  * the contact has opted out: the same jobs are cancelled (reason ``stop``); the task stays open, because a person may
    still phone the lead.
The API may also set ``first_staff_reply_at`` itself when it sends; the engine never overwrites it.
"""

STAFF_SENDER_KIND = "staff"
TASK_OPEN = "open"
TASK_HANDLED = "handled"

# The reasons the engine gives when it cancels a job (jobs.cancel_reason).
CANCEL_STAFF_REPLY = "staff_reply"
CANCEL_HANDLED = "handled"
CANCEL_TASK_CLOSED = "task_closed"
CANCEL_STOP = "stop"
