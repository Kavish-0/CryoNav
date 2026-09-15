/* ═══════════════════════════════════════════════════════════════
   MissionController — owns the mission state and hands it out.

   Two channels, deliberately separated:

     CONTINUOUS  → a mutable ref, rewritten every frame, read inside
                   useFrame by the scene. Never touches React, so
                   scrolling causes zero re-renders.

     DISCRETE    → the phase index only (8 values across the whole
                   page), pushed through React state so the HUD and
                   narrative text can transition.

   That split is the reason the experience can hold 60fps while a
   dozen scene objects all track the same scroll position.
   ═══════════════════════════════════════════════════════════════ */

import React, { createContext, useContext, useRef, useState, useEffect, useMemo } from 'react';
import createMission, { phaseIndexAt } from '../data/missionData';
import demoTrajectory from '../data/demoTrajectory';

const MissionContext = createContext(null);

export function useMission() {
  const ctx = useContext(MissionContext);
  if (!ctx) throw new Error('useMission must be used inside <MissionController>');
  return ctx;
}

export function MissionController({ children, scrollRef }) {
  // Live API data could replace this snapshot; the baked file is real
  // backend geometry either way, so the scene is never empty.
  const mission = useMemo(() => createMission(demoTrajectory), []);

  /* Continuous channel — mutated in place, read by the scene */
  const stateRef = useRef(mission.derive(0));

  /* Discrete channel — only the phase reaches React */
  const [phaseIndex, setPhaseIndex] = useState(0);
  const phaseRef = useRef(0);

  useEffect(() => {
    let frame = null;
    let lastProgress = -1;
    let stillFrames = 0;

    const tick = () => {
      frame = null;
      const p = scrollRef.current ?? 0;
      // Rewrite the shared state object in place
      const next = mission.derive(p);
      Object.assign(stateRef.current, next);

      const idx = phaseIndexAt(p);
      if (idx !== phaseRef.current) {
        phaseRef.current = idx;
        setPhaseIndex(idx);          // the only React update in the loop
      }

      // The scroll driver keeps easing after the last scroll event fires, so
      // keep deriving until it settles. Otherwise the mission freezes short
      // of where the reader stopped — at the bottom of the page that meant
      // the final phase, and its Enter button, never appeared. A few still
      // frames are required before stopping because this listener can run
      // in the same frame as, but before, the driver's first easing step.
      stillFrames = Math.abs(p - lastProgress) > 1e-5 ? 0 : stillFrames + 1;
      lastProgress = p;
      if (stillFrames < 3) frame = requestAnimationFrame(tick);
    };

    const onScroll = () => {
      stillFrames = 0;
      if (frame === null) frame = requestAnimationFrame(tick);
    };

    tick();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [mission, scrollRef]);

  const value = useMemo(
    () => ({ mission, state: stateRef, phaseIndex, data: mission.data }),
    [mission, phaseIndex]
  );

  return <MissionContext.Provider value={value}>{children}</MissionContext.Provider>;
}

export default MissionController;
