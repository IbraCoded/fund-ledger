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


def _scalar(sql: str, params: list[object]) -> Decimal:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        (value,) = cursor.fetchone()
    return Decimal(value)


def total_imbalance(*, as_of: datetime | None = None) -> Decimal:
    """System-wide sum of signed base amounts. The north star: must always be 0."""
    sql = f"SELECT COALESCE(SUM({SIGNED}), 0) FROM ledger_entry e"
    params: list[object] = []
    if as_of is not None:
        sql += " WHERE e.created_at <= %s"
        params.append(as_of)
    return _scalar(sql, params)


def unbalanced_transfers(*, limit: int = 100) -> list[tuple[UUID, Decimal]]:
    sql = f"""
        SELECT e.transfer_id, SUM({SIGNED})
          FROM ledger_entry e
         GROUP BY e.transfer_id
        HAVING SUM({SIGNED}) <> 0
         ORDER BY e.transfer_id
         LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [limit])
        return [(row[0], Decimal(row[1])) for row in cursor.fetchall()]
