/* ═══════════════════════════════════════════════════════════════
   Config Service — GET /config, GET /demo-dates
   Aligned to Arman0212/CryoNav src/api/main.py

   GET /config returns:
     { region, stations, origins, held_out_demo_dates,
       forecast_horizon_days, ship, routing_weights, alternative_profiles }
   There is no grid_resolution / bounds / vessel_defaults field — those
   names were guesses that don't match the real response.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const configService = {
  async getConfig() {
    const { data } = await apiClient.get('/config');
    return data;
  },

  /**
   * Background reachability check for the connection indicator. Silent: the
   * backend runs a route calculation on its event loop for up to a minute,
   * and a poll timing out meanwhile should flip the indicator, not raise an
   * error toast.
   */
  async ping() {
    const { data } = await apiClient.get('/config', { silent: true });
    return data;
  },

  /**
   * Domain bounds from /config, combined with the real grid geometry from
   * GET /grid. The shape and cell size are now live values rather than the
   * constants this used to hardcode — /grid is the authority.
   */
  async getGridInfo() {
    const [{ data: config }, { data: grid }] = await Promise.all([
      apiClient.get('/config'),
      apiClient.get('/grid'),
    ]);
    return {
      bounds: config.region,              // { name, lon_min, lon_max, lat_min, lat_max }
      gridResolutionKm: grid.cell_size_km,
      gridShape: grid.shape,              // from the cube; do not hardcode
      bathymetrySource: grid.bathymetry_source,
    };
  },

  /**
   * Ship/vessel defaults. The backend calls this field `ship`, not
   * `vessel_defaults`.
   */
  async getVesselDefaults() {
    const { data } = await apiClient.get('/config');
    return data.ship || {};
  },

  /**
   * Available demo dates (GET /demo-dates) — held-out dates the model was
   * never trained on, plus the full date range of the Zarr cube.
   * @returns {Promise<{all_dates?: string[], demo_dates: string[], range?: {start: string, end: string}}>}
   */
  async getDemoDates() {
    const { data } = await apiClient.get('/demo-dates');
    return data;
  },
};

export default configService;
