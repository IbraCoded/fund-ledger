"""Each fund's standard chart of accounts, and lookups into it."""

from uuid import UUID

from funds.models import Fund, LimitedPartner
from ledger.models import Account, AccountType


def account_code(account_type: str, *, currency: str, lp: LimitedPartner | None = None) -> str:
    if account_type == AccountType.LP_CAPITAL:
        assert lp is not None  # noqa: S101 (assertion is valid here)
        return f"LP-{lp.id.hex}"
    if account_type in (AccountType.CASH, AccountType.INVESTMENT):
        return f"{account_type}-{currency}"
    return str(account_type)


def ensure_account(fund: Fund, account_type: str, currency: str | None = None) -> Account:
    currency = currency or fund.base_currency
    account, _ = Account.objects.get_or_create(
        fund=fund,
        code=account_code(account_type, currency=currency),
        defaults={"account_type": account_type, "currency": currency},
    )
    return account


def open_fund_accounts(fund: Fund) -> None:
    """Create the fund's standard accounts. Idempotent."""
    for account_type in (
        AccountType.CASH,
        AccountType.INVESTMENT,
        AccountType.FEE_EXPENSE,
        AccountType.GAIN_LOSS,
        AccountType.GP_CAPITAL,
    ):
        ensure_account(fund, account_type)
    for commitment in fund.commitments.select_related("lp"):
        Account.objects.get_or_create(
            fund=fund,
            code=account_code(
                AccountType.LP_CAPITAL, currency=fund.base_currency, lp=commitment.lp
            ),
            defaults={
                "account_type": AccountType.LP_CAPITAL,
                "currency": fund.base_currency,
                "owner_lp": commitment.lp,
            },
        )


def get_account(fund: Fund, account_type: str, currency: str | None = None) -> Account:
    code = account_code(account_type, currency=currency or fund.base_currency)
    return Account.objects.get(fund=fund, code=code)


def lp_capital_accounts(fund: Fund) -> dict[UUID, Account]:
    accounts = Account.objects.filter(
        fund=fund, account_type=AccountType.LP_CAPITAL, currency=fund.base_currency
    )
    return {a.owner_lp_id: a for a in accounts if a.owner_lp_id is not None}
