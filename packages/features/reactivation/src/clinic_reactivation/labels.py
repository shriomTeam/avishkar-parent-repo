"""Display text for the patient types, kept here so the frontend does not duplicate it."""

from typing import NamedTuple

UNCLASSIFIED = "unclassified"


class TypeInfo(NamedTuple):
    label: str
    description: str
    kind: str | None  # new, retention; None for unclassified


TYPE_INFO: dict[str, TypeInfo] = {
    "lapsed_high_value": TypeInfo(
        "Lapsed high-value", "Top spenders who are well past their usual return time.", "new"
    ),
    "churned_member": TypeInfo("Churned member", "Membership cancelled or lapsed and no visit since.", "new"),
    "consult_not_converted": TypeInfo(
        "Consult not converted", "Had a consult but no treatment booked within the window.", "new"
    ),
    "overdue_maintenance": TypeInfo(
        "Overdue maintenance", "Repeat patients who are overdue for their usual service.", "new"
    ),
    "one_and_done": TypeInfo("One-and-done", "Visited once and has not come back.", "new"),
    "lapsed_regular": TypeInfo("Lapsed regulars", "Repeat patients who are past their usual return time", "new"),
    "unused_balance": TypeInfo(
        "Unused balance", "Prepaid credit or package still unused. Already paid, so retention value.", "retention"
    ),
    UNCLASSIFIED: TypeInfo("Unclassified", "Dormant, but matches none of the enabled patient types.", None),
}
