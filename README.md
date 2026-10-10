# Geospatial File Measurement API

A production-quality backend API built with **FastAPI** that accepts geospatial files (Shapefile, KML), processes the features within them, and returns measurement information including area for polygons and length for linestrings.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## Table of Contents

- [Features](#features)
- [Setup](#setup)
- [API Documentation](#api-documentation)
- [Architecture](#architecture)
- [Design Decisions](#design-decisions)
- [Testing](#testing)
- [Learnings](#learnings)
- [Future Scope](#future-scope)

---

## Features

- **File Upload**: Accept `.zip` (Shapefile) and `.kml` files via REST API
- **Feature Extraction**: Parse geometry type, coordinates (WKT), CRS, and properties for every feature
- **Measurement Calculation**:
  - **Polygon/MultiPolygon** → Area (square meters)
  - **LineString/MultiLineString** → Length (meters)
  - **Point/MultiPoint** → No measurement (handled gracefully)
  - **Unsupported types** → Graceful error response (no crash)
- **CRS Handling**: Automatic UTM zone detection and reprojection from geographic to projected CRS
- **Async Processing**: Background task processing with status tracking
- **Interactive API Docs**: Auto-generated Swagger UI and ReDoc
- **Comprehensive Tests**: Unit + integration tests for all layers

---

## Setup

### Prerequisites

- **Python 3.11+**
- **pip** (Python package manager)
- **GDAL** (required by geopandas/fiona — see platform-specific notes below)

### GDAL Installation

<details>
<summary><strong>Windows</strong></summary>

Option 1: Install via conda:
```bash
conda install -c conda-forge gdal fiona geopandas
```

Option 2: Download pre-built wheels from [Christoph Gohlke's site](https://www.lfd.uci.edu/~gohlke/pythonlibs/) for GDAL and Fiona, then:
```bash
pip install GDAL‑x.x.x‑cpXX‑cpXX‑win_amd64.whl
pip install fiona‑x.x.x‑cpXX‑cpXX‑win_amd64.whl
```
</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
brew install gdal
```
</details>

<details>
<summary><strong>Ubuntu/Debian</strong></summary>

```bash
sudo apt-get install gdal-bin libgdal-dev
export CPLUS_INCLUDE_PATH=/usr/include/gdal
export C_INCLUDE_PATH=/usr/include/gdal
```
</details>

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/<your-username>/geo-measurement-api.git
   cd geo-measurement-api
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment (optional)**
   ```bash
   cp .env.example .env
   # Edit .env as needed
   ```

5. **Run the application**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Access the API**
   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
   - Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

## API Documentation

### Base URL

```
http://localhost:8000
```

### Endpoints Overview

| Method   | Endpoint                        | Description                      |
|----------|---------------------------------|----------------------------------|
| `POST`   | `/api/files/`                   | Upload a geospatial file         |
| `GET`    | `/api/files/`                   | List all uploaded files          |
| `GET`    | `/api/files/{id}/`              | Get file information             |
| `GET`    | `/api/files/{id}/measurements/` | Get feature measurements         |
| `DELETE` | `/api/files/{id}/`              | Delete a file and its data       |
| `GET`    | `/health`                       | Health check                     |

---

### 1. Upload File

**`POST /api/files/`**

Upload a `.zip` (Shapefile) or `.kml` file. The file is validated, stored, and processing begins in the background.

**Request:**
```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@survey.kml"
```

**Response (201 Created):**
```json
{
  "id": "a1b2c3d4e5f6",
  "filename": "survey.kml",
  "file_type": "kml",
  "file_size_bytes": 15234,
  "status": "PENDING",
  "message": "File uploaded successfully. Processing started."
}
```

**Shapefile Upload:**
```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@parcels.zip"
```

**Error Responses:**
- `400` — Unsupported file type or empty file
- `413` — File exceeds maximum size (50 MB default)

---

### 2. List Files

**`GET /api/files/`**

**Response (200 OK):**
```json
[
  {
    "id": "a1b2c3d4e5f6",
    "filename": "survey.kml",
    "file_type": "kml",
    "file_size_bytes": 15234,
    "feature_count": 120,
    "crs": "EPSG:4326",
    "status": "COMPLETED",
    "error_message": null,
    "uploaded_at": "2024-01-15T10:30:00Z",
    "processed_at": "2024-01-15T10:30:05Z"
  }
]
```

---

### 3. File Information

**`GET /api/files/{id}/`**

**Request:**
```bash
curl http://localhost:8000/api/files/a1b2c3d4e5f6/
```

**Response (200 OK):**
```json
{
  "id": "a1b2c3d4e5f6",
  "filename": "survey.kml",
  "file_type": "kml",
  "file_size_bytes": 15234,
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error_message": null,
  "uploaded_at": "2024-01-15T10:30:00Z",
  "processed_at": "2024-01-15T10:30:05Z"
}
```

**Status Values:**
| Status       | Description                        |
|--------------|------------------------------------|
| `PENDING`    | File uploaded, processing not started |
| `PROCESSING` | File is being processed            |
| `COMPLETED`  | Processing finished successfully   |
| `FAILED`     | Processing encountered an error    |

---

### 4. Get Measurements

**`GET /api/files/{id}/measurements/`**

**Request:**
```bash
curl http://localhost:8000/api/files/a1b2c3d4e5f6/measurements/
```

**Response (200 OK):**
```json
{
  "file_id": "a1b2c3d4e5f6",
  "filename": "survey.kml",
  "crs": "EPSG:4326",
  "feature_count": 3,
  "features": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "geometry_wkt": "POLYGON ((77.0 28.0, 77.01 28.0, 77.01 28.01, 77.0 28.01, 77.0 28.0))",
      "original_crs": "EPSG:4326",
      "projected_crs": "EPSG:32643",
      "properties": {"name": "Parcel A", "area_type": "residential"},
      "area_sq_meters": 1108934.5621,
      "length_meters": null,
      "measurement_error": null
    },
    {
      "feature_index": 1,
      "geometry_type": "LineString",
      "geometry_wkt": "LINESTRING (77.0 28.0, 77.05 28.05)",
      "original_crs": "EPSG:4326",
      "projected_crs": "EPSG:32643",
      "properties": {"name": "Road Segment"},
      "area_sq_meters": null,
      "length_meters": 7423.8912,
      "measurement_error": null
    },
    {
      "feature_index": 2,
      "geometry_type": "Point",
      "geometry_wkt": "POINT (77.0 28.0)",
      "original_crs": "EPSG:4326",
      "projected_crs": null,
      "properties": {"name": "Survey Marker"},
      "area_sq_meters": null,
      "length_meters": null,
      "measurement_error": null
    }
  ]
}
```

**Error Responses:**
- `404` — File not found
- `409` — File still processing or processing failed

---

### 5. Delete File

**`DELETE /api/files/{id}/`**

```bash
curl -X DELETE http://localhost:8000/api/files/a1b2c3d4e5f6/
```

**Response:** `204 No Content`

---

## Architecture

### Application Structure

```
geo-measurement-api/
├── app/
│   ├── __init__.py           # Package initialization
│   ├── main.py               # FastAPI app entry point, middleware, lifecycle
│   ├── config.py             # Pydantic Settings configuration
│   ├── database.py           # SQLAlchemy async engine & session factory
│   ├── models.py             # ORM models (GeoFile, Feature)
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── routers/
│   │   └── files.py          # API endpoint definitions
│   └── services/
│       ├── crs_handler.py    # CRS detection & transformation
│       ├── measurement.py    # Geometry measurement calculations
│       └── file_processor.py # File reading & feature extraction
├── tests/
│   └── test_api.py           # Unit & integration tests
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

### Layered Architecture

```
┌─────────────────────────────────────────┐
│           API Layer (Routers)           │  ← HTTP handling, validation
├─────────────────────────────────────────┤
│          Schema Layer (Pydantic)        │  ← Request/response contracts
├─────────────────────────────────────────┤
│         Service Layer (Business)        │  ← Processing, measurements, CRS
├─────────────────────────────────────────┤
│          Data Layer (SQLAlchemy)        │  ← Persistence, ORM
└─────────────────────────────────────────┘
```

### File Processing Flow

```
Upload Request
    │
    ▼
Validate File (type, size, content)
    │
    ▼
Save to Disk → Create DB Record (PENDING)
    │
    ▼
Start Background Task
    │
    ▼
Update Status → PROCESSING
    │
    ▼
Read File (geopandas/fiona)
    ├── .zip → Extract → Find .shp → gpd.read_file()
    └── .kml → Enable KML driver → gpd.read_file()
    │
    ▼
Extract CRS from GeoDataFrame
    │
    ▼
For Each Feature:
    ├── Extract geometry type, WKT, properties
    ├── Determine projected CRS (UTM auto-detection)
    ├── Transform geometry to projected CRS
    ├── Calculate measurement (area/length)
    └── Create Feature record in DB
    │
    ▼
Update Status → COMPLETED (or FAILED)
```

### Measurement Calculation Flow

```
Geometry Input
    │
    ▼
Check Geometry Type
    ├── Point/MultiPoint → No measurement needed
    ├── Polygon/MultiPolygon → Calculate area
    ├── LineString/MultiLineString → Calculate length
    └── Other → Graceful error message
    │
    ▼
Get Projected CRS
    ├── Already projected? → Use as-is
    └── Geographic (lat/lon)?
        ├── Get centroid coordinates
        ├── Calculate UTM zone number
        ├── Handle polar regions (UPS)
        └── Return EPSG code
    │
    ▼
Transform Geometry (pyproj Transformer)
    │
    ▼
Calculate (Shapely .area or .length)
    │
    ▼
Return Result (in meters / sq meters)
```

### CRS Handling Strategy

The application uses **UTM Zone Auto-Detection** based on the geometry's centroid:

1. **Check source CRS**: If already projected (units in meters/feet), use as-is
2. **Geographic CRS (EPSG:4326)**: Determine the UTM zone:
   - **UTM Zone Formula**: `zone = floor((longitude + 180) / 6) + 1`
   - **Northern hemisphere**: `EPSG:326{zone}` (e.g., EPSG:32643 for zone 43)
   - **Southern hemisphere**: `EPSG:327{zone}` (e.g., EPSG:32756 for zone 56)
3. **Polar regions**: Latitude > 84°N → UPS North (EPSG:32661); < 80°S → UPS South (EPSG:32761)
4. **Transform**: Use `pyproj.Transformer` with `always_xy=True` for consistent coordinate ordering

This approach provides accuracy within ±0.04% for geometries within their UTM zone, which is sufficient for most survey and GIS applications.

---

## Design Decisions

### 1. FastAPI over Django

**Chosen:** FastAPI  
**Rationale:**
- Native async support — ideal for file I/O and background processing
- Automatic OpenAPI/Swagger documentation from type hints
- Pydantic integration for request/response validation
- Lighter footprint for a focused API service
- Better performance for I/O-bound workloads

**Alternative considered:** Django + DRF provides a more batteries-included approach (admin panel, ORM migrations), but adds overhead unnecessary for this focused API.

### 2. SQLite + SQLAlchemy (Async)

**Chosen:** SQLite with async SQLAlchemy  
**Rationale:**
- Zero configuration — no external database server needed
- Async driver (`aiosqlite`) keeps the event loop non-blocking
- SQLAlchemy ORM allows easy migration to PostgreSQL/PostGIS in production
- Sufficient for the scope of this assignment

**Alternative considered:** PostgreSQL with PostGIS would add native spatial queries but adds setup complexity.

### 3. UTM Auto-Detection for CRS

**Chosen:** Automatic UTM zone selection from centroid  
**Rationale:**
- Universal — works anywhere on Earth without manual configuration
- Accurate — UTM provides ±0.04% accuracy within a zone
- Deterministic — same geometry always maps to the same projected CRS
- Handles polar regions with UPS fallback

**Alternatives considered:**
- **Equal-area projections** (e.g., Albers) — better for area but requires knowing the region
- **Web Mercator (EPSG:3857)** — extreme distortion at high latitudes, unsuitable for area
- **Geodesic calculations** (pyproj.Geod) — accurate but slower, doesn't integrate with Shapely

### 4. Background Processing with FastAPI BackgroundTasks

**Chosen:** FastAPI `BackgroundTasks` with thread pool executor  
**Rationale:**
- Simple — no external task queue (Celery, RQ) needed
- The geospatial processing runs in a `ThreadPoolExecutor` to avoid blocking async
- Status tracking via database allows polling from the client

**Alternative considered:** Celery + Redis for production-scale workloads with many concurrent uploads.

### 5. WKT for Geometry Storage

**Chosen:** Well-Known Text (WKT) in a text column  
**Rationale:**
- Human-readable and debuggable
- Standard format understood by all GIS tools
- No database extension needed (unlike PostGIS geometry columns)

**Alternative considered:** GeoJSON or WKB — GeoJSON is more verbose, WKB is binary and not human-readable.

### 6. Feature Properties as JSON

**Chosen:** JSON column for feature properties  
**Rationale:**
- Flexible — different files have different attribute schemas
- No schema migration needed when property structure varies
- SQLite supports JSON natively

---

## Testing

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest -v

# Run with coverage
pip install pytest-cov
pytest --cov=app --cov-report=term-missing -v
```

### Test Structure

| Test Class              | Scope       | What's Tested                                    |
|-------------------------|-------------|--------------------------------------------------|
| `TestCRSHandler`        | Unit        | UTM zone detection, polar regions, CRS projection |
| `TestMeasurements`      | Unit        | Area, length, point, unsupported types            |
| `TestHealthEndpoint`    | Integration | Health check, root endpoint                       |
| `TestFileUpload`        | Integration | KML upload, Shapefile upload, validation          |
| `TestFileInfo`          | Integration | File retrieval, 404 handling                      |
| `TestMeasurementsEndpoint`| Integration | Measurement retrieval, 404 handling             |

---

## Learnings

1. **CRS matters more than you think**: Directly calculating area on EPSG:4326 coordinates gives results in "square degrees" — a meaningless unit. The UTM auto-detection strategy was critical for producing correct, real-world measurements.

2. **Fiona's KML driver**: KML support in Fiona requires explicit driver registration (`fiona.drvsupport.supported_drivers["KML"] = "r"`). This isn't well-documented and required investigation.

3. **Async + Geospatial**: GeoPandas and Fiona are synchronous, CPU/IO-bound libraries. Running them directly in an async handler blocks the event loop. Wrapping them in `run_in_executor` was essential for maintaining API responsiveness.

4. **Property sanitization**: Geospatial file attributes can contain Python objects (datetime, Decimal) that aren't JSON-serializable. A sanitization step before database storage prevents subtle serialization errors.

5. **Shapefile ZIP handling**: Shapefiles consist of multiple mandatory files (.shp, .shx, .dbf, .prj). Robust extraction requires recursive search within the ZIP since users may nest files in subdirectories.

---

## Future Scope

1. **GeoJSON Support**: Add support for `.geojson` / `.json` file uploads — straightforward with `gpd.read_file()`.

2. **PostGIS Integration**: Replace SQLite with PostgreSQL + PostGIS for native spatial indexing, spatial queries (intersection, containment), and better geometry storage.

3. **Celery Task Queue**: Replace `BackgroundTasks` with Celery + Redis for production-scale concurrent processing, retry mechanisms, and task monitoring.

4. **Streaming Large Files**: Implement chunked upload for files > 100 MB to reduce memory pressure.

5. **WebSocket Status Updates**: Push real-time processing status to clients instead of requiring polling.

6. **Measurement Units**: Allow users to request measurements in different units (acres, hectares, kilometers, miles).

7. **Geodesic Calculations**: Use `pyproj.Geod` for geodesic area/distance as an alternative to UTM projection, especially for geometries spanning multiple UTM zones.

8. **Docker Deployment**: Add `Dockerfile` and `docker-compose.yml` for containerized deployment with proper GDAL dependencies.

9. **API Authentication**: Add JWT-based authentication and per-user file isolation.

10. **File Format Validation**: Deep validation of Shapefile integrity (presence of .shx, .dbf, .prj) and KML schema validation before processing.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
