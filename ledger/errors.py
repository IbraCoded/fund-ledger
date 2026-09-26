class LedgerError(Exception):
    """Base for expected, business-level failures. Carries its own HTTP mapping."""

    code = "ledger_error"
    http_status = 400


class InvalidTransfer(LedgerError):
    code = "invalid_transfer"


class UnbalancedTransfer(InvalidTransfer):
    code = "unbalanced_transfer"


class UnknownAccount(InvalidTransfer):
    code = "unknown_account"


class InsufficientFunds(LedgerError):
    code = "insufficient_funds"
    http_status = 409


class ClosedPeriod(LedgerError):
    code = "period_closed"
    http_status = 409


class IdempotencyConflict(LedgerError):
    code = "idempotency_conflict"
    http_status = 422


class AlreadyReversed(LedgerError):
    code = "already_reversed"
    http_status = 409


class MissingFxRate(LedgerError):
    code = "missing_fx_rate"
    http_status = 422
