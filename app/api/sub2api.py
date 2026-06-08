from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.core.config import Settings, get_settings
from app.schemas.sub2api import Sub2APIDatabaseStatusResponse
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
