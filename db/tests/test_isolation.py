"""Company isolation: no role in one company can read or write the other company's data."""
import psycopg
import pytest

from conftest import ROLES, as_superuser, as_user, raises_db, user_key

COMPANY_TABLES = [
    "sites", "accounts", "parties", "financial_periods", "journal_entries", "journal_lines",
    "approval_requests", "bills", "installment_schedule", "bill_allocations", "follow_ups",
    "attachments", "reconciliations",
]
ACCOUNTANT_ONLY_TABLES = ["import_batches", "import_rows"]
ALL_TABLES = COMPANY_TABLES + ACCOUNTANT_ONLY_TABLES + [
    "companies", "profiles", "company_memberships", "audit_log", "security_events",
    "doc_counters", "backup_runs", "system_settings",
]


def company_ids_visible(db, table):
    col = "id" if table == "companies" else "company_id"
    return {r[0] for r in db.execute(f"select distinct {col} from fin.{table}").fetchall()}


@pytest.mark.parametrize("table", COMPANY_TABLES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("company,other", [("JGT", "ART"), ("ART", "JGT")])
def test_role_sees_only_own_company(db, world, table, role, company, other):
    as_user(db, world.users[user_key(company, role)])
    seen = company_ids_visible(db, table)
    assert world.companies[other] not in seen
    assert seen == {world.companies[company]}, f"{role} should see its own {table} rows"


@pytest.mark.parametrize("table", ACCOUNTANT_ONLY_TABLES)
@pytest.mark.parametrize("role", ROLES)
def test_import_staging_needs_accountant(db, world, table, role):
    as_user(db, world.users[user_key("ART", role)])
    seen = company_ids_visible(db, table)
    expected = {world.companies["ART"]} if role in ("company_admin", "accountant") else set()
    assert seen == expected


@pytest.mark.parametrize("table", ["companies", "audit_log"])
def test_company_scoped_meta_tables(db, world, table):
    as_user(db, world.users[user_key("JGT", "company_admin")])
    assert company_ids_visible(db, table) - {None} == {world.companies["JGT"]}


@pytest.mark.parametrize("table", ALL_TABLES)
def test_no_jwt_sees_nothing(db, world, table):
    as_user(db, None)
    if table == "doc_counters":
        with raises_db(sqlstate="42501"):
            db.execute(f"select 1 from fin.{table}")
        return
    assert db.execute(f"select count(*) from fin.{table}").fetchone()[0] == 0


@pytest.mark.parametrize("table", ALL_TABLES)
@pytest.mark.parametrize("api_role", ["anon", "authenticated"])
def test_supabase_api_roles_have_no_access(db, world, table, api_role):
    """Even with a valid JWT, the public REST roles can't touch the fin schema."""
    as_superuser(db)
    db.execute("select set_config('request.jwt.claims', %s, true)",
               (f'{{"sub": "{world.users["super"]}"}}',))
    db.execute(f"set local role {api_role}")
    with raises_db(sqlstate="42501"):
        db.execute(f"select 1 from fin.{table} limit 1")


def test_super_admin_sees_both(db, world):
    as_user(db, world.users["super"])
    assert company_ids_visible(db, "journal_entries") == set(world.companies.values())


def test_multi_company_viewer_sees_both_but_cannot_write(db, world):
    as_user(db, world.users["both:viewer"])
    assert company_ids_visible(db, "bills") == set(world.companies.values())
    with raises_db(sqlstate="42501"):
        db.execute("insert into fin.parties (company_id, name, kind) values (%s, 'X', 'customer')",
                   (world.companies["ART"],))


@pytest.mark.parametrize("key", ["disabled:accountant", "inactive_membership:accountant"])
def test_revoked_access_sees_nothing(db, world, key):
    as_user(db, world.users[key])
    for table in COMPANY_TABLES:
        assert db.execute(f"select count(*) from fin.{table}").fetchone()[0] == 0, table


def test_deactivation_takes_effect_immediately(db, world):
    uid = world.users[user_key("ART", "accountant")]
    as_user(db, uid)
    assert db.execute("select count(*) from fin.journal_entries").fetchone()[0] > 0
    as_user(db, world.users["super"])
    db.execute("update fin.profiles set is_active = false where user_id = %s", (uid,))
    as_user(db, uid)
    assert db.execute("select count(*) from fin.journal_entries").fetchone()[0] == 0


@pytest.mark.parametrize("role", ROLES)
def test_cannot_insert_into_other_company(db, world, role):
    as_user(db, world.users[user_key("JGT", role)])
    with raises_db(sqlstate="42501"):
        db.execute("insert into fin.parties (company_id, name, kind) values (%s, 'Intruder', 'customer')",
                   (world.companies["ART"],))
    with raises_db(sqlstate="42501"):
        db.execute("""insert into fin.journal_entries (company_id, entry_type, entry_date, description)
                      values (%s, 'expense', '2025-08-01', 'Intruder')""", (world.companies["ART"],))


@pytest.mark.parametrize("role", ROLES)
def test_cannot_update_or_delete_other_company(db, world, role):
    as_user(db, world.users[user_key("JGT", role)])
    art = world.companies["ART"]
    for sql in (
        "update fin.parties set name = 'hacked' where company_id = %s",
        "update fin.journal_entries set description = 'hacked' where company_id = %s",
        "update fin.bills set notes = 'hacked' where company_id = %s",
        "delete from fin.journal_entries where company_id = %s",
        "delete from fin.bills where company_id = %s",
    ):
        assert db.execute(sql, (art,)).rowcount == 0, sql


def test_cross_company_reference_rejected_even_for_super_admin(db, world):
    """A JGT entry can never point at an ART party or account."""
    as_user(db, world.users["super"])
    jgt = world.companies["JGT"]
    with raises_db(sqlstate="23503"):
        db.execute("""insert into fin.journal_entries (company_id, entry_type, entry_date, description, party_id)
                      values (%s, 'receipt', '2025-08-01', 'x', %s)""", (jgt, world.parties["ART"]))
    eid = db.execute("""insert into fin.journal_entries (company_id, entry_type, entry_date, description)
                        values (%s, 'expense', '2025-08-01', 'x') returning id""", (jgt,)).fetchone()[0]
    with raises_db(sqlstate="23503"):
        db.execute("""insert into fin.journal_lines (entry_id, company_id, line_no, account_id, debit)
                      values (%s, %s, 1, %s, 10)""", (eid, jgt, world.accounts[("ART", "CASH")]))
    with raises_db(sqlstate="23503"):  # line claiming the other company
        db.execute("""insert into fin.journal_lines (entry_id, company_id, line_no, account_id, debit)
                      values (%s, %s, 1, %s, 10)""", (eid, world.companies["ART"], world.accounts[("ART", "CASH")]))


def test_cannot_read_other_company_via_bill_balances(db, world):
    as_user(db, world.users[user_key("JGT", "accountant")])
    rows = db.execute("select * from fin.bill_balances(%s)", (world.companies["ART"],)).fetchall()
    assert rows == []


def test_membership_visibility(db, world):
    as_user(db, world.users[user_key("ART", "accountant")])
    rows = db.execute("select user_id from fin.company_memberships").fetchall()
    assert {r[0] for r in rows} == {world.users[user_key("ART", "accountant")]}
    as_user(db, world.users[user_key("ART", "company_admin")])
    companies = {r[0] for r in db.execute("select company_id from fin.company_memberships").fetchall()}
    assert companies == {world.companies["ART"]}


def test_ensure_period_cannot_be_called_directly(db, world):
    """Security review fix: no direct creation of periods (in any company)."""
    as_user(db, world.users[user_key("JGT", "company_admin")])
    with raises_db(match="only run inside a database trigger"):
        db.execute("select fin.ensure_period(%s, '2031-01-15')", (world.companies["ART"],))


def test_reversal_mismatch_probe_sees_nothing_of_other_company(db, world):
    """Security review fix: comparing another company's entries reveals nothing (RLS applies)."""
    as_superuser(db)
    art_entries = [r[0] for r in db.execute(
        "select id from fin.journal_entries where company_id = %s and status = 'posted' limit 2",
        (world.companies["ART"],)).fetchall()]
    as_user(db, world.users[user_key("JGT", "accountant")])
    n = db.execute("select fin.reversal_mismatches(%s, %s)", (art_entries[0], art_entries[1])).fetchone()[0]
    assert n == 0  # lines are invisible, so nothing can be learned


def test_every_definer_function_is_guarded(db, world):
    """Every SECURITY DEFINER function the API role may call is on a reviewed allow-list."""
    as_superuser(db)
    rows = db.execute("""select p.proname from pg_proc p where p.pronamespace = 'fin'::regnamespace and p.prosecdef
                         and has_function_privilege('app_api', p.oid, 'execute') and p.prorettype <> 'trigger'::regtype""").fetchall()
    reviewed = {  # read-only permission checks about the current user, or trigger-only / self-checking
        "backup_fingerprint", "backup_health", "can_edit_bill", "can_edit_entry", "can_manage_user", "company_role",
        "consume_approval", "ensure_period", "has_role", "is_company_admin_anywhere", "is_super_admin",
        "next_entry_no", "shares_company", "validate_posting"}
    assert {r[0] for r in rows} <= reviewed, {r[0] for r in rows} - reviewed
