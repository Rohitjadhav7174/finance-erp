from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import CurrentUser, current_user
from ..db import get_db
from ..security_events import record_security_event

router = APIRouter(tags=["me"])


@router.get("/me")
def me(request: Request, user: CurrentUser = Depends(current_user), db=Depends(get_db)):
    profile = db.execute(
        """select user_id, full_name, email, phone, is_active, is_super_admin, can_view_consolidated, version
           from fin.profiles where user_id = %s""",
        (user.id,),
    ).fetchone()
    if profile is None or not profile["is_active"]:
        record_security_event("access_denied_inactive", user_id=user.id, email=user.email,
                              client_ip=request.client.host if request.client else "")
        raise HTTPException(403, "Your account is not active. Contact your administrator.")
    companies = db.execute(
        """select c.id, c.code, c.name, c.theme_color, c.fy_start_month,
                  coalesce(fin.company_role(c.id)::text, case when %s then 'super_admin' end) as role
           from fin.companies c where c.is_active order by c.name""",
        (profile["is_super_admin"],),
    ).fetchall()
    return {"profile": profile, "companies": [c for c in companies if c["role"]]}
