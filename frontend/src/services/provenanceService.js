/* ═══════════════════════════════════════════════════════════════
   Provenance Service — GET /data/provenance, /data/coverage, /bergs/live

   Endpoints added by the backend data-layer work. These are what let the
   UI say where a number came from rather than just showing it, which is
   the whole point of the credibility story.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const provenanceService = {
  /** Which dataset each variable came from, with citations. */
  async getProvenance() {
    const { data } = await apiClient.get('/data/provenance');
    return data;
  },

  /** Markdown coverage/gaps report for the cube. */
  async getCoverage() {
    const { data } = await apiClient.get('/data/coverage');
    return data;
  },

  /**
   * Live iceberg positions from the US National Ice Center weekly feed
   * (distinct from /bergs, which propagates drift forward in time).
   */
  async getLiveBergs() {
    // Optional external feed — the map shows "unavailable" instead of a toast
    const { data } = await apiClient.get('/bergs/live', { silent: true });
    return data;
  },
};

export default provenanceService;
