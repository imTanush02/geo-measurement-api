"""
Tests for the Geospatial File Measurement API.

Covers CRS handling, measurement calculations, file processing,
and API endpoint integration tests.
"""

import os
import json
import zipfile
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from shapely.geometry import Point, LineString, Polygon, MultiPolygon

# ─── Test Configuration ────────────────────────────────────────────

# Set test database before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_geo_measurement.db"
os.environ["UPLOAD_DIR"] = "./test_uploads"

from app.main import app
from app.database import init_db, engine, Base
from app.services.crs_handler import get_utm_epsg, get_projected_crs_for_geometry, transform_geometry
from app.services.measurement import calculate_measurement, MeasurementResult


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _create_test_kml(features: list[dict]) -> bytes:
    """
    Create a minimal KML file with given features.

    Args:
        features: List of dicts with 'name' and 'coordinates' keys.

    Returns:
        KML content as bytes.
    """
    placemarks = ""
    for feat in features:
        name = feat.get("name", "Test Feature")
        coords = feat.get("coordinates", "0,0,0")
        geom_type = feat.get("type", "Point")

        if geom_type == "Point":
            geometry = f"<Point><coordinates>{coords}</coordinates></Point>"
        elif geom_type == "LineString":
            geometry = f"<LineString><coordinates>{coords}</coordinates></LineString>"
        elif geom_type == "Polygon":
            geometry = (
                f"<Polygon><outerBoundaryIs><LinearRing>"
                f"<coordinates>{coords}</coordinates>"
                f"</LinearRing></outerBoundaryIs></Polygon>"
            )
        else:
            geometry = f"<Point><coordinates>{coords}</coordinates></Point>"

        placemarks += f"""
        <Placemark>
            <name>{name}</name>
            {geometry}
        </Placemark>
        """

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
            <name>Test KML</name>
            {placemarks}
        </Document>
    </kml>"""

    return kml.encode("utf-8")


def _create_test_shapefile_zip() -> bytes:
    """
    Create a minimal shapefile ZIP for testing.

    Uses geopandas to create a shapefile with a polygon,
    then zips it up and returns the bytes.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    # Create a simple polygon (roughly 1km x 1km near equator)
    polygon = Polygon([
        (77.0, 28.0),
        (77.01, 28.0),
        (77.01, 28.01),
        (77.0, 28.01),
        (77.0, 28.0),
    ])

    gdf = gpd.GeoDataFrame(
        {"name": ["Test Polygon"], "category": ["test"]},
        geometry=[polygon],
        crs="EPSG:4326",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = Path(tmpdir) / "test.shp"
        gdf.to_file(str(shp_path))

        # Create ZIP
        zip_path = Path(tmpdir) / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                filepath = shp_path.with_suffix(ext)
                if filepath.exists():
                    zf.write(filepath, filepath.name)

        return zip_path.read_bytes()


# ─── Unit Tests: CRS Handler ──────────────────────────────────────

class TestCRSHandler:
    """Tests for CRS handling utilities."""

    def test_utm_zone_northern_hemisphere(self):
        """UTM zone for Delhi (77°E, 28°N) should be EPSG:32643."""
        epsg = get_utm_epsg(77.0, 28.0)
        assert epsg == 32643

    def test_utm_zone_southern_hemisphere(self):
        """UTM zone for Sydney (151°E, 33°S) should be EPSG:32756."""
        epsg = get_utm_epsg(151.0, -33.0)
        assert epsg == 32756

    def test_utm_zone_western_hemisphere(self):
        """UTM zone for New York (-74°W, 40°N) should be EPSG:32618."""
        epsg = get_utm_epsg(-74.0, 40.0)
        assert epsg == 32618

    def test_polar_north(self):
        """Coordinates near North Pole should use UPS North (EPSG:32661)."""
        epsg = get_utm_epsg(0.0, 85.0)
        assert epsg == 32661

    def test_polar_south(self):
        """Coordinates near South Pole should use UPS South (EPSG:32761)."""
        epsg = get_utm_epsg(0.0, -81.0)
        assert epsg == 32761

    def test_projected_crs_for_point_geometry(self):
        """Should select appropriate UTM zone for a point geometry."""
        point = Point(77.0, 28.0)
        crs_str, crs = get_projected_crs_for_geometry(point, "EPSG:4326")
        assert crs_str == "EPSG:32643"

    def test_already_projected_crs(self):
        """Already projected CRS should be returned as-is."""
        point = Point(500000, 3100000)
        crs_str, crs = get_projected_crs_for_geometry(point, "EPSG:32643")
        assert crs_str == "EPSG:32643"

    def test_transform_geometry(self):
        """Geometry should be transformable between CRS."""
        point = Point(77.0, 28.0)
        transformed = transform_geometry(point, "EPSG:4326", "EPSG:32643")
        # Transformed coordinates should be in meters (not degrees)
        assert transformed.x > 10000  # UTM easting
        assert transformed.y > 10000  # UTM northing


# ─── Unit Tests: Measurements ─────────────────────────────────────

class TestMeasurements:
    """Tests for measurement calculations."""

    def test_polygon_area_calculation(self):
        """Polygon area should be calculated in square meters."""
        # ~1km x 1km polygon near equator
        polygon = Polygon([
            (77.0, 28.0),
            (77.01, 28.0),
            (77.01, 28.01),
            (77.0, 28.01),
            (77.0, 28.0),
        ])
        result = calculate_measurement(polygon, "Polygon", "EPSG:4326")
        assert result.area_sq_meters is not None
        assert result.area_sq_meters > 0
        assert result.error is None
        assert result.projected_crs is not None
        # ~1km x 1km ≈ 1,000,000 sq meters (roughly)
        assert 500_000 < result.area_sq_meters < 2_000_000

    def test_linestring_length_calculation(self):
        """LineString length should be calculated in meters."""
        line = LineString([(77.0, 28.0), (77.01, 28.0)])
        result = calculate_measurement(line, "LineString", "EPSG:4326")
        assert result.length_meters is not None
        assert result.length_meters > 0
        assert result.error is None
        # ~1km line
        assert 500 < result.length_meters < 2000

    def test_point_no_measurement(self):
        """Point geometries should have no measurements."""
        point = Point(77.0, 28.0)
        result = calculate_measurement(point, "Point", "EPSG:4326")
        assert result.area_sq_meters is None
        assert result.length_meters is None
        assert result.error is None

    def test_unsupported_geometry_type(self):
        """Unsupported geometry types should be handled gracefully."""
        point = Point(77.0, 28.0)
        result = calculate_measurement(point, "GeometryCollection", "EPSG:4326")
        assert result.error is not None
        assert "not supported" in result.error


# ─── Integration Tests: API Endpoints ──────────────────────────────

class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data


class TestFileUpload:
    """Tests for the file upload endpoint."""

    @pytest.mark.asyncio
    async def test_upload_kml_file(self, client):
        """Uploading a valid KML file should return 201."""
        kml_content = _create_test_kml([
            {"name": "Test Point", "type": "Point", "coordinates": "77.0,28.0,0"},
        ])

        response = await client.post(
            "/api/files/",
            files={"file": ("test.kml", kml_content, "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["file_type"] == "kml"
        assert data["status"] == "PENDING"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_upload_shapefile_zip(self, client):
        """Uploading a valid Shapefile ZIP should return 201."""
        zip_content = _create_test_shapefile_zip()

        response = await client.post(
            "/api/files/",
            files={"file": ("test.zip", zip_content, "application/zip")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["file_type"] == "shapefile"

    @pytest.mark.asyncio
    async def test_upload_unsupported_format(self, client):
        """Uploading an unsupported file format should return 400."""
        response = await client.post(
            "/api/files/",
            files={"file": ("test.csv", b"a,b,c", "text/csv")},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_empty_file(self, client):
        """Uploading an empty file should return 400."""
        response = await client.post(
            "/api/files/",
            files={"file": ("test.kml", b"", "application/xml")},
        )
        assert response.status_code == 400


class TestFileInfo:
    """Tests for the file info endpoint."""

    @pytest.mark.asyncio
    async def test_get_file_not_found(self, client):
        """Requesting a non-existent file should return 404."""
        response = await client.get("/api/files/nonexistent/")
        assert response.status_code == 404




class TestMeasurementsEndpoint:
    """Tests for the measurements endpoint."""

    @pytest.mark.asyncio
    async def test_measurements_not_found(self, client):
        """Requesting measurements for non-existent file should return 404."""
        response = await client.get("/api/files/nonexistent/measurements/")
        assert response.status_code == 404


class TestEndToEndProcessing:
    """End-to-end integration tests for upload, processing, and measurements."""

    @pytest.mark.asyncio
    async def test_e2e_kml_processing_and_measurements(self, client):
        """Uploading KML processes features and computes correct measurements."""
        import asyncio

        kml_content = _create_test_kml([
            {
                "name": "Field A",
                "type": "Polygon",
                "coordinates": "77.0,28.0,0 77.01,28.0,0 77.01,28.01,0 77.0,28.01,0 77.0,28.0,0",
            },
            {
                "name": "Road B",
                "type": "LineString",
                "coordinates": "77.0,28.0,0 77.01,28.0,0",
            },
            {
                "name": "Tower C",
                "type": "Point",
                "coordinates": "77.0,28.0,0",
            },
        ])

        # 1. Upload KML
        response = await client.post(
            "/api/files/",
            files={"file": ("survey_delhi.kml", kml_content, "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code == 201
        data = response.json()
        file_id = data["id"]

        # 2. Poll until background processing completes
        for _ in range(20):
            await asyncio.sleep(0.1)
            info_res = await client.get(f"/api/files/{file_id}/")
            info_data = info_res.json()
            if info_data["status"] in ("COMPLETED", "FAILED"):
                break

        assert info_data["status"] == "COMPLETED"
        assert info_data["feature_count"] == 3
        assert info_data["crs"] == "EPSG:4326"

        # 3. Retrieve measurements
        meas_res = await client.get(f"/api/files/{file_id}/measurements/")
        assert meas_res.status_code == 200
        meas_data = meas_res.json()
        assert meas_data["feature_count"] == 3
        assert len(meas_data["features"]) == 3

        # Feature 0: Polygon -> area > 0, length is None
        feat0 = meas_data["features"][0]
        assert feat0["geometry_type"] == "Polygon"
        assert feat0["area_sq_meters"] is not None
        assert feat0["area_sq_meters"] > 0
        assert feat0["length_meters"] is None
        assert feat0["projected_crs"] == "EPSG:32643"

        # Feature 1: LineString -> length > 0, area is None
        feat1 = meas_data["features"][1]
        assert feat1["geometry_type"] == "LineString"
        assert feat1["length_meters"] is not None
        assert feat1["length_meters"] > 0
        assert feat1["area_sq_meters"] is None
        assert feat1["projected_crs"] == "EPSG:32643"

        # Feature 2: Point -> area is None, length is None
        feat2 = meas_data["features"][2]
        assert feat2["geometry_type"] == "Point"
        assert feat2["area_sq_meters"] is None
        assert feat2["length_meters"] is None

    @pytest.mark.asyncio
    async def test_e2e_shapefile_processing_and_measurements(self, client):
        """Uploading Shapefile ZIP processes features and computes correct measurements."""
        import asyncio

        zip_content = _create_test_shapefile_zip()

        # 1. Upload Shapefile
        response = await client.post(
            "/api/files/",
            files={"file": ("shapefile_test.zip", zip_content, "application/zip")},
        )
        assert response.status_code == 201
        data = response.json()
        file_id = data["id"]

        # 2. Poll until completed
        for _ in range(20):
            await asyncio.sleep(0.1)
            info_res = await client.get(f"/api/files/{file_id}/")
            info_data = info_res.json()
            if info_data["status"] in ("COMPLETED", "FAILED"):
                break

        assert info_data["status"] == "COMPLETED"
        assert info_data["feature_count"] == 1

        # 3. Check measurements
        meas_res = await client.get(f"/api/files/{file_id}/measurements/")
        assert meas_res.status_code == 200
        meas_data = meas_res.json()
        assert len(meas_data["features"]) == 1
        assert meas_data["features"][0]["area_sq_meters"] is not None
        assert meas_data["features"][0]["area_sq_meters"] > 0




class TestAdditionalGeometryCalculations:
    """Tests for MultiPolygon, MultiLineString, and invalid geometries."""

    def test_multipolygon_area(self):
        """MultiPolygon area should be calculated as sum of polygon areas."""
        p1 = Polygon([(77.0, 28.0), (77.01, 28.0), (77.01, 28.01), (77.0, 28.01), (77.0, 28.0)])
        p2 = Polygon([(77.02, 28.02), (77.03, 28.02), (77.03, 28.03), (77.02, 28.03), (77.02, 28.02)])
        mp = MultiPolygon([p1, p2])

        result = calculate_measurement(mp, "MultiPolygon", "EPSG:4326")
        assert result.area_sq_meters is not None
        assert result.area_sq_meters > 1_000_000
        assert result.error is None

    def test_invalid_polygon_handled_gracefully(self):
        """Self-intersecting polygon should be auto-repaired and measured."""
        # Bow-tie polygon (self-intersecting)
        bowtie = Polygon([(0, 0), (0, 2), (2, 0), (2, 2), (0, 0)])
        result = calculate_measurement(bowtie, "Polygon", "EPSG:4326")
        assert result.area_sq_meters is not None
        assert result.error is None
