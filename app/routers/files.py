"""
File upload and measurement API router.

Provides endpoints for:
    - POST   /api/files/                 → Upload a geospatial file
    - GET    /api/files/{id}/            → Get file information
    - GET    /api/files/{id}/measurements/ → Get feature measurements
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.config import get_settings
from app.models import GeoFile, Feature, FileStatus, generate_uuid
from app.schemas import (
    FileUploadResponse,
    FileInfoResponse,
    FeatureMeasurement,
    MeasurementsResponse,
    ErrorResponse,
)
from app.services.file_processor import process_file

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/files", tags=["Files"])


def _detect_file_type(filename: str) -> str:
    """
    Detect the geospatial file type from the filename extension.

    Args:
        filename: Original filename of the uploaded file.

    Returns:
        File type string ("shapefile" or "kml").

    Raises:
        HTTPException: If the file extension is not supported.
    """
    ext = Path(filename).suffix.lower()
    if ext == ".zip":
        return "shapefile"
    elif ext == ".kml":
        return "kml"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: '{ext}'. Accepted formats: .zip (Shapefile), .kml",
        )


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=201,
    summary="Upload a geospatial file",
    description="Upload a .zip (Shapefile) or .kml file for processing. "
    "The file is saved and processed asynchronously.",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file"},
        413: {"model": ErrorResponse, "description": "File too large"},
    },
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Geospatial file (.zip or .kml)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and process a geospatial file.

    The file is validated, saved to disk, and a background task is started
    to extract features and calculate measurements.
    """
    # Validate filename
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    # Detect file type
    file_type = _detect_file_type(file.filename)

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Generate unique ID and save file
    file_id = generate_uuid()
    clean_filename = Path(file.filename).name
    safe_filename = f"{file_id}_{clean_filename}"
    save_path = settings.upload_path / safe_filename

    save_path.write_bytes(content)
    logger.info(f"File saved: {save_path} ({len(content)} bytes)")

    # Create database record
    geo_file = GeoFile(
        id=file_id,
        filename=safe_filename,
        original_filename=file.filename,
        file_path=str(save_path),
        file_type=file_type,
        file_size_bytes=len(content),
        status=FileStatus.PENDING,
    )
    db.add(geo_file)
    await db.commit()
    await db.refresh(geo_file)

    # Start background processing
    background_tasks.add_task(_process_file_task, file_id)

    return FileUploadResponse(
        id=geo_file.id,
        filename=geo_file.original_filename,
        file_type=geo_file.file_type,
        file_size_bytes=geo_file.file_size_bytes,
        status=geo_file.status.value,
        message="File uploaded successfully. Processing started.",
    )


async def _process_file_task(file_id: str) -> None:
    """Background task wrapper for file processing."""
    from app.database import async_session

    async with async_session() as db:
        try:
            result = await db.execute(
                select(GeoFile).where(GeoFile.id == file_id)
            )
            geo_file = result.scalar_one_or_none()
            if geo_file:
                await process_file(geo_file, db)
        except Exception as e:
            logger.error(f"Background processing failed for {file_id}: {e}")



@router.get(
    "/{file_id}/",
    response_model=FileInfoResponse,
    summary="Get file information",
    description="Returns detailed information about an uploaded file, "
    "including feature count, CRS, and processing status.",
    responses={404: {"model": ErrorResponse}},
)
async def get_file_info(file_id: str, db: AsyncSession = Depends(get_db)):
    """Get information about a specific uploaded file."""
    result = await db.execute(
        select(GeoFile).where(GeoFile.id == file_id)
    )
    geo_file = result.scalar_one_or_none()

    if not geo_file:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")

    return FileInfoResponse(
        id=geo_file.id,
        filename=geo_file.original_filename,
        file_type=geo_file.file_type,
        file_size_bytes=geo_file.file_size_bytes,
        feature_count=geo_file.feature_count,
        crs=geo_file.crs,
        status=geo_file.status.value,
        error_message=geo_file.error_message,
        uploaded_at=geo_file.uploaded_at,
        processed_at=geo_file.processed_at,
    )


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get feature measurements",
    description="Returns measurements (area, length) for all features "
    "extracted from the uploaded file.",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "File not yet processed"},
    },
)
async def get_measurements(file_id: str, db: AsyncSession = Depends(get_db)):
    """Get measurements for all features in a file."""
    result = await db.execute(
        select(GeoFile).where(GeoFile.id == file_id)
    )
    geo_file = result.scalar_one_or_none()

    if not geo_file:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")

    if geo_file.status == FileStatus.PENDING or geo_file.status == FileStatus.PROCESSING:
        raise HTTPException(
            status_code=409,
            detail=f"File is still being processed (status: {geo_file.status.value}). "
            "Please try again later.",
        )

    if geo_file.status == FileStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"File processing failed: {geo_file.error_message}",
        )

    # Fetch features
    features_result = await db.execute(
        select(Feature)
        .where(Feature.file_id == file_id)
        .order_by(Feature.feature_index)
    )
    features = features_result.scalars().all()

    return MeasurementsResponse(
        file_id=geo_file.id,
        filename=geo_file.original_filename,
        crs=geo_file.crs,
        feature_count=geo_file.feature_count,
        features=[
            FeatureMeasurement(
                feature_index=f.feature_index,
                geometry_type=f.geometry_type,
                geometry_wkt=f.geometry_wkt,
                original_crs=f.original_crs,
                projected_crs=f.projected_crs,
                properties=f.properties,
                area_sq_meters=f.area_sq_meters,
                length_meters=f.length_meters,
                measurement_error=f.measurement_error,
            )
            for f in features
        ],
    )


