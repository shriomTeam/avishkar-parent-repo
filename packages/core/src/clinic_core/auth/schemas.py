import uuid

from pydantic import BaseModel, ConfigDict

from clinic_core.tenancy.schemas import WorkspaceOut


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    display_name: str


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    role: str
    workspace: WorkspaceOut


class AuthMeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    workspace: WorkspaceOut | None
    needs_onboarding: bool
    csrf_token: str
