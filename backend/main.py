"""Main FastAPI application entry point."""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.admin_routes import router as admin_router
from api.routes import router as api_router
from config import get_settings
from core.logging import setup_logging, get_logger

# Setup logging before anything else
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    settings = get_settings()
    
    # Configure GCP credentials if provided
    settings.configure_gcp_credentials()
    
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"CORS origins: {settings.get_cors_origins()}")
    
    # Log provider configuration
    logger.info(f"")
    logger.info(f"╔══════════════════════════════════════════════════════════════")
    logger.info(f"║ 🔧 PROVIDER CONFIGURATION")
    logger.info(f"║ Embeddings: {settings.embedding_provider}")
    logger.info(f"║ Vector Store: {settings.vector_store_provider}")
    logger.info(f"║ RAG Pipeline: {settings.rag_provider}")
    if settings.gcp_project_id:
        logger.info(f"║ GCP Project: {settings.gcp_project_id}")
    logger.info(f"╚══════════════════════════════════════════════════════════════")

    # Initialize database tables (in production, use Alembic migrations)
    # from api.dependencies import get_engine
    # from models import Base
    # async with get_engine().begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
    logger.info("Shutting down...")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="AI-powered assistant for HVAC technicians",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()

        # Log request
        logger.info(
            f"REQUEST  | {request.method} {request.url.path} | "
            f"client={request.client.host if request.client else 'unknown'}"
        )

        # Process request
        try:
            response = await call_next(request)

            # Log response
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"RESPONSE | {request.method} {request.url.path} | "
                f"status={response.status_code} | duration={duration_ms}ms"
            )

            return response
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                f"ERROR    | {request.method} {request.url.path} | "
                f"error={type(e).__name__}: {e} | duration={duration_ms}ms"
            )
            raise

    # Include routers
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
