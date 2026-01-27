"""API routes."""

from api.routes import router as api_router
from api.admin_routes import router as admin_router

__all__ = ["api_router", "admin_router"]
