"""Accounting integrity: balance, immutability, reversals, duplicates, periods, audit."""
import psycopg
import pytest

from conftest import DSN, as_user, create_entry, post, raises_db, user_key

CO = "ART"


@pytest.fixture
def acct(db, world):
    as_user(db, world.users[user_key(CO, "accountant")])
    return lambda c: world.accounts[(CO, c)]


def cid(world):
    return world.companies[CO]


def test_unbalanced_entry_rejected(db, world, acct):
    eid = create_entry(db, cid(world), "expense", [(acct("EXP-DSL"), 500, 0), (acct("CASH"), 0, 499)],
                       payment_method="cash")
    with raises_db(match="not balanced"):
        post(db, eid)


def test_single_line_entry_rejected(db, world, acct):
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 500, 0)])
    with raises_db(match="at least two lines"):
        post(db, eid)


def test_line_must_be_debit_xor_credit(db, world, acct):
    with raises_db(sqlstate="23514"):
        create_entry(db, cid(world), "expense", [(acct("CASH"), 10, 10), (acct("EXP-DSL"), 0, 0)])
    with raises_db(sqlstate="23514"):
        create_entry(db, cid(world), "expense", [(acct("CASH"), -10, 0)])


def test_money_is_exact_decimal(db, world, acct):
    eid = create_entry(db, cid(world), "expense",
                       [(acct("EXP-DSL"), "0.10", 0), (acct("EXP-DSL"), "0.20", 0), (acct("CASH"), 0, "0.30")],
                       payment_method="cash")
    post(db, eid)  # 0.1 + 0.2 == 0.3 exactly; floats would fail
    with raises_db(sqlstate="22003"):
        create_entry(db, cid(world), "expense", [(acct("CASH"), "1e13", 0)])


def test_receipt_requires_cash_or_bank_and_method(db, world, acct):
    p = world.parties[CO]
    eid = create_entry(db, cid(world), "receipt", [(acct("ADV"), 0, 100, p), (acct("AR"), 100, 0, p)],
                       party_id=p, payment_method="cash")
    with raises_db(match="cash or bank"):
        post(db, eid)
    eid2 = create_entry(db, cid(world), "receipt", [(acct("CASH"), 100, 0), (acct("ADV"), 0, 100, p)], party_id=p)
    with raises_db(match="payment method"):
        post(db, eid2)


def test_transfer_only_between_cash_and_bank(db, world, acct):
    ok = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 5000, 0), (acct("CASH"), 0, 5000)])
    post(db, ok)
    bad = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 5000, 0), (acct("INC-OTH"), 0, 5000)])
    with raises_db(match="between cash/bank"):
        post(db, bad)


def test_transfer_is_not_income_or_expense(db, world, acct):
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 7000, 0), (acct("CASH"), 0, 7000)])
    post(db, eid)
    n = db.execute("""select count(*) from fin.journal_lines l join fin.accounts a on a.id = l.account_id
                      where l.entry_id = %s and a.type in ('income', 'expense')""", (eid,)).fetchone()[0]
    assert n == 0


def test_bill_cannot_move_cash(db, world, acct):
    eid = create_entry(db, cid(world), "bill_sale", [(acct("CASH"), 100, 0), (acct("INC-SALE"), 0, 100)])
    with raises_db(match="does not move cash"):
        post(db, eid)


def test_posted_entry_is_immutable(db, world, acct):
    eid = create_entry(db, cid(world), "expense", [(acct("EXP-DSL"), 500, 0), (acct("CASH"), 0, 500)],
                       payment_method="cash")
    post(db, eid)
    with raises_db(match="immutable"):
        db.execute("update fin.journal_entries set description = 'changed' where id = %s", (eid,))
    # RLS hides posted entries from DELETE (0 rows); the trigger is the second layer below.
    assert db.execute("delete from fin.journal_entries where id = %s", (eid,)).rowcount == 0
    with raises_db(match="immutable"):
        db.execute("update fin.journal_lines set debit = 1 where entry_id = %s and debit > 0", (eid,))
    with raises_db(match="immutable"):
        db.execute("""insert into fin.journal_lines (entry_id, company_id, line_no, account_id, debit)
                      values (%s, %s, 9, %s, 1)""", (eid, cid(world), acct("CASH")))
    # RLS hides posted lines from DELETE entirely (0 rows), before the trigger even runs.
    assert db.execute("delete from fin.journal_lines where entry_id = %s", (eid,)).rowcount == 0
    # Super admin is bound by the same rule.
    as_user(db, world.users["super"])
    with raises_db(match="immutable"):
        db.execute("update fin.journal_entries set entry_date = '2020-01-01' where id = %s", (eid,))
    # Even the database owner (bypasses RLS) hits the trigger.
    db.execute("reset role")
    with raises_db(match="cannot be deleted"):
        db.execute("delete from fin.journal_entries where id = %s", (eid,))
    with raises_db(match="cannot be deleted"):
        db.execute("delete from fin.journal_lines where entry_id = %s", (eid,))


def test_reconciliation_fields_can_change_on_posted_lines(db, world, acct):
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 1, 0), (acct("CASH"), 0, 1)])
    post(db, eid)
    assert db.execute("update fin.journal_lines set reconciled_at = now() where entry_id = %s",
                      (eid,)).rowcount == 2


def _reversal(db, world, acct, original, lines):
    return create_entry(db, cid(world), "reversal", lines, reverses=original, description="SAMPLE reversal")


def test_reversal_requires_approval_and_four_eyes(db, world, acct):
    eid = create_entry(db, cid(world), "expense", [(acct("EXP-DSL"), 900, 0), (acct("CASH"), 0, 900)],
                       payment_method="cash")
    post(db, eid)
    rev = _reversal(db, world, acct, eid, [(acct("CASH"), 900, 0), (acct("EXP-DSL"), 0, 900)])
    with raises_db(match="approved reverse_entry"):
        post(db, rev)

    db.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
               "values (%s, 'reverse_entry', %s, 'Entered twice')", (cid(world), eid))
    with raises_db(sqlstate="42501", match="company admin"):  # accountant can't approve
        db.execute("update fin.approval_requests set status = 'approved' where target_id = %s", (eid,))
    with raises_db(sqlstate="42501"):  # still can't post
        post(db, rev)

    as_user(db, world.users[user_key(CO, "company_admin")])
    db.execute("update fin.approval_requests set status = 'approved', decision_note = 'ok' "
               "where target_id = %s", (eid,))
    as_user(db, world.users[user_key(CO, "accountant")])
    post(db, rev)
    assert db.execute("select status from fin.journal_entries where id = %s", (eid,)).fetchone()[0] == "reversed"
    assert db.execute("select status from fin.approval_requests where target_id = %s",
                      (eid,)).fetchone()[0] == "used"
    with raises_db(match="reversed entry cannot be changed"):
        db.execute("update fin.journal_entries set notes = 'x' where id = %s", (eid,))


def test_cannot_approve_own_request(db, world, acct):
    admin = world.users[user_key(CO, "company_admin")]
    as_user(db, admin)
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 3, 0), (acct("CASH"), 0, 3)])
    post(db, eid)
    db.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
               "values (%s, 'reverse_entry', %s, 'my own mistake')", (cid(world), eid))
    with raises_db(match="your own request"):
        db.execute("update fin.approval_requests set status = 'approved' where target_id = %s", (eid,))


def test_reversal_must_mirror_original(db, world, acct):
    eid = create_entry(db, cid(world), "expense", [(acct("EXP-DSL"), 900, 0), (acct("CASH"), 0, 900)],
                       payment_method="cash")
    post(db, eid)
    db.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
               "values (%s, 'reverse_entry', %s, 'Wrong amount')", (cid(world), eid))
    as_user(db, world.users[user_key(CO, "company_admin")])
    db.execute("update fin.approval_requests set status = 'approved' where target_id = %s", (eid,))
    as_user(db, world.users[user_key(CO, "accountant")])
    rev = _reversal(db, world, acct, eid, [(acct("CASH"), 800, 0), (acct("EXP-DSL"), 0, 800)])
    with raises_db(match="mirror"):
        post(db, rev)


def test_duplicate_receipt_reference_rejected(db, world, acct):
    p = world.parties[CO]
    lines = [(acct("CASH"), 100, 0), (acct("ADV"), 0, 100, p)]
    with raises_db(sqlstate="23505"):  # SAMPLE-R1 was already posted in seed data
        create_entry(db, cid(world), "receipt", lines, party_id=p, payment_method="cash", reference_no="sample-r1 ")
    # Different payment method is a different reference space (e.g. UPI txn id vs receipt book).
    create_entry(db, cid(world), "receipt", lines, party_id=p, payment_method="upi", reference_no="SAMPLE-R1")


def test_idempotency_key_blocks_double_submit(db, world, acct):
    lines = [(acct("EXP-DSL"), 5, 0), (acct("CASH"), 0, 5)]
    create_entry(db, cid(world), "expense", lines, payment_method="cash", idempotency_key="tap-123456")
    with raises_db(sqlstate="23505"):
        create_entry(db, cid(world), "expense", lines, payment_method="cash", idempotency_key="tap-123456")


def test_entry_numbers_are_sequential_per_fy(db, world, acct):
    nos = []
    for _ in range(3):
        eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 1, 0), (acct("CASH"), 0, 1)],
                           entry_date="2026-04-02")
        post(db, eid)
        nos.append(db.execute("select entry_no from fin.journal_entries where id = %s", (eid,)).fetchone()[0])
    seq = [int(n.rsplit("/", 1)[1]) for n in nos]
    assert all(n.startswith("ART/2026-27/") for n in nos)
    assert seq == [seq[0], seq[0] + 1, seq[0] + 2]


def test_internal_functions_not_callable_directly(db, world, acct):
    with raises_db(match="only run inside a database trigger"):
        db.execute("select fin.next_entry_no(%s, '2025-08-01')", (cid(world),))
    with raises_db(match="only run inside a database trigger"):
        db.execute("select fin.consume_approval(%s, 'reverse_entry', gen_random_uuid())", (cid(world),))


def test_closed_period_needs_approval(db, world, acct):
    as_user(db, world.users[user_key(CO, "company_admin")])
    db.execute("update fin.financial_periods set status = 'closed' where company_id = %s and start_date = '2025-08-01'",
               (cid(world),))
    as_user(db, world.users[user_key(CO, "accountant")])
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 1, 0), (acct("CASH"), 0, 1)],
                       entry_date="2025-08-15")
    with raises_db(match="post_in_closed_period"):
        post(db, eid)


def test_cannot_close_period_with_drafts(db, world, acct):
    create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 1, 0), (acct("CASH"), 0, 1)], entry_date="2025-11-03")
    as_user(db, world.users[user_key(CO, "company_admin")])
    with raises_db(match="unposted"):
        db.execute("update fin.financial_periods set status = 'closed' where company_id = %s "
                   "and start_date = '2025-11-01'", (cid(world),))


def test_audit_log_records_and_is_append_only(db, world, acct):
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 2, 0), (acct("CASH"), 0, 2)])
    post(db, eid)
    as_user(db, world.users[user_key(CO, "company_admin")])
    rows = db.execute("select action, actor_id from fin.audit_log where table_name = 'journal_entries' "
                      "and record_id = %s order by id", (str(eid),)).fetchall()
    assert [r[0] for r in rows] == ["insert", "update"]
    assert rows[0][1] == world.users[user_key(CO, "accountant")]
    with raises_db(sqlstate="42501"):
        db.execute("delete from fin.audit_log")
    db.execute("reset role")  # even the database owner can't rewrite history
    with raises_db(match="append-only"):
        db.execute("update fin.audit_log set action = 'x' where record_id = %s", (str(eid),))
    with raises_db(match="append-only"):
        db.execute("delete from fin.audit_log where record_id = %s", (str(eid),))


def test_optimistic_locking_version(db, world, acct):
    eid = create_entry(db, cid(world), "transfer", [(acct("BANK-1"), 2, 0), (acct("CASH"), 0, 2)])
    v = db.execute("select version from fin.journal_entries where id = %s", (eid,)).fetchone()[0]
    assert db.execute("update fin.journal_entries set notes = 'a' where id = %s and version = %s",
                      (eid, v)).rowcount == 1
    # A second editor still holding the old version updates nothing -> API returns 409.
    assert db.execute("update fin.journal_entries set notes = 'b' where id = %s and version = %s",
                      (eid, v)).rowcount == 0
