"""
SQLAlchemy ORM models for the geospatial measurement application.

Defines the database schema for uploaded files and their extracted
features with measurement data.
"""

import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Enum, Text, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from app.database import Base


class FileStatus(str, enum.Enum):
    """Processing status of an uploaded file."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def generate_uuid() -> str:
    """Generate a short UUID string for use as primary key."""
    return uuid.uuid4().hex[:12]


class GeoFile(Base):
    """
    Represents an uploaded geospatial file.

    Stores metadata about the file and its processing status.
    Features are extracted and stored separately in the Feature table.
    """

    __tablename__ = "geo_files"

    id = Column(String(12), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)  # "shapefile" or "kml"
    file_size_bytes = Column(Integer, nullable=False)
    feature_count = Column(Integer, default=0)
    crs = Column(String(50), nullable=True)
    status = Column(Enum(FileStatus), default=FileStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    uploaded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship to features
    features = relationship(
        "Feature",
        back_populates="geo_file",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<GeoFile(id={self.id}, filename={self.original_filename}, status={self.status})>"


class Feature(Base):
    """
    Represents a single geospatial feature extracted from an uploaded file.

    Stores the geometry information, properties, and calculated measurements
    for each feature found in the uploaded geospatial file.
    """

    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(12), ForeignKey("geo_files.id"), nullable=False)
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String(50), nullable=False)
    geometry_wkt = Column(Text, nullable=False)  # Well-Known Text representation
    original_crs = Column(String(50), nullable=True)
    projected_crs = Column(String(50), nullable=True)
    properties = Column(JSON, nullable=True)

    # Measurements
    area_sq_meters = Column(Float, nullable=True)
    length_meters = Column(Float, nullable=True)
    measurement_error = Column(String(500), nullable=True)

    # Relationship back to file
    geo_file = relationship("GeoFile", back_populates="features")

    def __repr__(self) -> str:
        return f"<Feature(id={self.id}, type={self.geometry_type}, file_id={self.file_id})>"
