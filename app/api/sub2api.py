from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, verify_csrf
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.sub2api import Sub2APIPrioritySyncRun, Sub2APISQLLog
from app.models.user import User
from app.schemas.sub2api import (
    Sub2APIDatabaseStatusResponse,
    Sub2APIPrioritySyncRunPageResponse,
    Sub2APIPrioritySyncRunResponse,
    Sub2APISQLLogPageResponse,
    Sub2APISQLLogResponse,
)
from app.services.priority_sync import refresh_and_sync_sub2api_account_priorities
from app.services.sub2api_database import probe_sub2api_database, safe_database_config

router = APIRouter(
    prefix="/sub2api",
    tags=["sub2api"],
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


@router.get("/priority-sync/runs", response_model=Sub2APIPrioritySyncRunPageResponse)
def list_priority_sync_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Sub2APIPrioritySyncRunPageResponse:
    total = db.scalar(select(func.count()).select_from(Sub2APIPrioritySyncRun)) or 0
    items = db.scalars(
        select(Sub2APIPrioritySyncRun)
        .order_by(Sub2APIPrioritySyncRun.created_at.desc(), Sub2APIPrioritySyncRun.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Sub2APIPrioritySyncRunPageResponse(
        items=list(items),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/priority-sync/runs/latest",
    response_model=Sub2APIPrioritySyncRunResponse | None,
)
def get_latest_priority_sync_run(
    db: Session = Depends(get_db),
) -> Sub2APIPrioritySyncRun | None:
    return db.scalar(
        select(Sub2APIPrioritySyncRun).order_by(
            Sub2APIPrioritySyncRun.created_at.desc(),
            Sub2APIPrioritySyncRun.id.desc(),
        )
    )


@router.get(
    "/priority-sync/runs/{run_id}",
    response_model=Sub2APIPrioritySyncRunResponse,
)
def get_priority_sync_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> Sub2APIPrioritySyncRun:
    run = db.get(Sub2APIPrioritySyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Priority sync run not found")
    return run


@router.post(
    "/priority-sync/run",
    response_model=Sub2APIPrioritySyncRunResponse,
    dependencies=[Depends(verify_csrf)],
)
async def run_priority_sync(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> Sub2APIPrioritySyncRun:
    return await refresh_and_sync_sub2api_account_priorities(
        db,
        database=settings.sub2api.database,
        user=user,
    )
