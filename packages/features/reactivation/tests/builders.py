"""Small builders shared by the pure tests."""

import uuid

from clinic_reactivation.analysis.exclusions import FlagValue
from clinic_reactivation.analysis.facts import PatientFacts, ReachabilityIngredients


def blank(**kw) -> PatientFacts:

    base = dict(
        patient_id=uuid.uuid4(),
        date_of_birth=None,
        is_minor=False,
        invalid_dob=False,
        do_not_contact_raw=None,
        deceased_raw=None,
        do_not_contact=FlagValue.ABSENT,
        deceased=FlagValue.ABSENT,
        visit_count=1,
        first_visit_day=None,
        last_visit_day=None,
        visit_days=(),
        visit_starts=(),
        visit_days_without_service=0,
        consult_visit_days=0,
        has_future_booking=False,
        usual_service_id=None,
        usual_service_category_norm=None,
        usual_service_visit_days=0,
        usual_provider_id=None,
        provider_staff_active=None,
        spend_cents=0,
        ticket_total_cents=0,
        average_ticket_cents=None,
        usual_service_ticket_total_cents=None,
        first_visit_ticket_cents=None,
        first_treatment_ticket_cents=None,
        spend_percentile=None,
        latest_consult_day=None,
        latest_consult_service_id=None,
        quoted_plan_cents=None,
        quoted_plan_invalid=False,
        converted_within_window=None,
        membership_rows=0,
        has_active_membership=False,
        latest_membership_status=None,
        latest_membership_end=None,
        latest_membership_fee_cents=None,
        prepaid_balance_cents=0,
        ingredients=ReachabilityIngredients(None, None, True, True, True),
        duplicate_appointments=0,
        completed_in_future=0,
        stale_booked_in_past=0,
        past_appointments=0,
    )
    base.update(kw)
    return PatientFacts(**base)
