import pytest

from src.auth.database import database_url_from_environment


def test_database_url_requires_explicit_environment_configuration():
    with pytest.raises(RuntimeError, match="must be configured explicitly"):
        database_url_from_environment({})
    with pytest.raises(RuntimeError, match="must be configured explicitly"):
        database_url_from_environment({"EKIP_DATABASE_URL": "  "})


def test_database_url_only_accepts_postgresql_psycopg_without_connecting():
    url = database_url_from_environment(
        {
            "EKIP_DATABASE_URL":
                "postgresql+psycopg://test_user:test_password@127.0.0.1:5432/isolated_auth_test"
        }
    )

    assert url.drivername == "postgresql+psycopg"
    assert url.database == "isolated_auth_test"
    assert url.render_as_string(hide_password=True).endswith("/isolated_auth_test")


@pytest.mark.parametrize(
    "value",
    [
        "not a SQLAlchemy URL",
        "sqlite+pysqlite:///:memory:",
        "postgresql://user:password@127.0.0.1/test",
        "postgresql+psycopg:///missing_host",
        "postgresql+psycopg://127.0.0.1/",
    ],
)
def test_database_url_rejects_malformed_or_unsupported_configuration(value):
    with pytest.raises(RuntimeError):
        database_url_from_environment({"EKIP_DATABASE_URL": value})
