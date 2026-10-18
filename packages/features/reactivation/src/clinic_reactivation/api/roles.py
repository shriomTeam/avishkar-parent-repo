"""Who may call the Dormant patients endpoints, shared so the rule can't drift between routers."""

from fastapi import Depends

from clinic_core.api import require_role
from clinic_db.models.core import StaffRole

# Start runs, analyse files and see patient-level lists.
MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]
# Read run status and type totals.
VIEWERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK))]
