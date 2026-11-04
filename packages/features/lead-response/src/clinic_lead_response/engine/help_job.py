"""The help job: a lead texted HELP.

The wording of the answer is still a placeholder (``gateway/texts.py``) and has not been approved, so the engine sends
nothing. The job ends ``cancelled`` with the reason ``help_wording_pending``, which says exactly why it did nothing and
can be found later. When the wording is approved, this handler is where the send goes (``Purpose.HELP``, which ignores
quiet hours and is blocked for an opted-out contact by the gateway).
"""

import logging

from clinic_lead_response.engine.results import Cancel, End
from clinic_lead_response.gateway.log import log_event

log = logging.getLogger("lead_response.engine")

CANCEL_REASON = "help_wording_pending"


async def handle(engine, job) -> End:
    log_event(log, "help_skipped", tenant_id=job.tenant_id, trace_id=job.trace_id, job_id=job.id, reason=CANCEL_REASON)
    return Cancel(CANCEL_REASON)
