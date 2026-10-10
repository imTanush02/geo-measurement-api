"""
CRS handling and transformation utilities.

Provides strategies for selecting an appropriate projected CRS
for accurate area and distance calculations from geographic coordinates.

Strategy: UTM Zone Auto-Detection
----------------------------------
Given a geometry in EPSG:4326 (lat/lon), we determine the UTM zone
from the geometry's centroid. UTM projections are conformal and
provide accurate measurements within their zone (±0.04% distortion).

For polar regions (latitude > 84°N or < 80°S), we fall back to
appropriate polar stereographic projections (EPSG:32661 / EPSG:32761).
"""

import math
import logging

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform

logger = logging.getLogger(__name__)


def get_utm_epsg(longitude: float, latitude: float) -> int:
    """
    Determine the appropriate UTM EPSG code for a given lon/lat coordinate.

    The UTM system divides the Earth into 60 zones, each 6° wide.
    Northern hemisphere zones use EPSG:326xx, southern use EPSG:327xx.

    Args:
        longitude: Longitude in degrees (-180 to 180).
        latitude: Latitude in degrees (-90 to 90).

    Returns:
        EPSG code for the appropriate UTM zone.
    """
    # Handle polar regions
    if latitude > 84.0:
        return 32661  # UPS North
    if latitude < -80.0:
        return 32761  # UPS South

    # Calculate UTM zone number (1-60)
    zone_number = int((longitude + 180) / 6) + 1

    # Clamp to valid range
    zone_number = max(1, min(60, zone_number))

    if latitude >= 0:
        return 32600 + zone_number  # Northern hemisphere
    else:
        return 32700 + zone_number  # Southern hemisphere


def get_projected_crs_for_geometry(geometry, source_crs_str: str) -> tuple[str, CRS]:
    """
    Determine the best projected CRS for a given geometry.

    Uses the centroid of the geometry to select the appropriate UTM zone.
    If the source CRS is already projected, returns it as-is.

    Args:
        geometry: A Shapely geometry object.
        source_crs_str: Source CRS as a string (e.g., "EPSG:4326").

    Returns:
        Tuple of (projected_crs_string, pyproj.CRS object).
    """
    source_crs = CRS.from_user_input(source_crs_str)

    # If already projected (units are meters/feet), no transformation needed
    if source_crs.is_projected:
        logger.info(f"CRS {source_crs_str} is already projected, using as-is.")
        return source_crs_str, source_crs

    # Get centroid in geographic coordinates
    centroid = geometry.centroid
    lon, lat = centroid.x, centroid.y

    # Clamp coordinates to valid ranges
    lon = max(-180.0, min(180.0, lon))
    lat = max(-90.0, min(90.0, lat))

    utm_epsg = get_utm_epsg(lon, lat)
    projected_crs_str = f"EPSG:{utm_epsg}"
    projected_crs = CRS.from_epsg(utm_epsg)

    logger.info(
        f"Selected {projected_crs_str} for geometry at ({lon:.4f}, {lat:.4f})"
    )
    return projected_crs_str, projected_crs


def transform_geometry(geometry, source_crs_str: str, target_crs_str: str):
    """
    Transform a Shapely geometry from one CRS to another.

    Uses pyproj Transformer with 'always_xy=True' to ensure
    consistent coordinate ordering (longitude, latitude).

    Args:
        geometry: Shapely geometry to transform.
        source_crs_str: Source CRS string.
        target_crs_str: Target CRS string.

    Returns:
        Transformed Shapely geometry in the target CRS.
    """
    source_crs = CRS.from_user_input(source_crs_str)
    target_crs = CRS.from_user_input(target_crs_str)

    transformer = Transformer.from_crs(
        source_crs, target_crs, always_xy=True
    )

    return transform(transformer.transform, geometry)
