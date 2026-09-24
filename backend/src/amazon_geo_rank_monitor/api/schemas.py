from pydantic import BaseModel, Field


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1)
    marketplace: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    asins: list[str] = Field(min_length=1)
    geo_profile_ids: list[str] = Field(min_length=1)
    search_depth: int = Field(default=100, ge=1)
    provider_mode: str = "managed"
    schedule: str | None = None


class RankCheckBody(BaseModel):
    marketplace: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    asins: list[str] = Field(min_length=1)
    geo_profile_ids: list[str] = Field(min_length=1)
    search_depth: int = Field(default=100, ge=1)
    provider_mode: str = "managed"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1)


class CheckoutCreate(BaseModel):
    credit_pack_id: str = Field(min_length=1)
