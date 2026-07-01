# pyGherkin

A [pyRevit](https://github.com/eirannejad/pyRevit) extension that imports the
Geometry Dashboard's CSV exports (`levels.csv`, `floor-plates.csv`,
`framing.csv`, `connections.csv`) into a Revit model — creating levels, floor
slabs, diagrid framing and connection-node markers, with stable tracking IDs
that survive design iteration.

The extension lives in [`pyGherkin.extension/`](pyGherkin.extension). See its
[README](pyGherkin.extension/README.md) for full install instructions, the
import workflow, tracking-ID / in-place-update behaviour and tuning options.

## Layout

```
pyGherkin.extension/
├── lib/pygherkin/          shared CSV / units / level / uid-tracking helpers
└── pyGherkin.tab/          the pyGherkin ribbon tab
    ├── Data.panel/         reserved (empty until it gets a button)
    ├── Levels.panel/       Import Levels
    ├── Floors.panel/       Import Floors
    └── Structural.panel/   Import Framing, Import Connections
```

## Install (quick)

1. Copy the `pyGherkin.extension` folder somewhere permanent, e.g.
   `%APPDATA%\pyRevit\Extensions\pyGherkin.extension`.
2. If you used a custom location: pyRevit tab > Settings > Custom Extension
   Directories > add the folder *containing* `pyGherkin.extension`.
3. pyRevit tab > Reload. A **pyGherkin** tab appears.

Requires pyRevit 4.8+ (scripts run on the default IronPython engine and are
CPython3-compatible).

Coordinates: meters, origin at building centre, base at Z=0, +Z up; converted
to Revit internal feet on import (1 ft = 0.3048 m exactly).
