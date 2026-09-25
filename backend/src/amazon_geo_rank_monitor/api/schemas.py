from pydantic import BaseModel, Field, field_validator

from amazon_geo_rank_monitor.auth.api_keys import normalize_scopes


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1)
    marketplace: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    asins: list[str] = Field(min_length=1)
    geo_profile_ids: list[str] = Field(min_length=1)
    search_depth: int = Field(default=100, ge=1)
    provider_mode: str = "managed"
    schedule: str | None = None


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    marketplace: str | None = Field(default=None, min_length=1)
    keyword: str | None = Field(default=None, min_length=1)
    asins: list[str] | None = Field(default=None, min_length=1)
    geo_profile_ids: list[str] | None = Field(default=None, min_length=1)
    search_depth: int | None = Field(default=None, ge=1)
    provider_mode: str | None = None
    schedule: str | None = None
    enabled: bool | None = None


class RankCheckBody(BaseModel):
    marketplace: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    asins: list[str] = Field(min_length=1)
    geo_profile_ids: list[str] = Field(min_length=1)
    search_depth: int = Field(default=100, ge=1)
    provider_mode: str = "managed"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=lambda: ["*"], min_length=1)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        return normalize_scopes(value)


class CheckoutCreate(BaseModel):
    credit_pack_id: str = Field(min_length=1)


class AccountRegister(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=512)
    display_name: str = Field(min_length=1, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)
    invitation_token: str | None = Field(default=None, min_length=8)


class AccountLogin(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)
    workspace_id: str | None = None


class WorkspaceSwitch(BaseModel):
    workspace_id: str = Field(min_length=1)


class InvitationAccept(BaseModel):
    invitation_token: str = Field(min_length=8)


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(min_length=1)


class MemberRoleUpdate(BaseModel):
    role: str = Field(min_length=1)


class BootstrapOwnerCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=512)
    display_name: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=8)
    new_password: str = Field(min_length=10, max_length=512)


class EmailVerificationRequest(BaseModel):
    token: str = Field(min_length=8)
