from contextlib import contextmanager
from decimal import Decimal as D

import pytest
from django.db import DatabaseError, connection, transaction

from ledger.db_roles import apply_grants, ensure_login_role
from ledger.queries import native_balance
from ledger.services import post_transfer
from tests.factories import two_legs

pytestmark = pytest.mark.django_db

ROLE = "ledger_app_test"


@pytest.fixture
def app_role(world):
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {ROLE} NOLOGIN")
    apply_grants(ROLE)
    return ROLE


@contextmanager
def acting_as(role):
    """Run statements as `role` inside a savepoint; a failure rolls the role switch back too."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL ROLE {role}")
        yield cursor
        cursor.execute("RESET ROLE")


def test_app_role_can_do_its_whole_job(world, app_role):
    """Locks (FOR UPDATE / FOR SHARE), inserts, triggers and reads all work with least privilege."""
    with acting_as(app_role):
        post_transfer(
            idempotency_key="as-app",
            legs=two_legs(world.equity, world.cash, D("10")),
            period=world.period,
            transfer_type="ADJUSTMENT",
        )
        assert native_balance(world.cash.id) == D("10")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_entry SET amount = amount",
        "DELETE FROM ledger_entry",
        "UPDATE ledger_transfer SET description = 'edited'",
        "DELETE FROM ledger_transfer",
        "TRUNCATE ledger_entry",
        "ALTER TABLE ledger_entry DISABLE TRIGGER ALL",
        "DROP TABLE ledger_entry",
        "CREATE TABLE sneaky (id int)",
        "DELETE FROM django_migrations",
    ],
)
def test_app_role_cannot_tamper_with_the_ledger(app_role, statement):
    with (
        pytest.raises(DatabaseError, match="permission denied|must be owner"),
        acting_as(app_role) as cursor,
    ):
        cursor.execute(statement)


def test_login_role_is_unprivileged_with_timeouts():
    ensure_login_role("ledger_app_test_login", "test-password")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolconfig "
            "FROM pg_roles WHERE rolname = %s",
            ["ledger_app_test_login"],
        )
        superuser, createrole, createdb, login, config = cursor.fetchone()
    assert (superuser, createrole, createdb, login) == (False, False, False, True)
    assert {"statement_timeout=5s", "lock_timeout=3s"} <= set(config)
