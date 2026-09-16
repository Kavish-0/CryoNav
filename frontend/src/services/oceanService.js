/* ═══════════════════════════════════════════════════════════════
   Ocean Service — GET /ocean

   Real CMEMS GLORYS12 reanalysis. The variables (uo, vo, sst, zos) were
   in the data cube all along but had no route, which is why this page
   used to read "Not Connected". The endpoint now serves them.

   `stride` subsamples the current vectors for arrow rendering — a full
   264x220 vector field is far more than a screen can show, and the raw
   fields are still returned for raster use.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const oceanService = {
  /**
   * @param {string} date - ISO date (YYYY-MM-DD)
   * @param {number} [stride=6] - Vector subsampling; higher = fewer arrows
   * @returns {Promise<{
   *   date: string, source: string, is_real: boolean,
   *   vectors: {lat:number,lon:number,u:number,v:number,speed:number}[],
   *   sst: number[][], speed: number[][], zos: number[][], shape: number[],
   *   stats: {mean_current_ms:number, max_current_ms:number, mean_sst_c:number, mean_ssh_m:number}
   * }>}
   */
  async getOcean(date, stride = 6, fields = false) {
    /* Optional endpoint — the map shows "unavailable" instead of a toast.
       A cold day measures ~11 s (full CMEMS fields serialised out of the
       cube) and longer when other heavy requests are queued ahead of it, so
       the 30 s default is too tight. */
    /* `fields` pulls the full sst/speed/zos rasters (~3 MB). The map draws
       arrows only, so it leaves them off; the Ocean page asks for them. */
    const { data } = await apiClient.get('/ocean', {
      params: { date, stride, fields }, timeout: 120000, silent: true,
    });
    return data;
  },
};

export default oceanService;
