"""
CryoNav — Iceberg risk field computation.

Generates a normalised probability-of-presence per grid cell per day
using kernel density estimation from ensemble drift tracks.
This is the deliverable the router consumes.
"""
import numpy as np
from scipy.ndimage import gaussian_filter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import DOMAIN


from scipy.spatial import cKDTree

_GRID_KDTREE_CACHE = {}

def _get_kdtree(lat_grid, lon_grid):
    shape = lat_grid.shape
    key = (shape, float(lat_grid[0, 0]), float(lon_grid[0, 0]))
    if key not in _GRID_KDTREE_CACHE:
        coords = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
        _GRID_KDTREE_CACHE[key] = (cKDTree(coords), shape)
    return _GRID_KDTREE_CACHE[key]


def compute_risk_field(ensemble_tracks, lat_grid, lon_grid,
                       horizon_days=14, sigma_km=50.0):
    """
    Probability of berg presence per cell per day, from the drift ensemble.

    Each berg's ensemble is a sample of where that berg might be, so the
    fraction of its members landing in a cell - smoothed with a Gaussian KDE,
    which conserves total mass - estimates P(that berg is in the cell). The
    bergs are separate samples, so they combine as 1 - prod(1 - p), which
    stays inside [0, 1].

    This used to divide each berg-day field by its own maximum, so every berg
    peaked at exactly 1.0 however widely its ensemble was spread, and the sum
    over bergs was renormalised again per day. That produced a relative
    density, not a probability, while cell_cost compared it against a cutoff
    documented as one: a berg 1,500 nm off the track and a berg sitting on it
    both read 1.0 at their centres. Once bergs were selected for being near
    the corridor, that mis-scaling sealed the destination approach and every
    route came back infeasible.

    Args:
        ensemble_tracks: list of dicts from propagate(), each with 'ensemble'
        lat_grid: (ny, nx) latitude grid
        lon_grid: (ny, nx) longitude grid
        horizon_days: number of forecast days
        sigma_km: KDE bandwidth in km (converted to grid cells)

    Returns:
        risk_field: (horizon_days, ny, nx), the probability in [0, 1] that at
        least one tracked berg is in the cell on that day.
    """
    ny, nx = lat_grid.shape
    cell_size_km = 25.0  # from config
    sigma_cells = sigma_km / cell_size_km

    if not ensemble_tracks:
        return np.zeros((horizon_days, ny, nx), dtype=np.float32)

    tree, _ = _get_kdtree(lat_grid, lon_grid)

    # P(no berg here), multiplied through berg by berg.
    clear = np.ones((horizon_days, ny, nx), dtype=np.float32)

    for berg_result in ensemble_tracks:
        ensemble = berg_result["ensemble"]  # (n_ens, n_days+1, 2)
        n_ens = ensemble.shape[0]
        if n_ens == 0:
            continue
        max_days = min(horizon_days, ensemble.shape[1] - 1)

        for day in range(max_days):
            counts = np.zeros((ny, nx), dtype=np.float32)
            pts = ensemble[:, day + 1, :2]  # (n_ens, 2)

            _, flat_indices = tree.query(pts)
            yis, xis = np.unravel_index(flat_indices, (ny, nx))
            np.add.at(counts, (yis, xis), 1.0)

            if counts.sum() <= 0:
                continue

            # Smoothing conserves mass, so dividing by the member count leaves
            # a probability per cell rather than an arbitrary density.
            pr = gaussian_filter(counts, sigma=sigma_cells) / float(n_ens)
            np.clip(pr, 0.0, 1.0, out=pr)
            clear[day] *= (1.0 - pr)

    return (1.0 - clear).astype(np.float32)


def generate_synthetic_bergs_for_demo(n_bergs=5, rng=None):
    """
    Generate synthetic berg positions and tracks for demo purposes.
    Returns list of berg info dicts suitable for propagation.
    """
    if rng is None:
        rng = np.random.default_rng(42)
    
    bergs = []
    for i in range(n_bergs):
        bergs.append({
            "berg_id": f"BERG_{i+1:03d}",
            "lat": rng.uniform(-72, -63),
            "lon": rng.uniform(0, 90),
            "length_m": rng.uniform(500, 3000),
            "width_m": rng.uniform(300, 1500),
        })
    
    return bergs
