"""The least-privilege database role the running application connects as.

Migrations run as the owner. The API process connects as the app role, which can read
and write ordinary tables but cannot UPDATE or DELETE ledger rows, TRUNCATE anything,
change the schema, or disable the triggers that enforce the ledger's invariants.
"""

from django.db import connection
from psycopg import sql

APPEND_ONLY_TABLES = ("ledger_entry", "ledger_transfer")
READ_ONLY_TABLES = ("django_migrations",)

# Fail fast rather than queue behind a hot lock, and never sit idle holding locks.
ROLE_SETTINGS = {
    "statement_timeout": "5s",
    "lock_timeout": "3s",
    "idle_in_transaction_session_timeout": "30s",
}


def _render(statement: sql.Composable) -> str:
    """Render with proper identifier/literal quoting (never string-format SQL by hand)."""
    connection.ensure_connection()
    return statement.as_string(connection.connection)


def _tables(names: tuple[str, ...]) -> sql.Composable:
    return sql.SQL(", ").join(sql.Identifier(n) for n in names)


def ensure_login_role(role: str, password: str) -> None:
    ident = sql.Identifier(role)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        verb = sql.SQL("ALTER" if cursor.fetchone() else "CREATE")
        cursor.execute(
            _render(
                sql.SQL(
                    "{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                ).format(verb, ident, sql.Literal(password))
            )
        )
        for name, value in ROLE_SETTINGS.items():
            cursor.execute(
                _render(
                    sql.SQL("ALTER ROLE {} SET {} = {}").format(
                        ident, sql.Identifier(name), sql.Literal(value)
                    )
                )
            )


def apply_grants(role: str) -> None:
    """Idempotent: revoke everything, then grant exactly what the app needs."""
    r = sql.Identifier(role)
    db = sql.Identifier(connection.settings_dict["NAME"])
    statements = [
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(r),
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(r),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, r),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(r),
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(r),
        sql.SQL("REVOKE UPDATE, DELETE ON {} FROM {}").format(_tables(APPEND_ONLY_TABLES), r),
        sql.SQL("REVOKE INSERT, UPDATE, DELETE ON {} FROM {}").format(_tables(READ_ONLY_TABLES), r),
    ]
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(_render(statement))
