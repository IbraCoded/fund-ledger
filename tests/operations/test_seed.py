import pytest
from django.core.management import call_command

from funds.models import Commitment, Fund, LimitedPartner, Period
from ledger.models import Transfer
from ledger.reconciliation import total_imbalance
from operations.models import CapitalCall, Distribution

pytestmark = pytest.mark.django_db


def test_seed_is_repeatable():
    call_command("seed_demo")
    call_command("seed_demo")
    assert Fund.objects.count() == 1
    assert LimitedPartner.objects.count() == 10
    assert Commitment.objects.count() == 10
    assert Period.objects.count() == 8
    assert CapitalCall.objects.count() == 2
    assert Distribution.objects.count() == 1
    assert Transfer.objects.count() == 6
    assert total_imbalance() == 0
