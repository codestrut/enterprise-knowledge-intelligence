from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.auth.access_tokens import (
    ACCESS_TOKEN_TTL,
    AccessTokenError,
    decode_access_token,
    issue_access_token,
)
from src.auth.permissions import Permission, Role
from src.auth.service import AuthenticatedPrincipal


SECRET = "test-only-secret-material-longer-than-32-bytes"


def principal():
    return AuthenticatedPrincipal(
        user_id=uuid4(),
        membership_id=uuid4(),
        organisation_id=uuid4(),
        role=Role.READER,
        permissions=frozenset({Permission.DOCUMENTS_READ}),
    )


def test_access_token_round_trips_scoped_ids_and_short_expiry():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    value = principal()
    family_id = uuid4()
    issued = issue_access_token(value, family_id, secret=SECRET, now=now)

    claims = decode_access_token(issued.token, secret=SECRET, now=now + timedelta(seconds=1))

    assert claims.user_id == value.user_id
    assert claims.membership_id == value.membership_id
    assert claims.organisation_id == value.organisation_id
    assert claims.family_id == family_id
    assert issued.expires_at - now == ACCESS_TOKEN_TTL


@pytest.mark.parametrize("token", [None, "", "a.b", "not-a-token", "x" * 2049])
def test_malformed_access_tokens_are_rejected_without_echoing_value(token):
    with pytest.raises(AccessTokenError) as exc:
        decode_access_token(token, secret=SECRET)
    assert str(exc.value) == "Invalid access token."


def test_tampered_and_expired_access_tokens_are_rejected():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    issued = issue_access_token(principal(), uuid4(), secret=SECRET, now=now)
    body, signature = issued.token.split(".")
    changed = "A" if signature[-1] != "A" else "B"

    with pytest.raises(AccessTokenError):
        decode_access_token(f"{body}.{signature[:-1]}{changed}", secret=SECRET, now=now)
    with pytest.raises(AccessTokenError):
        decode_access_token(issued.token, secret=SECRET, now=now + ACCESS_TOKEN_TTL)


def test_access_token_requires_a_strong_configured_secret():
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        issue_access_token(principal(), uuid4(), secret="too-short")



def test_noncanonical_base64_signature_encoding_is_rejected():
    issued = issue_access_token(principal(), uuid4(), secret=SECRET)
    body, signature = issued.token.split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last_index = alphabet.index(signature[-1])
    # For a 32-byte HMAC, the last base64 character has four unused low bits.
    # Changing one of those bits preserves the decoded signature bytes.
    alternate_signature = signature[:-1] + alphabet[last_index ^ 1]

    with pytest.raises(AccessTokenError):
        decode_access_token(f"{body}.{alternate_signature}", secret=SECRET)
