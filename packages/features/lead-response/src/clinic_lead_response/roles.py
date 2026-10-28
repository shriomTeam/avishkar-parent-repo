"""Who may do what. Routers (later chunks) apply these with ``Depends(require_role(...))``; the server decides."""

from fastapi import Depends

from clinic_core.api import require_role
from clinic_db.models.core import StaffRole

# Read tasks and threads, reply, mark handled.
TASK_ROLES = (StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK, StaffRole.CONSULTANT)

# Edit practice settings.
SETTINGS_ROLES = (StaffRole.OWNER, StaffRole.OFFICE_MANAGER)

# Dependency lists a router applies; the sets above stay the source of truth.
SETTINGS_READERS = [Depends(require_role(*TASK_ROLES))]
SETTINGS_EDITORS = [Depends(require_role(*SETTINGS_ROLES))]
