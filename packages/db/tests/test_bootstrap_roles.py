from unittest.mock import MagicMock

import pytest

from clinic_db import bootstrap_roles


@pytest.mark.parametrize("auth_role", [None, (False,), (True,)])
def test_auth_role_is_provisioned_without_rotating_existing_login(monkeypatch, auth_role):
    monkeypatch.setenv("DATABASE_OWNER_URL", "postgresql+psycopg://owner:example@localhost/clinic")
    monkeypatch.setenv("CLINIC_AUTH_PASSWORD", "managed-auth-password")
    conn = MagicMock()
    conn.info.dbname = "clinic"
    queries = []

    def execute(statement, params=None):
        rendered = statement if isinstance(statement, str) else statement.as_string()
        queries.append(rendered)
        result = MagicMock()
        result.fetchone.return_value = auth_role if params == ("clinic_auth",) else (True,)
        return result

    conn.execute.side_effect = execute
    connection = MagicMock()
    connection.__enter__.return_value = conn
    monkeypatch.setattr(bootstrap_roles.psycopg, "connect", lambda *args, **kwargs: connection)
    assert bootstrap_roles.main() == 0
    changes = [query for query in queries if query.startswith(("CREATE ROLE", "ALTER ROLE"))]
    if auth_role == (True,):
        assert changes == []
    else:
        assert len(changes) == 1
        assert '"clinic_auth" LOGIN PASSWORD' in changes[0]
        assert "managed-auth-password" in changes[0]
        assert "BYPASSRLS" not in changes[0]
    assert 'GRANT CONNECT ON DATABASE "clinic" TO "clinic_auth"' in queries
