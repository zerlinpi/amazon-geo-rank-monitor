from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher

from amazon_geo_rank_monitor.repositories.scim_repository import SCIM_ROLES

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

FILTER_RE = re.compile(
    r'^\s*(id|userName|externalId|displayName)\s+eq\s+"([^"]+)"\s*$',
    re.IGNORECASE,
)
GROUP_MEMBER_FILTER_RE = re.compile(
    r'^members\[value\s+eq\s+"([^"]+)"\]$',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScimPrincipal:
    owner_id: str
    token_prefix: str
    auth_type: str = "scim"
    key_id: None = None
    user_id: None = None


@dataclass(frozen=True)
class ScimTokenCreation:
    plaintext: str
    prefix: str


class ScimService:
    def __init__(self, *, repository, pepper: str) -> None:
        if not pepper:
            raise ValueError("SCIM token pepper must not be empty")
        self._repository = repository
        self._pepper = pepper.encode()
        self._passwords = PasswordHasher()

    def _hash(self, plaintext: str) -> str:
        return hmac.new(
            self._pepper,
            plaintext.encode(),
            hashlib.sha256,
        ).hexdigest()

    def get_config(self, *, owner_id: str) -> dict:
        config = self._repository.get_config(owner_id=owner_id)
        if config is None:
            return {
                "owner_id": owner_id,
                "enabled": False,
                "default_role": "viewer",
                "token_prefix": None,
                "has_token": False,
            }
        return self._public_config(config)

    def update_config(
        self,
        *,
        owner_id: str,
        enabled: bool,
        default_role: str,
    ) -> dict:
        config = self._repository.upsert_config(
            owner_id=owner_id,
            enabled=enabled,
            default_role=default_role,
        )
        return self._public_config(config)

    def rotate_token(self, *, owner_id: str) -> ScimTokenCreation:
        plaintext = f"agrscim_{secrets.token_urlsafe(36)}"
        prefix = plaintext[:24]
        self._repository.set_token(
            owner_id=owner_id,
            token_prefix=prefix,
            token_hash=self._hash(plaintext),
        )
        return ScimTokenCreation(plaintext=plaintext, prefix=prefix)

    def authenticate(self, plaintext: str) -> ScimPrincipal | None:
        if not plaintext.startswith("agrscim_"):
            return None
        prefix = plaintext[:24]
        config = self._repository.get_config_by_prefix(token_prefix=prefix)
        if (
            config is None
            or not config["enabled"]
            or not config["token_hash"]
        ):
            return None
        if not hmac.compare_digest(
            self._hash(plaintext),
            config["token_hash"],
        ):
            return None
        return ScimPrincipal(
            owner_id=config["owner_id"],
            token_prefix=prefix,
        )

    def list_users(
        self,
        *,
        owner_id: str,
        filter_expression: str | None,
        start_index: int,
        count: int,
    ) -> dict:
        email = None
        external_id = None
        direct_id = None
        if filter_expression:
            attribute, value = self._parse_filter(filter_expression)
            if attribute.lower() == "username":
                email = self._normalize_email(value)
            elif attribute.lower() == "externalid":
                external_id = value
            elif attribute.lower() == "id":
                direct_id = value
            else:
                raise ValueError("unsupported SCIM Users filter")
        if direct_id:
            try:
                rows = [
                    self._repository.get_scim_user(
                        owner_id=owner_id,
                        membership_id=direct_id,
                    )
                ]
            except KeyError:
                rows = []
        else:
            rows = self._repository.list_scim_users(
                owner_id=owner_id,
                email=email,
                external_id=external_id,
            )
        return self._list_response(
            [self.serialize_user(row) for row in rows],
            start_index=start_index,
            count=count,
        )

    def get_user(self, *, owner_id: str, membership_id: str) -> dict:
        return self.serialize_user(
            self._repository.get_scim_user(
                owner_id=owner_id,
                membership_id=membership_id,
            )
        )

    def create_user(self, *, owner_id: str, payload: dict) -> dict:
        email = self._normalize_email(str(payload.get("userName") or ""))
        config = self._repository.get_config(owner_id=owner_id)
        default_role = (
            config["default_role"]
            if config and config["default_role"] in SCIM_ROLES
            else "viewer"
        )
        role = self._payload_role(payload, default_role)
        active = bool(payload.get("active", True))
        external_id = self._optional_string(payload.get("externalId"))
        display_name = self._display_name(payload, email)
        row = self._repository.provision_user(
            owner_id=owner_id,
            email=email,
            display_name=display_name,
            password_hash=self._passwords.hash(secrets.token_urlsafe(48)),
            external_id=external_id,
            role=role,
            active=active,
        )
        return self.serialize_user(row)

    def replace_user(
        self,
        *,
        owner_id: str,
        membership_id: str,
        payload: dict,
    ) -> dict:
        existing = self._repository.get_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
        )
        requested_email = self._normalize_email(
            str(payload.get("userName") or existing["email"])
        )
        if requested_email != existing["email"]:
            raise ValueError(
                "SCIM userName changes are not supported for shared user identities"
            )
        role = self._payload_role(payload, existing["role"])
        row = self._repository.update_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
            display_name=self._display_name(payload, existing["email"]),
            external_id=self._optional_string(payload.get("externalId")),
            active=bool(payload.get("active", True)),
            role=role,
        )
        return self.serialize_user(row)

    def patch_user(
        self,
        *,
        owner_id: str,
        membership_id: str,
        payload: dict,
    ) -> dict:
        existing = self._repository.get_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
        )
        display_name = None
        external_id = None
        active = None
        role = None

        operations = payload.get("Operations")
        if not isinstance(operations, list):
            raise ValueError("SCIM PatchOp requires Operations")
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("invalid SCIM patch operation")
            op = str(operation.get("op") or "").lower()
            if op not in {"add", "replace", "remove"}:
                raise ValueError("unsupported SCIM patch operation")
            path = str(operation.get("path") or "").strip()
            value = operation.get("value")

            if not path and isinstance(value, dict):
                if "active" in value:
                    active = bool(value["active"])
                if "displayName" in value:
                    display_name = str(value["displayName"])
                if "externalId" in value:
                    external_id = self._optional_string(value["externalId"])
                if "userName" in value:
                    self._reject_username_change(
                        existing["email"],
                        str(value["userName"]),
                    )
                if "roles" in value:
                    role = self._roles_value(value["roles"], existing["role"])
                continue

            normalized_path = path.lower()
            if normalized_path == "active":
                active = False if op == "remove" else bool(value)
            elif normalized_path == "displayname":
                display_name = "" if op == "remove" else str(value or "")
            elif normalized_path == "externalid":
                external_id = None if op == "remove" else self._optional_string(value)
            elif normalized_path == "username":
                if op == "remove":
                    raise ValueError("SCIM userName cannot be removed")
                self._reject_username_change(existing["email"], str(value or ""))
            elif normalized_path == "roles":
                if op == "remove":
                    config = self._repository.get_config(owner_id=owner_id)
                    role = config["default_role"] if config else "viewer"
                else:
                    role = self._roles_value(value, existing["role"])
            else:
                raise ValueError(f"unsupported SCIM user patch path: {path}")

        row = self._repository.update_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
            display_name=display_name,
            external_id=external_id,
            active=active,
            role=role,
        )
        return self.serialize_user(row)

    def delete_user(self, *, owner_id: str, membership_id: str) -> None:
        self._repository.suspend_scim_user(
            owner_id=owner_id,
            membership_id=membership_id,
        )

    def list_groups(
        self,
        *,
        owner_id: str,
        filter_expression: str | None,
        start_index: int,
        count: int,
    ) -> dict:
        if not filter_expression:
            rows = self._repository.list_groups(owner_id=owner_id)
        else:
            attribute, value = self._parse_filter(filter_expression)
            normalized = attribute.lower()
            if normalized == "displayname":
                rows = self._repository.find_group_by_display_name(
                    owner_id=owner_id,
                    display_name=value,
                )
            elif normalized == "id":
                try:
                    rows = [
                        self._repository.get_group(
                            owner_id=owner_id,
                            group_id=value,
                        )
                    ]
                except KeyError:
                    rows = []
            elif normalized == "externalid":
                rows = [
                    row
                    for row in self._repository.list_groups(owner_id=owner_id)
                    if row["external_id"] == value
                ]
            else:
                raise ValueError("unsupported SCIM Groups filter")
        return self._list_response(
            [self.serialize_group(row) for row in rows],
            start_index=start_index,
            count=count,
        )

    def get_group(self, *, owner_id: str, group_id: str) -> dict:
        return self.serialize_group(
            self._repository.get_group(
                owner_id=owner_id,
                group_id=group_id,
            )
        )

    def create_group(self, *, owner_id: str, payload: dict) -> dict:
        display_name = str(payload.get("displayName") or "").strip()
        if not display_name:
            raise ValueError("SCIM group displayName is required")
        row = self._repository.create_group(
            owner_id=owner_id,
            display_name=display_name,
            external_id=self._optional_string(payload.get("externalId")),
            membership_ids=self._member_ids(payload.get("members")),
        )
        return self.serialize_group(row)

    def replace_group(
        self,
        *,
        owner_id: str,
        group_id: str,
        payload: dict,
    ) -> dict:
        display_name = str(payload.get("displayName") or "").strip()
        if not display_name:
            raise ValueError("SCIM group displayName is required")
        row = self._repository.update_group(
            owner_id=owner_id,
            group_id=group_id,
            display_name=display_name,
            external_id=self._optional_string(payload.get("externalId")),
            membership_ids=self._member_ids(payload.get("members")),
        )
        return self.serialize_group(row)

    def patch_group(
        self,
        *,
        owner_id: str,
        group_id: str,
        payload: dict,
    ) -> dict:
        operations = payload.get("Operations")
        if not isinstance(operations, list):
            raise ValueError("SCIM PatchOp requires Operations")
        current = self._repository.get_group(
            owner_id=owner_id,
            group_id=group_id,
        )
        display_name = None
        external_id = None
        add_ids: list[str] = []
        remove_ids: list[str] = []
        replace_ids: list[str] | None = None

        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("invalid SCIM patch operation")
            op = str(operation.get("op") or "").lower()
            if op not in {"add", "replace", "remove"}:
                raise ValueError("unsupported SCIM patch operation")
            path = str(operation.get("path") or "").strip()
            value = operation.get("value")

            if not path and isinstance(value, dict):
                if "displayName" in value:
                    display_name = str(value["displayName"])
                if "externalId" in value:
                    external_id = self._optional_string(value["externalId"])
                if "members" in value:
                    replace_ids = self._member_ids(value["members"])
                continue

            normalized_path = path.lower()
            member_match = GROUP_MEMBER_FILTER_RE.match(path)
            if normalized_path == "displayname":
                if op == "remove":
                    raise ValueError("SCIM group displayName cannot be removed")
                display_name = str(value or "")
            elif normalized_path == "externalid":
                external_id = None if op == "remove" else self._optional_string(value)
            elif normalized_path == "members":
                ids = self._member_ids(value)
                if op == "remove":
                    remove_ids.extend(ids)
                elif op == "replace":
                    replace_ids = ids
                else:
                    add_ids.extend(ids)
            elif member_match and op == "remove":
                remove_ids.append(member_match.group(1))
            else:
                raise ValueError(f"unsupported SCIM group patch path: {path}")

        if display_name is not None or external_id is not None or replace_ids is not None:
            current = self._repository.update_group(
                owner_id=owner_id,
                group_id=group_id,
                display_name=display_name,
                external_id=external_id,
                membership_ids=replace_ids,
            )
        if add_ids or remove_ids:
            current = self._repository.patch_group_members(
                owner_id=owner_id,
                group_id=group_id,
                add_ids=add_ids,
                remove_ids=remove_ids,
            )
        return self.serialize_group(current)

    def delete_group(self, *, owner_id: str, group_id: str) -> None:
        self._repository.delete_group(owner_id=owner_id, group_id=group_id)

    def list_admin_groups(self, *, owner_id: str) -> list[dict]:
        return self._repository.list_groups(owner_id=owner_id)

    def set_group_role(
        self,
        *,
        owner_id: str,
        group_id: str,
        mapped_role: str | None,
    ) -> dict:
        return self._repository.set_group_role(
            owner_id=owner_id,
            group_id=group_id,
            mapped_role=mapped_role,
        )

    @staticmethod
    def service_provider_config() -> dict:
        return {
            "schemas": [
                "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
            ],
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 200},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "Bearer Token",
                    "description": "Workspace-scoped SCIM provisioning token",
                    "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
                    "primary": True,
                }
            ],
        }

    @staticmethod
    def resource_types() -> dict:
        resources = [
            {
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
                ],
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": SCIM_USER_SCHEMA,
            },
            {
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
                ],
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "schema": SCIM_GROUP_SCHEMA,
            },
        ]
        return {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(resources),
            "startIndex": 1,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }

    @staticmethod
    def schemas() -> dict:
        resources = [
            {
                "id": SCIM_USER_SCHEMA,
                "name": "User",
                "description": "Workspace user",
                "attributes": [
                    {"name": "userName", "type": "string", "required": True},
                    {"name": "displayName", "type": "string"},
                    {"name": "active", "type": "boolean"},
                    {"name": "externalId", "type": "string"},
                    {"name": "roles", "type": "complex", "multiValued": True},
                ],
                "meta": {"resourceType": "Schema"},
            },
            {
                "id": SCIM_GROUP_SCHEMA,
                "name": "Group",
                "description": "Workspace provisioning group",
                "attributes": [
                    {"name": "displayName", "type": "string", "required": True},
                    {"name": "externalId", "type": "string"},
                    {"name": "members", "type": "complex", "multiValued": True},
                ],
                "meta": {"resourceType": "Schema"},
            },
        ]
        return {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(resources),
            "startIndex": 1,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }

    @staticmethod
    def serialize_user(row: dict) -> dict:
        return {
            "schemas": [SCIM_USER_SCHEMA],
            "id": row["membership_id"],
            **({"externalId": row["external_id"]} if row["external_id"] else {}),
            "userName": row["email"],
            "displayName": row["display_name"],
            "name": {"formatted": row["display_name"]},
            "active": row["active"],
            "roles": [
                {
                    "value": row["role"],
                    "display": row["role"],
                    "primary": True,
                }
            ],
            "meta": {
                "resourceType": "User",
                "created": row["created_at"],
                "lastModified": row["updated_at"],
            },
        }

    @staticmethod
    def serialize_group(row: dict) -> dict:
        return {
            "schemas": [SCIM_GROUP_SCHEMA],
            "id": row["id"],
            **({"externalId": row["external_id"]} if row["external_id"] else {}),
            "displayName": row["display_name"],
            "members": [
                {
                    "value": member["membership_id"],
                    "display": member["email"],
                }
                for member in row["members"]
            ],
            "meta": {
                "resourceType": "Group",
                "created": row["created_at"],
                "lastModified": row["updated_at"],
            },
        }

    @staticmethod
    def _public_config(config: dict) -> dict:
        return {
            "owner_id": config["owner_id"],
            "enabled": config["enabled"],
            "default_role": config["default_role"],
            "token_prefix": config["token_prefix"],
            "has_token": bool(config["token_hash"]),
            "created_at": config["created_at"],
            "updated_at": config["updated_at"],
        }

    @staticmethod
    def _parse_filter(expression: str) -> tuple[str, str]:
        match = FILTER_RE.match(expression)
        if not match:
            raise ValueError("unsupported SCIM filter expression")
        return match.group(1), match.group(2)

    @staticmethod
    def _list_response(
        resources: list[dict],
        *,
        start_index: int,
        count: int,
    ) -> dict:
        start = max(start_index, 1)
        size = min(max(count, 0), 200)
        offset = start - 1
        page = resources[offset : offset + size]
        return {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(resources),
            "startIndex": start,
            "itemsPerPage": len(page),
            "Resources": page,
        }

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if (
            not normalized
            or "@" not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
        ):
            raise ValueError("SCIM userName must be a valid email address")
        return normalized

    @staticmethod
    def _optional_string(value) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @classmethod
    def _display_name(cls, payload: dict, email: str) -> str:
        direct = str(payload.get("displayName") or "").strip()
        if direct:
            return direct[:200]
        name = payload.get("name")
        if isinstance(name, dict):
            formatted = str(name.get("formatted") or "").strip()
            if formatted:
                return formatted[:200]
            parts = [
                str(name.get("givenName") or "").strip(),
                str(name.get("familyName") or "").strip(),
            ]
            joined = " ".join(part for part in parts if part)
            if joined:
                return joined[:200]
        return email.split("@", 1)[0][:200]

    @classmethod
    def _payload_role(cls, payload: dict, fallback: str) -> str:
        return cls._roles_value(payload.get("roles"), fallback)

    @staticmethod
    def _roles_value(value, fallback: str) -> str:
        if value is None:
            return fallback if fallback in SCIM_ROLES else "viewer"
        items = value if isinstance(value, list) else [value]
        candidates: list[str] = []
        for item in items:
            if isinstance(item, dict):
                role = str(item.get("value") or item.get("display") or "").lower()
            else:
                role = str(item).lower()
            if role == "owner":
                raise ValueError("SCIM cannot provision owner role")
            if role in SCIM_ROLES:
                candidates.append(role)
        if not candidates:
            return fallback if fallback in SCIM_ROLES else "viewer"
        priority = {"admin": 3, "analyst": 2, "viewer": 1}
        return max(candidates, key=lambda item: priority[item])

    @staticmethod
    def _member_ids(value) -> list[str]:
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in items:
            if isinstance(item, dict):
                member_id = str(item.get("value") or "").strip()
            else:
                member_id = str(item).strip()
            if member_id:
                result.append(member_id)
        return list(dict.fromkeys(result))

    @classmethod
    def _reject_username_change(cls, existing: str, requested: str) -> None:
        if cls._normalize_email(requested) != existing:
            raise ValueError(
                "SCIM userName changes are not supported for shared user identities"
            )
