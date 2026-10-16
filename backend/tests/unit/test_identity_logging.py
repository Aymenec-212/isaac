"""Authorization codes and state must not reach Uvicorn access logs."""

import logging

from mosaique.observability.logging import RedactAccessQuery


def test_query_secrets_are_removed_from_access_log():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("local", "GET", "/auth/callback?code=secret&state=private", "1.1", 302),
        None,
    )
    assert RedactAccessQuery().filter(record)
    assert "secret" not in record.getMessage()
    assert "private" not in record.getMessage()
    assert "/auth/callback" in record.getMessage()
