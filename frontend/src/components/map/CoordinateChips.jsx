/* CoordinateChips — cursor position, view state and what lies under the cursor.

   Written straight to DOM nodes through refs: mousemove fires far too
   often to route through React state, and this is exactly the kind of
   readout that would otherwise re-render the whole map page.

   `inspect(lat, lon)` returns a short description of the grid cell under
   the cursor (sea-ice value, depth) or null outside the model grid. It is
   called at most once per animation frame. */

import React, { useEffect, useRef } from 'react';
import { useMap, useMapEvents } from 'react-leaflet';

export default function CoordinateChips({ projection, gridShape, inspect }) {
  const map = useMap();
  const coordRef = useRef(null);
  const zoomRef = useRef(null);
  const inspectRef = useRef(null);
  const pending = useRef(null);
  const frame = useRef(null);

  const showInspect = (text) => {
    if (!inspectRef.current) return;
    inspectRef.current.textContent = text || '';
    inspectRef.current.style.display = text ? '' : 'none';
  };

  useMapEvents({
    mousemove(e) {
      const { lat, lng } = e.latlng;
      if (coordRef.current) {
        coordRef.current.textContent =
          `${Math.abs(lat).toFixed(2)}°${lat < 0 ? 'S' : 'N'}  ${Math.abs(lng).toFixed(2)}°${lng < 0 ? 'W' : 'E'}`;
      }
      if (!inspect) return;
      pending.current = e.latlng;
      if (frame.current === null) {
        frame.current = requestAnimationFrame(() => {
          frame.current = null;
          const ll = pending.current;
          showInspect(ll ? inspect(ll.lat, ll.lng) : null);
        });
      }
    },
    mouseout() {
      pending.current = null;
      showInspect(null);
    },
    zoomend() {
      if (zoomRef.current) zoomRef.current.textContent = `z${map.getZoom()}`;
    },
  });

  useEffect(() => {
    if (zoomRef.current) zoomRef.current.textContent = `z${map.getZoom()}`;
  }, [map]);

  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);

  return (
    <div className="map-chips">
      <span className="map-chip" ref={coordRef}>—</span>
      <span className="map-chip is-inspect" ref={inspectRef} style={{ display: 'none' }} />
      <span className="map-chip" ref={zoomRef}>z3</span>
      <span className="map-chip">{projection === 'polar' ? 'EPSG:3031' : 'EPSG:3857'}</span>
      {gridShape && <span className="map-chip">{gridShape.join(' × ')} grid</span>}
    </div>
  );
}
