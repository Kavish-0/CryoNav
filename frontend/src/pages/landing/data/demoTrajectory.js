/* ═══ demoTrajectory — REAL CryoNav backend geometry, baked at build time.

   Regenerated against the merged backend (2017–2024 cube, 50-member drift
   ensemble) from GET /bergs, POST /route and GET /observed on 2023-01-13:

     · A window of the real `balanced` corridor around the point where it
       passes closest to BERG_001 — true bearing and shape preserved.
     · The real `min_ice` corridor as the alternative route. The re-route
       in this experience is the router's own answer, not art.
     · The berg's real mean_track, with an uncertainty radius per step
       derived from the real 50-member ensemble spread.

   One deliberate distortion, stated plainly: berg drift is amplified 26x
   so 48 hours of real movement (a few km) reads at scene scale. Bearings,
   relative timing and route shape are untouched — which is why the HUD
   labels the experience a visualisation.

   Offline fallback; MissionController prefers live API data when reachable.
   ═══ */

const demoTrajectory = {
  "source": "CryoNav backend \u2014 GET /bergs, POST /route, GET /observed (2023-01-13)",
  "anchor": {
    "lat": -63.6847,
    "lon": 43.8119
  },
  "sceneScale": 0.4971,
  "driftAmplification": 26.0,
  "route": [
    [
      -237.28,
      -137.26
    ],
    [
      -229.33,
      -127.09
    ],
    [
      -217.59,
      -116.31
    ],
    [
      -180.0,
      -92.8
    ],
    [
      -157.42,
      -80.91
    ],
    [
      -134.22,
      -69.34
    ],
    [
      -110.93,
      -58.19
    ],
    [
      -70.39,
      -37.43
    ],
    [
      -56.9,
      -27.92
    ],
    [
      -47.17,
      -18.8
    ],
    [
      -38.87,
      -9.84
    ],
    [
      -30.73,
      -0.94
    ],
    [
      -13.87,
      16.73
    ],
    [
      -3.47,
      25.5
    ],
    [
      11.19,
      34.2
    ],
    [
      31.57,
      42.75
    ],
    [
      56.34,
      50.98
    ],
    [
      110.36,
      66.1
    ],
    [
      137.94,
      72.9
    ],
    [
      165.8,
      79.2
    ],
    [
      193.92,
      84.96
    ],
    [
      250.54,
      94.95
    ],
    [
      277.31,
      99.51
    ],
    [
      300.0,
      104.43
    ]
  ],
  "altRoute": [
    [
      2.58,
      -165.19
    ],
    [
      17.77,
      -148.13
    ],
    [
      33.31,
      -131.22
    ],
    [
      49.19,
      -114.48
    ],
    [
      65.44,
      -97.92
    ],
    [
      82.04,
      -81.53
    ],
    [
      98.78,
      -65.05
    ],
    [
      114.93,
      -47.62
    ],
    [
      130.25,
      -28.95
    ],
    [
      145.99,
      -10.46
    ],
    [
      163.34,
      6.4
    ],
    [
      182.09,
      21.91
    ],
    [
      201.5,
      36.9
    ],
    [
      221.34,
      51.64
    ],
    [
      241.84,
      65.81
    ],
    [
      263.68,
      78.43
    ],
    [
      287.1,
      89.2
    ],
    [
      310.93,
      99.64
    ],
    [
      334.05,
      111.32
    ],
    [
      356.68,
      123.92
    ],
    [
      379.54,
      136.51
    ]
  ],
  "berg": {
    "id": "BERG_001",
    "lengthM": 2646,
    "widthM": 1137,
    "track": [
      {
        "t": 0,
        "pos": [
          -105.8,
          74.18
        ]
      },
      {
        "t": 24,
        "pos": [
          -23.5,
          288.97
        ]
      },
      {
        "t": 48,
        "pos": [
          45.72,
          480.5
        ]
      },
      {
        "t": 72,
        "pos": [
          115.36,
          514.48
        ]
      },
      {
        "t": 96,
        "pos": [
          262.67,
          502.22
        ]
      },
      {
        "t": 120,
        "pos": [
          381.73,
          488.73
        ]
      },
      {
        "t": 144,
        "pos": [
          395.93,
          472.09
        ]
      },
      {
        "t": 168,
        "pos": [
          511.91,
          374.39
        ]
      }
    ],
    "spread": [
      0.0,
      4.55,
      6.94,
      7.36,
      7.73,
      9.12,
      9.08,
      9.19
    ],
    "members": 50
  },
  "seaIce": 0.0583,
  "metrics": {
    "min_ice": {
      "distance_nm": 3214.8,
      "time_h": 231.1,
      "fuel_t": 246.7,
      "ice_h": 3.2
    },
    "balanced": {
      "distance_nm": 3049.1,
      "time_h": 219.1,
      "fuel_t": 233.3,
      "ice_h": 3.2
    }
  }
};

export default demoTrajectory;
