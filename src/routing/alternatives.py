"""
CryoNav — Alternative route generation and comparison.

Generates 4+ candidate routes with different weight profiles.
Computes comparison metrics and templates rejection reasons from the numbers.
NEVER hard-codes rejection sentences — always generated from metrics.
"""
import numpy as np
from pathlib import Path
import json, sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import ROUTING, DOMAIN
from src.routing.astar import astar_route, smooth_path


def generate_alternatives(sic_fields, berg_risk_field, bathy, land_mask,
                          lat_grid, lon_grid, start_yx, goal_yx,
                          sic_today=None, cell_size_km=25.0,
                          weight_overrides=None):
    """
    Generate all candidate routes and the comparison table.
    
    Args:
        weight_overrides: optional {profile_key: {"w_time", "w_fuel", "w_risk"}}
            replacing that profile's configured weights. POST /route uses it to
            apply the caller's cost weights to the "balanced" profile; the other
            profiles keep their configured weights so they stay fixed reference
            alternatives to compare against.

    Returns:
        routes: dict mapping profile name -> route result dict
        comparison: list of dicts with all metrics
        rejections: list of rejection reason strings (generated from numbers)
    """
    profiles = ROUTING["alternatives"]["profiles"]
    routes = {}

    # The profiles are independent searches over the same read-only fields, so
    # they run concurrently. A* releases the GIL inside numpy, so this is a real
    # wall-clock win on the five-profile request the UI makes.
    from concurrent.futures import ThreadPoolExecutor

    def _compute_single_profile(name, profile):
        weights = dict(profile)
        if weight_overrides and name in weight_overrides:
            weights.update(weight_overrides[name])

        # Use persistence SIC (today's field repeated) for the persistence_route
        if profile.get("use_persistence") and sic_today is not None:
            fields = np.stack([sic_today] * sic_fields.shape[0], axis=0)
        else:
            fields = sic_fields

        route = astar_route(
            sic_fields=fields,
            berg_risk_field=berg_risk_field,
            bathy=bathy, land_mask=land_mask,
            lat_grid=lat_grid, lon_grid=lon_grid,
            start_yx=start_yx, goal_yx=goal_yx,
            w_time=weights.get("w_time", 1.0),
            w_fuel=weights.get("w_fuel", 0.5),
            w_risk=weights.get("w_risk", 2.0),
            v_open_kn=ROUTING["speed_model"]["v_open_kn"],
            cell_size_km=cell_size_km,
            ignore_ice=profile.get("ignore_ice", False),
        )

        route["profile_name"] = profile["name"]
        route["profile_key"] = name

        # Smooth the path
        if route["success"] and route["path_latlon"]:
            route["path_latlon_smooth"] = smooth_path(route["path_latlon"])

        return name, route

    with ThreadPoolExecutor(max_workers=min(len(profiles), 8)) as executor:
        futures = [executor.submit(_compute_single_profile, name, profile)
                   for name, profile in profiles.items()]
        for f in futures:
            name, route = f.result()
            routes[name] = route

    # Build comparison table
    comparison = build_comparison_table(routes)
    
    # Generate rejection reasons
    rejections = generate_rejection_reasons(routes, comparison)
    
    return routes, comparison, rejections


def build_comparison_table(routes: dict) -> list:
    """
    Build the route comparison table with all metrics.
    
    For each route: distance (nm), transit time (h), hours in SIC > 0.3,
    hours in SIC > 0.7, estimated fuel (t), max berg risk along track, and the
    closest approach to a tracked berg.
    """
    table = []
    
    for name, route in routes.items():
        row = {
            "profile": route.get("profile_name", name),
            "key": name,
            "success": route["success"],
            "distance_nm": round(route.get("distance_nm", 0), 1),
            "time_h": round(route.get("time_h", 0), 1),
            "ice_hours_03": round(route.get("ice_hours_03", 0), 1),
            "ice_hours_07": round(route.get("ice_hours_07", 0), 1),
            "fuel_t": round(route.get("fuel_t", 0), 1),
            "max_berg_risk": round(route.get("max_berg_risk", 0), 3),
            # Closest the plotted route passes to a tracked berg's projected
            # position. Set by the API once the full path is assembled, so it
            # is absent when this table is built from raw router output.
            "min_berg_distance_nm": route.get("min_berg_distance_nm"),
            "n_cells": route.get("n_cells", 0),
        }
        table.append(row)
    
    return table


def generate_rejection_reasons(routes: dict, comparison: list) -> list:
    """
    Generate rejection reasons for non-recommended routes.
    Templated from computed metrics — NEVER hard-coded.
    
    The recommended route is 'balanced'. All others get rejection reasons.
    """
    rejections = []
    
    balanced = None
    for row in comparison:
        if row["key"] == "balanced":
            balanced = row
            break
    
    if balanced is None or not balanced["success"]:
        return [{"profile": r["profile"], "reason": "No balanced route found"} 
                for r in comparison]
    
    for row in comparison:
        if row["key"] == "balanced":
            rejections.append({
                "profile": row["profile"],
                "key": row["key"],
                "reason": "✓ RECOMMENDED — Best balance of time, fuel, and safety",
                "recommended": True,
            })
            continue
        
        if not row["success"]:
            rejections.append({
                "profile": row["profile"],
                "key": row["key"],
                "reason": "Failed: No feasible path found with these constraints",
                "recommended": False,
            })
            continue
        
        # Build rejection from metric differences
        parts = []
        
        # Distance comparison
        dist_diff = row["distance_nm"] - balanced["distance_nm"]
        if abs(dist_diff) > 5:
            if dist_diff < 0:
                parts.append(f"{abs(dist_diff):.0f} nm shorter")
            else:
                parts.append(f"{dist_diff:.0f} nm longer")
        
        # Time comparison
        time_diff = row["time_h"] - balanced["time_h"]
        if abs(time_diff) > 1:
            if time_diff > 0:
                parts.append(f"{time_diff:.0f} h longer")
            else:
                parts.append(f"{abs(time_diff):.0f} h shorter")
        
        # Ice exposure
        ice_diff = row["ice_hours_07"] - balanced["ice_hours_07"]
        if ice_diff > 1:
            parts.append(f"{ice_diff:.0f} h more in 70%+ ice")
        
        # Fuel
        fuel_diff = row["fuel_t"] - balanced["fuel_t"]
        if abs(fuel_diff) > 1:
            if fuel_diff > 0:
                parts.append(f"{fuel_diff:.0f} t more fuel")
            else:
                parts.append(f"{abs(fuel_diff):.0f} t less fuel")
        
        # Berg risk
        if row["max_berg_risk"] > balanced["max_berg_risk"] + 0.05:
            parts.append(f"higher berg risk ({row['max_berg_risk']:.1%})")
        
        if parts:
            # Template: "Rejected: [positive] but [negatives]"
            positives = [p for p in parts if "shorter" in p or "less" in p]
            negatives = [p for p in parts if "longer" in p or "more" in p or "higher" in p]
            
            if positives and negatives:
                reason = f"Rejected: {', '.join(positives)} but {', '.join(negatives)}"
            elif negatives:
                reason = f"Rejected: {', '.join(negatives)}"
            else:
                reason = f"Alternative: {', '.join(positives)}"
        else:
            reason = "Similar to recommended route"
        
        rejections.append({
            "profile": row["profile"],
            "key": row["key"],
            "reason": reason,
            "recommended": False,
        })
    
    return rejections


def format_comparison_for_display(comparison, rejections):
    """Format comparison table and rejections for the UI side panel."""
    display = {
        "table": comparison,
        "rejections": rejections,
        "headers": [
            {"key": "profile", "label": "Route", "align": "left"},
            {"key": "distance_nm", "label": "Distance (nm)", "align": "right"},
            {"key": "time_h", "label": "Time (h)", "align": "right"},
            {"key": "ice_hours_03", "label": "SIC>30% (h)", "align": "right"},
            {"key": "ice_hours_07", "label": "SIC>70% (h)", "align": "right"},
            {"key": "fuel_t", "label": "Fuel (t)", "align": "right"},
            {"key": "max_berg_risk", "label": "Max Berg Risk", "align": "right"},
            {"key": "min_berg_distance_nm", "label": "Berg clearance (nm)", "align": "right"},
        ],
    }
    return display
