"""Bounded, policy-checked Argon2id password helpers."""

import os
import threading
import unicodedata

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHash, VerificationError


_PASSWORD_HASHER = PasswordHasher(type=Type.ID)
ARGON2_CONCURRENCY_ENV = "EKIP_ARGON2_MAX_CONCURRENCY"
_DEFAULT_ARGON2_CONCURRENCY = 4
_MAX_ARGON2_CONCURRENCY = 16


def argon2_concurrency_from_environment() -> int:
    """Return the cap on simultaneous Argon2 verifications (each uses ~64 MiB by default)."""
    raw = os.environ.get(ARGON2_CONCURRENCY_ENV)
    if raw is None:
        return _DEFAULT_ARGON2_CONCURRENCY
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if not 1 <= value <= _MAX_ARGON2_CONCURRENCY:
        raise ValueError(
            f"{ARGON2_CONCURRENCY_ENV} must be an integer between 1 and {_MAX_ARGON2_CONCURRENCY}."
        )
    return value


# Process-wide cap (single-worker deployment) so a login flood cannot exhaust memory or CPU.
_VERIFY_SLOTS = threading.BoundedSemaphore(argon2_concurrency_from_environment())
MIN_PASSWORD_CODEPOINTS = 15
MAX_PASSWORD_CODEPOINTS = 128
MAX_PASSWORD_UTF8_BYTES = 512

# Offline whole-password denylist. It deliberately avoids a runtime breach
# lookup, which would disclose password-derived data and make account setup
# depend on a third-party service. Extend through reviewed source updates.
_COMMON_PASSWORDS = frozenset(
    {
        "passwordpassword",
        "password12345678",
        "password123456789",
        "qwertyuiopasdfg",
        "123456789012345",
        "1234567890123456",
        "welcome12345678",
        "adminadminadmin",
        "changemechangeme",
        "correcthorsebatterystaple",
        "iloveyouiloveyou",
        "footballfootball",
        "monkeymonkey123",
        "sunshine12345678",
        "trustno1trustno1",
        "letmeinletmein123",
        "passw0rdpassw0rd",
        "abc123abc123abc",
        "123qwe123qwe123",
        "welcomehome1234",
    }
)


class PasswordPolicyError(ValueError):
    """Password rejected by policy without including its value."""


def _password_utf8(password: object) -> bytes:
    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be text.")
    if len(password) > MAX_PASSWORD_CODEPOINTS:
        raise PasswordPolicyError("Password exceeds the maximum permitted length.")
    try:
        encoded = password.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise PasswordPolicyError("Password contains invalid Unicode.") from None
    if len(encoded) > MAX_PASSWORD_UTF8_BYTES:
        raise PasswordPolicyError("Password exceeds the maximum permitted length.")
    return encoded


def validate_new_password(password: object) -> str:
    """Validate a new password using code-point length and exact input bytes.

    Passwords are not trimmed, truncated, or Unicode-normalized. NFC variants
    therefore remain distinct secrets; this rule is shared by hashing and
    verification so accepted values are unambiguous.
    """
    _password_utf8(password)
    assert isinstance(password, str)
    if len(password) < MIN_PASSWORD_CODEPOINTS:
        raise PasswordPolicyError(
            f"Password must contain at least {MIN_PASSWORD_CODEPOINTS} characters."
        )
    if unicodedata.normalize("NFC", password).casefold() in _COMMON_PASSWORDS:
        raise PasswordPolicyError("Choose a password that is not commonly used.")
    return password


def hash_password(password: str) -> str:
    """Return a salted Argon2id hash after bounded policy validation."""
    return _PASSWORD_HASHER.hash(validate_new_password(password))


def verify_password(password: object, encoded_hash: object) -> bool:
    """Verify credentials without raising for absent or malformed inputs."""
    if not isinstance(encoded_hash, str) or not encoded_hash:
        return False
    try:
        _password_utf8(password)
    except PasswordPolicyError:
        return False
    if not isinstance(password, str) or not password:
        return False
    try:
        with _VERIFY_SLOTS:
            return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (VerificationError, InvalidHash):
        return False
