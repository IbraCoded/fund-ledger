"""Load profile: capital calls (writes), replays (idempotency path) and balance reads."""

import os
import random
import uuid

from locust import HttpUser, between, task

DEMO_NS = uuid.UUID("6f1c6a8e-3b7d-4c55-9a0e-2f4f7b1d9c10")  # same as seed_demo
FUND_ID = os.environ.get("FUND_ID", str(uuid.uuid5(DEMO_NS, "fund")))
LOAD_DATE = os.environ.get("LOAD_DATE", "2026-09-15")  # must fall in an OPEN seeded period


class LedgerUser(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self):
        accounts = self.client.get(f"/api/v1/funds/{FUND_ID}/accounts/", name="accounts").json()
        self.account_ids = [a["id"] for a in accounts]
        self.sent: list[tuple[str, dict]] = []

    @task(3)
    def capital_call(self):
        key = str(uuid.uuid4())
        body = {"total_amount": "100.00", "notice_date": LOAD_DATE, "due_date": LOAD_DATE}
        self.client.post(
            f"/api/v1/funds/{FUND_ID}/capital-calls/",
            json=body,
            headers={"Idempotency-Key": key},
            name="capital_call",
        )
        self.sent.append((key, body))
        del self.sent[:-50]

    @task(1)
    def replay(self):
        if not self.sent:
            return
        key, body = random.choice(self.sent)
        with self.client.post(
            f"/api/v1/funds/{FUND_ID}/capital-calls/",
            json=body,
            headers={"Idempotency-Key": key},
            name="capital_call_replay",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"replay returned {response.status_code}, expected 200")

    @task(6)
    def balance(self):
        account_id = random.choice(self.account_ids)
        self.client.get(f"/api/v1/accounts/{account_id}/balance/", name="balance")
