"""Backup status for administrators. Backups themselves run outside the app (scheduled job),
so a compromised web server cannot read or delete them."""
from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db

router = APIRouter(tags=["admin-backups"])


@router.get("/admin/backup-health")
def health(db=Depends(get_db)):
    h = db.execute("select fin.backup_health() as h").fetchone()["h"]
    if h is None:
        raise HTTPException(403, "Only administrators can see backup status.")
    return h


@router.get("/admin/backups")
def runs(db=Depends(get_db)):
    if not db.execute("select fin.is_super_admin() as ok").fetchone()["ok"]:
        raise HTTPException(403, "Only the super admin can see backup details.")
    rows = db.execute("""select id, started_at, finished_at, status::text, object_key, size_bytes, sha256, row_counts,
                                control_totals, verified_at, error
                         from fin.backup_runs order by started_at desc limit 60""").fetchall()
    return {"health": health(db), "runs": rows}
