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
    Compute berg risk field from ensemble tracks.
    
    Args:
        ensemble_tracks: list of dicts from propagate(), each with 'ensemble' array
        lat_grid: (ny, nx) latitude grid
        lon_grid: (ny, nx) longitude grid
        horizon_days: number of forecast days
        sigma_km: KDE bandwidth in km (converted to grid cells)
    
    Returns:
        risk_field: (horizon_days, ny, nx) normalised probability of berg presence
    """
    ny, nx = lat_grid.shape
    cell_size_km = 25.0  # from config
    sigma_cells = sigma_km / cell_size_km
    
    risk = np.zeros((horizon_days, ny, nx), dtype=np.float32)
    if not ensemble_tracks:
        return risk

    tree, shape = _get_kdtree(lat_grid, lon_grid)
    
    for berg_result in ensemble_tracks:
        ensemble = berg_result["ensemble"]  # (n_ens, n_days+1, 2)
        n_ens = ensemble.shape[0]
        max_days = min(horizon_days, ensemble.shape[1] - 1)
        
        for day in range(max_days):
            day_field = np.zeros((ny, nx), dtype=np.float32)
            pts = ensemble[:, day + 1, :2]  # (n_ens, 2)
            
            _, flat_indices = tree.query(pts)
            yis, xis = np.unravel_index(flat_indices, (ny, nx))
            np.add.at(day_field, (yis, xis), 1.0)
            
            # Apply Gaussian KDE smoothing
            if day_field.sum() > 0:
                day_field = gaussian_filter(day_field, sigma=sigma_cells)
                m = day_field.max()
                if m > 0:
                    day_field /= m
            
            risk[day] += day_field
    
    # Normalize across all bergs
    for day in range(horizon_days):
        m = risk[day].max()
        if m > 0:
            risk[day] /= m
    
    return risk


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
