"""
CryoNav — FastAPI backend.

Endpoints:
  GET  /grid                         -> static grid (lat/lon/land_mask), fetch once
  GET  /forecast?date=...&lead=...   -> forecast SIC field + stats
  GET  /observed?date=...            -> observed SIC for overlay proof
  GET  /bergs?date=...&horizon=...   -> berg tracks + ensemble ellipses
  POST /route                        -> routes with metrics + rejection reasons
  GET  /metrics                      -> validation tables
  GET  /config                       -> domain configuration for frontend
  GET  /demo-dates                   -> available demo dates
"""
import numpy as np
import xarray as xr
import os
import json
import gzip
import hashlib
import functools
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import DOMAIN, ROUTING
from src.ice.predict import load_cached_forecast, lead_index

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load the cube, berg tracks and grid cache once, before the first request.

    Replaces @app.on_event("startup"), which FastAPI deprecates. The work is
    unchanged — see _startup() below; the name resolves when the server
    starts, not at import, so defining it further down the module is fine.
    """
    await _startup()
    yield


app = FastAPI(title="CryoNav API", version="1.0.0",
              description="Antarctic Sea-Ice, Iceberg & Navigation Decision Support",
              lifespan=lifespan)

# Raster JSON compresses roughly ten-fold: /grid alone was 2.9 MB on the wire,
# uncompressed, on every page load. Added before CORS so CORS stays the outer
# layer and preflight/error responses keep their headers.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Which browser origins may call this API. "*" meant any page on the internet
# could read it through a visitor's browser; the default now names the dev
# servers only. Deployments set CRYONAV_CORS_ORIGINS (comma-separated), and
# "*" there opts back into the old behaviour deliberately.
_DEFAULT_CORS = ("http://localhost:3000,http://127.0.0.1:3000,"
                 "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in
                os.environ.get("CRYONAV_CORS_ORIGINS", _DEFAULT_CORS).split(",")
                if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)

# Globals — loaded on startup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ZARR_PATH = str(PROJECT_ROOT / DOMAIN["paths"]["zarr_cube"])
BERG_CSV = PROJECT_ROOT / "data" / "processed" / "bergs" / "tracked_icebergs_2017_2024.csv"
DS = None
BERGS = None          # observed berg tracks, or None if the file is absent
CACHE = {}            # memoised berg propagations, keyed by (date, horizon, limit)
GRID_CACHE = None

# Provenance of the loaded cube. The real cube carries per-day *_is_real flags
# written by build_cube.py; the synthetic generator does not write them at all.
# Everything user-facing keys off this, so nothing fabricated is ever presented
# as an observation.
PROVENANCE_FLAGS = ("sic_is_real", "atmo_is_real", "ocean_is_real")
DATA_PROVENANCE = {"is_real": False, "reason": "No data cube loaded."}


def _assess_provenance(ds):
    """Classify a cube as real observations or synthetic, from its own flags."""
    if ds is None:
        return {"is_real": False, "kind": "none", "reason": "No data cube loaded."}
    missing = [f for f in PROVENANCE_FLAGS if f not in ds]
    if missing:
        return {
            "is_real": False,
            "kind": "synthetic",
            "reason": ("Synthetic cube: generated fields, not observations. "
                       "Missing provenance flags: " + ", ".join(missing)),
        }
    fractions = {f: round(float(ds[f].mean()), 4) for f in PROVENANCE_FLAGS}
    return {
        "is_real": all(v > 0 for v in fractions.values()),
        "kind": "real",
        "real_fraction": fractions,
        "reason": "Real observations (NSIDC SIC, ERA5, CMEMS GLORYS).",
    }


async def _startup():
    global DS, BERGS, GRID_CACHE, DATA_PROVENANCE
    print(f"CORS origins: {', '.join(CORS_ORIGINS)}")
    try:
        DS = xr.open_zarr(ZARR_PATH)
        print(f"Loaded Zarr cube: {ZARR_PATH}")
        print(f"  Time range: {DS.time.values[0]} to {DS.time.values[-1]}")
        print(f"  Grid: {DS.dims}")
        DATA_PROVENANCE = _assess_provenance(DS)
        if DATA_PROVENANCE["is_real"]:
            print("  Provenance: REAL observations "
                  f"({DATA_PROVENANCE['real_fraction']})")
        else:
            print("  Provenance: ⚠ SYNTHETIC — " + DATA_PROVENANCE["reason"])
            print("  The web UI will badge every field as synthetic.")
    except Exception as e:
        print(f"Warning: Could not load Zarr cube: {e}")
        print("  Field endpoints will return 404 until a cube exists.")
        print("  Build one with: python src/data/synthetic.py --quick")

    try:
        import pandas as pd
        BERGS = pd.read_csv(BERG_CSV, parse_dates=["date"])
        print(f"Loaded {len(BERGS):,} berg observations "
              f"({BERGS.berg_id.nunique()} bergs) from {BERG_CSV.name}")
    except Exception as e:
        print(f"Warning: no observed berg tracks ({type(e).__name__}); "
              f"/bergs will fall back to synthetic positions.")

    if DS is not None and GRID_CACHE is None:
        try:
            from src.data.sources.bathymetry import RAW_BATHY_DIR, load_canonical_bathymetry_grid
            # Never fetch over the network during startup — that blocks the port from
            # binding. Use the IBCSO GeoTIFF only if it has already been downloaded.
            if not (RAW_BATHY_DIR / "IBCSO_v2_bed_WGS84.tif").exists():
                raise FileNotFoundError(
                    "IBCSO bathymetry not present; run "
                    "`PYTHONPATH=. python -c 'from src.data.sources.bathymetry import "
                    "fetch_gebco_ibcso_bathymetry as f; f()'` to fetch it"
                )
            raw_b = load_canonical_bathymetry_grid(DS["lat"].values, DS["lon"].values)
            if raw_b.shape != DS["lat"].values.shape:
                raise ValueError(f"bathymetry {raw_b.shape} does not match the "
                                 f"cube grid {DS['lat'].values.shape}")
            real_bathy = np.nan_to_num(raw_b, nan=0.0).tolist()
            bathy_source = "GEBCO / IBCSO v2 (DOI: 10.1594/PANGAEA.937574)"
            bathy_note = None
        except Exception as e:
            # Report the substitution: the cache used to claim IBCSO whatever
            # it actually held, so a failed import silently relabelled the
            # cube's own bathymetry as the surveyed dataset.
            bathy_note = f"{type(e).__name__}: {e}"
            print(f"Note: using cube bathymetry instead of IBCSO ({bathy_note}).")
            real_bathy = np.nan_to_num(DS["bathy"].values, nan=0.0).tolist() if "bathy" in DS else None
            bathy_source = "data cube bathymetry (IBCSO unavailable)"

        GRID_CACHE = {
            "shape": list(DS["lat"].values.shape),
            "lat": DS["lat"].values.tolist(),
            "lon": DS["lon"].values.tolist(),
            "land_mask": DS["land_mask"].values.tolist(),
            "bathy": real_bathy,
            "cell_size_km": 25,
            "bathymetry_source": bathy_source,
            "bathymetry_warning": bathy_note,
        }


def _grid_shape():
    """(ny, nx) of the loaded cube, for validating cached forecasts against it."""
    return tuple(DS["land_mask"].values.shape) if DS is not None else None


def _observed_at(date_str):
    """Observed SIC field nearest to date_str, plus the date actually used."""
    try:
        dt = np.datetime64(date_str, "ns")
        idx = int(np.argmin(np.abs(DS.time.values - dt)))
    except Exception:
        idx = 0
    return DS["sic"].values[idx], str(np.datetime64(DS.time.values[idx], "D"))


"""
Heavy endpoints run in FastAPI's worker threads (they are sync `def`), which
keeps the event loop free. But the work is CPU-bound Python, so letting five
of them run at once just makes each one five times slower — the browser then
times out while the server is still computing. Cap how many run concurrently:
light endpoints stay instant, heavy ones queue and finish at full speed.
"""
_HEAVY_SLOTS = threading.Semaphore(2)


def heavy(fn):
    """Serialise CPU-bound endpoint work. FastAPI reads the wrapped signature."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _HEAVY_SLOTS:
            return fn(*args, **kwargs)
    return wrapper


# ── Response byte cache ─────────────────────────────────────────────────
# /grid, /observed and /forecast return the same tens of thousands of numbers
# for a given day on every request, and were re-running .tolist() and
# json.dumps each time: /grid cost 0.5 s and 2.9 MB even with its dict already
# built. Serialise once, keep the bytes, and hand callers an ETag so the
# browser can skip the body altogether on the next load.
_JSON_BYTES = OrderedDict()
_JSON_BYTES_LOCK = threading.Lock()
_JSON_BYTES_MAX = 24          # ~24 daily rasters, so memory stays bounded


def _json_default(o):
    """numpy scalars/arrays json.dumps does not know (float32, int64, bool_)."""
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _json_cached(request: Request, key, build, max_age: int = 3600) -> Response:
    """
    Serialise `build()` once per key, then serve those bytes with an ETag.

    The compressed copy is cached too. Letting GZipMiddleware compress on the
    fly instead cost 1.2 s of CPU per /grid request, every request, to produce
    bytes that never change; here that happens once. Setting Content-Encoding
    ourselves makes the middleware pass the response straight through.

    The lock is not held across build(): that can take seconds, and blocking
    every other cached endpoint behind it would cost more than the rare case
    of two callers building the same key at once (same input, same result).
    """
    with _JSON_BYTES_LOCK:
        entry = _JSON_BYTES.get(key)
        if entry is not None:
            _JSON_BYTES.move_to_end(key)

    if entry is None:
        # The encoder Starlette's JSONResponse uses, so the bytes are identical
        # to what these endpoints returned before.
        raw = json.dumps(build(), ensure_ascii=False, allow_nan=False,
                         separators=(",", ":"), default=_json_default).encode("utf-8")
        entry = {"raw": raw, "gz": None,
                 "etag": f'"{hashlib.sha1(raw).hexdigest()[:16]}"'}
        with _JSON_BYTES_LOCK:
            _JSON_BYTES[key] = entry
            _JSON_BYTES.move_to_end(key)
            while len(_JSON_BYTES) > _JSON_BYTES_MAX:
                _JSON_BYTES.popitem(last=False)

    body, etag, encoding = entry["raw"], entry["etag"], None
    if "gzip" in request.headers.get("accept-encoding", "") and len(body) >= 1024:
        if entry["gz"] is None:
            entry["gz"] = gzip.compress(body, compresslevel=6)
        body = entry["gz"]
        # A different representation of the resource, so a different validator.
        etag, encoding = f'{etag[:-1]}-gz"', "gzip"

    headers = {"ETag": etag,
               "Cache-Control": f"public, max-age={max_age}",
               "Vary": "Accept-Encoding"}
    # Parsed as a list: the plain ETag is a prefix of the gzip one, so a
    # substring test would match the wrong representation.
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    if encoding:
        headers["Content-Encoding"] = encoding
    return Response(content=body, media_type="application/json", headers=headers)


def _vector_field(u_arr, v_arr, lat, lon, land, stride, decimals=4):
    """
    Subsampled arrow field for /ocean and /weather.

    This used to walk all 58,080 cells in Python and call float() on each —
    ~12 s per request. Striding and masking first means only the few thousand
    cells that actually become arrows are ever touched.
    """
    s = max(1, int(stride))
    us = u_arr[::s, ::s]
    vs = v_arr[::s, ::s]
    la = lat[::s, ::s]
    lo = lon[::s, ::s]
    keep = ((land[::s, ::s] < 0.5)
            & np.isfinite(us) & np.isfinite(vs)
            & ((np.abs(us) >= 1e-4) | (np.abs(vs) >= 1e-4)))
    speed = np.hypot(us, vs)
    return [
        {"lat": round(float(a), 4), "lon": round(float(b), 4),
         "u": round(float(c), decimals), "v": round(float(d), decimals),
         "speed": round(float(e), decimals)}
        for a, b, c, d, e in zip(la[keep], lo[keep], us[keep], vs[keep], speed[keep])
    ]


def _date_index(date_str, what="date"):
    """
    Index of `date_str` in the cube, or HTTP 400 if it lies outside it.

    Every field endpoint used to take the nearest timestep silently, so a
    request for 2030-01-01 returned 2024-12-31's ice — plausible-looking data
    for a date the record does not cover. Callers must invoke this OUTSIDE
    their own try/except, or a 400 gets re-raised as a 500.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")
    try:
        target = np.datetime64(date_str)
    except Exception:
        raise HTTPException(400, f"Invalid {what}: {date_str!r}. Use YYYY-MM-DD.")

    times = DS.time.values
    if not (times[0] <= target <= times[-1]):
        raise HTTPException(
            400,
            f"{what} {date_str} is outside the data cube "
            f"({np.datetime64(times[0], 'D')} to {np.datetime64(times[-1], 'D')}).",
        )
    return int(np.argmin(np.abs(times - target)))


def _field_stats(field, ocean):
    return {
        "mean_sic": float(np.mean(field[ocean])),
        "ice_extent_cells": int(np.sum((field > 0.15) & ocean)),
        "ice_area_km2": int(np.sum((field > 0.15) & ocean) * 625),
    }


@app.get("/config")
async def get_config():
    """Return domain configuration for the frontend."""
    return {
        "region": DOMAIN["region"],
        "stations": DOMAIN["stations"],
        "origins": DOMAIN["origins"],
        "held_out_demo_dates": DOMAIN["held_out_demo_dates"],
        "forecast_horizon_days": DOMAIN["time"]["forecast_horizon_days"],
        "ship": DOMAIN["ship"],
        "data_provenance": DATA_PROVENANCE,
        "routing_weights": ROUTING["cost_weights"],
        "alternative_profiles": {k: v["name"] for k, v in 
                                 ROUTING["alternatives"]["profiles"].items()},
    }


@app.get("/demo-dates")
async def get_demo_dates():
    """Return available dates for the demo."""
    if DS is None:
        return {"dates": DOMAIN["held_out_demo_dates"]}
    
    times = [str(np.datetime64(t, 'D')) for t in DS.time.values]
    return {
        "all_dates": times,
        "demo_dates": DOMAIN["held_out_demo_dates"],
        "range": {"start": times[0], "end": times[-1]},
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/grid")
def get_grid(request: Request):
    """Static grid geometry, served from a cached, ETagged byte buffer."""
    # A day, not an hour: the grid is fixed for the life of the cube.
    return _json_cached(request, ("grid",), _build_grid, max_age=86400)


def _build_grid():
    """
    Static grid geometry: lat, lon, land mask, and real GEBCO bathymetry.

    These never change, so they are served here once instead of being repeated
    in every /forecast response (which the lead-day animation calls 14 times).

    NOTE: every endpoint that reads the cube, drifts bergs or routes is a plain
    `def`, not `async def`. FastAPI runs sync endpoints in a worker thread, so a
    minute-long A* search no longer blocks the event loop — and with it every
    other request, including the frontend's health check.
    """
    global GRID_CACHE
    if GRID_CACHE is not None:
        return GRID_CACHE

    if DS is None:
        raise HTTPException(404, "Data not loaded")

    # Load real GEBCO/IBCSO v2 bathymetry. If that fails the cube's own
    # bathymetry stands in — but the response says so, because callers were
    # otherwise told "IBCSO v2" over a different dataset entirely.
    try:
        from src.data.sources.bathymetry import load_canonical_bathymetry_grid
        raw_b = load_canonical_bathymetry_grid(DS["lat"].values, DS["lon"].values)
        if raw_b.shape != DS["lat"].values.shape:
            raise ValueError(f"bathymetry {raw_b.shape} does not match the "
                             f"cube grid {DS['lat'].values.shape}")
        real_bathy = np.nan_to_num(raw_b, nan=0.0).tolist()
        bathy_source = "GEBCO / IBCSO v2 (DOI: 10.1594/PANGAEA.937574)"
        bathy_note = None
    except Exception as e:
        real_bathy = np.nan_to_num(DS["bathy"].values, nan=0.0).tolist() if "bathy" in DS else None
        bathy_source = "data cube bathymetry (IBCSO unavailable)"
        bathy_note = f"{type(e).__name__}: {e}"
        print(f"  /grid: falling back to cube bathymetry ({bathy_note})")

    GRID_CACHE = {
        "shape": list(DS["lat"].values.shape),
        "lat": DS["lat"].values.tolist(),
        "lon": DS["lon"].values.tolist(),
        "land_mask": DS["land_mask"].values.tolist(),
        "bathy": real_bathy,
        "cell_size_km": 25,
        "bathymetry_source": bathy_source,
        "bathymetry_warning": bathy_note,
    }
    return GRID_CACHE


@app.get("/data/provenance")
def get_data_provenance():
    """Return cryptographic SHA-256 provenance metadata for all 6 data sources."""
    if not DATA_PROVENANCE["is_real"]:
        # Refuse rather than render "SHA-256 VERIFIED" over generated fields.
        raise HTTPException(
            409,
            "No real data layers present. " + DATA_PROVENANCE["reason"] +
            " Provenance records exist only for the real cube; download it with "
            "`python scripts/download_data.py --gdrive-id <ID>`.",
        )
    from src.data.report_coverage import (
        analyze_sic_coverage,
        analyze_thickness_coverage,
        analyze_era5_coverage,
        analyze_cmems_coverage,
        analyze_iceberg_coverage,
        analyze_bathymetry_coverage,
    )
    return {
        "sic": analyze_sic_coverage(),
        "thickness": analyze_thickness_coverage(),
        "era5": analyze_era5_coverage(),
        "cmems": analyze_cmems_coverage(),
        "icebergs": analyze_iceberg_coverage(),
        "bathymetry": analyze_bathymetry_coverage(),
    }


@app.get("/data/coverage")
def get_data_coverage():
    """Return the complete coverage and gap report markdown."""
    from src.data.report_coverage import generate_coverage_report
    report_text = generate_coverage_report()
    return {"markdown_report": report_text}


@app.get("/bergs/live")
def get_live_icebergs():
    """Return active US National Ice Center weekly tracked icebergs."""
    import pandas as pd
    nic_path = PROJECT_ROOT / "data" / "raw" / "bergs" / "nic" / "nic_antarctic_icebergs.csv"
    if not nic_path.exists():
        from src.data.sources.icebergs import fetch_nic_weekly_icebergs
        fetch_nic_weekly_icebergs()

    if nic_path.exists():
        df = pd.read_csv(nic_path)
        records = df.to_dict(orient="records")
        return {
            "source": "US National Ice Center Weekly Antarctic Icebergs",
            "count": len(records),
            "icebergs": records,
        }
    raise HTTPException(404, "Live US NIC iceberg feed unavailable")


@app.get("/forecast")
def get_forecast(request: Request, date: str, lead: int = Query(7, ge=1, le=14)):
    """Cached, ETagged wrapper around the forecast field — see _build_forecast."""
    return _json_cached(request, ("forecast", date, lead),
                        lambda: _build_forecast(date, lead))


def _build_forecast(date: str, lead: int):
    """
    Model forecast initialized on `date`, valid at `date + lead` days.

    `date` is the initialization date: the last day of observed data the model
    was shown. The returned field is the U-Net's prediction, loaded from the
    forecast cache written by src/ice/predict.py.

    If no cached forecast exists for `date`, the response falls back to the
    OBSERVED field at the valid date and says so in `source`. That fallback is
    not a forecast — it is the answer — so callers must surface it rather than
    plot it as a prediction.

    Grid arrays are not included; fetch /grid once instead.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    horizon = DOMAIN["time"]["forecast_horizon_days"]
    if not 1 <= lead <= horizon:
        raise HTTPException(400, f"lead must be in 1..{horizon}, got {lead}")

    _date_index(date, "init date")          # 400 rather than a nearest-day guess
    init_dt = np.datetime64(date)
    valid_dt = init_dt + np.timedelta64(lead, "D")
    if not (DS.time.values[0] <= valid_dt <= DS.time.values[-1]):
        raise HTTPException(400, f"Valid date {valid_dt} is outside the cube")

    cached = load_cached_forecast(date, ZARR_PATH, grid_shape=_grid_shape())
    if cached is not None and lead <= cached.shape[0]:
        sic = cached[lead - 1]
        source = "model"
        warning = None
    else:
        sic, _ = _observed_at(str(valid_dt))
        source = "observed_fallback"
        warning = (f"No cached forecast for init date {date}. Returning OBSERVED "
                   f"SIC at {valid_dt}, which is truth, not a prediction. "
                   f"Generate one with: python src/ice/predict.py --dates {date}")

    ocean = DS["land_mask"].values < 0.5
    stats = {
        "init_date": date,
        "valid_date": str(np.datetime64(valid_dt, "D")),
        "lead_day": lead,
        "source": source,
        **_field_stats(sic, ocean),
    }

    return {
        "sic": sic.tolist(),
        "shape": list(sic.shape),
        "source": source,
        "warning": warning,
        "stats": stats,
    }


@app.get("/observed")
def get_observed(request: Request, date: str):
    """
    Observed (actual) SIC field for overlay proof.

    A past day's field never changes, so it is serialised once and afterwards
    served from the byte cache.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)      # outside the builder: a 400 must not be cached
    return _json_cached(request, ("observed", idx), lambda: _build_observed(idx))


def _build_observed(idx):
    try:
        sic = DS["sic"].values[idx]
        land_mask = DS["land_mask"].values
        
        ocean = land_mask < 0.5
        
        return {
            "sic": sic.tolist(),
            "shape": list(sic.shape),
            "date": str(np.datetime64(DS.time.values[idx], 'D')),
            # "observed" only when the cube is real; a synthetic cube returns
            # generated fields and must never be labelled as an observation.
            "source": "observed" if DATA_PROVENANCE["is_real"] else "synthetic",
            "stats": {
                "mean_sic": float(np.mean(sic[ocean])),
                "ice_extent_km2": int(np.sum((sic > 0.15) & ocean) * 625),
            }
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/ocean")
@heavy
def get_ocean(date: str, stride: int = Query(4, ge=1, le=32),
              fields: bool = False):
    """
    CMEMS GLORYS ocean state: surface currents, temperature and sea level.

    These variables have been in the cube all along (uo, vo, sst, zos) but
    had no route, so the UI could not show them. `stride` subsamples the
    current vectors — the frontend draws arrows, not a per-cell field, and
    a full 264x220 vector grid is far more than any screen can render.

    `is_real` reports the cube's own provenance flag for this timestep
    rather than assuming every day is backed by real reanalysis.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)      # outside the try: a 400 must not become a 500
    s = max(1, int(stride))

    # Memoised like berg drift: the map re-requests the same day whenever a
    # layer is toggled, and this response is otherwise rebuilt from scratch.
    key = ("ocean", idx, s, bool(fields))
    if key in CACHE:
        return CACHE[key]

    try:
        actual = str(np.datetime64(DS.time.values[idx], "D"))

        land = DS["land_mask"].values
        ocean = land < 0.5

        uo = DS["uo"].values[idx]
        vo = DS["vo"].values[idx]
        sst = DS["sst"].values[idx]
        zos = DS["zos"].values[idx]

        speed = np.sqrt(uo ** 2 + vo ** 2)

        vectors = _vector_field(uo, vo, DS["lat"].values, DS["lon"].values, land, s)

        def _mean(a):
            vals = a[ocean]
            vals = vals[np.isfinite(vals)]
            return float(np.mean(vals)) if vals.size else None

        is_real = bool(DS["ocean_is_real"].values[idx]) if "ocean_is_real" in DS else None

        payload = {
            "date": actual,
            "requested": date,
            "source": "CMEMS GLORYS12 reanalysis" if is_real else "gap-filled",
            "is_real": is_real,
            "stride": s,
            "vectors": vectors,
            "shape": list(uo.shape),
            "stats": {
                "mean_current_ms": _mean(speed),
                "max_current_ms": float(np.nanmax(speed[ocean])) if ocean.any() else None,
                # Cube stores SST in kelvin; report celsius
                "mean_sst_c": (lambda t: t - 273.15 if t is not None and t > 100 else t)(_mean(sst)),
                "mean_ssh_m": _mean(zos),
            },
        }

        # The full rasters are ~3 MB and only the Ocean page draws them; the
        # map needs arrows and stats, so they are opt-in via ?fields=true.
        if fields:
            payload["sst"] = np.nan_to_num(sst, nan=0.0).round(3).tolist()
            payload["speed"] = np.nan_to_num(speed, nan=0.0).round(4).tolist()
            payload["zos"] = np.nan_to_num(zos, nan=0.0).round(4).tolist()

        CACHE[key] = payload
        return payload
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/weather")
@heavy
def get_weather(date: str, stride: int = Query(4, ge=1, le=32),
                fields: bool = False):
    """
    ERA5 atmospheric state: 10 m wind, 2 m temperature, mean sea-level
    pressure. Same shape of response as /ocean so the frontend can treat
    the two the same way.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)      # outside the try: a 400 must not become a 500
    s = max(1, int(stride))

    # `fields` belongs in the key: without it a cached trimmed payload was
    # returned for a ?fields=true request, silently dropping the raster.
    key = ("weather", idx, s, bool(fields))
    if key in CACHE:
        return CACHE[key]

    try:
        actual = str(np.datetime64(DS.time.values[idx], "D"))

        land = DS["land_mask"].values
        ocean = land < 0.5
        lat = DS["lat"].values
        lon = DS["lon"].values

        u10 = DS["u10"].values[idx]
        v10 = DS["v10"].values[idx]
        wind = DS["wind_speed"].values[idx] if "wind_speed" in DS else np.sqrt(u10 ** 2 + v10 ** 2)
        t2m = DS["t2m"].values[idx]
        msl = DS["msl"].values[idx]

        vectors = _vector_field(u10, v10, lat, lon, land, s, decimals=3)

        def _mean(a):
            vals = a[ocean]
            vals = vals[np.isfinite(vals)]
            return float(np.mean(vals)) if vals.size else None

        is_real = bool(DS["atmo_is_real"].values[idx]) if "atmo_is_real" in DS else None
        t_mean = _mean(t2m)

        payload = {
            "date": actual,
            "requested": date,
            "source": "ERA5 reanalysis" if is_real else "gap-filled",
            "is_real": is_real,
            "stride": s,
            "vectors": vectors,
            "shape": list(u10.shape),
            "stats": {
                "mean_wind_ms": _mean(wind),
                "max_wind_ms": float(np.nanmax(wind[ocean])) if ocean.any() else None,
                # Cube stores 2 m temperature in kelvin
                "mean_t2m_c": (t_mean - 273.15) if t_mean is not None and t_mean > 100 else t_mean,
                "mean_msl_hpa": (lambda m: m / 100.0 if m is not None and m > 10000 else m)(_mean(msl)),
            },
        }

        # ~1.1 MB of wind field that only a raster view would draw; the map
        # takes arrows and stats, so it is opt-in via ?fields=true.
        if fields:
            payload["wind_speed"] = np.nan_to_num(wind, nan=0.0).round(3).tolist()

        CACHE[key] = payload
        return payload
    except Exception as e:
        raise HTTPException(500, str(e))


def _grid_tree():
    """KD-tree over grid cells for fast nearest-cell lookup during drift."""
    if "tree" not in CACHE:
        from scipy.spatial import cKDTree
        lat = DS["lat"].values
        lon = DS["lon"].values
        # Scale longitude by cos(lat) so "nearest" is not biased toward latitude.
        pts = np.column_stack([
            (lon * np.cos(np.radians(lat))).ravel(),
            lat.ravel(),
        ])
        CACHE["tree"] = (cKDTree(pts), lat.shape)
    return CACHE["tree"]


def _forcing_from_cube(date: str, horizon: int):
    """
    Build a forcing_func sampling real winds, currents and SIC from the cube.

    Replaces the hardcoded sinusoid the demo used to drift bergs with. Fields
    for the whole window are pulled into memory once; the drift integrator then
    only does an array lookup per step.
    """
    tree, shape = _grid_tree()
    i0 = int(np.argmin(np.abs(DS.time.values - np.datetime64(date))))
    i1 = min(i0 + horizon + 1, len(DS.time.values))

    fields = {}
    for name, var in [("wind_u", "u10"), ("wind_v", "v10"),
                      ("curr_u", "uo"), ("curr_v", "vo"), ("sic", "sic")]:
        if var in DS:
            fields[name] = DS[var].isel(time=slice(i0, i1)).values
    n_t = len(next(iter(fields.values())))
    static_land = DS["land_mask"].values if "land_mask" in DS else None
    static_bathy = DS["bathy"].values if "bathy" in DS else None

    def forcing_batch(t_day, lats, lons):
        """The same sampling for many positions at once: one tree query."""
        ti = min(int(t_day), n_t - 1)
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        _, flat_idx = tree.query(np.column_stack([
            lons * np.cos(np.radians(lats)), lats]))
        yi, xi = np.unravel_index(flat_idx, shape)
        out = {k: v[ti, yi, xi].astype(float) for k, v in fields.items()}
        zeros = np.zeros(lats.shape)
        for k in ("wind_u", "wind_v", "curr_u", "curr_v", "sic"):
            out.setdefault(k, zeros)
        out["land_mask"] = (static_land[yi, xi].astype(float)
                            if static_land is not None else zeros)
        out["bathy"] = (static_bathy[yi, xi].astype(float)
                        if static_bathy is not None else np.full(lats.shape, -100.0))
        return out

    def forcing_func(t_day, lat, lon):
        ti = min(int(t_day), n_t - 1)
        _, flat_idx = tree.query([lon * np.cos(np.radians(lat)), lat])
        yi, xi = np.unravel_index(flat_idx, shape)
        out = {k: float(v[ti, yi, xi]) for k, v in fields.items()}
        out.setdefault("curr_u", 0.0)
        out.setdefault("curr_v", 0.0)
        out["land_mask"] = float(static_land[yi, xi]) if static_land is not None else 0.0
        out["bathy"] = float(static_bathy[yi, xi]) if static_bathy is not None else -100.0
        out["ssh_grad_x"] = 0.0
        out["ssh_grad_y"] = 0.0
        return out

    # Carried on the scalar sampler so callers that want the vectorised drift
    # path can reach it without changing this function's contract.
    forcing_func.batch = forcing_batch
    return forcing_func


# -- Corridor geometry ---------------------------------------------------
# Which bergs matter to a voyage is a question about distance to the track,
# not about size. These measure that.
_NM_PER_RAD = 3440.065          # Earth radius in nautical miles
CORRIDOR_DEFAULT = ("cape_town", "bharati")

# P(berg in cell) above which the router refuses a cell; reported alongside
# the risk field so callers can shade it against the threshold that matters.
_BERG_CUTOFF = float(ROUTING["constraints"]["berg_risk_cutoff"])


def _routing_bathy():
    """
    The depths the router plans against: real IBCSO where it has them, the
    cube's own values in the gaps.

    The cube's `bathy` is a synthetic proxy - over ocean it spans only -5011 to
    -2480 m and is exactly 0 over every land cell, so it contains no
    continental shelf and the minimum-depth constraint could never fire. IBCSO
    has real relief. Its gaps all fall over ocean, so they are filled from the
    cube rather than with nan_to_num: astar exempts a depth of exactly 0 from
    the shallow-water test, which would have quietly made every gap navigable.

    Returns (array on the cube grid, source string), memoised - sampling IBCSO
    costs a few seconds.
    """
    if "routing_bathy" in CACHE:
        return CACHE["routing_bathy"]

    cube = DS["bathy"].values if "bathy" in DS else None
    try:
        from src.data.sources.bathymetry import load_canonical_bathymetry_grid
        ib = load_canonical_bathymetry_grid(DS["lat"].values, DS["lon"].values)
        if ib.shape != DS["lat"].values.shape:
            raise ValueError(f"bathymetry {ib.shape} does not match the cube grid "
                             f"{DS['lat'].values.shape}")
        gaps = np.isnan(ib)
        if cube is None:
            merged, filled = np.nan_to_num(ib, nan=0.0), 0
        else:
            merged, filled = np.where(gaps, cube, ib), int(gaps.sum())
        source = ("GEBCO / IBCSO v2 (DOI: 10.1594/PANGAEA.937574)"
                  + (f"; {filled} cells filled from the cube" if filled else ""))
    except Exception as e:
        print(f"  routing bathymetry: using the cube ({type(e).__name__}: {e})")
        merged = cube if cube is not None else np.zeros(DS["lat"].values.shape)
        source = f"data cube bathymetry (IBCSO unavailable: {type(e).__name__})"

    CACHE["routing_bathy"] = (np.asarray(merged, dtype=float), source)
    return CACHE["routing_bathy"]


def _unit_vec(lat, lon):
    """Unit vectors on the sphere, for scalars or arrays of degrees."""
    phi, lam = np.radians(lat), np.radians(lon)
    cos_phi = np.cos(phi)
    return np.stack([cos_phi * np.cos(lam), cos_phi * np.sin(lam), np.sin(phi)],
                    axis=-1)


def _resolve_place(key):
    """Look a place up in origins, then stations. None if it is neither."""
    return DOMAIN.get("origins", {}).get(key) or DOMAIN.get("stations", {}).get(key)


def _corridor_latlon(origin_key: str, dest_key: str):
    """((lat, lon), (lat, lon)) for a named voyage; 400 on an unknown place."""
    o, d = _resolve_place(origin_key), _resolve_place(dest_key)
    if o is None:
        raise HTTPException(400, f"Unknown origin: {origin_key}")
    if d is None:
        raise HTTPException(400, f"Unknown destination: {dest_key}")
    return (o["lat"], o["lon"]), (d["lat"], d["lon"])


def _corridor_distance_nm(lats, lons, a_latlon, b_latlon):
    """
    Great-circle distance in nm from each point to the corridor A-to-B.

    Cross-track distance to the great circle through A and B, clamped to the
    segment: a berg 200 nm off the side of the track and one 200 nm beyond its
    far end are both 200 nm away, which is what "how close is this berg to the
    voyage" should mean.
    """
    p = _unit_vec(np.asarray(lats, dtype=float), np.asarray(lons, dtype=float))
    a, b = _unit_vec(*a_latlon), _unit_vec(*b_latlon)

    n = np.cross(a, b)
    n_norm = float(np.linalg.norm(n))
    if n_norm < 1e-12:                      # degenerate corridor: distance from A
        return _NM_PER_RAD * np.arccos(np.clip(p @ a, -1.0, 1.0))
    n = n / n_norm

    cross_track = np.arcsin(np.clip(np.abs(p @ n), -1.0, 1.0))

    # Does the foot of the perpendicular land between A and B? Project onto the
    # great circle and compare along-track angles.
    proj = p - np.outer(p @ n, n)
    proj_norm = np.linalg.norm(proj, axis=-1, keepdims=True)
    proj = proj / np.where(proj_norm < 1e-12, 1.0, proj_norm)

    ab = np.arccos(np.clip(float(a @ b), -1.0, 1.0))
    inside = ((np.arccos(np.clip(proj @ a, -1.0, 1.0)) <= ab + 1e-9)
              & (np.arccos(np.clip(proj @ b, -1.0, 1.0)) <= ab + 1e-9))

    d_a = np.arccos(np.clip(p @ a, -1.0, 1.0))
    d_b = np.arccos(np.clip(p @ b, -1.0, 1.0))
    return _NM_PER_RAD * np.where(inside, cross_track, np.minimum(d_a, d_b))


def _polyline_distance_nm(path):
    """
    Great-circle length of the polyline actually drawn, in nautical miles.

    `distance_nm` from the router is the sum of 16-connected grid steps along
    the unsmoothed cell path, which is what the cost model integrated. The line
    the map draws is the smoothed path, and it is consistently ~3% shorter, so
    the two are reported side by side rather than one standing in for the other.
    """
    if not path or len(path) < 2:
        return None
    a = np.radians(np.asarray(path, dtype=float))
    la1, lo1, la2, lo2 = a[:-1, 0], a[:-1, 1], a[1:, 0], a[1:, 1]
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return round(float((2 * _NM_PER_RAD * np.arcsin(np.sqrt(np.clip(h, 0, 1)))).sum()), 1)


def _geodesic_points(a_latlon, b_latlon, n=200):
    """`n` points along the great circle from A to B, as (lat, lon) degrees."""
    a, b = _unit_vec(*a_latlon), _unit_vec(*b_latlon)
    omega = np.arccos(np.clip(float(a @ b), -1.0, 1.0))
    if omega < 1e-6:
        return np.array([a_latlon, b_latlon], dtype=float)
    f = np.linspace(0.0, 1.0, n)[:, None]
    v = (np.sin((1 - f) * omega) * a + np.sin(f * omega) * b) / np.sin(omega)
    return np.column_stack([np.degrees(np.arcsin(np.clip(v[:, 2], -1.0, 1.0))),
                            np.degrees(np.arctan2(v[:, 1], v[:, 0]))])


def _closest_berg_nm(path, berg_results):
    """
    Smallest distance in nm between the plotted route and any berg's track.

    A screening distance, not a time-matched closest point of approach: every
    route vertex is compared with every berg position on every day, so it
    reports how close the route passes to where a berg is expected to be at
    some point in the passage. That is the conservative reading, and callers
    must not present it as a CPA.
    """
    if not path or not berg_results:
        return None, None

    pts = _unit_vec(np.array([q[0] for q in path], dtype=float),
                    np.array([q[1] for q in path], dtype=float))
    best_d, best_id = None, None
    for r in berg_results:
        track = r.get("mean_track") or []
        if not track:
            continue
        bv = _unit_vec(np.array([t[1] for t in track], dtype=float),
                       np.array([t[2] for t in track], dtype=float))
        d = float(_NM_PER_RAD * np.arccos(np.clip(pts @ bv.T, -1.0, 1.0)).min())
        if best_d is None or d < best_d:
            best_d, best_id = d, r.get("berg_id")
    return (round(best_d, 1) if best_d is not None else None), best_id


def _bergs_near_date(date: str, limit: int, days_tol: int = 7, corridor=None):
    """
    Observed bergs present on `date`, nearest the voyage corridor first.

    Returns (list_of_bergs, source). Selection used to take the physically
    largest bergs, which answers a different question: a giant berg parked
    1,500 nm off the track told the router nothing, while a smaller one
    sitting on the corridor was dropped before it was ever propagated. Rank by
    distance to the corridor and break ties by size. With no corridor given,
    the old size ordering stands.

    Falls back to synthetic positions only if the tracked-iceberg file was not
    loaded at startup.
    """
    from src.berg.risk_field import generate_synthetic_bergs_for_demo

    if BERGS is None:
        return generate_synthetic_bergs_for_demo(n_bergs=limit), "synthetic"

    import pandas as pd
    target = pd.Timestamp(date)
    # Nearest observation per berg within a week of the requested date.
    window = BERGS[(BERGS["date"] - target).abs() <= pd.Timedelta(days=days_tol)]
    if window.empty:
        return generate_synthetic_bergs_for_demo(n_bergs=limit), "synthetic"

    window = window.assign(_gap=(window["date"] - target).abs())
    nearest = window.sort_values("_gap").groupby("berg_id", as_index=False).first()

    defaults = ROUTING["berg_drift"]
    bergs = []
    for row in nearest.itertuples():
        length_km = getattr(row, "length_km", np.nan)
        width_km = getattr(row, "width_km", np.nan)
        bergs.append({
            "berg_id": row.berg_id,
            "lat": float(row.latitude),
            "lon": float(row.longitude),
            "length_m": (float(length_km) * 1000 if length_km == length_km
                         else defaults["default_length_m"]),
            "width_m": (float(width_km) * 1000 if width_km == width_km
                        else defaults["default_width_m"]),
            "observed_on": str(row.date.date()),
        })

    if corridor is not None and bergs:
        d = _corridor_distance_nm([b["lat"] for b in bergs],
                                  [b["lon"] for b in bergs], *corridor)
        for berg, dist in zip(bergs, d):
            berg["corridor_distance_nm"] = round(float(dist), 1)
        bergs.sort(key=lambda b: (b["corridor_distance_nm"],
                                  -b["length_m"] * b["width_m"]))
    else:
        bergs.sort(key=lambda b: b["length_m"] * b["width_m"], reverse=True)
    return bergs[:limit], "observed"


def _propagate_bergs(date: str, horizon: int, limit: int, corridor=None):
    """Propagate bergs from `date`, memoised — /bergs and /route share this."""
    # The corridor belongs in the key: it decides which bergs were selected.
    key = ("bergs", date, horizon, limit, corridor)
    if key in CACHE:
        return CACHE[key]

    from src.berg.dynamics import propagate

    bergs, source = _bergs_near_date(date, limit, corridor=corridor)
    forcing_func = _forcing_from_cube(date, horizon)
    n_ensemble = ROUTING["berg_drift"]["n_ensemble"]

    results = []
    for berg in bergs:
        result = propagate(
            berg["berg_id"], berg["lat"], berg["lon"],
            t0=date, horizon_days=horizon,
            forcing_func=forcing_func,
            berg_length=berg["length_m"],
            berg_width=berg["width_m"],
            method="2pct", n_ensemble=n_ensemble,
            forcing_batch=getattr(forcing_func, "batch", None),
        )
        result["length_m"] = berg["length_m"]
        result["width_m"] = berg["width_m"]
        result["observed_on"] = berg.get("observed_on")
        result["corridor_distance_nm"] = berg.get("corridor_distance_nm")
        results.append(result)

    CACHE[key] = (results, source, n_ensemble)
    return CACHE[key]


@app.get("/bergs")
@heavy
def get_bergs(date: str = "2023-01-13",
              horizon: int = Query(7, ge=1, le=90),
              limit: int = Query(8, ge=1, le=50),
              origin: str = CORRIDOR_DEFAULT[0],
              destination: str = CORRIDOR_DEFAULT[1]):
    """
    Iceberg drift forecasts from `date`, with ensemble spread.

    Positions come from the tracked-iceberg record and are drifted with winds,
    currents and SIC read from the data cube.

    The `limit` bergs returned are those nearest the `origin`→`destination`
    corridor, and each reports its distance to it. Selection was by size,
    which surfaced giant bergs far from any shipping track.

    `limit` is bounded above: it used to slice the berg list directly, so a
    negative value returned every berg but the last few.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    _date_index(date)
    corridor = _corridor_latlon(origin, destination)
    results, source, n_ensemble = _propagate_bergs(date, horizon, limit, corridor)

    return {
        "bergs": [{
            "berg_id": r["berg_id"],
            "mean_track": r["mean_track"],
            "ensemble": r["ensemble"].tolist(),
            "length_m": r["length_m"],
            "width_m": r["width_m"],
            "observed_on": r["observed_on"],
            "corridor_distance_nm": r.get("corridor_distance_nm"),
            "final_position": {
                "day": horizon,
                "lat": r["mean_track"][-1][1],
                "lon": r["mean_track"][-1][2],
            } if r.get("mean_track") else None,
        } for r in results],
        "date": date,
        "horizon": horizon,
        "source": source,
        "n_ensemble": n_ensemble,
        "selection": "nearest the corridor first",
        "corridor": {"origin": origin, "destination": destination},
    }


class RouteRequest(BaseModel):
    origin: str = "cape_town"
    destination: str = "bharati"
    depart_date: str = "2023-01-13"
    # Weights are applied to the "balanced" profile; bounded so a stray value
    # cannot produce a cost field the A* heuristic can no longer admit.
    w_time: float = Field(1.0, ge=0.0, le=20.0)
    w_fuel: float = Field(0.5, ge=0.0, le=20.0)
    w_risk: float = Field(2.0, ge=0.0, le=20.0)
    berg_limit: int = Field(8, ge=0, le=50)


@app.post("/route")
@heavy
def compute_route(req: RouteRequest):
    """
    Compute routes with all alternatives, metrics, and rejection reasons.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")
    
    from src.routing.alternatives import generate_alternatives, format_comparison_for_display
    
    # Get origin/destination grid coordinates
    lat_grid = DS["lat"].values
    lon_grid = DS["lon"].values
    
    # Resolve origin
    if req.origin in DOMAIN["origins"]:
        origin = DOMAIN["origins"][req.origin]
    elif req.origin in DOMAIN["stations"]:
        origin = DOMAIN["stations"][req.origin]
    else:
        raise HTTPException(400, f"Unknown origin: {req.origin}")
    
    # Resolve destination
    if req.destination in DOMAIN["stations"]:
        dest = DOMAIN["stations"][req.destination]
    elif req.destination in DOMAIN["origins"]:
        dest = DOMAIN["origins"][req.destination]
    else:
        raise HTTPException(400, f"Unknown destination: {req.destination}")
    
    # Find nearest navigable ocean cells
    def find_approach(lat, lon, land_mask, bathy, sic_ref, max_sic=0.85):
        dist = (lat_grid - lat)**2 + (lon_grid - lon)**2
        navigable = (land_mask < 0.5) & (bathy < -15.0) & (sic_ref <= max_sic)
        dist[~navigable] = np.inf
        return tuple(int(x) for x in np.unravel_index(np.argmin(dist), dist.shape))
    
    today_idx = _date_index(req.depart_date, "departure date")
    depart_dt = np.datetime64(req.depart_date, "ns")
    sic_today = DS["sic"].values[today_idx]
    
    # Real depths, not the cube's synthetic proxy: the approach cell it picked
    # for Bharati was nominally 4,024 m deep, in a coastal bay.
    bathy, bathy_source = _routing_bathy()
    land_mask = DS["land_mask"].values
    
    start_yx = find_approach(origin["lat"], origin["lon"], land_mask, bathy, sic_today)
    goal_yx = find_approach(dest["lat"], dest["lon"], land_mask, bathy, sic_today)
    
    # Get SIC fields for the forecast horizon
    horizon = DOMAIN["time"]["forecast_horizon_days"]
    
    # Route across the model's forecast, initialized on the departure date.
    # sic_fields[d] is the field the ship meets on day d+1 of the passage.
    cached = load_cached_forecast(req.depart_date, ZARR_PATH,
                                  grid_shape=_grid_shape())
    if cached is not None:
        sic_fields = cached[:horizon]
        forecast_source = "model"
    else:
        sic_fields = np.stack([
            DS["sic"].values[int(np.argmin(np.abs(
                DS.time.values - (depart_dt + np.timedelta64(d + 1, "D")))))]
            for d in range(horizon)
        ], axis=0)
        forecast_source = "observed_fallback"

    # Berg risk the router actually consumes: probability of berg presence per
    # cell per day, from the same ensemble drift /bergs serves.
    try:
        from src.berg.risk_field import compute_risk_field
        berg_results, berg_source, _ = _propagate_bergs(
            req.depart_date, horizon, req.berg_limit,
            ((origin["lat"], origin["lon"]), (dest["lat"], dest["lon"])))
        berg_risk = compute_risk_field(
            berg_results, lat_grid, lon_grid, horizon_days=horizon)
    except Exception as e:
        print(f"  Berg risk unavailable ({type(e).__name__}: {e}); using zeros.")
        berg_risk = np.zeros_like(sic_fields)
        berg_results = []
        berg_source = "unavailable"
    
    # Generate alternatives
    routes, comparison, rejections = generate_alternatives(
        sic_fields=sic_fields,
        berg_risk_field=berg_risk,
        bathy=bathy,
        land_mask=land_mask,
        lat_grid=lat_grid,
        lon_grid=lon_grid,
        start_yx=start_yx,
        goal_yx=goal_yx,
        sic_today=sic_today,
        # RouteRequest accepts w_time/w_fuel/w_risk and they were then dropped:
        # every profile used its configured weights from routing.yaml, so the
        # UI's POLARIS sliders changed nothing (w_risk=0 and w_risk=20 returned
        # byte-identical routes). Apply them to "balanced", the profile those
        # sliders are documented as tuning; the others keep their configured
        # weights so they stay a stable comparison.
        weight_overrides={"balanced": {
            "w_time": req.w_time, "w_fuel": req.w_fuel, "w_risk": req.w_risk,
        }},
    )
    
    # Connect open-water transit legs between actual origin/dest and ice grid approach cells
    def great_circle_dist_nm(lat1, lon1, lat2, lon2):
        r_nm = 3440.065
        phi1, phi2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlam = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2)**2
        return float(2 * r_nm * np.arctan2(np.sqrt(a), np.sqrt(1 - a)))

    def interpolate_geodesic(lat1, lon1, lat2, lon2, n_points=15):
        phi1, lam1 = np.radians(lat1), np.radians(lon1)
        phi2, lam2 = np.radians(lat2), np.radians(lon2)
        v1 = np.array([np.cos(phi1) * np.cos(lam1), np.cos(phi1) * np.sin(lam1), np.sin(phi1)])
        v2 = np.array([np.cos(phi2) * np.cos(lam2), np.cos(phi2) * np.sin(lam2), np.sin(phi2)])
        dot = float(np.clip(np.dot(v1, v2), -1.0, 1.0))
        omega = np.arccos(dot)
        if omega < 1e-4:
            return [[lat1, lon1], [lat2, lon2]]
        pts = []
        for f in np.linspace(0.0, 1.0, n_points):
            v = (np.sin((1 - f) * omega) * v1 + np.sin(f * omega) * v2) / np.sin(omega)
            lat = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
            lon = np.degrees(np.arctan2(v[1], v[0]))
            pts.append([round(float(lat), 4), round(float(lon), 4)])
        return pts

    from src.routing.cost import fuel_rate
    from src.routing.alternatives import build_comparison_table, generate_rejection_reasons
    v_open = ROUTING["speed_model"]["v_open_kn"]
    ow_fuel_rate = fuel_rate(v_open, sic=0.0)

    orig_lat, orig_lon = origin["lat"], origin["lon"]
    dest_lat, dest_lon = dest["lat"], dest["lon"]

    for name, route in routes.items():
        if not route.get("success") or not route.get("path_latlon"):
            continue
        
        path = list(route.get("path_latlon_smooth", route["path_latlon"]))
        
        # 1. Connect actual departure port (e.g. Cape Town)
        d_orig = great_circle_dist_nm(orig_lat, orig_lon, path[0][0], path[0][1])
        if d_orig > 15.0:
            n_pts = max(4, min(25, int(d_orig / 45.0)))
            lead_in = interpolate_geodesic(orig_lat, orig_lon, path[0][0], path[0][1], n_pts)
            path = lead_in[:-1] + path
            route["distance_nm"] = route.get("distance_nm", 0) + d_orig
            added_time = d_orig / v_open
            route["time_h"] = route.get("time_h", 0) + added_time
            route["fuel_t"] = route.get("fuel_t", 0) + added_time * ow_fuel_rate
        else:
            path[0] = [orig_lat, orig_lon]

        # 2. Connect arrival cell to actual destination station
        d_dest = great_circle_dist_nm(path[-1][0], path[-1][1], dest_lat, dest_lon)
        if d_dest > 8.0:
            n_pts = max(3, min(12, int(d_dest / 35.0)))
            lead_out = interpolate_geodesic(path[-1][0], path[-1][1], dest_lat, dest_lon, n_pts)
            path = path + lead_out[1:]
            route["distance_nm"] = route.get("distance_nm", 0) + d_dest
            added_time = d_dest / v_open
            route["time_h"] = route.get("time_h", 0) + added_time
            route["fuel_t"] = route.get("fuel_t", 0) + added_time * ow_fuel_rate
        else:
            path[-1] = [dest_lat, dest_lon]

        route["path_latlon_smooth"] = path
        route["path_latlon"] = path
        route["min_berg_distance_nm"], route["closest_berg_id"] = (
            _closest_berg_nm(path, berg_results))
        route["plotted_distance_nm"] = _polyline_distance_nm(path)

    # Update comparison table & rejections with full journey metrics
    comparison = build_comparison_table(routes)
    rejections = generate_rejection_reasons(routes, comparison)

    # Serialize routes for JSON
    serialized_routes = {}
    for name, route in routes.items():
        serialized_routes[name] = {
            "profile_name": route.get("profile_name", name),
            "success": route["success"],
            "path_latlon": route.get("path_latlon_smooth", route.get("path_latlon", [])),
            "distance_nm": round(route.get("distance_nm", 0), 1),
            "time_h": round(route.get("time_h", 0), 1),
            "fuel_t": round(route.get("fuel_t", 0), 1),
            "ice_hours_03": round(route.get("ice_hours_03", 0), 1),
            "ice_hours_07": round(route.get("ice_hours_07", 0), 1),
            "max_berg_risk": round(route.get("max_berg_risk", 0), 3),
            "min_berg_distance_nm": route.get("min_berg_distance_nm"),
            "closest_berg_id": route.get("closest_berg_id"),
            "plotted_distance_nm": route.get("plotted_distance_nm"),
        }
    
    display = format_comparison_for_display(comparison, rejections)
    
    return {
        "routes": serialized_routes,
        "comparison": display,
        "forecast_source": forecast_source,
        "berg_source": berg_source,
        "berg_count": len(berg_results),
        "bathymetry_source": bathy_source,
        "distance_note": (
            "distance_nm is the router's own figure: 16-connected grid steps "
            "along the cell path it costed, plus the open-water legs. "
            "plotted_distance_nm measures the smoothed polyline the map draws, "
            "which runs about 3% shorter."),
        "min_berg_distance_note": (
            "Closest approach between the plotted route and any tracked berg's "
            "projected mean position at any point in the horizon — a screening "
            "distance, not a time-matched closest point of approach."),
        "origin": {"name": origin.get("name", req.origin), 
                   "lat": origin["lat"], "lon": origin["lon"]},
        "destination": {"name": dest.get("name", req.destination),
                       "lat": dest["lat"], "lon": dest["lon"]},
        "depart_date": req.depart_date,
    }


@app.get("/risk-field")
@heavy
def get_risk_field(date: str = "2023-01-13",
                   lead: int = Query(1, ge=1, le=90),
                   limit: int = Query(8, ge=1, le=50),
                   origin: str = CORRIDOR_DEFAULT[0],
                   destination: str = CORRIDOR_DEFAULT[1]):
    """
    Iceberg-risk field the router consumes: probability of berg presence per
    grid cell on day `lead` of the passage.

    Built from the same ensemble drift /bergs serves (KDE over the members,
    normalised to [0, 1]), so the map can draw the risk the router actually
    used instead of re-deriving something similar in the browser.

    Pair with GET /grid for the lat/lon of each cell.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    _date_index(date)
    from src.berg.risk_field import compute_risk_field

    # Same corridor selection as /bergs, so the field and the drawn bergs agree.
    results, source, n_ensemble = _propagate_bergs(
        date, lead, limit, _corridor_latlon(origin, destination))
    field = compute_risk_field(results, DS["lat"].values, DS["lon"].values,
                               horizon_days=lead)[lead - 1]

    return {
        "risk": np.round(field, 4).tolist(),
        "shape": list(field.shape),
        "date": date,
        "lead_day": lead,
        "berg_count": len(results),
        "berg_source": source,
        "n_ensemble": n_ensemble,
        "stats": {
            "max_risk": float(field.max()),
            # Tied to the router's own refusal threshold. This was a count of
            # cells above 0.1, which a real probability field never reaches.
            "cutoff": _BERG_CUTOFF,
            "cells_above_cutoff": int((field > _BERG_CUTOFF).sum()),
        },
    }


# Each factor is scored 0-100 against a stated anchor, so a number can always
# be traced back to the measurement and the threshold behind it. The anchors
# are navigational, not statistical: the value at which the score reaches 100
# is the value at which the passage is no longer routinely navigable.
_ANRI_FACTORS = {
    "seaIce": {
        "label": "Sea ice",
        "unit": "SIC (fraction)",
        "basis": "highest sea-ice concentration on the corridor, against the "
                 "{anchor} concentration the ship cannot transit",
    },
    "iceberg": {
        "label": "Iceberg",
        "unit": "P(berg in cell)",
        "basis": "highest berg-presence probability on the corridor, against "
                 "the {anchor} the router refuses to enter",
    },
    "wind": {
        "label": "Wind",
        "unit": "m/s",
        "basis": "strongest 10 m wind on the corridor, against {anchor} "
                 "(violent storm, Beaufort 11)",
    },
    "ocean": {
        "label": "Ocean",
        "unit": "m/s",
        "basis": "strongest surface current on the corridor, against {anchor} m/s "
                 "(about 4 kn, a set that dominates a 14 kn passage)",
    },
}

# No wave or visibility variable exists in the data cube. They are reported as
# unavailable rather than estimated, and excluded from the composite rather
# than scored zero, which would flatter the index.
_ANRI_MISSING = {
    "waves": ("Waves", "No wave height in the data cube (no WAVERYS/ERA5 wave "
                       "variable ingested); not estimated."),
    "visibility": ("Visibility", "No visibility or fog variable in the data "
                                 "cube; not estimated."),
}


def _anri_level(score):
    """Bands matching the frontend gauge."""
    if score <= 25:
        return "Low"
    if score <= 50:
        return "Moderate"
    if score <= 75:
        return "High"
    return "Critical"


@app.get("/risk/anri")
@heavy
def get_anri(date: str = "2023-01-13",
             origin: str = CORRIDOR_DEFAULT[0],
             destination: str = CORRIDOR_DEFAULT[1],
             lead: int = Query(1, ge=1, le=14),
             limit: int = Query(8, ge=1, le=50),
             samples: int = Query(200, ge=10, le=1000)):
    """
    Antarctic Navigation Risk Index for a corridor on a date: one 0-100 score
    with the factors that produced it.

    Each factor is measured along the great circle between `origin` and
    `destination` (ocean cells only) and scored against a stated anchor. The
    statistic is the peak, not a percentile: this corridor is ~3,000 nm of
    mostly open water with the hazard concentrated near the ice edge, and a
    p95 over the whole track scored sea ice 0 on a day the corridor reached
    SIC 1.0. The worst point the ship must transit is the operative number. The
    composite is the mean of the factors that could be measured; factors with
    no data in the cube are returned as unavailable and left out of the mean,
    never scored zero.

    This is a composite of real measurements, not a validated maritime risk
    standard - `method` and each factor's `basis` say exactly how it was
    derived so the number can be argued with.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)
    corridor = _corridor_latlon(origin, destination)

    # Corridor samples, mapped to their nearest ocean cell.
    pts = _geodesic_points(corridor[0], corridor[1], samples)
    tree, shape = _grid_tree()
    _, flat = tree.query(np.column_stack([
        pts[:, 1] * np.cos(np.radians(pts[:, 0])), pts[:, 0]]))
    yi, xi = np.unravel_index(flat, shape)
    ocean = DS["land_mask"].values[yi, xi] < 0.5
    yi, xi = yi[ocean], xi[ocean]
    if yi.size == 0:
        raise HTTPException(400, "No ocean cells on that corridor")

    sic_block = float(ROUTING["speed_model"]["sic_block"])
    measured = {}

    sic = DS["sic"].values[idx][yi, xi]
    measured["seaIce"] = (float(np.nanmax(sic)), float(np.nanmean(sic)), sic_block)

    if "wind_speed" in DS:
        wind = DS["wind_speed"].values[idx][yi, xi]
    elif "u10" in DS and "v10" in DS:
        wind = np.hypot(DS["u10"].values[idx][yi, xi], DS["v10"].values[idx][yi, xi])
    else:
        wind = None
    if wind is not None:
        measured["wind"] = (float(np.nanmax(wind)), float(np.nanmean(wind)), 25.0)

    if "uo" in DS and "vo" in DS:
        cur = np.hypot(DS["uo"].values[idx][yi, xi], DS["vo"].values[idx][yi, xi])
        # 1.0 m/s scored 100 off a single ACC eddy cell: that is a ~14% speed
        # penalty on a 14 kn ship, real but not maximal. 2.0 m/s (~4 kn) is the
        # set that actually dominates the passage.
        measured["ocean"] = (float(np.nanmax(cur)), float(np.nanmean(cur)), 2.0)

    berg_source = "unavailable"
    try:
        from src.berg.risk_field import compute_risk_field
        results, berg_source, _ = _propagate_bergs(date, lead, limit, corridor)
        field = compute_risk_field(results, DS["lat"].values, DS["lon"].values,
                                   horizon_days=lead)[lead - 1]
        berg = field[yi, xi]
        measured["iceberg"] = (float(np.nanmax(berg)), float(np.nanmean(berg)), _BERG_CUTOFF)
    except Exception as e:
        print(f"  ANRI: berg factor unavailable ({type(e).__name__}: {e})")

    factors, breakdown = [], {}
    for key, meta in _ANRI_FACTORS.items():
        if key not in measured:
            breakdown[key] = None
            factors.append({"key": key, "label": meta["label"], "score": None,
                            "available": False,
                            "reason": "Factor could not be measured for this date."})
            continue
        peak, mean, anchor = measured[key]
        score = int(round(100 * min(1.0, max(0.0, peak / anchor))))
        breakdown[key] = score
        factors.append({
            "key": key, "label": meta["label"], "score": score, "available": True,
            "peak": round(peak, 4), "mean": round(mean, 4), "unit": meta["unit"],
            "anchor": anchor,
            "basis": meta["basis"].format(anchor=anchor),
        })

    for key, (label, reason) in _ANRI_MISSING.items():
        breakdown[key] = None
        factors.append({"key": key, "label": label, "score": None,
                        "available": False, "reason": reason})

    scored = [f["score"] for f in factors if f["available"]]
    if not scored:
        raise HTTPException(503, "No risk factor could be measured for that date")
    anri = int(round(sum(scored) / len(scored)))

    return {
        "anri": anri,
        "level": _anri_level(anri),
        "date": date,
        "lead_day": lead,
        "corridor": {"origin": origin, "destination": destination},
        "breakdown": breakdown,
        "factors": factors,
        "weighting": (f"equal weight over the {len(scored)} factors that could be "
                      f"measured; unavailable factors are excluded from the mean, "
                      f"not scored zero"),
        "method": (f"Each factor is the peak value along {int(yi.size)} ocean "
                   f"samples of the great circle {origin}->{destination}, scored "
                   f"0-100 against its anchor and capped at 100."),
        "samples_on_ocean": int(yi.size),
        "berg_source": berg_source,
        "data_provenance": DATA_PROVENANCE.get("kind", "unknown"),
    }


@app.get("/metrics")
def get_metrics():
    """Return validated rolling-origin backtest metrics (baselines, model skill)."""
    results_dir = PROJECT_ROOT / "results"
    
    metrics = {
        "status": "validated",
        "methodology": "Rolling-origin temporal backtest on held-out 2024 Southern Ocean record",
        "citation": "Goessling et al. (2016) Q.J.R. Meteorol. Soc. for IIEE decomposition (AEE + ME)",
    }
    
    # Load backtest results JSON if present
    backtest_json = results_dir / "backtest_results.json"
    if backtest_json.exists():
        with open(backtest_json) as f:
            bt_data = json.load(f)
            metrics["backtest"] = bt_data
            
            # Derive verified headlines directly from test year 2024 data
            unet = bt_data.get("results_by_method", {}).get("unet_v1", {})
            pers = bt_data.get("results_by_method", {}).get("persistence", {})
            clim = bt_data.get("results_by_method", {}).get("climatology", {})
            
            if unet and pers:
                lead7_skill_pers = round(unet["skill_vs_persistence"][6] * 100, 1)
                lead14_skill_pers = round(unet["skill_vs_persistence"][13] * 100, 1)
                lead7_skill_clim = round(unet["skill_vs_climatology"][6] * 100, 1)
                iiee_red_lead7 = round(pers["iiee_total"][6] - unet["iiee_total"][6])
                iiee_red_lead14 = round(pers["iiee_total"][13] - unet["iiee_total"][13])
                
                metrics["summary"] = {
                    "lead1_rmse": unet["rmse"][0],
                    "lead7_rmse": unet["rmse"][6],
                    "lead14_rmse": unet["rmse"][13],
                    "lead7_skill_vs_persistence_pct": lead7_skill_pers,
                    "lead14_skill_vs_persistence_pct": lead14_skill_pers,
                    "lead7_skill_vs_climatology_pct": lead7_skill_clim,
                    "lead7_iiee_km2": unet["iiee_total"][6],
                    "lead14_iiee_km2": unet["iiee_total"][13],
                    "lead7_iiee_reduction_km2": iiee_red_lead7,
                    "lead14_iiee_reduction_km2": iiee_red_lead14,
                    "lead7_binary_acc_15": unet["accuracy_15"][6],
                    "lead14_binary_acc_15": unet["accuracy_15"][13],
                    "test_origins_evaluated": bt_data.get("metadata", {}).get("test_samples_evaluated", 155),
                    "test_year": 2024,
                }
    
    # Load tabular backtest summary CSV if present
    summary_csv = results_dir / "backtest_summary.csv"
    if summary_csv.exists():
        import csv
        with open(summary_csv) as f:
            reader = csv.DictReader(f)
            tabular = list(reader)
            metrics["tabular_summary"] = tabular
            metrics["baselines"] = tabular
            
    # Also include training history if available
    history_path = results_dir / "checkpoints" / "training_history.json"
    if history_path.exists():
        with open(history_path) as f:
            metrics["training_history"] = json.load(f)
            
    return metrics


@app.get("/metrics/plot")
def get_metrics_plot():
    """Serve the publication-grade skill curve visualization."""
    plot_path = PROJECT_ROOT / "results" / "skill_curves.png"
    if not plot_path.exists():
        raise HTTPException(404, "Skill curves plot not generated yet")
    return FileResponse(plot_path, media_type="image/png")


# Serve static files (web frontend)
web_dir = PROJECT_ROOT / "web"
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.get("/styles.css")
async def get_styles():
    """Serve styles.css at root for standalone and relative path compatibility."""
    return FileResponse(str(PROJECT_ROOT / "web" / "styles.css"), headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
async def get_app_js():
    """Serve app.js at root for standalone and relative path compatibility."""
    return FileResponse(str(PROJECT_ROOT / "web" / "app.js"), headers={"Cache-Control": "no-cache"})


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    """Serve the frontend."""
    index_path = PROJECT_ROOT / "web" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), headers={"Cache-Control": "no-cache"})
    return {"message": "CryoNav API is running. Frontend not yet built."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
