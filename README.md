# Fund Ledger

[![CI](https://github.com/IbraCoded/fund-ledger/actions/workflows/ci.yml/badge.svg)](https://github.com/IbraCoded/fund-ledger/actions/workflows/ci.yml)

A double-entry ledger for private-equity fund accounting (capital calls, distributions,
FX, period close, LP statements) where PostgreSQL itself enforces correctness:
the database rejects unbalanced, edited or deleted entries, not just the code.

**Live:** https://ledger.ibracoded.dev/api/docs/

## Try it in 30 seconds

Open the [live docs](https://ledger.ibracoded.dev/api/docs/), click **Authorize**, paste a key,
and use "Try it out":

| Key | Can do |
|---|---|
| `fl_3d769a148fa5.su4Cf7cnvsQFFTeB5gw_M_7cEaCDFZlfvp1Atbs5QHI` (VIEWER) | Read everything in the showcase fund, *Glasgow Growth Partners I*. Any write is a 403 |
| `fl_def53111b50a.df5eLJA9lebQuVSzNNRebDh8sZ7KzdhBhEokdwLzY1Q` (LP) | Read Kelvin Family Office's statement only. Every other LP is a 404, not a 403 |
| `fl_107bfb758381.vQvdjSgdHuRdk4r2Y4JHx51MDIuuafpTcOV3VickPhg` (sandbox) | CONTROLLER on today's sandbox fund: post capital calls, replay them, reverse them, close periods. Everything else is a 404 |

The first two keys are read-only. The sandbox key reaches only a fresh, empty fund that is
replaced every night. Nothing is deleted: yesterday's fund just stops being reachable. Roles are
per fund, so the sandbox key is an outsider on the showcase fund and gets a 404 there like anyone
else. All keys are rate limited and revocable. Find today's sandbox fund with `GET /api/v1/me/`:

```bash
curl -s https://ledger.ibracoded.dev/api/v1/me/ \
  -H "Authorization: Bearer fl_107bfb758381.vQvdjSgdHuRdk4r2Y4JHx51MDIuuafpTcOV3VickPhg"
```

Or run every check at once:

```bash
git clone https://github.com/IbraCoded/fund-ledger && cd fund-ledger
API=https://ledger.ibracoded.dev \
VIEWER_KEY=fl_3d769a148fa5.su4Cf7cnvsQFFTeB5gw_M_7cEaCDFZlfvp1Atbs5QHI \
LP_KEY=fl_def53111b50a.df5eLJA9lebQuVSzNNRebDh8sZ7KzdhBhEokdwLzY1Q \
WRITE_KEY=fl_107bfb758381.vQvdjSgdHuRdk4r2Y4JHx51MDIuuafpTcOV3VickPhg \
scripts/tour.sh
```

## Architecture

![Fund Ledger architecture](docs/architecture.svg)

Imports only point downwards: `api` → `operations` → `ledger` → `funds` → PostgreSQL. The
`ledger` engine doesn't know what a capital call is. It only moves amounts between accounts
atomically, exactly once, and never lets the books go out of balance. Business operations are
thin clients of that engine, so the part that must be correct stays small enough to test
exhaustively. Every rule is enforced three times: serializers reject malformed input, services
apply business rules, and the database has the final say even if the first two have bugs.

## Invariants and how they're enforced

| Invariant | Enforced by | Proven by |
|---|---|---|
| Every transfer balances | Deferred constraint trigger, checked at commit | [`test_unbalanced_transfer_is_rejected_at_commit`](tests/ledger/test_db_invariants.py#L38) |
| Entries are append-only | Trigger **and** database permissions | [`test_app_role_cannot_tamper_with_the_ledger`](tests/ledger/test_db_roles.py#L60) |
| Balances are derived, never stored | No balance column | [`test_point_in_time_balance`](tests/ledger/test_post_transfer.py#L107) |
| Money is exact | `NUMERIC(20,4)`; floats rejected at the edge | [`test_json_numbers_are_parsed_as_decimal`](tests/api/test_capital_calls_api.py#L46) |
| Money moves exactly once | Unique key, savepoint and request fingerprint | [`test_concurrent_duplicates_create_exactly_one_transfer`](tests/ledger/test_idempotency.py#L47) |
| No overdrafts under concurrency | Row locks in primary-key order | [`test_no_account_goes_negative_under_concurrent_load`](tests/ledger/test_concurrency.py#L18) |
| Nothing posts into a closed period | `FOR SHARE` trigger; closing is final | [`test_close_waits_for_in_flight_postings`](tests/operations/test_periods.py#L93) |
| Σ LP capital = NAV | Exact allocation and double entry | [`test_partners_capital_equals_nav`](tests/operations/test_statements.py#L80) |

223 tests, including Hypothesis property tests and multi-connection concurrency tests that
really commit. CI enforces 85% branch coverage.

## Security

- **Authentication:** API keys with 256 random bits; only their SHA-256 digest is stored, and
  keys expire and can be revoked. Not bcrypt, because slow hashes protect guessable passwords and
  a 256-bit secret has nothing to guess. Not JWT, because a key must be revocable immediately,
  which needs a lookup anyway.
- **Authorization:** fund-scoped roles (LP, VIEWER, OPERATOR, CONTROLLER) and object-level
  checks. A non-member gets a 404, never a 403. A test fails the build if any endpoint lacks a
  role requirement.
- **Database:** the app connects as a least-privilege role that can't UPDATE, DELETE or TRUNCATE
  ledger rows, change the schema or disable triggers. Lock and statement timeouts are set.
- **Edge:** Caddy provides TLS, HSTS and CSP, and caps request bodies. `/metrics` isn't public.
  Rate limits apply per user, with a tighter budget for money-moving requests.
- **Supply chain:** ruff security rules, pip-audit, a Trivy image scan and Dependabot.
- **Ops:** the deploy key is a forced-command SSH key that can only deploy a commit. Backups
  are encrypted and off-site, with a restore drill that must reconcile.
- **Known limits:** a compromised app can still insert *balanced* entries. There's no
  maker-checker approval, no external identity provider, and failed-auth throttling is left to
  the edge.

## The concurrency story

1. [`9024689`](https://github.com/IbraCoded/fund-ledger/commit/9024689): a concurrent transfer
   test exposes an **overdraft race**. Two requests read the same balance, both pass the check,
   and the account goes negative.
2. [`1437358`](https://github.com/IbraCoded/fund-ledger/commit/1437358): locking accounts with
   `SELECT … FOR UPDATE` fixes the race but exposes a **deadlock**: two opposing transfers each
   hold one lock and wait for the other.
3. [`3694c96`](https://github.com/IbraCoded/fund-ledger/commit/3694c96): taking locks in
   **primary-key order** makes a cycle impossible. Retrying on deadlock or serialization
   failure stays in as a second line of defence.

## Operations

- **Deploy:** CI → image pushed to GHCR → forced-command SSH deploy → one-shot migrate job as the
  owner role → wait for health → `reconcile` → public smoke test. Rolling back means redeploying
  the previous commit SHA. Migrations don't roll back, so they're kept backwards compatible.
- **Backups:** nightly, encrypted, copied off-site, with a restore drill that must reconcile.
- **Monitoring:** Prometheus and Grafana (localhost only), with alerts on reconciliation
  imbalance, availability, deadlocks and latency.

## Performance

Locust ran 50 users for 2 minutes with a mix of 60% balance reads, 30% capital calls and 10%
replays. It used 4 gunicorn workers and PostgreSQL 16 in Docker on a Ryzen 9 8940HX laptop,
starting from a freshly seeded database. Rate limits were lifted for the benchmark only.

| Endpoint | RPS | p50 | p95 | p99 | Failures |
|---|---:|---:|---:|---:|---:|
| balance (read) | 63.9 | 330 ms | 530 ms | 630 ms | 0 |
| capital_call | 32.4 | 380 ms | 610 ms | 720 ms | 0 |
| capital_call_replay | 10.5 | 330 ms | 520 ms | 630 ms | 0 |
| **All requests** | **107.2** | **340 ms** | **570 ms** | **670 ms** | **0** |

After the run the ledger reconciled to exactly zero, there were no deadlock retries, and every
replay returned the original. The test runs the system flat out, so the latencies are mostly
queueing. The ceiling is the **hot fund lock**: capital calls on one fund run one at a time.
Authentication costs under 1 ms per request.

![Grafana during the load test](docs/grafana-loadtest.png)

**What moved the numbers.** Before posting, each capital call checks that no LP is called beyond
their commitment. That means summing every LP's contribution history while holding the fund lock,
and every call makes that history longer. The check originally ran one query per LP. On a fund
of about 5,400 transfers it took about 170 ms per call, which capped capital calls at 6 per
second. A single grouped query does the same work in 22 ms. Under identical conditions:

| | One query per LP | One grouped query |
|---|---:|---:|
| All requests/s | 63.5 | 107.2 |
| capital_call/s | 18.2 | 32.4 |
| capital_call p50 / p99 | 790 / 1,600 ms | 380 / 720 ms |
| Throughput from start to end of run | 88 → 47/s | 106 → 90/s |

The check still grows with history, as the rising latency line shows, just about 8× more slowly.
Balance checkpoints at period close would stop the growth altogether (see Tradeoffs). Grafana's
latency panel times only the transfer inside Django; Locust's figures also include waiting for
a free worker.

## Tradeoffs and what I'd change

- **Balances are derived, so costs grow with history** (see Performance). I'd store balance
  checkpoints at period close: a closed period can never change, so its checkpoint never goes stale.
- **Capital calls on one fund are serialised by the fund lock.** Moving call numbering to a
  sequence would stop the fund row being a lock.
- **Pro-rata is by commitment.** There is no full distribution waterfall (preferred return, carry).
- **It runs on a single VPS.** A deploy restarts the API, so there's brief downtime.
- **Throttling is approximate.** That's good enough for abuse protection, but not for
  billing-grade quotas.

## Running locally

```bash
make demo    # builds and starts everything, seeds a fund, prints a key per role
make tour    # authentication, authorization, exactly-once and reconciliation checks
```

Then open http://localhost:8000/api/docs/ and paste a key. Run the tests with `make test`.
Everything `make` runs is plain `docker compose` (see the [Makefile](Makefile)).
