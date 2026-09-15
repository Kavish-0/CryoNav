/* ═══════════════════════════════════════════════════════════════
   useMapStore — Map state (center, zoom, active layers, selection)
   ═══════════════════════════════════════════════════════════════ */

import { create } from 'zustand';
import { MAP_LAYERS } from '@utils/constants';

/** Build default layer visibility from MAP_LAYERS config */
function getDefaultLayerVisibility() {
  const layers = {};
  Object.values(MAP_LAYERS).forEach((layer) => {
    layers[layer.id] = layer.defaultOn;
  });
  return layers;
}

const useMapStore = create((set, get) => ({
  /* ── Map View ── */
  center: [-75, 0],
  zoom: 3,
  setView: (center, zoom) => set({ center, zoom }),

  /* ── Layer Visibility ── */
  layers: getDefaultLayerVisibility(),
  toggleLayer: (layerId) =>
    set((state) => ({
      layers: { ...state.layers, [layerId]: !state.layers[layerId] },
    })),
  setLayerVisible: (layerId, visible) =>
    set((state) => ({
      layers: { ...state.layers, [layerId]: visible },
    })),
  isLayerVisible: (layerId) => get().layers[layerId] ?? false,

  /* ── Selected Map Feature ── */
  selectedFeature: null,  // { type: 'iceberg'|'route'|'station', id, data }
  setSelectedFeature: (feature) => set({ selectedFeature: feature }),
  clearSelection: () => set({ selectedFeature: null }),

  /* ── Map Interaction Mode ── */
  interactionMode: 'navigate',  // 'navigate' | 'selectOrigin' | 'selectDestination' | 'measure'
  setInteractionMode: (mode) => set({ interactionMode: mode }),

  /* ── Iceberg Drift Horizon ──
     Shared by the map and the Icebergs page so both show the same drift. */
  bergHorizon: 7,  // days, 1–60
  setBergHorizon: (days) => set({ bergHorizon: days }),
}));

export default useMapStore;
