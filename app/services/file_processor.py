"""
File processing service.

Handles reading geospatial files (Shapefile and KML), extracting features,
and orchestrating measurement calculations. Runs processing in a thread pool
to avoid blocking the async event loop during I/O-heavy geospatial operations.
"""

import logging
import zipfile
import tempfile
import shutil
from pathlib import Path
import math
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
try:
    import fiona
    if hasattr(fiona, "drvsupport"):
        fiona.drvsupport.supported_drivers["KML"] = "r"
except (ImportError, AttributeError):
    fiona = None
from shapely.geometry import shape, mapping
from shapely import wkt

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeoFile, Feature, FileStatus
from app.services.measurement import calculate_measurement

logger = logging.getLogger(__name__)

import pandas as pd

# Thread pool for CPU/IO-bound geospatial operations
_executor = ThreadPoolExecutor(max_workers=4)


def _sanitize_properties(properties: dict) -> dict:
    """
    Sanitize feature properties for JSON serialization.

    Converts non-serializable values (datetime, bytes, etc.) to strings
    and maps NaN/NaT/Inf to None to prevent JSON encoding errors during API response serialization.
    """
    sanitized = {}
    for key, value in properties.items():
        if value is None or pd.isna(value) or (isinstance(value, float) and math.isinf(value)):
            sanitized[key] = None
        elif isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, (datetime,)):
            sanitized[key] = value.isoformat()
        else:
            sanitized[key] = str(value)
    return sanitized


def _read_shapefile(file_path: Path) -> gpd.GeoDataFrame:
    """
    Read a Shapefile from a ZIP archive.

    Extracts the ZIP to a temporary directory, locates the .shp file,
    and reads it using GeoPandas.

    Args:
        file_path: Path to the .zip file containing the Shapefile.

    Returns:
        GeoDataFrame with all features from the Shapefile.

    Raises:
        ValueError: If the ZIP does not contain a .shp file.
    """
    temp_dir = tempfile.mkdtemp(prefix="geo_shp_")
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(temp_dir)

        # Find the .shp file (may be in a subdirectory)
        shp_files = list(Path(temp_dir).rglob("*.shp"))
        if not shp_files:
            raise ValueError(
                "No .shp file found in the uploaded ZIP archive. "
                "Ensure the ZIP contains a valid Shapefile (.shp, .shx, .dbf)."
            )

        logger.info(f"Found Shapefile: {shp_files[0].name}")
        gdf = gpd.read_file(str(shp_files[0]))
        return gdf
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _read_kml(file_path: Path) -> gpd.GeoDataFrame:
    """
    Read a KML file into a GeoDataFrame.

    Supports reading via PyOGRIO (default in GeoPandas 1.0+) or Fiona.

    Args:
        file_path: Path to the .kml file.

    Returns:
        GeoDataFrame with all features from the KML file.
    """
    if fiona is not None and hasattr(fiona, "drvsupport"):
        try:
            fiona.drvsupport.supported_drivers["KML"] = "r"
        except Exception:
            pass

    logger.info(f"Reading KML file: {file_path.name}")
    try:
        return gpd.read_file(str(file_path))
    except Exception as e:
        logger.warning(f"Default engine failed for KML, attempting driver='KML': {e}")
        return gpd.read_file(str(file_path), driver="KML")


def _process_file_sync(geo_file_id: str, file_path: str, file_type: str) -> dict:
    """
    Synchronous file processing function (runs in thread pool).

    Reads the geospatial file, extracts features, calculates measurements,
    and returns the results as a dictionary.

    Args:
        geo_file_id: Database ID of the GeoFile record.
        file_path: Path to the uploaded file.
        file_type: Type of file ("shapefile" or "kml").

    Returns:
        Dictionary with processing results including features and CRS.
    """
    path = Path(file_path)

    # Read file based on type
    if file_type == "shapefile":
        gdf = _read_shapefile(path)
    elif file_type == "kml":
        gdf = _read_kml(path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Extract CRS
    source_crs = str(gdf.crs) if gdf.crs else "EPSG:4326"

    # Normalize CRS string
    if gdf.crs:
        try:
            epsg = gdf.crs.to_epsg()
            if epsg:
                source_crs = f"EPSG:{epsg}"
        except Exception:
            pass

    logger.info(f"File CRS: {source_crs}, Features: {len(gdf)}")

    # Process each feature
    features_data = []
    for idx, row in gdf.iterrows():
        geometry = row.geometry

        if geometry is None or geometry.is_empty:
            logger.warning(f"Feature {idx}: empty or null geometry, skipping.")
            continue

        geometry_type = geometry.geom_type
        geometry_wkt_str = geometry.wkt

        # Extract properties (all columns except geometry)
        props = {}
        for col in gdf.columns:
            if col != "geometry" and col != gdf.geometry.name:
                props[col] = row[col]
        props = _sanitize_properties(props)

        # Calculate measurements
        measurement = calculate_measurement(geometry, geometry_type, source_crs)

        feature_data = {
            "feature_index": int(idx) if not isinstance(idx, int) else idx,
            "geometry_type": geometry_type,
            "geometry_wkt": geometry_wkt_str,
            "original_crs": source_crs,
            "projected_crs": measurement.projected_crs,
            "properties": props,
            "area_sq_meters": measurement.area_sq_meters,
            "length_meters": measurement.length_meters,
            "measurement_error": measurement.error,
        }
        features_data.append(feature_data)

    return {
        "crs": source_crs,
        "feature_count": len(features_data),
        "features": features_data,
    }


async def process_file(geo_file: GeoFile, db: AsyncSession) -> None:
    """
    Process an uploaded geospatial file asynchronously.

    Updates the GeoFile status, runs the processing in a thread pool,
    creates Feature records in the database, and updates the final status.

    Args:
        geo_file: The GeoFile ORM instance to process.
        db: Async database session.
    """
    import asyncio

    # Update status to PROCESSING
    geo_file.status = FileStatus.PROCESSING
    db.add(geo_file)
    await db.commit()

    try:
        # Run CPU/IO-bound processing in thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            _process_file_sync,
            geo_file.id,
            geo_file.file_path,
            geo_file.file_type,
        )

        # Create Feature records
        for feat_data in result["features"]:
            feature = Feature(
                file_id=geo_file.id,
                **feat_data,
            )
            db.add(feature)

        # Update GeoFile with results
        geo_file.crs = result["crs"]
        geo_file.feature_count = result["feature_count"]
        geo_file.status = FileStatus.COMPLETED
        geo_file.processed_at = datetime.now(timezone.utc)

        db.add(geo_file)
        await db.commit()

        logger.info(
            f"File {geo_file.id} processed successfully: "
            f"{result['feature_count']} features extracted."
        )

    except Exception as e:
        geo_file.status = FileStatus.FAILED
        geo_file.error_message = str(e)
        geo_file.processed_at = datetime.now(timezone.utc)
        db.add(geo_file)
        await db.commit()

        logger.error(f"File processing failed for {geo_file.id}: {e}", exc_info=True)
        raise
