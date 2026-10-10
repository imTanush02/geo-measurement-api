"""
This is where the magic happens for file processing!

We read the map files (like Shapefiles and KML), pull out all the shapes,
and calculate their measurements. We do this in the background so our server
doesn't freeze up while crunching numbers.
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
    Cleans up the feature properties so we can safely convert them to JSON.
    Things like dates or weird numbers get turned into text or nulls so they don't break anything.
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
    Opens up a zipped Shapefile and reads all the map data inside.
    We unzip it to a temporary folder, find the .shp file, and let GeoPandas do its thing!
    """
    temp_dir = tempfile.mkdtemp(prefix="geo_shp_")
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(temp_dir)

        # Let's hunt for that .shp file inside the zip...
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
    Reads a KML file and turns it into a GeoDataFrame we can work with.
    It tries the newest engine first, and falls back to an older one if needed.
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
    This is the heavy-lifter function that actually processes the file.
    It runs in our background thread pool.
    """
    path = Path(file_path)

    # Figure out how to read it based on the file type
    if file_type == "shapefile":
        gdf = _read_shapefile(path)
    elif file_type == "kml":
        gdf = _read_kml(path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Try to grab the CRS (Coordinate Reference System), default to standard GPS (EPSG:4326)
    source_crs = str(gdf.crs) if gdf.crs else "EPSG:4326"

    # Let's try to get a nice clean EPSG code if possible
    if gdf.crs:
        try:
            epsg = gdf.crs.to_epsg()
            if epsg:
                source_crs = f"EPSG:{epsg}"
        except Exception:
            pass

    logger.info(f"File CRS: {source_crs}, Features: {len(gdf)}")

    # Go through every single shape one by one
    features_data = []
    for idx, row in gdf.iterrows():
        geometry = row.geometry

        # If the shape is missing or empty, just skip it and move on
        if geometry is None or geometry.is_empty:
            logger.warning(f"Feature {idx}: empty or null geometry, skipping.")
            continue

        geometry_type = geometry.geom_type
        geometry_wkt_str = geometry.wkt

        # Grab all the extra info (properties) attached to this shape
        props = {}
        for col in gdf.columns:
            if col != "geometry" and col != gdf.geometry.name:
                props[col] = row[col]
        props = _sanitize_properties(props)

        # Let's calculate the area or length!
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
    Kicks off the file processing asynchronously.
    It updates the file's status in the database, runs the heavy lifting in the background,
    and then saves all the results when it's done.
    """
    import asyncio

    # Let everyone know we're working on it
    geo_file.status = FileStatus.PROCESSING
    db.add(geo_file)
    await db.commit()

    try:
        # Send the heavy work to our background thread pool so we don't block the main app
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            _process_file_sync,
            geo_file.id,
            geo_file.file_path,
            geo_file.file_type,
        )

        # Save all the shapes we found into the database
        for feat_data in result["features"]:
            feature = Feature(
                file_id=geo_file.id,
                **feat_data,
            )
            db.add(feature)

        # We did it! Update the file with the final counts and mark it complete
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
        # Uh oh, something went horribly wrong. Log it and mark as failed.
        geo_file.status = FileStatus.FAILED
        geo_file.error_message = str(e)
        geo_file.processed_at = datetime.now(timezone.utc)
        db.add(geo_file)
        await db.commit()

        logger.error(f"File processing failed for {geo_file.id}: {e}", exc_info=True)
        raise
