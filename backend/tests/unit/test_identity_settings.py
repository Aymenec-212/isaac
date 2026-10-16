"""Identity deployment configuration must fail closed before serving pilot traffic."""

import pytest
from pydantic import ValidationError

from mosaique.config.settings import Settings


def settings(**overrides):
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test:test@localhost/test",
        token_secret="dummy-test-signing-value-at-least-32-characters",
        **{"application_mode": "enterprise", **overrides},
    )


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "pilot"},
        {
            "environment": "pilot",
            "public_origin": "https://app.test",
            "application_mode": "prototype",
        },
        {"public_origin": "https://app.test/path"},
        {"public_origin": "https://user@app.test"},
        {"oidc_issuer": "https://issuer.test/"},
        {
            "oidc_issuer": "http://issuer.test/",
            "oidc_client_id": "test",
            "oidc_client_secret": "dummy",
        },
        {
            "oidc_issuer": "https://issuer.test/wrong/",
            "oidc_client_id": "test",
            "oidc_client_secret": "dummy",
        },
    ],
)
def test_invalid_identity_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        settings(**values)


def test_explicit_enterprise_pilot_configuration():
    result = settings(
        environment="pilot",
        public_origin="https://app.test",
        oidc_issuer="https://issuer.test/",
        oidc_client_id="test",
        oidc_client_secret="dummy",
    )
    assert result.application_mode == "enterprise"


def test_oidc_secret_is_redacted_in_configuration_diagnostics():
    secret = "dummy-oidc-secret-never-print"
    configured = settings(
        public_origin="https://app.test",
        oidc_issuer="https://issuer.test/",
        oidc_client_id="test",
        oidc_client_secret=secret,
    )
    assert secret not in repr(configured)
    with pytest.raises(ValidationError) as error:
        settings(
            public_origin="bad origin",
            oidc_issuer="https://issuer.test/",
            oidc_client_id="test",
            oidc_client_secret=secret,
        )
    assert secret not in str(error.value)
