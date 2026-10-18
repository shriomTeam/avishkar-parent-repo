from datetime import timedelta

from clinic_core.events import APPOINTMENT_BOOKED, CONSENT_CHANGED
from clinic_core.features import Feature, NavItem, Schedule
from clinic_engagement import SequenceDef, Step
from clinic_reactivation.router import router
from clinic_reactivation.runs import (
    REAP_EVERY_SECONDS,
    REAP_JOB,
    RUN_REQUESTED,
    on_run_requested,
    reap_stuck_runs,
)
from clinic_reactivation.service import FEATURE_KEY, on_appointment_booked, on_consent_changed

DEFAULT_SEQUENCE = SequenceDef(
    key="reactivation.default",
    steps=(
        Step(
            delay=timedelta(0),
            channel="sms",
            template="Hi {first_name}, it's {clinic_name}! It's been a while and we'd love to see you again. "
            "Book a time that suits you: {booking_link} Reply STOP to opt out.",
        ),
        Step(
            delay=timedelta(days=3),
            channel="sms",
            template="Hi {first_name}, just checking in from {clinic_name}. Want us to hold a spot for you "
            "this week? Reply YES and we'll call you, or book here: {booking_link}",
        ),
        Step(
            delay=timedelta(days=7),
            channel="email",
            subject="We miss you at {clinic_name}",
            template="Hi {first_name},\n\nIt's been a while since your last visit. "
            "Book your next appointment here: {booking_link}\n\n{clinic_name}",
        ),
    ),
)

feature = Feature(
    key=FEATURE_KEY,
    name="Dormant Revenue Finder",
    description="Finds lapsed patients in the clinic's own data and brings them back automatically.",
    router=router,
    event_handlers={
        APPOINTMENT_BOOKED: [on_appointment_booked],
        CONSENT_CHANGED: [on_consent_changed],
        RUN_REQUESTED: [on_run_requested],
    },
    jobs={REAP_JOB: reap_stuck_runs},
    schedules=[Schedule(REAP_JOB, REAP_EVERY_SECONDS)],
    nav=[NavItem(label="Dormant patients", path="/reactivation", roles=("owner", "office_manager", "front_desk"))],
    sequences=[DEFAULT_SEQUENCE],
    trial_eligible=True,
)
