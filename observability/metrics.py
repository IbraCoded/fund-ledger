from prometheus_client import Counter, Histogram

TRANSFERS = Counter(
    "ledger_transfers_total",
    "Transfer requests by type and outcome (created, replayed, rejected, error)",
    ["transfer_type", "outcome"],
)
TRANSFER_LATENCY = Histogram(
    "ledger_transfer_duration_seconds",
    "Time to post or replay a transfer, including lock waits",
    ["transfer_type"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
DB_RETRIES = Counter(
    "ledger_db_retries_total",
    "Operations retried after a deadlock or serialization failure",
    ["sqlstate"],
)
