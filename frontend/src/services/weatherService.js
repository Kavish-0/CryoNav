/* ═══════════════════════════════════════════════════════════════
   Weather Service — GET /weather

   Real ERA5 reanalysis (10 m wind, 2 m temperature, mean sea-level
   pressure) out of the data cube. Same response shape as /ocean so both
   can be handled the same way on the client.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';

const weatherService = {
  /**
   * @param {string} date - ISO date (YYYY-MM-DD)
   * @param {number} [stride=6] - Wind-vector subsampling
   * @returns {Promise<{
   *   date: string, source: string, is_real: boolean,
   *   vectors: {lat:number,lon:number,u:number,v:number,speed:number}[],
   *   wind_speed: number[][], shape: number[],
   *   stats: {mean_wind_ms:number, max_wind_ms:number, mean_t2m_c:number, mean_msl_hpa:number}
   * }>}
   */
  async getWeather(date, stride = 6) {
    /* Optional endpoint — the map shows "unavailable" instead of a toast.
       Same cost profile as /ocean: ~13 s cold, longer behind a queue. */
    const { data } = await apiClient.get('/weather', {
      params: { date, stride }, timeout: 120000, silent: true,
    });
    return data;
  },
};

export default weatherService;
