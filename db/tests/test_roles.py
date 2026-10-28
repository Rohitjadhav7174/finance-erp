"""Role permissions within a company (enforced in the database, not just the UI)."""
import pytest

from conftest import as_superuser, as_user, create_entry, post, raises_db, user_key


def cash_expense(db, world, company="ART", amount=500, **kw):
    a = lambda c: world.accounts[(company, c)]  # noqa: E731
    return create_entry(db, world.companies[company], "expense",
                        [(a("EXP-DSL"), amount, 0), (a("CASH"), 0, amount)],
                        payment_method="cash", description="SAMPLE diesel", **kw)


def test_viewer_cannot_create_anything(db, world):
    as_user(db, world.users[user_key("ART", "viewer")])
    with raises_db(sqlstate="42501"):
        cash_expense(db, world)
    with raises_db(sqlstate="42501"):
        db.execute("insert into fin.parties (company_id, name, kind) values (%s, 'x', 'customer')",
                   (world.companies["ART"],))


def test_data_entry_creates_draft_but_cannot_post(db, world):
    as_user(db, world.users[user_key("ART", "data_entry")])
    eid = cash_expense(db, world)
    with raises_db(sqlstate="42501"):
        post(db, eid)
    db.execute("update fin.journal_entries set status = 'pending_approval' where id = %s", (eid,))
    as_user(db, world.users[user_key("ART", "accountant")])
    post(db, eid)
    no, approver = db.execute("select entry_no, approved_by from fin.journal_entries where id = %s",
                              (eid,)).fetchone()
    assert no.startswith("ART/2025-26/")
    assert approver == world.users[user_key("ART", "accountant")]


def test_data_entry_cannot_edit_others_drafts(db, world):
    as_user(db, world.users[user_key("ART", "accountant")])
    eid = cash_expense(db, world)
    as_user(db, world.users[user_key("ART", "data_entry")])
    assert db.execute("update fin.journal_entries set description = 'x' where id = %s",
                      (eid,)).rowcount == 0
    assert db.execute("delete from fin.journal_entries where id = %s", (eid,)).rowcount == 0


def test_data_entry_cannot_post_by_setting_status_on_insert(db, world):
    as_user(db, world.users[user_key("ART", "data_entry")])
    with raises_db(match="created as draft"):
        db.execute("""insert into fin.journal_entries (company_id, entry_type, entry_date, description, status)
                      values (%s, 'expense', '2025-08-01', 'x', 'posted')""", (world.companies["ART"],))


def test_created_by_cannot_be_spoofed(db, world):
    me = world.users[user_key("ART", "data_entry")]
    as_user(db, me)
    eid = db.execute("""insert into fin.journal_entries (company_id, entry_type, entry_date, description, created_by)
                        values (%s, 'expense', '2025-08-01', 'x', %s) returning created_by""",
                     (world.companies["ART"], world.users["super"])).fetchone()[0]
    assert eid == me


def test_opening_balance_needs_company_admin(db, world):
    a = lambda c: world.accounts[("ART", c)]  # noqa: E731
    as_user(db, world.users[user_key("ART", "accountant")])
    eid = create_entry(db, world.companies["ART"], "opening",
                       [(a("CASH"), 198000, 0), (a("OBE"), 0, 198000)], entry_date="2025-04-01")
    with raises_db(match="company admin"):
        post(db, eid)
    as_user(db, world.users[user_key("ART", "company_admin")])
    post(db, eid)


def test_second_opening_balance_needs_approval(db, world):
    a = lambda c: world.accounts[("JGT", c)]  # noqa: E731
    cid = world.companies["JGT"]
    as_user(db, world.users[user_key("JGT", "company_admin")])
    first = create_entry(db, cid, "opening", [(a("CASH"), 1000, 0), (a("OBE"), 0, 1000)])
    post(db, first)
    second = create_entry(db, cid, "opening", [(a("CASH"), 50, 0), (a("OBE"), 0, 50)])
    with raises_db(match="approved opening_balance"):
        post(db, second)
    db.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
               "values (%s, 'opening_balance', %s, 'Correct opening cash')", (cid, second))
    as_user(db, world.users["super"])
    db.execute("update fin.approval_requests set status = 'approved' where target_id = %s", (second,))
    as_user(db, world.users[user_key("JGT", "company_admin")])
    post(db, second)


def test_only_super_admin_creates_companies(db, world):
    as_user(db, world.users[user_key("ART", "company_admin")])
    with raises_db(sqlstate="42501"):
        db.execute("insert into fin.companies (code, name) values ('XYZ', 'SAMPLE X')")
    as_user(db, world.users["super"])
    cid = db.execute("insert into fin.companies (code, name) values ('XYZ', 'SAMPLE X') returning id").fetchone()[0]
    n = db.execute("select count(*) from fin.accounts where company_id = %s and is_system", (cid,)).fetchone()[0]
    assert n == 6, "default chart of accounts is seeded"


def test_company_admin_cannot_grant_company_admin_or_touch_self(db, world):
    admin = world.users[user_key("ART", "company_admin")]
    as_user(db, admin)
    target = world.users[user_key("JGT", "viewer")]
    with raises_db(sqlstate="42501", match="super admin"):
        db.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, 'company_admin')",
                   (target, world.companies["ART"]))
    with raises_db(sqlstate="42501", match="your own"):
        db.execute("update fin.company_memberships set role = 'accountant' where user_id = %s", (admin,))
    # but may grant ordinary roles in own company
    db.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, 'viewer')",
               (target, world.companies["ART"]))
    # and never in another company
    with raises_db(sqlstate="42501"):
        db.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, 'viewer')",
                   (world.users[user_key("ART", "viewer")], world.companies["JGT"]))


@pytest.mark.parametrize("flag", ["is_super_admin", "can_view_consolidated", "is_active"])
def test_privilege_flags_only_by_super_admin(db, world, flag):
    me = world.users[user_key("ART", "company_admin")]
    as_user(db, me)
    new = "false" if flag == "is_active" else "true"
    with raises_db(sqlstate="42501"):
        db.execute(f"update fin.profiles set {flag} = {new} where user_id = %s",
                   (world.users[user_key("ART", "viewer")],))
    with raises_db(sqlstate="42501"):
        db.execute(f"update fin.profiles set {flag} = {new} where user_id = %s", (me,))


def test_user_can_edit_own_name(db, world):
    me = world.users[user_key("ART", "viewer")]
    as_user(db, me)
    assert db.execute("update fin.profiles set full_name = 'SAMPLE New Name' where user_id = %s",
                      (me,)).rowcount == 1


def test_super_admin_cannot_remove_own_rights(db, world):
    as_user(db, world.users["super"])
    with raises_db(match="your own super admin"):
        db.execute("update fin.profiles set is_super_admin = false where user_id = %s", (world.users["super"],))


@pytest.mark.parametrize("role,visible", [("company_admin", True), ("accountant", False),
                                          ("data_entry", False), ("viewer", False)])
def test_audit_log_visible_to_admins_only(db, world, role, visible):
    as_user(db, world.users[user_key("ART", role)])
    n = db.execute("select count(*) from fin.audit_log").fetchone()[0]
    assert (n > 0) is visible


def test_security_events_super_admin_only(db, world):
    as_user(db, world.users[user_key("ART", "company_admin")])
    assert db.execute("select count(*) from fin.security_events").fetchone()[0] == 0
    as_user(db, world.users["super"])
    assert db.execute("select count(*) from fin.security_events").fetchone()[0] > 0


def test_only_company_admin_closes_periods(db, world):
    cid = world.companies["ART"]
    as_user(db, world.users[user_key("ART", "accountant")])
    assert db.execute("update fin.financial_periods set status = 'closed' where company_id = %s "
                      "and start_date = '2025-08-01'", (cid,)).rowcount == 0
    as_user(db, world.users[user_key("ART", "company_admin")])
    assert db.execute("update fin.financial_periods set status = 'closed' where company_id = %s "
               "and start_date = '2025-08-01'", (cid,)).rowcount == 1
