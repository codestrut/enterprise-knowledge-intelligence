"""Canonical roles and permissions for server-side authorization.

These bundles describe what a role may do within its assigned scope. They do
not establish an identity or organisation membership; request authorization
must validate those separately before checking a permission.
"""

from enum import StrEnum
from types import MappingProxyType


class Permission(StrEnum):
    """Organisation-scoped operations assigned through membership roles."""

    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_QUERY = "documents:query"
    DOCUMENTS_UPLOAD = "documents:upload"
    DOCUMENTS_DELETE = "documents:delete"
    MEMBERS_MANAGE = "members:manage"
    AUTH_CONFIGURE = "auth:configure"
    AUDIT_READ = "audit:read"
    TENANT_READ = "tenant:read"


class PlatformPermission(StrEnum):
    """Platform-scoped operations, never granted by an organisation role."""

    ORGANISATIONS_READ = "organisations:read"
    ORGANISATIONS_CREATE = "organisations:create"
    ORGANISATIONS_APPROVE = "organisations:approve"
    PROVISIONING_RETRY = "organisations:provisioning-retry"
    PROVISIONING_RECOVER = "organisations:provisioning-recover"
    ORGANISATIONS_SUSPEND = "organisations:suspend"
    PLATFORM_ROLES_ASSIGN = "platform-roles:assign"
    USERS_MANAGE = "platform-users:manage"
    AUDIT_READ = "platform-audit:read"


class PlatformRole(StrEnum):
    """Small, explicit platform role profiles; assignments are user-scoped."""

    SUPER_ADMINISTRATOR = "platform_super_administrator"
    TENANT_CREATOR = "platform_tenant_creator"
    TENANT_APPROVER = "platform_tenant_approver"
    PROVISIONING_OPERATOR = "platform_provisioning_operator"


class Role(StrEnum):
    """Built-in EKIP roles."""

    ORGANISATION_ADMINISTRATOR = "organisation_administrator"
    CONTRIBUTOR = "contributor"
    READER = "reader"


_DOCUMENT_OPERATIONS = frozenset(
    {
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_QUERY,
        Permission.DOCUMENTS_UPLOAD,
        Permission.DOCUMENTS_DELETE,
    }
)

ROLE_PERMISSIONS = MappingProxyType(
    {
        Role.ORGANISATION_ADMINISTRATOR: frozenset(
            {
                *_DOCUMENT_OPERATIONS,
                Permission.MEMBERS_MANAGE,
                Permission.AUTH_CONFIGURE,
                Permission.AUDIT_READ,
                Permission.TENANT_READ,
            }
        ),
        Role.CONTRIBUTOR: frozenset({*_DOCUMENT_OPERATIONS, Permission.TENANT_READ}),
        Role.READER: frozenset(
            {Permission.DOCUMENTS_READ, Permission.DOCUMENTS_QUERY, Permission.TENANT_READ}
        ),
    }
)

PLATFORM_ROLE_PERMISSIONS = MappingProxyType(
    {
        PlatformRole.SUPER_ADMINISTRATOR: frozenset(PlatformPermission),
        PlatformRole.TENANT_CREATOR: frozenset({PlatformPermission.ORGANISATIONS_READ, PlatformPermission.ORGANISATIONS_CREATE}),
        PlatformRole.TENANT_APPROVER: frozenset({PlatformPermission.ORGANISATIONS_READ, PlatformPermission.ORGANISATIONS_APPROVE}),
        PlatformRole.PROVISIONING_OPERATOR: frozenset({
            PlatformPermission.ORGANISATIONS_READ,
            PlatformPermission.PROVISIONING_RETRY,
            PlatformPermission.PROVISIONING_RECOVER,
        }),
    }
)

# Backward-compatible bootstrap: the legacy flag is treated as the super-admin
# role until explicit role assignments are rolled out to existing operators.
PLATFORM_ADMINISTRATOR_PERMISSIONS = PLATFORM_ROLE_PERMISSIONS[PlatformRole.SUPER_ADMINISTRATOR]


def permissions_for_platform_role(role: PlatformRole | str) -> frozenset[PlatformPermission]:
    try:
        normalized_role = role if isinstance(role, PlatformRole) else PlatformRole(role)
    except ValueError as exc:
        raise ValueError(f"Unknown platform role: {role!r}") from exc
    return PLATFORM_ROLE_PERMISSIONS[normalized_role]


def permissions_for_role(role: Role | str) -> frozenset[Permission]:
    """Return the immutable permission bundle for a known built-in role."""
    try:
        normalized_role = role if isinstance(role, Role) else Role(role)
    except ValueError as exc:
        raise ValueError(f"Unknown EKIP role: {role!r}") from exc
    return ROLE_PERMISSIONS[normalized_role]


def role_allows(role: Role | str, permission: Permission | str) -> bool:
    """Check a role bundle; identity and scope validation remain separate."""
    try:
        normalized_permission = (
            permission
            if isinstance(permission, Permission)
            else Permission(permission)
        )
    except ValueError as exc:
        raise ValueError(f"Unknown EKIP permission: {permission!r}") from exc
    return normalized_permission in permissions_for_role(role)


def platform_permissions_for_user(is_platform_admin: bool) -> frozenset[PlatformPermission]:
    """Resolve global permissions from user-level platform assignment only."""
    if is_platform_admin is not True:
        return frozenset()
    return PLATFORM_ADMINISTRATOR_PERMISSIONS
