"""Who may do what. Routers (later chunks) apply these with ``Depends(require_role(...))``; the server decides."""

from clinic_db.models.core import StaffRole

# Read tasks and threads, reply, mark handled.
TASK_ROLES = (StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK, StaffRole.CONSULTANT)

# Edit practice settings.
SETTINGS_ROLES = (StaffRole.OWNER, StaffRole.OFFICE_MANAGER)
