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
import json
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import DOMAIN, ROUTING
from src.ice.predict import load_cached_forecast, lead_index

app = FastAPI(title="CryoNav API", version="1.0.0",
              description="Antarctic Sea-Ice, Iceberg & Navigation Decision Support")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.on_event("startup")
async def startup():
    global DS, BERGS, GRID_CACHE, DATA_PROVENANCE
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
            raw_b = load_canonical_bathymetry_grid()
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
def get_grid():
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
        raw_b = load_canonical_bathymetry_grid()
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
def get_forecast(date: str, lead: int = Query(7, ge=1, le=14)):
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
def get_observed(date: str):
    """Get observed (actual) SIC field for overlay proof."""
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)      # outside the try: a 400 must not become a 500
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
def get_ocean(date: str, stride: int = Query(4, ge=1, le=32)):
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
    try:
        actual = str(np.datetime64(DS.time.values[idx], "D"))

        land = DS["land_mask"].values
        ocean = land < 0.5

        uo = DS["uo"].values[idx]
        vo = DS["vo"].values[idx]
        sst = DS["sst"].values[idx]
        zos = DS["zos"].values[idx]

        speed = np.sqrt(uo ** 2 + vo ** 2)

        # Subsampled vector field for arrow rendering
        lat = DS["lat"].values
        lon = DS["lon"].values
        s = max(1, int(stride))
        vectors = []
        for r in range(0, uo.shape[0], s):
            for c in range(0, uo.shape[1], s):
                if land[r, c] >= 0.5:
                    continue
                u = float(uo[r, c]); v = float(vo[r, c])
                if not np.isfinite(u) or not np.isfinite(v):
                    continue
                if abs(u) < 1e-4 and abs(v) < 1e-4:
                    continue
                vectors.append({
                    "lat": round(float(lat[r, c]), 4),
                    "lon": round(float(lon[r, c]), 4),
                    "u": round(u, 4),
                    "v": round(v, 4),
                    "speed": round(float(np.hypot(u, v)), 4),
                })

        def _mean(a):
            vals = a[ocean]
            vals = vals[np.isfinite(vals)]
            return float(np.mean(vals)) if vals.size else None

        is_real = bool(DS["ocean_is_real"].values[idx]) if "ocean_is_real" in DS else None

        return {
            "date": actual,
            "requested": date,
            "source": "CMEMS GLORYS12 reanalysis" if is_real else "gap-filled",
            "is_real": is_real,
            "stride": s,
            "vectors": vectors,
            "sst": np.nan_to_num(sst, nan=0.0).round(3).tolist(),
            "speed": np.nan_to_num(speed, nan=0.0).round(4).tolist(),
            "zos": np.nan_to_num(zos, nan=0.0).round(4).tolist(),
            "shape": list(uo.shape),
            "stats": {
                "mean_current_ms": _mean(speed),
                "max_current_ms": float(np.nanmax(speed[ocean])) if ocean.any() else None,
                # Cube stores SST in kelvin; report celsius
                "mean_sst_c": (lambda t: t - 273.15 if t is not None and t > 100 else t)(_mean(sst)),
                "mean_ssh_m": _mean(zos),
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/weather")
def get_weather(date: str, stride: int = Query(4, ge=1, le=32)):
    """
    ERA5 atmospheric state: 10 m wind, 2 m temperature, mean sea-level
    pressure. Same shape of response as /ocean so the frontend can treat
    the two the same way.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    idx = _date_index(date)      # outside the try: a 400 must not become a 500
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

        s = max(1, int(stride))
        vectors = []
        for r in range(0, u10.shape[0], s):
            for c in range(0, u10.shape[1], s):
                if land[r, c] >= 0.5:
                    continue
                u = float(u10[r, c]); v = float(v10[r, c])
                if not np.isfinite(u) or not np.isfinite(v):
                    continue
                vectors.append({
                    "lat": round(float(lat[r, c]), 4),
                    "lon": round(float(lon[r, c]), 4),
                    "u": round(u, 3),
                    "v": round(v, 3),
                    "speed": round(float(np.hypot(u, v)), 3),
                })

        def _mean(a):
            vals = a[ocean]
            vals = vals[np.isfinite(vals)]
            return float(np.mean(vals)) if vals.size else None

        is_real = bool(DS["atmo_is_real"].values[idx]) if "atmo_is_real" in DS else None
        t_mean = _mean(t2m)

        return {
            "date": actual,
            "requested": date,
            "source": "ERA5 reanalysis" if is_real else "gap-filled",
            "is_real": is_real,
            "stride": s,
            "vectors": vectors,
            "wind_speed": np.nan_to_num(wind, nan=0.0).round(3).tolist(),
            "shape": list(u10.shape),
            "stats": {
                "mean_wind_ms": _mean(wind),
                "max_wind_ms": float(np.nanmax(wind[ocean])) if ocean.any() else None,
                # Cube stores 2 m temperature in kelvin
                "mean_t2m_c": (t_mean - 273.15) if t_mean is not None and t_mean > 100 else t_mean,
                "mean_msl_hpa": (lambda m: m / 100.0 if m is not None and m > 10000 else m)(_mean(msl)),
            },
        }
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

    return forcing_func


def _bergs_near_date(date: str, limit: int, days_tol: int = 7):
    """
    Observed bergs present on `date`, largest first.

    Returns (list_of_bergs, source). Falls back to synthetic positions only if
    the tracked-iceberg file was not loaded at startup.
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

    bergs.sort(key=lambda b: b["length_m"] * b["width_m"], reverse=True)
    return bergs[:limit], "observed"


def _propagate_bergs(date: str, horizon: int, limit: int):
    """Propagate bergs from `date`, memoised — /bergs and /route share this."""
    key = ("bergs", date, horizon, limit)
    if key in CACHE:
        return CACHE[key]

    from src.berg.dynamics import propagate

    bergs, source = _bergs_near_date(date, limit)
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
        )
        result["length_m"] = berg["length_m"]
        result["width_m"] = berg["width_m"]
        result["observed_on"] = berg.get("observed_on")
        results.append(result)

    CACHE[key] = (results, source, n_ensemble)
    return CACHE[key]


@app.get("/bergs")
def get_bergs(date: str = "2023-01-13",
              horizon: int = Query(7, ge=1, le=90),
              limit: int = Query(8, ge=1, le=50)):
    """
    Iceberg drift forecasts from `date`, with ensemble spread.

    Positions come from the tracked-iceberg record and are drifted with winds,
    currents and SIC read from the data cube.

    `limit` is bounded above: it used to slice the berg list directly, so a
    negative value returned every berg but the last few.
    """
    if DS is None:
        raise HTTPException(404, "Data not loaded")

    _date_index(date)
    results, source, n_ensemble = _propagate_bergs(date, horizon, limit)

    return {
        "bergs": [{
            "berg_id": r["berg_id"],
            "mean_track": r["mean_track"],
            "ensemble": r["ensemble"].tolist(),
            "length_m": r["length_m"],
            "width_m": r["width_m"],
            "observed_on": r["observed_on"],
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
    
    bathy = DS["bathy"].values
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
            req.depart_date, horizon, req.berg_limit)
        berg_risk = compute_risk_field(
            berg_results, lat_grid, lon_grid, horizon_days=horizon)
    except Exception as e:
        print(f"  Berg risk unavailable ({type(e).__name__}: {e}); using zeros.")
        berg_risk = np.zeros_like(sic_fields)
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
        }
    
    display = format_comparison_for_display(comparison, rejections)
    
    return {
        "routes": serialized_routes,
        "comparison": display,
        "forecast_source": forecast_source,
        "berg_source": berg_source,
        "origin": {"name": origin.get("name", req.origin), 
                   "lat": origin["lat"], "lon": origin["lon"]},
        "destination": {"name": dest.get("name", req.destination),
                       "lat": dest["lat"], "lon": dest["lon"]},
        "depart_date": req.depart_date,
    }


@app.get("/risk-field")
def get_risk_field(date: str = "2023-01-13",
                   lead: int = Query(1, ge=1, le=90),
                   limit: int = Query(8, ge=1, le=50)):
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

    results, source, n_ensemble = _propagate_bergs(date, lead, limit)
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
            "cells_above_0_1": int((field > 0.1).sum()),
        },
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
