"""
Pydantic schemas for API request/response serialization.

Defines the data contracts for the REST API, ensuring consistent
and validated input/output across all endpoints.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ─── File Schemas ───────────────────────────────────────────────────

class FileUploadResponse(BaseModel):
    """Response after a successful file upload."""

    id: str = Field(..., description="Unique identifier for the uploaded file")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="Detected file type (shapefile/kml)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    status: str = Field(..., description="Processing status")
    message: str = Field(..., description="Status message")

    model_config = {"from_attributes": True}


class FileInfoResponse(BaseModel):
    """Detailed information about an uploaded file."""

    id: str
    filename: str
    file_type: str
    file_size_bytes: int
    feature_count: int
    crs: str | None
    status: str
    error_message: str | None = None
    uploaded_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ─── Feature & Measurement Schemas ──────────────────────────────────

class FeatureMeasurement(BaseModel):
    """Measurement data for a single feature."""

    feature_index: int = Field(..., description="Index of the feature in the file")
    geometry_type: str = Field(..., description="Type of geometry (Point, LineString, Polygon, etc.)")
    geometry_wkt: str = Field(..., description="Geometry in Well-Known Text format")
    original_crs: str | None = Field(None, description="Original CRS of the feature")
    projected_crs: str | None = Field(None, description="Projected CRS used for measurement")
    properties: dict | None = Field(None, description="Feature attributes/properties")
    area_sq_meters: float | None = Field(None, description="Area in square meters (Polygon only)")
    length_meters: float | None = Field(None, description="Length in meters (LineString only)")
    measurement_error: str | None = Field(
        None, description="Error message if measurement could not be calculated"
    )

    model_config = {"from_attributes": True}


class MeasurementsResponse(BaseModel):
    """Response containing measurements for all features in a file."""

    file_id: str
    filename: str
    crs: str | None
    feature_count: int
    features: list[FeatureMeasurement]


# ─── Error Schemas ──────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str = Field(..., description="Error description")
