/* ═══════════════════════════════════════════════════════════════
   Risk Field Service — GET /risk-field

   The iceberg-risk field the router itself consumes: probability of berg
   presence per grid cell on a given day of the passage, built by KDE over
   the same drift ensemble GET /bergs serves. Pair with GET /grid for the
   lat/lon of each cell.

   Optional endpoint: older backends compute this only inside POST /route
   and return 404 here, so the layer reports itself unavailable rather than
   raising an error toast.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const riskFieldService = {
  /**
   * @param {string} date - Drift start date (YYYY-MM-DD)
   * @param {number} [lead=1] - Day of the passage, 1..90
   * @param {number} [limit=8] - Largest bergs propagated into the field
   * @returns {Promise<{
   *   risk: number[][], shape: number[], date: string, lead_day: number,
   *   berg_count: number, berg_source: string, n_ensemble: number,
   *   stats: { max_risk: number, cells_above_0_1: number }
   * }>}
   */
  async getRiskField(date, lead = 1, limit = 8) {
    /* Propagating the drift ensemble for a date the server has not seen
       before takes far longer than apiClient's 30 s default — the first
       request for a date measured ~40 s and surfaced as a spurious
       "unavailable". Widen it here, as POST /route does. */
    const { data } = await apiClient.get('/risk-field', {
      params: { date, lead, limit },
      timeout: 180000,
      silent: true,
    });
    return data;
  },
};

export default riskFieldService;
