"""Independent checks that the books balance.

Deliberately raw SQL on the raw columns, not the ORM and not the generated
signed_* columns: the checker should share as little code as possible with the thing
it checks. If the ORM layer or the generated column had a bug, this still wouldn't.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db import connection

SIGNED = "CASE WHEN e.direction = 'DEBIT' THEN e.base_amount ELSE -e.base_amount END"
SqlParam = datetime | UUID | int


def _scalar(sql: str, params: list[SqlParam]) -> Decimal:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        (value,) = cursor.fetchone()
    return Decimal(value)


def total_imbalance(*, as_of: datetime | None = None) -> Decimal:
    """System-wide sum of signed base amounts. The north star: must always be 0."""
    sql = f"SELECT COALESCE(SUM({SIGNED}), 0) FROM ledger_entry e"  # noqa: S608 (raw SQL, not user input)
    params: list[SqlParam] = []
    if as_of is not None:
        sql += " WHERE e.created_at <= %s"
        params.append(as_of)
    return _scalar(sql, params)


def unbalanced_transfers(
    *, fund_id: UUID | None = None, limit: int = 100
) -> list[tuple[UUID, Decimal]]:
    join, where = "", ""
    params: list[SqlParam] = []
    if fund_id is not None:
        join = "JOIN ledger_account a ON a.id = e.account_id"
        where = "WHERE a.fund_id = %s"
        params.append(fund_id)
    sql = f""" 
        SELECT e.transfer_id, SUM({SIGNED})
          FROM ledger_entry e {join} {where}
         GROUP BY e.transfer_id
        HAVING SUM({SIGNED}) <> 0
         ORDER BY e.transfer_id
         LIMIT %s
    """  # noqa: S608 (raw SQL, not user input)
    params.append(limit)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [(row[0], Decimal(row[1])) for row in cursor.fetchall()]


def period_imbalance(period_id: UUID) -> Decimal:
    sql = f"""
        SELECT COALESCE(SUM({SIGNED}), 0)
          FROM ledger_entry e
          JOIN ledger_transfer t ON t.id = e.transfer_id
         WHERE t.period_id = %s
    """  # noqa: S608 (raw SQL, not user input)
    return _scalar(sql, [period_id])


def fund_imbalance(fund_id: UUID) -> Decimal:
    sql = f"""
        SELECT COALESCE(SUM({SIGNED}), 0)
          FROM ledger_entry e JOIN ledger_account a ON a.id = e.account_id
         WHERE a.fund_id = %s
    """  # noqa: S608 (raw SQL, not user input)
    return _scalar(sql, [fund_id])
