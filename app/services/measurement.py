"""
Measurement calculation service.

Computes area and length for supported geometry types after
transforming them to an appropriate projected CRS.

Supported geometry types:
    - Polygon / MultiPolygon → area (sq meters)
    - LineString / MultiLineString → length (meters)
    - Point / MultiPoint → no measurement required
    - GeometryCollection → handled gracefully (skipped)
"""

import logging
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from app.services.crs_handler import (
    get_projected_crs_for_geometry,
    transform_geometry,
)

logger = logging.getLogger(__name__)

# Geometry types that support area calculation
AREA_TYPES = {"Polygon", "MultiPolygon"}

# Geometry types that support length calculation
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}

# Geometry types that require no measurement
NO_MEASUREMENT_TYPES = {"Point", "MultiPoint"}

# All supported geometry types
SUPPORTED_TYPES = AREA_TYPES | LENGTH_TYPES | NO_MEASUREMENT_TYPES


@dataclass
class MeasurementResult:
    """Result of a measurement calculation for a single feature."""

    projected_crs: str | None = None
    area_sq_meters: float | None = None
    length_meters: float | None = None
    error: str | None = None


def calculate_measurement(
    geometry: BaseGeometry,
    geometry_type: str,
    source_crs: str,
) -> MeasurementResult:
    """
    Calculate measurements for a given geometry.

    Transforms the geometry to an appropriate projected CRS before
    computing area or length to ensure accuracy.

    Args:
        geometry: Shapely geometry object.
        geometry_type: Type string (e.g., "Polygon", "LineString").
        source_crs: Source CRS string (e.g., "EPSG:4326").

    Returns:
        MeasurementResult with computed values or error message.
    """
    result = MeasurementResult()

    # Handle unsupported geometry types gracefully
    if geometry_type not in SUPPORTED_TYPES:
        result.error = (
            f"Geometry type '{geometry_type}' is not supported for measurement. "
            f"Supported types: {', '.join(sorted(SUPPORTED_TYPES))}"
        )
        logger.warning(result.error)
        return result

    # Points don't need measurements
    if geometry_type in NO_MEASUREMENT_TYPES:
        logger.info(f"No measurement required for {geometry_type}.")
        return result

    try:
        import shapely
        if hasattr(geometry, "is_valid") and not geometry.is_valid:
            try:
                geometry = shapely.make_valid(geometry)
            except Exception:
                pass

        # Determine projected CRS and transform geometry
        projected_crs_str, projected_crs = get_projected_crs_for_geometry(
            geometry, source_crs
        )
        result.projected_crs = projected_crs_str

        # Transform to projected CRS if needed
        if projected_crs_str != source_crs:
            projected_geometry = transform_geometry(
                geometry, source_crs, projected_crs_str
            )
        else:
            projected_geometry = geometry

        # Calculate area for polygon types
        if geometry_type in AREA_TYPES:
            result.area_sq_meters = round(projected_geometry.area, 4)
            logger.info(
                f"Calculated area: {result.area_sq_meters} sq meters "
                f"using {projected_crs_str}"
            )

        # Calculate length for line types
        elif geometry_type in LENGTH_TYPES:
            result.length_meters = round(projected_geometry.length, 4)
            logger.info(
                f"Calculated length: {result.length_meters} meters "
                f"using {projected_crs_str}"
            )

    except Exception as e:
        result.error = f"Measurement calculation failed: {str(e)}"
        logger.error(result.error, exc_info=True)

    return result
