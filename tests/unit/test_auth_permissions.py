import pytest

from src.auth.permissions import (
    PLATFORM_ADMINISTRATOR_PERMISSIONS,
    Permission,
    PlatformPermission,
    Role,
    permissions_for_role,
    platform_permissions_for_user,
    role_allows,
)


def test_organisation_administrator_has_all_defined_permissions():
    assert permissions_for_role(Role.ORGANISATION_ADMINISTRATOR) == frozenset(
        Permission
    )


def test_contributor_can_manage_documents_but_not_members_or_authentication():
    assert permissions_for_role(Role.CONTRIBUTOR) == frozenset(
        {
            Permission.DOCUMENTS_READ,
            Permission.DOCUMENTS_QUERY,
            Permission.DOCUMENTS_UPLOAD,
            Permission.DOCUMENTS_DELETE,
        }
    )


def test_reader_is_limited_to_document_read_and_query():
    assert permissions_for_role(Role.READER) == frozenset(
        {Permission.DOCUMENTS_READ, Permission.DOCUMENTS_QUERY}
    )


def test_platform_permissions_are_user_scoped_and_do_not_include_customer_content():
    assert platform_permissions_for_user(False) == frozenset()
    assert platform_permissions_for_user(True) == PLATFORM_ADMINISTRATOR_PERMISSIONS
    assert PlatformPermission.ORGANISATIONS_CREATE in PLATFORM_ADMINISTRATOR_PERMISSIONS
    assert PlatformPermission.ORGANISATIONS_SUSPEND in PLATFORM_ADMINISTRATOR_PERMISSIONS
    assert not any("documents:" in permission.value for permission in PLATFORM_ADMINISTRATOR_PERMISSIONS)


def test_platform_role_cannot_be_assigned_as_an_organisation_role():
    with pytest.raises(ValueError):
        Role("platform_administrator")


def test_role_permission_check_accepts_enum_and_string_values():
    assert role_allows(Role.READER, Permission.DOCUMENTS_QUERY)
    assert role_allows("reader", "documents:query")
    assert not role_allows("reader", "documents:delete")


def test_unknown_roles_and_permissions_fail_closed():
    with pytest.raises(ValueError, match="Unknown EKIP role"):
        permissions_for_role("unknown")
    with pytest.raises(ValueError, match="Unknown EKIP permission"):
        role_allows(Role.READER, "documents:export")


def test_role_permission_bundles_are_immutable():
    with pytest.raises(AttributeError):
        permissions_for_role(Role.READER).add(Permission.DOCUMENTS_DELETE)
