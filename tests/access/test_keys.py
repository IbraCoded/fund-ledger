import hashlib
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from access.keys import issue_key, verify_key
from access.models import ApiKey, FundMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create(username="alice")


def test_issued_key_verifies(user):
    api_key, raw = issue_key(user, name="laptop")
    assert raw.startswith(f"fl_{api_key.prefix}.")
    assert verify_key(raw) == api_key


def test_raw_secret_is_never_stored(user):
    api_key, raw = issue_key(user, name="laptop")
    secret = raw.split(".", 1)[1]
    row = ApiKey.objects.filter(pk=api_key.pk).values().get()
    assert all(secret not in str(value) for value in row.values())
    assert row["key_hash"] == hashlib.sha256(secret.encode()).hexdigest()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw[:-1] + ("A" if raw[-1] != "A" else "B"),  # wrong secret
        lambda raw: "fl_000000000000." + raw.split(".", 1)[1],  # unknown prefix
        lambda raw: raw.replace(".", ""),  # no separator
        lambda raw: raw.removeprefix("fl_"),  # no scheme prefix
        lambda raw: "",
    ],
)
def test_tampered_keys_do_not_verify(user, mutate):
    _, raw = issue_key(user, name="laptop")
    assert verify_key(mutate(raw)) is None


def test_revoked_expired_and_inactive_keys_do_not_verify(user):
    _, revoked = issue_key(user, name="a")
    ApiKey.objects.filter(name="a").update(revoked_at=timezone.now())
    _, expired = issue_key(user, name="b", expires_at=timezone.now() - timedelta(seconds=1))
    _, live = issue_key(user, name="c")
    assert verify_key(revoked) is None
    assert verify_key(expired) is None
    assert verify_key(live) is not None
    user.is_active = False
    user.save()
    assert verify_key(live) is None


def test_hash_column_cannot_hold_a_raw_key(user):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        ApiKey.objects.create(user=user, name="x", prefix="abc", key_hash="fl_abc.not-a-hash")


def test_key_commands_round_trip(pe):
    call_command("grant_access", "bob", "--fund", str(pe.fund.id), "--role", "VIEWER")
    assert FundMembership.objects.get(user__username="bob").role == "VIEWER"

    out = StringIO()
    call_command("create_api_key", "bob", "--name", "cli", stdout=out, stderr=StringIO())
    raw = out.getvalue().strip().splitlines()[-1]
    api_key = verify_key(raw)
    assert api_key is not None

    call_command("revoke_api_key", api_key.prefix, stdout=StringIO())
    assert verify_key(raw) is None


def test_lp_role_requires_an_lp_with_a_commitment(pe):
    with pytest.raises(CommandError, match="--lp is required"):
        call_command("grant_access", "carol", "--fund", str(pe.fund.id), "--role", "LP")
    with pytest.raises(CommandError, match="no commitment"):
        call_command(
            "grant_access",
            "carol",
            "--fund",
            str(pe.fund.id),
            "--role",
            "LP",
            "--lp",
            "00000000-0000-0000-0000-000000000000",  # not a committed LP
        )
