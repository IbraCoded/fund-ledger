from ledger.errors import LedgerError


class CommitmentExceeded(LedgerError):
    code = "commitment_exceeded"
    http_status = 409


class NoPeriod(LedgerError):
    code = "no_period"
    http_status = 409


class PeriodNotClosable(LedgerError):
    code = "period_not_closable"
    http_status = 409
