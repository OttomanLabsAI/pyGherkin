# -*- coding: utf-8 -*-
"""Create floor slabs from a Geometry Dashboard floor-plates.csv.

CSV columns (the ones used here):
  id, level_name, base_z_m, thickness_mm, form, vertices_xy_m
where vertices_xy_m is a closed polygon "x y;x y;...;x y" in meters, centred
on the building axis. Both 'disc' and 'wedged' forms are handled uniformly
by building the floor boundary straight from this polygon, so wedge cut-outs
come through automatically.

Each floor is created at its named level. base_z_m is the slab BASE; Revit
floors hang below their level by default, so we set Height Offset From Level
so the slab TOP meets the level (toggle with SLAB_TOP_AT_LEVEL below).

Floor.Create's signature changed in Revit 2022. This handles both the modern
(CurveLoop list + type id + level id) and legacy (CurveArray + FloorType +
Level) APIs.
"""

__title__ = 'Import\nFloors'
__author__ = 'pyGherkin'
__doc__ = ('Reads floor-plates.csv exported from the Geometry Dashboard and '
           'creates floor slabs at their levels from each plate boundary '
           '(disc and wedged forms supported).')

from pyrevit import DB, forms, revit, script
from math import cos, sin

import pygherkin as pg

output = script.get_output()
doc = revit.doc

# If True, offset each slab down by its thickness so the slab TOP sits at the
# level elevation (base_z_m is the slab base). If False, the slab base sits at
# the level and it projects upward.
SLAB_TOP_AT_LEVEL = True

MIN_SEG_FT = 1.0 / 256.0   # Revit short-curve tolerance (~1.2 mm)


def parse_vertices(text):
    """'x y;x y;...' (meters) -> list of (x_ft, y_ft), de-duplicated and open
    (no repeated closing point)."""
    pts = []
    for chunk in text.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split()
        if len(parts) < 2:
            continue
        pts.append((pg.m_to_ft(parts[0]), pg.m_to_ft(parts[1])))
    # drop a duplicated closing vertex if present
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    # drop consecutive duplicates / near-duplicates below tolerance
    cleaned = []
    for p in pts:
        if not cleaned:
            cleaned.append(p)
            continue
        dx, dy = p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]
        if (dx * dx + dy * dy) ** 0.5 >= MIN_SEG_FT:
            cleaned.append(p)
    # final wrap segment tolerance
    if len(cleaned) >= 2:
        dx, dy = cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]
        if (dx * dx + dy * dy) ** 0.5 < MIN_SEG_FT:
            cleaned = cleaned[:-1]
    return cleaned


def split_boundary_loops(text):
    """Split a boundary string into outer + inner (hole) loops on the HOLE
    marker. Returns a list of segment-lists; first is the outer loop. The
    marker is written by the dashboard as ' ; HOLE ; ' between loops."""
    text = (text or '').strip()
    if not text:
        return []
    # tolerate optional surrounding semicolons around HOLE
    import re
    parts = re.split(r'\s*;?\s*HOLE\s*;?\s*', text)
    loops = []
    for part in parts:
        segs = parse_boundary(part)
        if len(segs) >= 2:
            loops.append(segs)
    return loops


def parse_boundary(text):
    """Decode the analytic boundary column into a list of segments in FEET:
       arc  -> ('A', cx, cy, r, a0, a1)   angles in radians, CCW a0->a1
       line -> ('L', x0, y0, x1, y1)
    Returns [] if the field is empty/unparseable (caller falls back to verts).
    """
    text = (text or '').strip()
    if not text:
        return []
    segs = []
    for tok in text.split('|'):
        f = tok.split()
        if not f:
            continue
        kind = f[0].upper()
        try:
            if kind == 'A' and len(f) >= 6:
                segs.append(('A', pg.m_to_ft(f[1]), pg.m_to_ft(f[2]),
                             pg.m_to_ft(f[3]), float(f[4]), float(f[5])))
            elif kind == 'L' and len(f) >= 5:
                segs.append(('L', pg.m_to_ft(f[1]), pg.m_to_ft(f[2]),
                             pg.m_to_ft(f[3]), pg.m_to_ft(f[4])))
        except Exception:
            return []   # malformed -> signal fallback
    return segs


def _arc_point(cx, cy, r, ang, z):
    return DB.XYZ(cx + r * cos(ang), cy + r * sin(ang), z)


def build_curveloop_from_boundary(segs, z_ft):
    """Closed DB.CurveLoop from analytic arc/line segments at height z.
    Endpoints are chained so consecutive curves share an exact point (we use
    the previous curve's end as the next curve's start), guaranteeing the loop
    closes despite CSV rounding."""
    loop = DB.CurveLoop()
    curves = []
    for s in segs:
        if s[0] == 'A':
            _, cx, cy, r, a0, a1 = s
            p0 = _arc_point(cx, cy, r, a0, z_ft)
            p1 = _arc_point(cx, cy, r, a1, z_ft)
            mid = _arc_point(cx, cy, r, a0 + (a1 - a0) * 0.5, z_ft)
            curves.append(('A', p0, p1, mid))
        else:
            _, x0, y0, x1, y1 = s
            curves.append(('L', DB.XYZ(x0, y0, z_ft), DB.XYZ(x1, y1, z_ft), None))

    n = len(curves)
    for i in range(n):
        kind, p0, p1, mid = curves[i]
        # snap this curve's start to the previous curve's end (exact closure)
        prev_end = curves[i - 1][2]
        start = prev_end
        end = p1
        if start.DistanceTo(p0) > 0.01:   # sanity: shouldn't drift far
            start = p0
        if kind == 'A':
            loop.Append(DB.Arc.Create(start, end, mid))
        else:
            if start.DistanceTo(end) < MIN_SEG_FT:
                continue
            loop.Append(DB.Line.CreateBound(start, end))
    return loop


def build_curveloop_from_points(pts_ft, z_ft):
    """Closed DB.CurveLoop from 2D points at height z."""
    loop = DB.CurveLoop()
    n = len(pts_ft)
    for i in range(n):
        a = pts_ft[i]
        b = pts_ft[(i + 1) % n]
        p0 = DB.XYZ(a[0], a[1], z_ft)
        p1 = DB.XYZ(b[0], b[1], z_ft)
        loop.Append(DB.Line.CreateBound(p0, p1))
    return loop


def _curvearray_from_loop(loop):
    arr = DB.CurveArray()
    for crv in loop:
        arr.Append(crv)
    return arr


def create_floor(loops_list, floor_type, level):
    """Create a floor from one or more DB.CurveLoops (first = outer boundary,
    rest = holes), using the modern API if present, else the legacy
    CurveArray one (holes unsupported on the very old path). Returns the Floor."""
    if not isinstance(loops_list, (list, tuple)):
        loops_list = [loops_list]
    if hasattr(DB.Floor, 'Create'):
        from System.Collections.Generic import List
        loops = List[DB.CurveLoop]()
        for lp in loops_list:
            loops.Add(lp)
        return DB.Floor.Create(doc, loops, floor_type.Id, level.Id)
    # legacy: outer loop only
    arr = _curvearray_from_loop(loops_list[0])
    return doc.Create.NewFloor(arr, floor_type, level, False)


def main():
    path = pg.pick_csv('Select floor-plates.csv exported from the Geometry Dashboard')
    if not path:
        return

    rows = pg.read_csv_rows(path)
    if not rows:
        forms.alert('No rows found in:\n{}'.format(path))
        return

    # validate columns early
    if 'level_name' not in rows[0] or 'base_z_m' not in rows[0]:
        forms.alert('This does not look like a floor-plates.csv export.\n'
                    'Missing column: level_name / base_z_m.')
        return
    has_boundary = 'boundary' in rows[0]
    has_verts = 'vertices_xy_m' in rows[0]
    if not has_boundary and not has_verts:
        forms.alert('floor-plates.csv has neither a "boundary" nor a '
                    '"vertices_xy_m" column - nothing to build floors from.')
        return

    floor_type = pg.pick_floor_type(doc, 'Floor type for all plates')
    if not floor_type:
        if not pg.collect_floor_types(doc):
            forms.alert('No (non-foundation) floor types are available in this '
                        'model.\nCreate or load a floor type first, then re-run.')
        return  # cancelled or none available

    pg.offer_cleanup(doc, [DB.BuiltInCategory.OST_Floors], 'floors')

    have_uids = bool(rows) and 'uid' in rows[0]
    placed, skipped, failed, curved, cored, uid_failed = 0, 0, 0, 0, 0, 0
    with revit.Transaction('pyGherkin - Import Floors'):
        if have_uids:
            pg.ensure_uid_param(doc)
        max_value = len(rows)
        with forms.ProgressBar(title='Placing floors ({value} of {max_value})',
                               cancellable=True) as pbar:
            for i, row in enumerate(rows):
                if pbar.cancelled:
                    output.print_md(':warning: Cancelled - partial import kept.')
                    break
                fid = (row.get('id') or str(i + 1)).strip()
                try:
                    name = row['level_name'].strip()
                    base_z_ft = pg.m_to_ft(row['base_z_m'])
                    level = pg.find_host_level(doc, name, base_z_ft)
                    if level is None:
                        failed += 1
                        if failed <= 10:
                            output.print_md(':cross_mark: floor {} - no level "{}"'
                                            .format(fid, name))
                        continue

                    # Prefer the analytic boundary (true arcs/curves, with any
                    # core hole as an inner loop); fall back to the faceted
                    # vertex ring if it's absent/bad.
                    loops = None
                    used_curves = False
                    holed = False
                    if has_boundary:
                        loop_segs = split_boundary_loops(row.get('boundary', ''))
                        if loop_segs:
                            try:
                                built = []
                                for ls in loop_segs:
                                    built.append(build_curveloop_from_boundary(
                                        ls, level.Elevation))
                                loops = built
                                used_curves = True
                                holed = len(built) > 1
                            except Exception:
                                loops = None
                    if loops is None:
                        if not has_verts:
                            failed += 1
                            continue
                        pts = parse_vertices(row.get('vertices_xy_m', ''))
                        if len(pts) < 3:
                            skipped += 1
                            continue
                        loops = [build_curveloop_from_points(pts, level.Elevation)]

                    # Build at the level plane; use Height Offset to position
                    # the slab so it stays associated to the level.
                    floor = create_floor(loops, floor_type, level)
                    if used_curves:
                        curved += 1
                    if holed:
                        cored += 1

                    # offset = where the slab sits relative to its level
                    offset = base_z_ft - level.Elevation
                    if SLAB_TOP_AT_LEVEL:
                        thk = floor_thickness_ft(floor, row)
                        offset -= thk   # drop so the top meets base_z
                    pg.set_param(
                        floor,
                        DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM,
                        offset)

                    pg.set_comments(floor, '{} Floor - {}'.format(pg.MARKER, row.get('form', '').strip()))
                    uid = (row.get('uid') or '').strip()
                    pg.set_mark(floor, uid or 'PG-FL-{}'.format(fid))
                    if uid and not pg.set_uid(floor, uid):
                        uid_failed += 1
                    placed += 1
                except Exception as err:
                    failed += 1
                    if failed <= 10:
                        output.print_md(':cross_mark: floor {} - {}'.format(fid, err))
                pbar.update_progress(i + 1, max_value)

    output.print_md('# pyGherkin - Floors import')
    output.print_md('Source: `{}`'.format(path))
    output.print_md('- Floors placed: **{}**'.format(placed))
    if curved:
        output.print_md('  - with true curved edges (arcs): **{}**'.format(curved))
    if placed - curved > 0 and curved > 0:
        output.print_md('  - from faceted vertex fallback: **{}**'.format(placed - curved))
    if cored:
        output.print_md('  - with a core cut (inner hole): **{}**'.format(cored))
    if skipped:
        output.print_md('- Skipped (degenerate boundary): **{}**'.format(skipped))
    if uid_failed:
        output.print_md('- Tracking ID not writable on: **{}**'.format(uid_failed))
    if failed:
        output.print_md('- Failed: **{}**'.format(failed))
    note = ('slab top aligned to base_z_m' if SLAB_TOP_AT_LEVEL
            else 'slab base aligned to base_z_m')
    output.print_md('*Vertical placement: {}. Toggle SLAB_TOP_AT_LEVEL at the '
                    'top of the script to flip this.*'.format(note))


def floor_thickness_ft(floor, row):
    """Slab thickness in feet: prefer the actual type thickness, fall back to
    the CSV thickness_mm, else 0."""
    try:
        ft_type = doc.GetElement(floor.GetTypeId())
        p = ft_type.get_Parameter(DB.BuiltInParameter.FLOOR_ATTR_DEFAULT_THICKNESS_PARAM)
        if p:
            v = p.AsDouble()
            if v > 0:
                return v
    except Exception:
        pass
    try:
        mm = float(row.get('thickness_mm', 0) or 0)
        return pg.m_to_ft(mm / 1000.0)
    except Exception:
        return 0.0


main()
