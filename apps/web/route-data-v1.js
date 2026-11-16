// Route geometry reproduced from the student site's public bootstrap feed.
// These are third-party APPROXIMATE route centerlines, not a surveyed road
// network, CCNY-official GPS, or a verified pickup-location inventory.
export const ROUTE_SOURCE = "Student public tracker · approximate path";
export const ROUTE_PATHS = Object.freeze([
  {
    "id": "northbound",
    "label": "Northbound to 145th St",
    "direction": "NB",
    "coordinates": [
      [
        40.811144,
        -73.953374
      ],
      [
        40.812709,
        -73.953141
      ],
      [
        40.814319,
        -73.953106
      ],
      [
        40.815889,
        -73.952855
      ],
      [
        40.817319,
        -73.95227
      ],
      [
        40.81833995298843,
        -73.95099996354817
      ],
      [
        40.81992752226471,
        -73.9496900738688
      ],
      [
        40.82147121104544,
        -73.94856206482446
      ],
      [
        40.822134,
        -73.94812
      ],
      [
        40.823377,
        -73.947192
      ],
      [
        40.824648,
        -73.946215
      ],
      [
        40.82393,
        -73.94458
      ]
    ]
  },
  {
    "id": "southbound",
    "label": "Southbound to 125th St",
    "direction": "SB",
    "coordinates": [
      [
        40.82393,
        -73.94458
      ],
      [
        40.822851,
        -73.94194
      ],
      [
        40.820331,
        -73.943781
      ],
      [
        40.821281,
        -73.946125
      ],
      [
        40.822134,
        -73.94812
      ],
      [
        40.82147121104544,
        -73.94856206482446
      ],
      [
        40.81992752226471,
        -73.9496900738688
      ],
      [
        40.81833995298843,
        -73.95099996354817
      ],
      [
        40.817319,
        -73.95227
      ],
      [
        40.815889,
        -73.952855
      ],
      [
        40.814319,
        -73.953106
      ],
      [
        40.812709,
        -73.953141
      ],
      [
        40.811021,
        -73.95425
      ],
      [
        40.810294,
        -73.953494
      ],
      [
        40.811144,
        -73.953374
      ]
    ]
  }
]);
export const ROUTE_STOPS = Object.freeze({
  "125": {
    "label": "125th St",
    "point": [
      40.811144,
      -73.953374
    ],
    "directions": [
      "NB"
    ],
    "terminal": true
  },
  "135": {
    "label": "135th St - Architecture",
    "point": [
      40.81833995298843,
      -73.95099996354817
    ],
    "directions": [
      "NB"
    ],
    "terminal": false
  },
  "marshak": {
    "label": "Marshak",
    "point": [
      40.81992752226471,
      -73.9496900738688
    ],
    "directions": [
      "NB",
      "SB"
    ],
    "terminal": false
  },
  "145": {
    "label": "145th St",
    "point": [
      40.82393,
      -73.94458
    ],
    "directions": [
      "SB"
    ],
    "terminal": true
  }
});
