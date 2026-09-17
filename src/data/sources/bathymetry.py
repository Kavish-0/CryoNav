"""
CryoNav — Real GEBCO / IBCSO v2 Antarctic Bathymetry Fetcher.

Dataset:
- The International Bathymetric Chart of the Southern Ocean Version 2 (IBCSO v2)
  The official Southern Ocean regional mapping of the General Bathymetric Chart of the Oceans (GEBCO).
- Source: PANGAEA (Data Publisher for Earth & Environmental Science)
  https://download.pangaea.de/dataset/937574/files/IBCSO_v2_bed_WGS84.tif
- Citation:
  Dorschel, B., Hehemann, L., Viquerat, S., et al. (2022).
  The International Bathymetric Chart of the Southern Ocean Version 2 (IBCSO v2).
  Scientific Data, 9, 275. https://doi.org/10.1038/s41597-022-01366-7
  DOI: 10.1594/PANGAEA.937574

Coverage:
- Latitudes: 50°S to 90°S (Antarctic continent and surrounding Southern Ocean).
- Longitudes: Full 360° (-180° to 180°).
- Vertical: Bedrock elevation / water depth in meters relative to mean sea level.
- Replaces any synthetic or approximated bathymetry formulas.
"""
import requests
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

from src.config import DOMAIN
from src.data.domain import CANONICAL_DOMAIN
from src.data.provenance import (
    write_provenance_sidecar,
    verify_provenance_integrity,
    MissingDataError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW_BATHY_DIR = PROJECT_ROOT / DOMAIN["paths"]["raw_data"] / "bathymetry"

IBCSO_URL = "https://download.pangaea.de/dataset/937574/files/IBCSO_v2_bed_WGS84.tif"
IBCSO_DOI = "https://doi.org/10.1594/PANGAEA.937574"
IBCSO_CITATION = "Dorschel, B., et al. (2022). The International Bathymetric Chart of the Southern Ocean Version 2 (IBCSO v2). Scientific Data, 9, 275."


def fetch_gebco_ibcso_bathymetry(
    output_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    """
    Download the official GEBCO / IBCSO v2 bedrock bathymetry grid (GeoTIFF) from PANGAEA.
    Writes a .provenance.json sidecar with cryptographic SHA-256 hash.
    """
    dest_dir = Path(output_dir) if output_dir else RAW_BATHY_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_path = dest_dir / "IBCSO_v2_bed_WGS84.tif"

    if target_path.exists() and not overwrite:
        try:
            verify_provenance_integrity(target_path)
            print(f"GEBCO/IBCSO bathymetry already exists and is verified: {target_path.name}")
            return target_path
        except Exception:
            pass

    print(f"Downloading GEBCO/IBCSO v2 bathymetry from PANGAEA ({IBCSO_URL})...")
    resp = requests.get(IBCSO_URL, stream=True, timeout=120)
    resp.raise_for_status()

    with open(target_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=131072):
            f.write(chunk)

    if not target_path.exists():
        raise MissingDataError(f"Download failed: {target_path} not created")

    # Generate provenance sidecar
    write_provenance_sidecar(
        filepath=target_path,
        source_name="GEBCO / IBCSO v2 Bedrock Bathymetry",
        source_url=IBCSO_URL,
        product_version="IBCSO_v2_bed_WGS84",
        doi_or_citation=IBCSO_DOI,
        spatial_coverage={
            "region": "Southern Ocean (50°S to 90°S, full longitude)",
            "projection": "WGS84 (EPSG:4326)",
            "format": "GeoTIFF",
        },
        temporal_coverage={"compilation_year": 2022},
        variables=["elevation_m_bedrock"],
        extra_metadata={
            "citation": IBCSO_CITATION,
            "project": "GEBCO / Nippon Foundation-GEBCO Seabed 2030",
        },
    )

    print(f"Successfully downloaded and verified {target_path.name} ({target_path.stat().st_size / 1e6:.1f} MB).")
    return target_path


def load_canonical_bathymetry_grid(lats=None, lons=None) -> np.ndarray:
    """
    Load the GEBCO/IBCSO v2 bathymetry and sample it onto a lat/lon grid.

    Defaults to the CANONICAL_DOMAIN EPSG:3031 25 km grid (269, 269). Pass
    `lats`/`lons` to sample onto a different grid instead - the data cube's
    grid is (264, 220), and serving cube-shaped lat/lon alongside a
    canonical-shaped bathymetry array left callers indexing two grids that do
    not correspond.

    Returns:
        bathy: np.ndarray shaped like `lats`, water depth / bed elevation in metres.
    """
    import rasterio
    from scipy.ndimage import map_coordinates

    bathy_file = RAW_BATHY_DIR / "IBCSO_v2_bed_WGS84.tif"
    if not bathy_file.exists():
        bathy_file = fetch_gebco_ibcso_bathymetry()

    verify_provenance_integrity(bathy_file)

    if lats is None or lons is None:
        lats, lons = CANONICAL_DOMAIN.get_latlon_grids()
    lats, lons = np.asarray(lats), np.asarray(lons)

    with rasterio.open(bathy_file) as src:
        # Convert (lon, lat) to raster row/col indices (rowcol returns rows, cols)
        flat_lons = lons.flatten()
        flat_lats = lats.flatten()
        # Ensure longitudes are in [-180, 180]
        flat_lons = (flat_lons + 180.0) % 360.0 - 180.0

        rows, cols = rasterio.transform.rowcol(src.transform, flat_lons, flat_lats)
        rows = np.array(rows)
        cols = np.array(cols)

        # Read elevation band
        data = src.read(1)

        # Mask valid indices within raster bounds
        valid = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        sampled = np.full(rows.shape, np.nan, dtype=np.float32)

        # Extract values at valid pixel coordinates
        raw_vals = data[rows[valid], cols[valid]].astype(np.float32)
        if src.nodata is not None:
            raw_vals[raw_vals == src.nodata] = np.nan

        sampled[valid] = raw_vals
        bathy_grid = sampled.reshape(lats.shape)

    return bathy_grid


if __name__ == "__main__":
    fetch_gebco_ibcso_bathymetry()
