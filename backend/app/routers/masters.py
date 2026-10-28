"""Parties (customers/suppliers/employees) and accounts (cash, bank, income, expense)."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from ..db import get_db
from ..errors import ConflictError

router = APIRouter(tags=["masters"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PartyKind = Literal["customer", "supplier", "employee", "other"]


class PartyIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: Name
    kind: PartyKind
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9+\- ]{7,20}$")] | None = None
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[0-9A-Z]{15}$")] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PartyPatch(BaseModel):
    model_config = {"extra": "forbid"}
    version: int
    name: Name | None = None
    kind: PartyKind | None = None
    phone: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


@router.get("/companies/{company_id}/parties")
def list_parties(company_id: uuid.UUID, db=Depends(get_db),
                 q: Annotated[str | None, Query(max_length=100)] = None,
                 kind: PartyKind | None = None, include_inactive: bool = False):
    where, params = ["company_id = %(cid)s"], {"cid": company_id}
    if not include_inactive:
        where.append("is_active")
    if kind:
        where.append("kind = %(kind)s")
        params["kind"] = kind
    if q and q.strip():
        where.append("lower(name) like %(like)s")
        params["like"] = "%" + q.strip().lower().replace("%", "\\%").replace("_", "\\_") + "%"
    return db.execute(
        f"""select p.id, p.name, p.kind::text, p.phone, p.gstin, p.notes, p.is_active, p.version,
                   (select coalesce(sum(l.debit - l.credit), 0)::numeric(14,2)::text from fin.journal_lines l
                      join fin.journal_entries e on e.id = l.entry_id join fin.accounts a on a.id = l.account_id
                      where l.party_id = p.id and e.status in ('posted', 'reversed') and a.subtype = 'receivable')
                     as receivable_balance,
                   (select coalesce(sum(l.credit - l.debit), 0)::numeric(14,2)::text from fin.journal_lines l
                      join fin.journal_entries e on e.id = l.entry_id join fin.accounts a on a.id = l.account_id
                      where l.party_id = p.id and e.status in ('posted', 'reversed') and a.subtype = 'payable')
                     as payable_balance
            from fin.parties p where {' and '.join(where)} order by p.name limit 500""",
        params,
    ).fetchall()


@router.post("/companies/{company_id}/parties", status_code=201)
def create_party(company_id: uuid.UUID, body: PartyIn, db=Depends(get_db)):
    return db.execute(
        """insert into fin.parties (company_id, name, kind, phone, gstin, notes)
           values (%s, %s, %s, %s, %s, %s) returning id, name, kind::text, phone, gstin, notes, is_active, version""",
        (company_id, body.name, body.kind, body.phone, body.gstin, body.notes),
    ).fetchone()


@router.patch("/parties/{party_id}")
def patch_party(party_id: uuid.UUID, body: PartyPatch, db=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    if not fields:
        raise HTTPException(422, "Nothing to update.")
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    row = db.execute(f"""update fin.parties set {sets} where id = %(id)s and version = %(version)s
                         returning id, name, kind::text, phone, notes, is_active, version""",
                     {**fields, "id": party_id, "version": body.version}).fetchone()
    if row is None:
        if db.execute("select 1 from fin.parties where id = %s", (party_id,)).fetchone():
            raise ConflictError()
        raise HTTPException(404, "Party not found, or you cannot edit parties.")
    return row


class AccountIn(BaseModel):
    model_config = {"extra": "forbid"}
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9-]{2,20}$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    kind: Literal["cash", "bank", "income", "expense"]
    bank_name: str | None = Field(default=None, max_length=120)
    account_no_last4: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] | None = None


ACCOUNT_KINDS = {"cash": ("asset", "cash"), "bank": ("asset", "bank"),
                 "income": ("income", "other"), "expense": ("expense", "other")}


@router.get("/companies/{company_id}/accounts")
def list_accounts(company_id: uuid.UUID, db=Depends(get_db)):
    return db.execute(
        """select a.id, a.code, a.name, a.type::text, a.subtype::text, a.bank_name, a.account_no_last4,
                  a.is_system, a.is_active, a.version,
                  (select coalesce(sum(l.debit - l.credit), 0)::numeric(14,2)::text from fin.journal_lines l
                     join fin.journal_entries e on e.id = l.entry_id
                     where l.account_id = a.id and e.status in ('posted', 'reversed')) as balance
           from fin.accounts a where a.company_id = %s order by a.type, a.code""",
        (company_id,),
    ).fetchall()


@router.post("/companies/{company_id}/accounts", status_code=201)
def create_account(company_id: uuid.UUID, body: AccountIn, db=Depends(get_db)):
    type_, subtype = ACCOUNT_KINDS[body.kind]
    return db.execute(
        """insert into fin.accounts (company_id, code, name, type, subtype, bank_name, account_no_last4)
           values (%s, %s, %s, %s, %s, %s, %s)
           returning id, code, name, type::text, subtype::text, bank_name, account_no_last4, is_system, is_active, version""",
        (company_id, body.code, body.name, type_, subtype, body.bank_name, body.account_no_last4),
    ).fetchone()
