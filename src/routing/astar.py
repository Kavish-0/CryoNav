"""
CryoNav — Time-expanded A* routing over the forecast ice grid.

Key insight: a node is (cell, time_index). Moving to a neighbour advances 
time by the traversal duration, and the SIC field used is the FORECAST FIELD 
FOR THAT ARRIVAL DAY, not today's. This is the point of the whole system.

16-connected neighbourhood, great-circle heuristic (admissible).
String-pulling post-process for smooth tracks.
High-performance implementation with vectorized heuristic precomputation
and flat-array state tracking.
"""
import math
import heapq
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import ROUTING, DOMAIN
from src.routing.cost import speed_in_ice, fuel_rate, cell_cost

CFG_SPEED = ROUTING["speed_model"]
CFG_FUEL = ROUTING["fuel_model"]
CFG_CONSTRAINTS = ROUTING["constraints"]

# 16-connected neighbourhood (dy, dx) offsets
NEIGHBOURS_16 = [
    (-1, 0), (1, 0), (0, -1), (0, 1),           # 4-connected
    (-1, -1), (-1, 1), (1, -1), (1, 1),         # 8-connected diagonals
    (-2, -1), (-2, 1), (2, -1), (2, 1),         # knight moves
    (-1, -2), (-1, 2), (1, -2), (1, 2),         # knight moves
]

NEIGHBOURS_8 = [
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
]


def great_circle_heuristic(y1, x1, y2, x2, lat_grid, lon_grid, v_open_kn=14.0):
    """
    Great-circle distance to goal ÷ v_open — admissible heuristic for A*.
    Returns estimated time in hours.
    """
    lat1 = math.radians(float(lat_grid[y1, x1]))
    lon1 = math.radians(float(lon_grid[y1, x1]))
    lat2 = math.radians(float(lat_grid[y2, x2]))
    lon2 = math.radians(float(lon_grid[y2, x2]))
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat * 0.5)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon * 0.5)**2
    a = min(1.0, max(0.0, a))
    dist_nm = (6371.0 * 0.539957) * 2.0 * math.asin(math.sqrt(a))
    v = v_open_kn if v_open_kn else 14.0
    return dist_nm / v


def precompute_goal_distances(lat_grid, lon_grid, gy, gx):
    """Vectorized great-circle distance (nm) from every grid cell to the goal."""
    lat1 = np.radians(lat_grid)
    lon1 = np.radians(lon_grid)
    lat2 = math.radians(float(lat_grid[gy, gx]))
    lon2 = math.radians(float(lon_grid[gy, gx]))
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat * 0.5)**2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon * 0.5)**2
    dist_nm = (6371.0 * 0.539957) * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return dist_nm


def cell_distance_km(y1, x1, y2, x2, cell_size_km=25.0):
    """Distance between adjacent cells in km."""
    dy = abs(y2 - y1)
    dx = abs(x2 - x1)
    return math.sqrt(dy * dy + dx * dx) * cell_size_km


def astar_route(sic_fields, berg_risk_field, bathy, land_mask,
                lat_grid, lon_grid,
                start_yx, goal_yx,
                w_time=1.0, w_fuel=0.5, w_risk=2.0,
                v_open_kn=14.0, cell_size_km=25.0,
                max_iterations=500000, connectivity=16,
                ignore_ice=False):
    """
    Time-expanded A* pathfinding over the forecast ice grid.
    
    Args:
        sic_fields: (n_days, ny, nx) or (ny, nx) — forecast SIC for each day.
                    The router picks the field for the arrival day.
        berg_risk_field: (n_days, ny, nx) or (ny, nx) — berg probability
        bathy: (ny, nx) — bathymetry (negative = depth)
        land_mask: (ny, nx) — 1 = land
        lat_grid, lon_grid: (ny, nx) — coordinate grids
        start_yx: (y, x) start cell
        goal_yx: (y, x) goal cell
        w_time, w_fuel, w_risk: cost weights
        ignore_ice: if True, route ignores ice (for great-circle baseline)
        
    Returns:
        dict with path, metrics, and rejection info
    """
    ny, nx = land_mask.shape
    n_days = sic_fields.shape[0] if sic_fields.ndim == 3 else 1
    
    if connectivity == 16:
        neighbours = NEIGHBOURS_16
    else:
        neighbours = NEIGHBOURS_8
    
    sy, sx = start_yx
    gy, gx = goal_yx
    
    if sy == gy and sx == gx:
        return _build_result([(sy, sx)], 0.0, 0.0, 0.0, 0.0, 0.0,
                             lat_grid, lon_grid, cell_size_km, success=True, iterations=0)

    # Precompute static obstacle mask (land or depth shallower than 15m)
    min_depth = CFG_CONSTRAINTS.get("min_depth_m", 15.0)
    impassable = (land_mask > 0.5) | ((bathy > -min_depth) & (bathy != 0))

    # Precompute goal distance array via vectorized Haversine
    goal_dist_nm = precompute_goal_distances(lat_grid, lon_grid, gy, gx)

    # Calculate admissible heuristic cost multiplier:
    # In open water, fuel rate = a + b*v + c*v^3.
    # time_per_nm = 1.0 / v_open_kn
    # fuel_per_nm = fuel_rate / v_open_kn
    # Since speed in ice is <= v_open_kn and resistance increases, cost per nm is strictly >= min_cost_per_nm.
    v_open = v_open_kn if v_open_kn else CFG_SPEED["v_open_kn"]
    ow = CFG_FUEL["open_water_coeffs"]
    open_fuel_rate = max(ow["a"] + ow["b"] * v_open + ow["c"] * (v_open ** 3), 0.1)
    min_cost_per_nm = (w_time + w_fuel * open_fuel_rate) / v_open

    # Precompute neighbor offsets with distances in nautical miles
    neighbor_offsets = []
    for dy, dx in neighbours:
        dist_km = math.sqrt(dy * dy + dx * dx) * cell_size_km
        dist_nm = dist_km * 0.539957
        neighbor_offsets.append((dy, dx, dist_nm))

    # Flat 1D arrays for speed
    total_cells = ny * nx
    INF = float("inf")
    g_score = np.full(total_cells, INF, dtype=np.float64)
    time_tracker = np.zeros(total_cells, dtype=np.float64)
    fuel_tracker = np.zeros(total_cells, dtype=np.float64)
    ice03_tracker = np.zeros(total_cells, dtype=np.float64)
    ice07_tracker = np.zeros(total_cells, dtype=np.float64)
    max_berg_tracker = np.zeros(total_cells, dtype=np.float64)
    came_from = {}

    start_idx = sy * nx + sx
    goal_idx = gy * nx + gx
    g_score[start_idx] = 0.0

    # Priority queue: (f_score, tentative_g, counter, cy, cx)
    counter = 0
    h0 = float(goal_dist_nm[sy, sx]) * min_cost_per_nm
    open_set = [(h0, 0.0, counter, sy, sx)]

    iterations = 0
    sic_3d = (sic_fields.ndim == 3)
    berg_3d = (berg_risk_field is not None and berg_risk_field.ndim == 3)

    sic_block = CFG_SPEED.get("sic_block", 0.9)
    max_sic = CFG_CONSTRAINTS.get("max_sic_traversal", 0.9)
    berg_cutoff = CFG_CONSTRAINTS.get("berg_risk_cutoff", 0.3)
    p_exp = CFG_SPEED.get("power_exponent", 2.0)
    ice_res_coeff = CFG_FUEL.get("ice_resistance_coeff", 0.8)
    thickness_factor = CFG_FUEL.get("thickness_factor", 0.5)

    while open_set and iterations < max_iterations:
        iterations += 1
        f, cg, _, cy, cx = heapq.heappop(open_set)
        curr_idx = cy * nx + cx

        if curr_idx == goal_idx:
            # Reconstruct path
            path = [(cy, cx)]
            curr = curr_idx
            while curr in came_from:
                curr = came_from[curr]
                path.append((curr // nx, curr % nx))
            path.reverse()

            return _build_result(
                path,
                float(time_tracker[curr_idx]),
                float(fuel_tracker[curr_idx]),
                float(ice03_tracker[curr_idx]),
                float(ice07_tracker[curr_idx]),
                float(max_berg_tracker[curr_idx]),
                lat_grid, lon_grid, cell_size_km,
                success=True, iterations=iterations,
            )

        if cg > g_score[curr_idx]:
            continue

        c_time = time_tracker[curr_idx]
        current_day = min(int(c_time / 24.0), n_days - 1)
        c_fuel = fuel_tracker[curr_idx]
        c_ice03 = ice03_tracker[curr_idx]
        c_ice07 = ice07_tracker[curr_idx]
        c_max_berg = max_berg_tracker[curr_idx]

        for dy, dx, dist_nm in neighbor_offsets:
            ny_pos = cy + dy
            nx_pos = cx + dx

            if ny_pos < 0 or ny_pos >= ny or nx_pos < 0 or nx_pos >= nx:
                continue

            n_idx = ny_pos * nx + nx_pos
            if impassable[ny_pos, nx_pos]:
                continue

            # Sea ice concentration
            if ignore_ice:
                sic = 0.0
            elif sic_3d:
                sic = float(sic_fields[current_day, ny_pos, nx_pos])
            else:
                sic = float(sic_fields[ny_pos, nx_pos])

            if sic >= max_sic:
                continue

            # Berg risk
            if berg_risk_field is not None:
                if berg_3d:
                    br = float(berg_risk_field[current_day, ny_pos, nx_pos])
                else:
                    br = float(berg_risk_field[ny_pos, nx_pos])
                if br > berg_cutoff:
                    continue
            else:
                br = 0.0

            # Speed in ice and fuel consumption
            if sic <= 0.01:
                spd = v_open
                f_rate = open_fuel_rate
            else:
                ratio = min(sic / sic_block, 1.0)
                spd = v_open * (1.0 - (ratio ** p_exp))
                if spd < 0.5:
                    continue
                f_rate = max(open_fuel_rate + ice_res_coeff * sic * (1.0 + thickness_factor), 0.1)

            time_h = dist_nm / spd
            fuel_t = f_rate * time_h
            ice_risk = max(0.0, sic - 0.15) / 0.75
            risk_score = ice_risk + br

            edge_cost = w_time * time_h + w_fuel * fuel_t + w_risk * risk_score
            tentative_g = cg + edge_cost

            if tentative_g < g_score[n_idx]:
                g_score[n_idx] = tentative_g
                came_from[n_idx] = curr_idx

                time_tracker[n_idx] = c_time + time_h
                fuel_tracker[n_idx] = c_fuel + fuel_t
                ice03_tracker[n_idx] = c_ice03 + (time_h if sic > 0.3 else 0.0)
                ice07_tracker[n_idx] = c_ice07 + (time_h if sic > 0.7 else 0.0)
                max_berg_tracker[n_idx] = max(c_max_berg, br)

                h = float(goal_dist_nm[ny_pos, nx_pos]) * min_cost_per_nm
                counter += 1
                heapq.heappush(open_set, (tentative_g + h, tentative_g, counter, ny_pos, nx_pos))

    # No path found
    return _build_result([], 0.0, 0.0, 0.0, 0.0, 0.0,
                         lat_grid, lon_grid, cell_size_km,
                         success=False, iterations=iterations)


def _build_result(path, time_h, fuel_t, ice_03, ice_07, max_berg,
                  lat_grid, lon_grid, cell_size_km, success, iterations):
    """Build standardised route result dict."""
    if not path or not success:
        return {
            "success": False,
            "path_yx": [],
            "path_latlon": [],
            "distance_nm": 0.0,
            "time_h": 0.0,
            "fuel_t": 0.0,
            "ice_hours_03": 0.0,
            "ice_hours_07": 0.0,
            "max_berg_risk": 0.0,
            "iterations": iterations,
            "n_cells": 0,
        }
    
    path_latlon = [(float(lat_grid[y, x]), float(lon_grid[y, x])) for y, x in path]
    
    total_dist_km = sum(
        cell_distance_km(path[i][0], path[i][1], path[i+1][0], path[i+1][1], cell_size_km)
        for i in range(len(path) - 1)
    )
    
    return {
        "success": True,
        "path_yx": path,
        "path_latlon": path_latlon,
        "distance_nm": total_dist_km * 0.539957,
        "time_h": time_h,
        "fuel_t": fuel_t,
        "ice_hours_03": ice_03,
        "ice_hours_07": ice_07,
        "max_berg_risk": max_berg,
        "iterations": iterations,
        "n_cells": len(path),
    }


def smooth_path(path_latlon, iterations=3):
    """String-pulling / smoothing to avoid Manhattan-like tracks."""
    if len(path_latlon) < 3:
        return path_latlon
    
    path = [list(p) for p in path_latlon]
    
    for _ in range(iterations):
        new_path = [path[0]]
        for i in range(1, len(path) - 1):
            lat = 0.25 * path[i-1][0] + 0.5 * path[i][0] + 0.25 * path[i+1][0]
            lon = 0.25 * path[i-1][1] + 0.5 * path[i][1] + 0.25 * path[i+1][1]
            new_path.append([lat, lon])
        new_path.append(path[-1])
        path = new_path
    
    return [tuple(p) for p in path]
