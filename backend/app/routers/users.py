"""Employee administration: create (invite), assign company roles, disable.

Permissions are enforced by RLS and database guards (a company admin can manage
accountant/data-entry/viewer access in their own companies; only a super admin can
grant company admin, consolidated view, or disable/enable a whole account). The
checks here exist to fail fast with clear messages and to avoid creating orphan
login accounts — they are not the security boundary."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ..auth import CurrentUser, current_user
from ..db import get_db, user_transaction
from ..errors import ConflictError
from ..ratelimit import limiter, sensitive_limit
from ..security_events import record_security_event
from ..supabase_admin import AuthAdmin, AuthAdminError, get_auth_admin

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

Role = Literal["company_admin", "accountant", "data_entry", "viewer"]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    company_id: uuid.UUID
    role: Role


class UserPatch(BaseModel):
    version: int
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    can_view_consolidated: bool | None = None


class MembershipPut(BaseModel):
    role: Role
    is_active: bool = True


class StatusChange(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _require_company_admin(db, company_id: uuid.UUID) -> None:
    if not db.execute("select fin.has_role(%s, 'company_admin') as ok", (company_id,)).fetchone()["ok"]:
        raise HTTPException(403, "Only a company admin of this company can manage its employees.")


@router.get("")
def list_users(company_id: uuid.UUID | None = None, db=Depends(get_db)):
    if company_id is not None:
        _require_company_admin(db, company_id)
        return db.execute(
            """select p.user_id, p.full_name, p.email, p.phone, p.is_active, p.is_super_admin,
                      p.can_view_consolidated, p.version, m.role, m.is_active as membership_active,
                      m.version as membership_version
               from fin.company_memberships m join fin.profiles p on p.user_id = m.user_id
               where m.company_id = %s order by p.full_name""",
            (company_id,),
        ).fetchall()
    rows = db.execute(
        """select p.user_id, p.full_name, p.email, p.phone, p.is_active, p.is_super_admin,
                  p.can_view_consolidated, p.version,
                  coalesce(json_agg(json_build_object('company_id', m.company_id, 'role', m.role,
                           'is_active', m.is_active)) filter (where m.user_id is not null), '[]') as memberships
           from fin.profiles p left join fin.company_memberships m on m.user_id = p.user_id
           where fin.can_manage_user(p.user_id) or p.user_id = fin.uid()
           group by p.user_id order by p.full_name"""
    ).fetchall()
    return rows


@router.post("", status_code=201)
@limiter.limit(sensitive_limit)
def create_user(request: Request, body: UserCreate, user: CurrentUser = Depends(current_user),
                db=Depends(get_db), admin: AuthAdmin = Depends(get_auth_admin)):
    _require_company_admin(db, body.company_id)
    if body.role == "company_admin" and not db.execute("select fin.is_super_admin() as ok").fetchone()["ok"]:
        raise HTTPException(403, "Only a super admin can create company admins.")

    existing = db.execute("select user_id from fin.profiles where lower(email) = lower(%s)",
                          (body.email,)).fetchone()
    if existing:
        user_id = existing["user_id"]
    else:
        try:
            user_id = admin.invite_user(body.email, body.full_name)
        except AuthAdminError:
            raise HTTPException(502, "Could not create the login account. Please try again.") from None
        db.execute("insert into fin.profiles (user_id, full_name, email, phone) values (%s, %s, %s, %s)",
                   (user_id, body.full_name.strip(), body.email.lower(), body.phone))
    db.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, %s)",
               (user_id, body.company_id, body.role))
    record_security_event("user_access_granted", user_id=user.id, client_ip=_ip(request),
                          detail={"target": str(user_id), "company_id": str(body.company_id), "role": body.role,
                                  "invited": not existing})
    return {"user_id": user_id, "invited": not existing}


@router.patch("/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, db=Depends(get_db)):
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    if not fields:
        raise HTTPException(422, "Nothing to update.")
    sets = ", ".join(f"{k} = %({k})s" for k in fields)  # keys come from the pydantic model only
    row = db.execute(
        f"update fin.profiles set {sets} where user_id = %(uid)s and version = %(version)s returning version",
        {**fields, "uid": user_id, "version": body.version},
    ).fetchone()
    if row is None:
        if db.execute("select 1 from fin.profiles where user_id = %s", (user_id,)).fetchone():
            raise ConflictError()
        raise HTTPException(404, "User not found.")
    return row


@router.put("/{user_id}/memberships/{company_id}")
@limiter.limit(sensitive_limit)
def put_membership(request: Request, user_id: uuid.UUID, company_id: uuid.UUID, body: MembershipPut,
                   user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    _require_company_admin(db, company_id)
    row = db.execute(
        """insert into fin.company_memberships (user_id, company_id, role, is_active) values (%s, %s, %s, %s)
           on conflict (user_id, company_id) do update set role = excluded.role, is_active = excluded.is_active
           returning role, is_active, version""",
        (user_id, company_id, body.role, body.is_active),
    ).fetchone()
    record_security_event("membership_changed", user_id=user.id, client_ip=_ip(request),
                          detail={"target": str(user_id), "company_id": str(company_id),
                                  "role": body.role, "is_active": body.is_active})
    return row


def _set_active(request: Request, user: CurrentUser, user_id: uuid.UUID, active: bool, reason: str,
                admin: AuthAdmin) -> dict:
    # Committed in its own transaction FIRST: the database blocks the account's data
    # access immediately, even if the login provider call below fails.
    with user_transaction(user, getattr(request.state, "request_id", ""), _ip(request)) as db:
        if user_id == user.id:
            raise HTTPException(422, "You cannot disable or enable your own account.")
        row = db.execute("update fin.profiles set is_active = %s where user_id = %s returning user_id",
                         (active, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "User not found.")
    event = "user_reactivated" if active else "user_deactivated"
    record_security_event(event, user_id=user.id, client_ip=_ip(request),
                          detail={"target": str(user_id), "reason": reason})
    try:
        admin.set_banned(user_id, banned=not active)
        login_updated = True
    except AuthAdminError:
        login_updated = False
        record_security_event("auth_ban_sync_failed", user_id=user.id, detail={"target": str(user_id)})
    return {"user_id": user_id, "is_active": active, "login_provider_updated": login_updated}


@router.post("/{user_id}/deactivate")
@limiter.limit(sensitive_limit)
def deactivate(request: Request, user_id: uuid.UUID, body: StatusChange,
               user: CurrentUser = Depends(current_user), admin: AuthAdmin = Depends(get_auth_admin)):
    return _set_active(request, user, user_id, False, body.reason, admin)


@router.post("/{user_id}/reactivate")
@limiter.limit(sensitive_limit)
def reactivate(request: Request, user_id: uuid.UUID, body: StatusChange,
               user: CurrentUser = Depends(current_user), admin: AuthAdmin = Depends(get_auth_admin)):
    return _set_active(request, user, user_id, True, body.reason, admin)
