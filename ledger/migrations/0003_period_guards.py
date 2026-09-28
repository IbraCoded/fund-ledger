from django.db import migrations

PERIOD_OPEN = [
    """
    CREATE OR REPLACE FUNCTION assert_period_open() RETURNS trigger AS $$
    DECLARE
        p_status TEXT;
    BEGIN
        -- FOR SHARE: many postings may hold it at once; close_period's FOR UPDATE
        -- must wait for all of them, and they must wait for it.
        SELECT p.status INTO p_status
          FROM ledger_transfer t
          JOIN funds_period p ON p.id = t.period_id
         WHERE t.id = NEW.transfer_id
           FOR SHARE OF p;
        IF p_status IS DISTINCT FROM 'OPEN' THEN
            RAISE EXCEPTION 'Transfer % belongs to a period that is not open (%)',
                            NEW.transfer_id, p_status
                USING ERRCODE = 'restrict_violation', CONSTRAINT = 'period_open';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER entry_period_open BEFORE INSERT ON ledger_entry
        FOR EACH ROW EXECUTE FUNCTION assert_period_open();
    """,
]
DROP_PERIOD_OPEN = [
    "DROP TRIGGER IF EXISTS entry_period_open ON ledger_entry;",
    "DROP FUNCTION IF EXISTS assert_period_open();",
]

CLOSED_IS_FINAL = [
    """
    CREATE OR REPLACE FUNCTION forbid_period_reopen() RETURNS trigger AS $$
    BEGIN
        IF OLD.status = 'CLOSED' THEN
            RAISE EXCEPTION 'Period % is closed; closed periods are final', OLD.id
                USING ERRCODE = 'restrict_violation', CONSTRAINT = 'period_closed_is_final';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER period_closed_is_final BEFORE UPDATE ON funds_period
        FOR EACH ROW EXECUTE FUNCTION forbid_period_reopen();
    """,
]
DROP_CLOSED_IS_FINAL = [
    "DROP TRIGGER IF EXISTS period_closed_is_final ON funds_period;",
    "DROP FUNCTION IF EXISTS forbid_period_reopen();",
]


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_integrity_triggers"),
        ("funds", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(PERIOD_OPEN, DROP_PERIOD_OPEN),
        migrations.RunSQL(CLOSED_IS_FINAL, DROP_CLOSED_IS_FINAL),
    ]
