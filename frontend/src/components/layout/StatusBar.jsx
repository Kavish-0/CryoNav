/* ═══════════════════════════════════════════════════════════════
   StatusBar — Bottom bar with data freshness and system info
   ═══════════════════════════════════════════════════════════════ */

import React from 'react';
import { Database, Clock, Cpu } from 'lucide-react';
import useAppStore from '@stores/useAppStore';

export default function StatusBar() {
  const viewMode = useAppStore((s) => s.viewMode);

  return (
    <footer className="statusbar">
      <div className="statusbar-left">
        <div className="statusbar-item">
          <Database size={11} />
          <span>Data Cube: antarctic_cube.zarr (5.3 GB)</span>
        </div>
        <div className="statusbar-item">
          <Cpu size={11} />
          <span>Model: U-Net sea-ice forecaster</span>
        </div>
      </div>
      <div className="statusbar-right">
        <div className="statusbar-item">
          <Clock size={11} />
          <span>Mode: {viewMode.toUpperCase()}</span>
        </div>
        <div className="statusbar-item">
          <span>CryoNav v1.0 — SIH 2024</span>
        </div>
      </div>
    </footer>
  );
}
