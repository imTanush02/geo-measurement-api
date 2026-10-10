"""
FastAPI application entry point.

Configures the application with CORS, logging, lifecycle events,
and registers all API routers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers import files

# ─── Logging Configuration ─────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-30s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()


# ─── Application Lifecycle ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME}")
    await init_db()
    logger.info("Database initialized.")
    settings.upload_path  # Ensure upload directory exists
    logger.info(f"Upload directory: {settings.upload_path.resolve()}")
    yield
    logger.info(f"Shutting down {settings.APP_NAME}")


# ─── Application Factory ───────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "A backend API service that accepts geospatial files (Shapefile, KML), "
        "processes the features within them, and returns measurement information "
        "including area for polygons and length for linestrings. "
        "Automatically handles CRS transformation to projected coordinate systems "
        "for accurate measurements."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Middleware ─────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ──────────────────────────────────────────────

app.include_router(files.router)


# ─── Health Check ───────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    description="Returns the service health status.",
)
async def health_check():
    """Service health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": "1.0.0",
    }


@app.get(
    "/",
    tags=["System"],
    summary="Root",
    description="API root with service information.",
)
async def root():
    """Root endpoint with API information."""
    return {
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "upload_file": "POST /api/files/",
            "list_files": "GET /api/files/",
            "file_info": "GET /api/files/{id}/",
            "measurements": "GET /api/files/{id}/measurements/",
            "delete_file": "DELETE /api/files/{id}/",
        },
    }
