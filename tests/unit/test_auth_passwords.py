import pytest

from src.auth.passwords import PasswordPolicyError, hash_password, verify_password


VALID_PASSWORD = "violet-cactus-orbit-sailed"


def test_passwords_are_hashed_with_argon2id_and_verify():
    encoded_hash = hash_password(VALID_PASSWORD)

    assert encoded_hash.startswith("$argon2id$")
    assert encoded_hash != VALID_PASSWORD
    assert verify_password(VALID_PASSWORD, encoded_hash)


def test_each_password_hash_uses_a_distinct_salt():
    assert hash_password(VALID_PASSWORD) != hash_password(VALID_PASSWORD)


def test_incorrect_password_is_rejected():
    assert not verify_password("wrong password", hash_password(VALID_PASSWORD))


@pytest.mark.parametrize("password", ["short", "a" * 14])
def test_passwords_shorter_than_fifteen_codepoints_are_rejected(password):
    with pytest.raises(PasswordPolicyError, match="at least 15"):
        hash_password(password)


@pytest.mark.parametrize(
    "password", ["a" * 129, "é" * 129, "\ud800" + "a" * 14]
)
def test_oversized_or_malformed_unicode_passwords_are_rejected(password):
    with pytest.raises(PasswordPolicyError):
        hash_password(password)
    assert not verify_password(password, "$argon2id$malformed")


@pytest.mark.parametrize(
    "password", ["password12345678", "PASSWORD12345678", "correcthorsebatterystaple"]
)
def test_common_passwords_are_rejected_without_revealing_password(password):
    with pytest.raises(PasswordPolicyError) as error:
        hash_password(password)
    assert password not in str(error.value)


def test_unicode_password_limit_uses_codepoints_and_utf8_bytes():
    password = "🔒" * 128
    assert verify_password(password, hash_password(password))
    assert not verify_password("🔒" * 129, "$argon2id$malformed")


@pytest.mark.parametrize(
    ("password", "encoded_hash"),
    [
        (None, "$argon2id$malformed"),
        ("", "$argon2id$malformed"),
        ("password", None),
        ("password", ""),
        ("password", "not-a-password-hash"),
        ("password", "$argon2id$malformed"),
        ([], "$argon2id$malformed"),
        ("password", object()),
    ],
)
def test_missing_or_malformed_credentials_fail_safely(password, encoded_hash):
    assert verify_password(password, encoded_hash) is False


@pytest.mark.parametrize("password", [None, "", [], 12])
def test_hashing_rejects_missing_or_non_text_passwords(password):
    with pytest.raises(PasswordPolicyError):
        hash_password(password)
