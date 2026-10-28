import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2,6}$")
    name: str = Field(min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    gstin: str | None = Field(default=None, pattern=r"^[0-9A-Z]{15}$")
    theme_color: str = Field(default="#1c7ed6", pattern=r"^#[0-9a-fA-F]{6}$")


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("")
def list_companies(db=Depends(get_db)):
    return db.execute(
        """select id, code, name, address, gstin, theme_color, fy_start_month, is_active,
                  fin.company_role(id)::text as my_role
           from fin.companies order by name"""
    ).fetchall()


@router.post("", status_code=201)
def create_company(body: CompanyIn, db=Depends(get_db)):
    # RLS allows only super admins; a default chart of accounts is created automatically.
    return db.execute(
        """insert into fin.companies (code, name, address, gstin, theme_color)
           values (%(code)s, %(name)s, %(address)s, %(gstin)s, %(theme_color)s)
           returning id, code, name, theme_color""",
        body.model_dump(),
    ).fetchone()


@router.get("/{company_id}/sites")
def list_sites(company_id: uuid.UUID, db=Depends(get_db)):
    return db.execute(
        "select id, name, is_active from fin.sites where company_id = %s order by name", (company_id,)
    ).fetchall()


@router.post("/{company_id}/sites", status_code=201)
def create_site(company_id: uuid.UUID, body: SiteIn, db=Depends(get_db)):
    row = db.execute(
        "insert into fin.sites (company_id, name) values (%s, %s) returning id, name, is_active",
        (company_id, body.name.strip()),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Company not found")
    return row
