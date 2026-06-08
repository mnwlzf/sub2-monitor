from fastapi import APIRouter

from app.api import auth, notifications, platforms, sub2api

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(notifications.router)
api_router.include_router(platforms.router)
api_router.include_router(sub2api.router)
