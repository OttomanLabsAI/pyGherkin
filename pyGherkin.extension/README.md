# pyGherkin

A pyRevit extension that imports the Geometry Dashboard's CSV exports
(`levels.csv`, `framing.csv`, `connections.csv`) into a Revit model.

## Ribbon layout

```
pyGherkin tab
├── Data        (far left - reserved, empty for now; hidden until it gets a button)
├── Levels
│   └── Import Levels
├── Floors
│   └── Import Floors
├── Structural
│   ├── Import Framing
│   └── Import Connections
└── pyGherkin v1.0   (Updates panel - titled with the current version)
    └── Install Update
```

Panel order is pinned in `pyGherkin.tab/bundle.yaml` (`layout:` key), so
`Data` will always sit on the far left once it has content. Revit hides
ribbon panels that contain no buttons, which is why Data is invisible until
its first `*.pushbutton` folder is added.

## Updates

The **pyGherkin vX.Y.Z** panel (far right) shows the installed version in its
title and holds **Install Update**, which fetches the newest published
`pyGherkin.extension` from GitHub (latest release, else newest tag, else the
default branch), compares it against `version.txt`, and installs it in one go —
the live folder is moved to `00 - Superseded\pyGherkin\...` (with automatic
rollback on failure), then pyRevit offers to reload. For a private repo or to
avoid API rate limits, set `github_token` (and optionally `github_repo`,
`update_downloads_folder`) in `%APPDATA%\pyRevit\pyGherkin_settings.json`.

## Install

1. Copy the `pyGherkin.extension` folder somewhere permanent, e.g.
   `%APPDATA%\pyRevit\Extensions\pyGherkin.extension`
   (or any folder you like).
2. If you did not use the default Extensions folder: pyRevit tab >
   Settings > Custom Extension Directories > add the folder *containing*
   `pyGherkin.extension`.
3. pyRevit tab > Reload. A **pyGherkin** tab appears.

Requires pyRevit 4.8+ (any recent release; scripts run on the default
IronPython engine and are CPython3-compatible too).

## Workflow

1. In the Geometry Dashboard, design the tower and press **Export CSV**
   (downloads `levels.csv`, `framing.csv`, `connections.csv`, and - if you
   are using the floor generator - `floor-plates.csv`).
2. **Import Levels** - creates levels (name + elevation, m -> ft).
   Re-running updates elevations of same-named levels, so you can iterate.
3. **Import Floors** - asks for one floor type, then creates a floor slab at
   each plate's level from its boundary. If the export has a `boundary`
   column (arcs + lines), slabs are placed with TRUE CURVED edges - discs
   become real circles, wedged plates keep their circular rim arcs - instead
   of faceted polygons. A centred **core cut** (inner circular hole) is
   carried in the same boundary after a `HOLE` marker and comes through as a
   real opening in the slab. Older exports with only `vertices_xy_m` still
   work (faceted fallback, outer boundary only). `base_z_m` is the slab base;
   by default each slab is offset so its TOP meets that elevation (toggle
   `SLAB_TOP_AT_LEVEL`).
4. **Import Framing** - asks for a beam type per `group` (currently just
   "Diagonal"), places beams start -> end on their host level, and sets
   **Cross-Section Rotation** from `rotation_rad` so beam bottoms face the
   building centre.
5. **Import Connections** - asks for a node family per hub type
   (Base / Interior / Apex) and places one instance per diagrid hub, with
   the hub's type, member count and member ids written into Comments and
   `PG-C-<id>` into Mark.

Coordinates: meters, origin at building centre, base at Z=0, +Z up.
Conversion: x 3.280839895 (exact 1/0.3048) to Revit internal feet. Place the
model relative to the Revit project origin (or move it afterwards).

## Tracking IDs (stable round-trip, taggable)

Every element the dashboard exports carries a stable `uid` derived from its
place in the structure, not its row position:

- Levels: `L-<levelIndex>`            (e.g. `L-3`)
- Framing: `F-<lowerLevel>-<startK>-<endK>`  (e.g. `F-3-5-6`)
- Connections: `C-<level>-<pointIndex>`      (e.g. `C-3-5`)
- Floors: `FL-<levelIndex>`           (e.g. `FL-7`)

These are invariant: a given diagonal keeps the same uid across re-exports
even when you add levels, change the profile elsewhere, or re-order the CSV.
A uid only changes if that element's actual position in the diagrid changes.

On import, the add-in creates a project SHARED PARAMETER called
**"pyGherkin UID"** (instance, Identity Data) and writes each element's uid
into it. Because it is a shared parameter it is **taggable, schedulable and
filterable** - unlike Comments/Mark. The uid is also mirrored into Mark.

**In-place update.** When you re-run Import Framing or Import Connections and
the model already contains tracked elements, you are offered:

- **Update in place** - elements whose uid still exists are moved/updated
  *keeping their Revit ElementId*, so any tags, dimensions and schedule rows
  attached to them stay valid. New uids are created; uids no longer in the
  export can be deleted on confirmation.
- **Delete & replace** - the old behaviour (remove all, place fresh; tags
  are lost).

This is what keeps tags consistent through design iteration: tweak the tower,
re-export, choose Update in place, and your annotation survives.

Levels and Floors are matched by name / level and updated in place already;
they also receive the `pyGherkin UID` parameter for tagging and scheduling.

## Re-import / cleanup
Everything pyGherkin places carries a `pyGherkin` marker at the start of its
Comments parameter. Import Floors, Import Framing and Import Connections
detect previous imports and offer to delete them first, so re-running after a
dashboard tweak is safe. Levels are never deleted - matching names update in
place.

## Rotation caveat (from the dashboard handoff)

`rotation_rad` assumes the common "default up = global +Z" beam family
convention. Revit families vary; if placed beams look rotated or mirrored,
open `Structural.panel/Framing.pushbutton/script.py` and adjust:

```python
ROTATION_SIGN = 1.0          # -1.0 if mirrored
ROTATION_OFFSET_DEG = 0.0    # e.g. 90 or 180 if consistently off
```

The CSV also carries the desired up vector (`up_x/y/z`) per member if you
ever want to orient against that directly instead.

## Connections - scope note

Import Connections places point-based FAMILY INSTANCES (Structural
Connections or Generic Models category) at the hub coordinates - markers /
node geometry, not native Revit steel connections.
`StructuralConnectionHandler` connections must reference already-joined
members and are connection-type specific; treat that as a follow-up pass on
the placed beams if your workflow needs it.

## Customising

- `lib/pygherkin/__init__.py` - shared CSV / units / level / cleanup helpers.
- `Connections.pushbutton/script.py` - `ALIGN_RADIALLY` rotates each hub so
  its family X-axis points outward from the building axis; set `False` to
  keep all hubs world-aligned.
