"""
CryoNav — Iceberg drift dynamics.

Full momentum-balance integrator (RK4, 1-hour steps):
  m dv/dt = F_air + F_water + F_coriolis + F_pressure_gradient + F_ice

Plus the empirical 2% rule as a permanent baseline:
  v_berg = u_current + 0.02 × u_wind
"""
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.config import ROUTING


# Physical constants from config
CFG = ROUTING["berg_drift"]
RHO_A = CFG["rho_air"]
RHO_W = CFG["rho_water"]
RHO_I = CFG["rho_ice"]
C_A = CFG["C_air"]
C_W = CFG["C_water"]
OMEGA = CFG["omega"]
G = CFG["g"]
DT = CFG["dt_seconds"]
SIC_LOCK = CFG["sic_lock_threshold"]


class Iceberg:
    """Represents an iceberg with physical properties."""
    
    def __init__(self, berg_id: str, lat: float, lon: float,
                 length_m: float = None, width_m: float = None,
                 thickness_m: float = None):
        self.berg_id = berg_id
        self.lat = lat
        self.lon = lon
        
        self.length = length_m or CFG["default_length_m"]
        self.width = width_m or CFG["default_width_m"]
        self.thickness = thickness_m or CFG["default_thickness_m"]
        
        # Derived geometry
        fr_ratio = CFG["freeboard_draft_ratio"]
        self.draft = self.thickness * (1 - fr_ratio)  # ~80% submerged
        self.freeboard = self.thickness * fr_ratio     # ~20% above water
        
        # Cross-sectional areas
        self.A_sail = self.length * self.freeboard    # above water (wind)
        self.A_keel = self.length * self.draft        # below water (current)
        
        # Mass (approximate)
        self.mass = RHO_I * self.length * self.width * self.thickness
        
        # Velocity (m/s, in local East-North coords)
        self.vx = 0.0  # eastward
        self.vy = 0.0  # northward


def coriolis_parameter(lat_deg: float) -> float:
    """Coriolis parameter f = 2Ω sin(φ). Negative in SH."""
    return 2 * OMEGA * np.sin(np.radians(lat_deg))


def _lat_lon_to_xy(lat, lon, ref_lat, ref_lon):
    """Convert lat/lon displacement to approximate metres."""
    dlat = lat - ref_lat
    dlon = lon - ref_lon
    y = dlat * 111320.0  # metres per degree latitude
    x = dlon * 111320.0 * np.cos(np.radians(ref_lat))
    return x, y


def _xy_to_lat_lon(x, y, ref_lat, ref_lon):
    """Convert metres back to lat/lon."""
    dlat = y / 111320.0
    dlon = x / (111320.0 * np.cos(np.radians(ref_lat)))
    return ref_lat + dlat, ref_lon + dlon


def forces(berg: Iceberg, wind_u, wind_v, curr_u, curr_v, sic, ssh_grad_x, ssh_grad_y):
    """
    Compute all forces on the iceberg.
    
    All inputs in SI units. Wind and current in m/s (E, N components).
    Returns acceleration (ax, ay) in m/s².
    """
    vx, vy = berg.vx, berg.vy
    m = berg.mass
    
    # Relative velocities
    rel_wind_x = wind_u - vx
    rel_wind_y = wind_v - vy
    rel_wind_speed = np.sqrt(rel_wind_x**2 + rel_wind_y**2) + 1e-10
    
    rel_curr_x = curr_u - vx
    rel_curr_y = curr_v - vy
    rel_curr_speed = np.sqrt(rel_curr_x**2 + rel_curr_y**2) + 1e-10
    
    # Air drag
    F_air_x = 0.5 * RHO_A * C_A * berg.A_sail * rel_wind_speed * rel_wind_x
    F_air_y = 0.5 * RHO_A * C_A * berg.A_sail * rel_wind_speed * rel_wind_y
    
    # Water drag
    F_water_x = 0.5 * RHO_W * C_W * berg.A_keel * rel_curr_speed * rel_curr_x
    F_water_y = 0.5 * RHO_W * C_W * berg.A_keel * rel_curr_speed * rel_curr_y
    
    # Coriolis: F = -m f k × v
    # In SH (f < 0): deflection is to the LEFT of motion
    f = coriolis_parameter(berg.lat)
    F_cor_x = m * f * vy
    F_cor_y = -m * f * vx
    
    # Sea surface pressure gradient
    F_pres_x = -m * G * ssh_grad_x
    F_pres_y = -m * G * ssh_grad_y
    
    # Sea-ice drag: when SIC > threshold, lock to pack
    if sic > SIC_LOCK:
        ice_drag_coeff = 5.0 * (sic - SIC_LOCK) / (1.0 - SIC_LOCK)
        # Strong drag toward zero velocity (locked in ice)
        F_ice_x = -ice_drag_coeff * m * vx
        F_ice_y = -ice_drag_coeff * m * vy
    else:
        F_ice_x = 0.0
        F_ice_y = 0.0
    
    # Total acceleration
    ax = (F_air_x + F_water_x + F_cor_x + F_pres_x + F_ice_x) / m
    ay = (F_air_y + F_water_y + F_cor_y + F_pres_y + F_ice_y) / m
    
    return ax, ay


def rk4_step(berg, dt, wind_u, wind_v, curr_u, curr_v, sic, 
             ssh_grad_x, ssh_grad_y):
    """
    One RK4 integration step.
    Updates berg position and velocity in-place.
    """
    # Save initial state
    x0, y0 = 0.0, 0.0  # relative position
    vx0, vy0 = berg.vx, berg.vy
    lat0, lon0 = berg.lat, berg.lon
    
    # k1
    ax1, ay1 = forces(berg, wind_u, wind_v, curr_u, curr_v, sic, 
                       ssh_grad_x, ssh_grad_y)
    k1_vx, k1_vy = ax1, ay1
    k1_x, k1_y = vx0, vy0
    
    # k2
    berg.vx = vx0 + 0.5 * dt * k1_vx
    berg.vy = vy0 + 0.5 * dt * k1_vy
    ax2, ay2 = forces(berg, wind_u, wind_v, curr_u, curr_v, sic,
                       ssh_grad_x, ssh_grad_y)
    k2_vx, k2_vy = ax2, ay2
    k2_x, k2_y = vx0 + 0.5 * dt * k1_vx, vy0 + 0.5 * dt * k1_vy
    
    # k3
    berg.vx = vx0 + 0.5 * dt * k2_vx
    berg.vy = vy0 + 0.5 * dt * k2_vy
    ax3, ay3 = forces(berg, wind_u, wind_v, curr_u, curr_v, sic,
                       ssh_grad_x, ssh_grad_y)
    k3_vx, k3_vy = ax3, ay3
    k3_x, k3_y = vx0 + 0.5 * dt * k2_vx, vy0 + 0.5 * dt * k2_vy
    
    # k4
    berg.vx = vx0 + dt * k3_vx
    berg.vy = vy0 + dt * k3_vy
    ax4, ay4 = forces(berg, wind_u, wind_v, curr_u, curr_v, sic,
                       ssh_grad_x, ssh_grad_y)
    k4_vx, k4_vy = ax4, ay4
    k4_x, k4_y = vx0 + dt * k3_vx, vy0 + dt * k3_vy
    
    # Update velocity
    berg.vx = vx0 + (dt / 6.0) * (k1_vx + 2*k2_vx + 2*k3_vx + k4_vx)
    berg.vy = vy0 + (dt / 6.0) * (k1_vy + 2*k2_vy + 2*k3_vy + k4_vy)
    
    # Update position from the same RK4 stages.
    # k*_x / k*_y are velocities, so the weighted sum times dt/6 is already a
    # displacement in metres. This previously multiplied by dt a second time,
    # then threw the result away and stepped with the mean velocity instead,
    # and finally overwrote the converted position with a second, redundant
    # conversion — three bugs in five lines, none of them reachable as RK4.
    dx_m = (dt / 6.0) * (k1_x + 2*k2_x + 2*k3_x + k4_x)
    dy_m = (dt / 6.0) * (k1_y + 2*k2_y + 2*k3_y + k4_y)

    berg.lat, berg.lon = _xy_to_lat_lon(dx_m, dy_m, lat0, lon0)


def empirical_2pct_rule(lat, lon, wind_u, wind_v, curr_u, curr_v, dt_hours=1.0):
    """
    2% rule: v_berg = u_current + 0.02 × u_wind
    
    Returns new (lat, lon) after dt_hours.
    """
    vx = curr_u + 0.02 * wind_u  # m/s
    vy = curr_v + 0.02 * wind_v
    
    dt_s = dt_hours * 3600.0
    dx = vx * dt_s
    dy = vy * dt_s
    
    new_lat = lat + dy / 111320.0
    new_lon = lon + dx / (111320.0 * np.cos(np.radians(lat)))
    
    return new_lat, new_lon


def _propagate_2pct_batch(berg_id, start_lat, start_lon, horizon_days,
                          forcing_batch, n_ensemble, rng,
                          n_steps_per_day, total_steps):
    """
    Drift every ensemble member together under the 2% rule.

    The scalar loop in propagate() calls forcing_func twice per member per
    hourly step - 33,600 nearest-cell lookups for one 50-member berg over 14
    days - which dominated the cost of /bergs and of every /route that builds a
    berg-risk field. Here each step samples all members in a single call and
    advances them with array arithmetic.

    The model is unchanged: same 2% rule, same hourly step, same daily
    sampling, same grounding rule, and member 0 still runs unperturbed. Only
    the order the perturbations are drawn in differs, so the tracks are
    statistically equivalent to the scalar loop rather than identical to it.

    forcing_batch(t_day, lats, lons) -> dict of arrays, one entry per member.
    """
    lats = np.full(n_ensemble, float(start_lat))
    lons = np.full(n_ensemble, float(start_lon))

    # (n_ensemble, horizon_days + 1, 2); day 0 is the start position.
    ensemble = np.zeros((n_ensemble, horizon_days + 1, 2))
    ensemble[:, 0, 0] = lats
    ensemble[:, 0, 1] = lons

    for step in range(total_steps):
        t_day = step * (DT / 3600.0) / 24.0
        f = forcing_batch(t_day, lats, lons)

        # Member 0 is the unperturbed control, as in the scalar loop.
        noise = rng.uniform(-0.1, 0.1, size=(4, n_ensemble))
        noise[:, 0] = 0.0
        wind_u = f["wind_u"] * (1.0 + noise[0])
        wind_v = f["wind_v"] * (1.0 + noise[1])
        curr_u = f["curr_u"] * (1.0 + noise[2])
        curr_v = f["curr_v"] * (1.0 + noise[3])

        new_lat, new_lon = empirical_2pct_rule(lats, lons, wind_u, wind_v,
                                               curr_u, curr_v, DT / 3600.0)

        # Halt members that would drift onto land or into the shallows.
        nf = forcing_batch(t_day, new_lat, new_lon)
        grounded = (nf["land_mask"] > 0.5) | (nf["bathy"] > -15.0)
        lats = np.where(grounded, lats, new_lat)
        lons = np.where(grounded, lons, new_lon)

        if (step + 1) % n_steps_per_day == 0:
            day = (step + 1) // n_steps_per_day
            if day < ensemble.shape[1]:
                ensemble[:, day, 0] = lats
                ensemble[:, day, 1] = lons

    mean_track = [(d, float(ensemble[:, d, 0].mean()), float(ensemble[:, d, 1].mean()))
                  for d in range(ensemble.shape[1])]
    return {"berg_id": berg_id, "mean_track": mean_track, "ensemble": ensemble}


def propagate(berg_id, start_lat, start_lon, t0, horizon_days,
              forcing_func, berg_length=None, berg_width=None,
              method="dynamics", n_ensemble=1, rng=None,
              forcing_batch=None):
    """
    Propagate an iceberg forward in time.
    
    Args:
        berg_id: Identifier
        start_lat, start_lon: Initial position
        t0: Start datetime
        horizon_days: How many days to propagate
        forcing_func: callable(t, lat, lon) -> dict with wind_u, wind_v, 
                      curr_u, curr_v, sic, ssh_grad_x, ssh_grad_y
        method: "dynamics" (full physics) or "2pct" (empirical rule)
        n_ensemble: Number of ensemble members (perturbed forcing)
        rng: numpy random generator for ensemble perturbation
        forcing_batch: optional callable(t, lats, lons) -> dict of arrays. When
                       given, a 2%-rule ensemble advances every member at once
                       instead of one at a time; see _propagate_2pct_batch.
    
    Returns:
        dict with mean_track, ensemble tracks, and risk_field
    """
    if rng is None:
        rng = np.random.default_rng(42)
    
    n_steps_per_day = int(24 * 3600 / DT)
    total_steps = horizon_days * n_steps_per_day

    if method == "2pct" and forcing_batch is not None and n_ensemble > 1:
        return _propagate_2pct_batch(berg_id, start_lat, start_lon, horizon_days,
                                     forcing_batch, n_ensemble, rng,
                                     n_steps_per_day, total_steps)
    
    all_tracks = []
    
    for ens in range(n_ensemble):
        # Perturb drag coefficients for ensemble
        if ens > 0:
            perturb = CFG["perturbation_fraction"]
            c_a_pert = C_A * (1 + rng.uniform(-perturb, perturb))
            c_w_pert = C_W * (1 + rng.uniform(-perturb, perturb))
        else:
            c_a_pert = C_A
            c_w_pert = C_W
        
        berg = Iceberg(berg_id, start_lat, start_lon, berg_length, berg_width)
        
        track = [(0, start_lat, start_lon)]
        
        for step in range(total_steps):
            t_hours = step * (DT / 3600.0)
            t_day = t_hours / 24.0
            
            # Get forcing at current position and time
            forcing = forcing_func(t_day, berg.lat, berg.lon)
            
            wind_u = forcing.get("wind_u", 0) * (1 + (rng.uniform(-0.1, 0.1) if ens > 0 else 0))
            wind_v = forcing.get("wind_v", 0) * (1 + (rng.uniform(-0.1, 0.1) if ens > 0 else 0))
            curr_u = forcing.get("curr_u", 0) * (1 + (rng.uniform(-0.1, 0.1) if ens > 0 else 0))
            curr_v = forcing.get("curr_v", 0) * (1 + (rng.uniform(-0.1, 0.1) if ens > 0 else 0))
            sic = forcing.get("sic", 0)
            ssh_gx = forcing.get("ssh_grad_x", 0)
            ssh_gy = forcing.get("ssh_grad_y", 0)
            
            if method == "dynamics":
                old_lat, old_lon = berg.lat, berg.lon
                rk4_step(berg, DT, wind_u, wind_v, curr_u, curr_v, sic,
                        ssh_gx, ssh_gy)
                next_f = forcing_func(t_day, berg.lat, berg.lon)
                if next_f.get("land_mask", 0.0) > 0.5 or next_f.get("bathy", -100.0) > -15.0:
                    # Grounded at coast / shoal: halt drift into land
                    berg.lat, berg.lon = old_lat, old_lon
                    berg.vx, berg.vy = 0.0, 0.0
            else:
                next_lat, next_lon = empirical_2pct_rule(
                    berg.lat, berg.lon, wind_u, wind_v, curr_u, curr_v, DT/3600)
                next_f = forcing_func(t_day, next_lat, next_lon)
                if next_f.get("land_mask", 0.0) > 0.5 or next_f.get("bathy", -100.0) > -15.0:
                    # Grounded at coast: halt drift into land
                    pass
                else:
                    berg.lat, berg.lon = next_lat, next_lon
            
            # Record position at daily intervals
            if (step + 1) % n_steps_per_day == 0:
                day = (step + 1) // n_steps_per_day
                track.append((day, berg.lat, berg.lon))
        
        all_tracks.append(track)
    
    # Compute mean track
    mean_track = []
    for day_idx in range(len(all_tracks[0])):
        lats = [all_tracks[e][day_idx][1] for e in range(n_ensemble) 
                if day_idx < len(all_tracks[e])]
        lons = [all_tracks[e][day_idx][2] for e in range(n_ensemble)
                if day_idx < len(all_tracks[e])]
        mean_track.append((all_tracks[0][day_idx][0], 
                          np.mean(lats), np.mean(lons)))
    
    # Ensemble array: (n_ensemble, horizon+1, 2)
    ensemble = np.zeros((n_ensemble, len(all_tracks[0]), 2))
    for e in range(n_ensemble):
        for d in range(len(all_tracks[e])):
            ensemble[e, d, 0] = all_tracks[e][d][1]  # lat
            ensemble[e, d, 1] = all_tracks[e][d][2]  # lon
    
    return {
        "berg_id": berg_id,
        "mean_track": mean_track,
        "ensemble": ensemble,
    }


def great_circle_distance_km(lat1, lon1, lat2, lon2):
    """Haversine great-circle distance in km."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    return R * 2 * np.arcsin(np.sqrt(a))
