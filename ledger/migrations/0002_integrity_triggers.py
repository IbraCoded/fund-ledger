from django.db import migrations

# --- 1. Every transfer's entries sum to zero, checked at COMMIT -------------------------
#
# A CHECK constraint sees one row; "entries of transfer X sum to zero" is a statement
# about a set of rows inserted across several statements. A CONSTRAINT TRIGGER declared
# DEFERRABLE INITIALLY DEFERRED runs at COMMIT, once all the rows exist.
TRANSFER_BALANCES = [
    """
    CREATE OR REPLACE FUNCTION assert_transfer_balances() RETURNS trigger AS $$
    DECLARE
        imbalance NUMERIC(20, 4);
    BEGIN
        SELECT COALESCE(SUM(CASE WHEN direction = 'DEBIT' THEN base_amount
                                 ELSE -base_amount END), 0)
          INTO imbalance
          FROM ledger_entry
         WHERE transfer_id = NEW.transfer_id;
        IF imbalance <> 0 THEN
            RAISE EXCEPTION 'Transfer % does not balance: %', NEW.transfer_id, imbalance
                USING ERRCODE = 'check_violation', CONSTRAINT = 'transfer_balanced';
        END IF;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE CONSTRAINT TRIGGER entry_balance_check
        AFTER INSERT ON ledger_entry
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION assert_transfer_balances();
    """,
]
DROP_TRANSFER_BALANCES = [
    "DROP TRIGGER IF EXISTS entry_balance_check ON ledger_entry;",
    "DROP FUNCTION IF EXISTS assert_transfer_balances();",
]

# --- 2. Entries and transfers are append-only ---------------------------------------------
APPEND_ONLY = [
    """
    CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only (attempted % on %)', TG_TABLE_NAME, TG_OP, OLD.id
            USING ERRCODE = 'restrict_violation', CONSTRAINT = 'append_only';
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER entry_append_only BEFORE UPDATE OR DELETE ON ledger_entry
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """,
    """
    CREATE TRIGGER transfer_append_only BEFORE UPDATE OR DELETE ON ledger_transfer
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """,
]
DROP_APPEND_ONLY = [
    "DROP TRIGGER IF EXISTS entry_append_only ON ledger_entry;",
    "DROP TRIGGER IF EXISTS transfer_append_only ON ledger_transfer;",
    "DROP FUNCTION IF EXISTS forbid_mutation();",
]

# --- 3. An entry's currency is its account's currency --------------------------------------
# Composite FK against the UNIQUE (id, currency) declared on Account. Django has no
# composite FKs, so we add it in SQL.
ENTRY_CURRENCY_MATCHES_ACCOUNT = [
    """
    ALTER TABLE ledger_entry
      ADD CONSTRAINT entry_currency_matches_account
      FOREIGN KEY (account_id, currency) REFERENCES ledger_account (id, currency);
    """,
]
DROP_ENTRY_CURRENCY_MATCHES_ACCOUNT = [
    "ALTER TABLE ledger_entry DROP CONSTRAINT IF EXISTS entry_currency_matches_account;",
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]

    operations = [
        migrations.RunSQL(TRANSFER_BALANCES, DROP_TRANSFER_BALANCES),
        migrations.RunSQL(APPEND_ONLY, DROP_APPEND_ONLY),
        migrations.RunSQL(ENTRY_CURRENCY_MATCHES_ACCOUNT, DROP_ENTRY_CURRENCY_MATCHES_ACCOUNT),
    ]
