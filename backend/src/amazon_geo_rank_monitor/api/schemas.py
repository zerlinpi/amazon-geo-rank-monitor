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


class MfaCompleteRequest(BaseModel):
    challenge_token: str = Field(min_length=8)
    code: str = Field(min_length=4, max_length=64)
    remember_device: bool = False


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)


class MfaDisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=4, max_length=64)


class WorkspaceMfaPolicyUpdate(BaseModel):
    require_mfa: bool


class SsoStartRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    email: str | None = Field(default=None, min_length=3, max_length=320)


class WorkspaceSsoConfigUpdate(BaseModel):
    provider_type: str = Field(default="oidc", min_length=1, max_length=32)
    display_name: str = Field(default="Enterprise SSO", min_length=1, max_length=200)
    issuer_url: str = Field(min_length=8, max_length=512)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=2048)
    email_domains: list[str] = Field(min_length=1)
    auto_join: bool = False
    enabled: bool = True


class WorkspaceSsoEnforcementUpdate(BaseModel):
    enforce_sso: bool


class WorkspaceScimConfigUpdate(BaseModel):
    enabled: bool
    default_role: str = Field(default="viewer", min_length=1, max_length=32)


class ScimGroupRoleUpdate(BaseModel):
    mapped_role: str | None = Field(default=None, max_length=32)


class AlertChannelsInput(BaseModel):
    emails: list[str] = Field(default_factory=list)
    slack_webhook_url: str | None = Field(default=None, max_length=2048)
    webhook_url: str | None = Field(default=None, max_length=2048)


class AlertRuleCreate(BaseModel):
    monitor_target_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    rule_type: str = Field(min_length=1, max_length=32)
    threshold: float | None = None
    asin: str | None = Field(default=None, max_length=32)
    geo_profile_id: str | None = Field(default=None, max_length=128)
    channels: AlertChannelsInput
    cooldown_minutes: int = Field(default=60, ge=0, le=10080)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    monitor_target_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    rule_type: str | None = Field(default=None, min_length=1, max_length=32)
    threshold: float | None = None
    asin: str | None = Field(default=None, max_length=32)
    geo_profile_id: str | None = Field(default=None, max_length=128)
    channels: AlertChannelsInput | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=10080)
    enabled: bool | None = None


class ReportScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    monitor_target_ids: list[str] = Field(min_length=1)
    recipients: list[str] = Field(min_length=1)
    schedule: str = Field(min_length=1, max_length=128)
    lookback_hours: int = Field(default=168, ge=1, le=8760)
    include_csv: bool = True
    enabled: bool = True


class ReportScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    monitor_target_ids: list[str] | None = Field(default=None, min_length=1)
    recipients: list[str] | None = Field(default=None, min_length=1)
    schedule: str | None = Field(default=None, min_length=1, max_length=128)
    lookback_hours: int | None = Field(default=None, ge=1, le=8760)
    include_csv: bool | None = None
    enabled: bool | None = None
