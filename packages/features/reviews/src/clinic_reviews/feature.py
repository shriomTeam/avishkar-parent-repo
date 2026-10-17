"""The 5-Star Machine: post-appointment review automation."""

from datetime import timedelta

from clinic_core.events import APPOINTMENT_COMPLETED, CONSENT_CHANGED
from clinic_core.features import Feature, NavItem, Schedule
from clinic_engagement import SequenceDef, Step
from clinic_reviews.constants import FEATURE_KEY
from clinic_reviews.public import router as public_router
from clinic_reviews.router import router
from clinic_reviews.service import dispatch_due, on_appointment_completed, on_consent_changed

SMS_SEQUENCE = SequenceDef(
    key="reviews.sms",
    steps=(
        Step(
            delay=timedelta(0),
            channel="sms",
            template=(
                "Hi {first_name}, thank you for visiting {clinic_name}. "
                "We'd appreciate hearing about your experience: {review_request_link} "
                "Reply STOP to opt out."
            ),
        ),
    ),
)

EMAIL_SEQUENCE = SequenceDef(
    key="reviews.email",
    steps=(
        Step(
            delay=timedelta(0),
            channel="email",
            subject="How was your visit to {clinic_name}?",
            template=(
                "Hi {first_name},\n\nThank you for visiting {clinic_name}. "
                "We'd appreciate hearing about your experience:\n{review_request_link}\n\n"
                "{clinic_name}"
            ),
        ),
    ),
)

feature = Feature(
    key=FEATURE_KEY,
    name="The 5-Star Machine",
    description="Asks patients for a rating after a completed visit, and invites 4- and 5-star ratings to Google.",
    router=router,
    public_router=public_router,
    jobs={"dispatch_due": dispatch_due},
    schedules=[Schedule(job="dispatch_due", every_seconds=60)],
    event_handlers={APPOINTMENT_COMPLETED: [on_appointment_completed], CONSENT_CHANGED: [on_consent_changed]},
    nav=[NavItem(label="Reviews", path="/reviews", roles=("owner", "office_manager", "front_desk"))],
    sequences=[SMS_SEQUENCE, EMAIL_SEQUENCE],
    trial_eligible=True,
)
