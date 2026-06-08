from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.sub2api import Sub2APISQLLog
from app.schemas.sub2api import (
    Sub2APIDatabaseStatusResponse,
    Sub2APISQLLogPageResponse,
    Sub2APISQLLogResponse,
)
from app.services.sub2api_database import probe_sub2api_database, safe_database_config

router = APIRouter(
    prefix="/sub2api",
    tags=["sub2api"],
    dependencies=[Depends(current_user)],
)


@router.get("/database/status", response_model=Sub2APIDatabaseStatusResponse)
def database_status(
    test: bool = True,
    settings: Settings = Depends(get_settings),
) -> Sub2APIDatabaseStatusResponse:
    database = settings.sub2api.database
    probe = probe_sub2api_database(database) if test else None
    return Sub2APIDatabaseStatusResponse(
        config=safe_database_config(database),
        probe=probe.__dict__ if probe else None,
    )


@router.get("/sql-logs", response_model=Sub2APISQLLogPageResponse)
def list_sql_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, max_length=32),
    operation: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),
) -> Sub2APISQLLogPageResponse:
    conditions = []
    if status:
        conditions.append(Sub2APISQLLog.status == status)
    if operation:
        conditions.append(Sub2APISQLLog.operation == operation)

    total = db.scalar(select(func.count()).select_from(Sub2APISQLLog).where(*conditions)) or 0
    items = db.scalars(
        select(Sub2APISQLLog)
        .where(*conditions)
        .order_by(Sub2APISQLLog.created_at.desc(), Sub2APISQLLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Sub2APISQLLogPageResponse(
        items=list(items),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sql-logs/{log_id}", response_model=Sub2APISQLLogResponse)
def get_sql_log(log_id: int, db: Session = Depends(get_db)) -> Sub2APISQLLog:
    log = db.get(Sub2APISQLLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="SQL log not found")
    return log
