"""Bills, installments, allocations — including concurrency."""
import threading
import uuid
from decimal import Decimal

import psycopg
import pytest

from conftest import DSN, as_user, create_entry, post, raises_db, user_key

CO = "ART"


@pytest.fixture
def ctx(db, world):
    as_user(db, world.users[user_key(CO, "accountant")])
    return world.companies[CO], (lambda c: world.accounts[(CO, c)]), world.parties[CO]


def make_bill(db, cid, a, party, amount=99000, due="2025-09-30", bill_no=None):
    eid = create_entry(db, cid, "bill_sale", [(a("AR"), amount, 0, party), (a("INC-SALE"), 0, amount)],
                       party_id=party, description="SAMPLE monthly bill")
    bid = db.execute(
        """insert into fin.bills (company_id, bill_no, direction, party_id, bill_date, due_date, amount,
               description, journal_entry_id)
           values (%s, %s, 'receivable', %s, '2025-08-01', %s, %s, 'SAMPLE bill', %s) returning id""",
        (cid, bill_no or f"SAMPLE-{uuid.uuid4().hex[:8]}", party, due, amount, eid),
    ).fetchone()[0]
    post(db, eid)
    return bid


def receive(db, cid, a, party, bill, amount, ref=None, date="2025-08-20"):
    eid = create_entry(db, cid, "receipt", [(a("CASH"), amount, 0), (a("AR"), 0, amount, party)],
                       party_id=party, payment_method="cash", reference_no=ref or uuid.uuid4().hex[:10],
                       entry_date=date, description="SAMPLE installment")
    db.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) values (%s, %s, %s, %s)",
               (cid, bill, eid, amount))
    post(db, eid)
    return eid


def status(db, cid, bill, as_of="2025-09-01"):
    return db.execute("select paid, outstanding, pay_status from fin.bill_balances(%s, %s) where bill_id = %s",
                      (cid, as_of, bill)).fetchone()


def test_bill_lifecycle_partial_then_full(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=99000)
    assert status(db, cid, bill) == (0, 99000, "pending")
    receive(db, cid, a, p, bill, 49500)
    assert status(db, cid, bill) == (Decimal("49500.00"), Decimal("49500.00"), "partially_paid")
    assert status(db, cid, bill, as_of="2025-10-15")[2] == "overdue"
    receive(db, cid, a, p, bill, 49500)
    assert status(db, cid, bill, as_of="2025-10-15") == (Decimal("99000.00"), 0, "paid")


def test_installments_are_not_income(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    rec = receive(db, cid, a, p, bill, 1000)
    income = db.execute("""select coalesce(sum(credit - debit), 0) from fin.journal_lines l
                           join fin.accounts ac on ac.id = l.account_id
                           where ac.type = 'income' and l.entry_id in (%s)""", (rec,)).fetchone()[0]
    assert income == 0


def test_allocated_receipt_must_credit_receivable(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    eid = create_entry(db, cid, "receipt", [(a("CASH"), 1000, 0), (a("INC-OTH"), 0, 1000)],
                       party_id=p, payment_method="cash", description="wrongly booked as income")
    db.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) values (%s, %s, %s, 1000)",
               (cid, bill, eid))
    with raises_db(match="credit Accounts Receivable"):
        post(db, eid)


def test_over_allocation_rejected(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    receive(db, cid, a, p, bill, 600)
    with raises_db(match="exceeds the bill outstanding"):
        receive(db, cid, a, p, bill, 500)


def test_allocation_party_and_direction_must_match(db, ctx, world):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    other = world.suppliers[CO]
    eid = create_entry(db, cid, "receipt", [(a("CASH"), 10, 0), (a("AR"), 0, 10, other)],
                       party_id=other, payment_method="cash")
    with raises_db(match="party must match"):
        db.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) values (%s, %s, %s, 10)",
                   (cid, bill, eid))
    exp = create_entry(db, cid, "expense", [(a("EXP-DSL"), 10, 0), (a("CASH"), 0, 10)],
                       party_id=p, payment_method="cash")
    with raises_db(match="receivable bills take receipts"):
        db.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) values (%s, %s, %s, 10)",
                   (cid, bill, exp))


def test_bill_entry_must_match_bill_amount_and_party(db, ctx):
    cid, a, p = ctx
    eid = create_entry(db, cid, "bill_sale", [(a("AR"), 900, 0, p), (a("INC-SALE"), 0, 900)], party_id=p)
    db.execute("""insert into fin.bills (company_id, bill_no, direction, party_id, bill_date, amount, description,
                      journal_entry_id) values (%s, 'SAMPLE-MISMATCH', 'receivable', %s, '2025-08-01', 1000, 'x', %s)""",
               (cid, p, eid))
    with raises_db(match="exactly the bill amount"):
        post(db, eid)


def test_posted_bill_is_frozen(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    with raises_db(match="frozen"):
        db.execute("update fin.bills set amount = 1 where id = %s", (bill,))
    assert db.execute("delete from fin.bills where id = %s", (bill,)).rowcount == 0  # RLS: drafts only
    db.execute("update fin.bills set notes = 'called customer' where id = %s", (bill,))  # allowed


def test_duplicate_bill_number_rejected(db, ctx):
    cid, a, p = ctx
    make_bill(db, cid, a, p, bill_no="SAMPLE-DUP-1")
    with raises_db(sqlstate="23505"):
        make_bill(db, cid, a, p, bill_no="sample-dup-1")


def test_installment_schedule_cannot_exceed_bill(db, ctx):
    cid, a, p = ctx
    bill = make_bill(db, cid, a, p, amount=1000)
    db.execute("insert into fin.installment_schedule (company_id, bill_id, seq, due_date, expected_amount) "
               "values (%s, %s, 1, '2025-09-01', 600)", (cid, bill))
    with raises_db(match="exceed the bill amount"):
        db.execute("insert into fin.installment_schedule (company_id, bill_id, seq, due_date, expected_amount) "
                   "values (%s, %s, 2, '2025-10-01', 500)", (cid, bill))


def test_concurrent_allocations_cannot_overpay(world):
    """Two cashiers record 600 each against a 1000 bill at the same moment: one must fail."""
    cid, party = world.companies[CO], world.parties[CO]
    a = lambda c: world.accounts[(CO, c)]  # noqa: E731
    acc = world.users[user_key(CO, "accountant")]
    with psycopg.connect(DSN) as setup:
        as_user(setup, acc)
        bill = make_bill(setup, cid, a, party, amount=1000)
        setup.commit()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def cashier():
        with psycopg.connect(DSN) as c:
            try:
                as_user(c, acc)
                barrier.wait()
                receive(c, cid, a, party, bill, 600)
                c.commit()
                results.append("ok")
            except psycopg.Error as e:
                c.rollback()
                results.append("exceeds" if "exceeds" in str(e) else f"other: {e}")

    threads = [threading.Thread(target=cashier) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert sorted(results) == ["exceeds", "ok"], results

    with psycopg.connect(DSN) as c:
        as_user(c, acc)
        assert status(c, cid, bill)[0] == Decimal("600.00")
