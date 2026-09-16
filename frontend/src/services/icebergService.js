/* ═══════════════════════════════════════════════════════════════
   Iceberg Service — GET /bergs
   Aligned to Arman0212/CryoNav src/api/main.py

   The backend has exactly one iceberg route: GET /bergs?date=...&horizon=...
   It returns { bergs: [{ berg_id, mean_track, ensemble, length_m, width_m }],
   date, horizon } for a fixed synthetic set of 5 bergs (there is no
   per-berg detail or trajectory endpoint, and no server-side bbox filter).
   getIceberg() and getTrajectory() below are implemented client-side on
   top of /bergs rather than hitting endpoints that don't exist.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const icebergService = {
  /**
   * Get tracked icebergs for a date, with their drift ensembles.
   *
   * `mean_track` entries are [day, lat, lon] arrays — note the integration
   * guide describes them as {day, lat, lon} objects, but src/api/main.py
   * indexes them positionally (mean_track[-1][1]), so arrays are correct.
   *
   * @param {string} [date='2023-01-13'] - Drift start date (backend default)
   * @param {number} [horizon=7] - Days to propagate
   * @param {number} [limit=8] - Number of largest bergs to return
   * @returns {Promise<Array>} [{ berg_id, mean_track, ensemble, length_m, width_m,
   *                              observed_on, final_position }]
   */
  async getIcebergs(date = '2023-01-13', horizon = 7, limit = 8) {
    /* Same cost as getIcebergsWithMeta — a 50-member ensemble for an
       uncached date runs ~12 s, and longer behind other heavy work, so the
       30 s default timed out on pages that load several fields at once. */
    const { data } = await apiClient.get('/bergs', {
      params: { date, horizon, limit },
      timeout: 120000,
    });
    return data.bergs;
  },

  /**
   * Same request, but keeping the envelope — `source` names the dataset
   * behind the bergs and `n_ensemble` how many members were propagated,
   * both of which the UI should show rather than hide.
   */
  async getIcebergsWithMeta(date = '2023-01-13', horizon = 7, limit = 8) {
    /* Propagating a 50-member ensemble takes ~15 s for a date the server has
       not seen before, and longer when queued behind other heavy work. */
    const { data } = await apiClient.get('/bergs', {
      params: { date, horizon, limit },
      timeout: 120000,
    });
    return data;
  },

  /**
   * Get a single iceberg's data.
   * NOTE: there's no GET /bergs/{id} route — this fetches the full /bergs
   * response for the date and picks out the matching berg_id client-side.
   *
   * @param {string} id - berg_id (e.g. "berg_0")
   * @param {string} [date='2023-01-20']
   * @param {number} [horizon=7]
   * @returns {Promise<Object|undefined>}
   */
  async getIceberg(id, date = '2023-01-20', horizon = 7) {
    const bergs = await this.getIcebergs(date, horizon);
    return bergs.find((b) => b.berg_id === id);
  },

  /**
   * Get the predicted trajectory (RK4 ensemble) for an iceberg.
   * NOTE: there's no GET /bergs/{id}/trajectory route — the RK4 ensemble
   * track is already included in each berg's /bergs response as
   * `mean_track` / `ensemble`, so this just extracts it.
   *
   * @param {string} id - berg_id
   * @param {string} [date='2023-01-20']
   * @param {number} [horizon=7] - Days of drift to request (server caps at 14)
   * @returns {Promise<{mean_track: object, ensemble: number[][]}|undefined>}
   */
  async getTrajectory(id, date = '2023-01-20', horizon = 7) {
    const berg = await this.getIceberg(id, date, horizon);
    if (!berg) return undefined;
    return { mean_track: berg.mean_track, ensemble: berg.ensemble };
  },
};

export default icebergService;
