"""
CryoNav — Sea-ice forecast inference and prediction.

Loads trained checkpoint and produces 14-day SIC forecasts.

Forecast cache convention (single source of truth for the API, the demo and
the router): forecast_<init_date>.npy holds (H, ny, nx), where entry [i] is
valid at init_date + (i + 1) days. The model saw observed data up to and
including init_date, and nothing after.
"""
import torch
import numpy as np
import xarray as xr
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import DOMAIN, MODEL, get_project_root
from src.ice.models import build_model
from src.ice.dataset import SeaIceDataset


def load_model(checkpoint_path: str = None, device=None):
    """Load trained model from checkpoint."""
    if device is None:
        if torch.cuda.is_available():
            device = torch.device("cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = torch.device("mps")
        else:
            device = torch.device("cpu")
    
    if checkpoint_path is None:
        checkpoint_path = str(Path(__file__).resolve().parent.parent.parent / 
                             "results" / "checkpoints" / "best_model.pt")
    
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    
    in_channels = ckpt.get("in_channels", 94)
    model = build_model(in_channels=in_channels)
    model.load_state_dict(ckpt["model_state_dict"])
    model = model.to(device)
    model.eval()
    
    print(f"Loaded model from {checkpoint_path} (epoch {ckpt.get('epoch', '?')}, "
          f"val_loss={ckpt.get('val_loss', '?'):.6f})")
    
    return model, device


CACHE_DIRNAME = "demo_cache"


def cache_dir(zarr_path: str = None) -> Path:
    """Directory holding cached model forecasts."""
    if zarr_path is None:
        zarr_path = str(get_project_root() / DOMAIN["paths"]["zarr_cube"])
    return Path(zarr_path).parent / CACHE_DIRNAME


def cache_path(init_date: str, zarr_path: str = None) -> Path:
    """
    Path of the cached forecast initialized on `init_date`.

    Convention, used by every consumer (API, demo, router):
      forecast_<init_date>.npy has shape (H, ny, nx) and entry [i] is the
      forecast valid at init_date + (i + 1) days. The model has seen observed
      data up to and including init_date, and nothing after it.
    """
    return cache_dir(zarr_path) / f"forecast_{init_date}.npy"


def load_cached_forecast(init_date: str, zarr_path: str = None, grid_shape=None):
    """
    Return the cached (H, ny, nx) forecast for `init_date`, or None.

    `grid_shape` is the (ny, nx) of the cube the caller intends to use it with.
    A cache written against a different grid — the real 264x220 cube's forecasts
    loaded next to a synthetic 269x269 cube, say — is silently wrong rather than
    merely stale, so it is rejected here and the caller falls back to observed.
    """
    path = cache_path(init_date, zarr_path)
    if not path.exists():
        return None
    arr = np.load(path)
    if grid_shape is not None and tuple(arr.shape[1:]) != tuple(grid_shape):
        print(f"Ignoring cached forecast {path.name}: grid {arr.shape[1:]} "
              f"does not match the loaded cube {tuple(grid_shape)}.")
        return None
    return arr


def lead_index(init_date: str, valid_date: str) -> int:
    """
    Index into a cached forecast for the field valid at `valid_date`.

    Returns -1 if valid_date is not covered (same day as init, or beyond the
    forecast horizon).
    """
    delta = int((np.datetime64(valid_date) - np.datetime64(init_date))
                / np.timedelta64(1, "D"))
    return delta - 1 if delta >= 1 else -1


def predict_from_init(model, device, zarr_path: str, init_date: str,
                      input_window: int = None) -> np.ndarray:
    """
    Forecast forward from `init_date`.

    The model is shown the `input_window` days ending on init_date inclusive,
    and nothing after. Returns (H, ny, nx) where [i] is valid at
    init_date + (i + 1) days.
    """
    if input_window is None:
        input_window = DOMAIN["time"]["input_window_days"]

    ds = xr.open_zarr(zarr_path)
    times = ds.time.values
    init_dt = np.datetime64(init_date)

    idx = int(np.argmin(np.abs(times - init_dt)))
    actual = np.datetime64(times[idx], "D")
    if actual != np.datetime64(init_date, "D"):
        raise ValueError(f"{init_date} is not in the cube (nearest: {actual})")
    if idx < input_window - 1:
        raise ValueError(f"Not enough history before {init_date}")

    sample = _build_sample(ds, idx, input_window)

    with torch.no_grad():
        inputs = sample["input"].unsqueeze(0).to(device)
        pred = model(inputs).squeeze(0).cpu().numpy()

    return pred


def _build_sample(ds, t_idx, K):
    """
    Build one model input from the cube, matching SeaIceDataset's channel order.

    t_idx is the index of the last observed day; channels run t_idx-K+1..t_idx.
    """
    norm = SeaIceDataset._normalize
    channels = []

    for t in range(t_idx - K + 1, t_idx + 1):
        sic = ds["sic"].values[t]
        channels.append(norm(sic, "sic"))

        for var in SeaIceDataset.DRIVER_VARS:
            channels.append(norm(ds[var].values[t], var))

        for var in SeaIceDataset.DERIVED_VARS:
            channels.append(norm(ds[var].values[t], var))

        channels.append(np.full_like(sic, ds["sin_doy"].values[t]))
        channels.append(np.full_like(sic, ds["cos_doy"].values[t]))

    for var in SeaIceDataset.STATIC_VARS:
        channels.append(norm(ds[var].values, var))

    return {
        "input": torch.from_numpy(np.stack(channels, axis=0).astype(np.float32)),
        "mask": torch.from_numpy(ds["sic_mask"].values.astype(np.float32)),
    }


def demo_init_dates() -> list:
    """
    Init dates the demo and web UI need cached.

    A demo date is the date the story verifies against; the model is
    initialized input_window_days earlier so it has genuinely seen nothing
    in between.
    """
    lead = DOMAIN["time"]["input_window_days"]
    return [str(np.datetime64(d) - np.timedelta64(lead, "D"))
            for d in DOMAIN.get("held_out_demo_dates", [])]


def cache_predictions(init_dates=None, model=None, device=None, zarr_path=None):
    """Precompute and cache forecasts for the given init dates."""
    if zarr_path is None:
        zarr_path = str(get_project_root() / DOMAIN["paths"]["zarr_cube"])
    if init_dates is None:
        init_dates = demo_init_dates()
    if model is None:
        model, device = load_model()

    out_dir = cache_dir(zarr_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok, failed = [], []
    for init_date in init_dates:
        try:
            pred = predict_from_init(model, device, zarr_path, init_date)
            np.save(cache_path(init_date, zarr_path), pred)
            valid_last = np.datetime64(init_date) + np.timedelta64(len(pred), "D")
            print(f"  {init_date} -> shape={pred.shape}, "
                  f"valid through {valid_last}, "
                  f"range=[{pred.min():.3f}, {pred.max():.3f}]")
            ok.append(init_date)
        except Exception as e:
            print(f"  {init_date} FAILED: {type(e).__name__}: {e}")
            failed.append(init_date)

    print(f"\nCache: {out_dir}\n  {len(ok)} written, {len(failed)} failed")
    return ok, failed


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Cache U-Net forecasts. Each file is keyed by its init "
                    "date -- the last day of observed data the model saw.")
    ap.add_argument("--dates", nargs="*", default=None,
                    help="Init dates (YYYY-MM-DD). Default: the dates the demo "
                         f"needs, {demo_init_dates()}")
    args = ap.parse_args()

    cache_predictions(init_dates=args.dates)
