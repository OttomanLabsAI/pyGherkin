# -*- coding: utf-8 -*-
"""Place connection (hub) markers from a Geometry Dashboard connections.csv.

CSV columns:
  id, type, level_index, point_index, x_m, y_m, z_m, member_count, member_ids

A "connection" is each diagrid node where members meet. For every distinct
hub TYPE in the file (Base / Interior / Apex) the user picks a loaded
point-based family type (Structural Connections or Generic Models category)
- e.g. a node/gusset/sphere family - and one instance is placed at each hub.

Each instance gets:
  Mark      = PG-C-<id>
  Comments  = pyGherkin Connection - <type> - <n> members - ids <member ids>

so hubs can be scheduled, filtered and cleaned up later.

Note: this places marker/joint FAMILY INSTANCES at the node coordinates. It
does not create native Revit steel connections (StructuralConnectionHandler),
which must be attached to already-joined members and is type-specific - do
that as a follow-up pass on the placed beams if required.
"""

__title__ = 'Import\nConnections'
__author__ = 'pyGherkin'
__doc__ = ('Reads connections.csv exported from the Geometry Dashboard and '
           'places a chosen node family at every diagrid hub (one type '
           'prompt per hub type: Base / Interior / Apex).')

import math

from pyrevit import DB, forms, revit, script
from Autodesk.Revit.DB.Structure import StructuralType

import pygherkin as pg

output = script.get_output()
doc = revit.doc

# Rotate each instance about Z so its X-axis points radially outward
# (useful for direction-sensitive node families). Set False to skip.
ALIGN_RADIALLY = True

HUB_CATEGORIES = [DB.BuiltInCategory.OST_StructConnections,
                  DB.BuiltInCategory.OST_GenericModel]


def parse_rows(rows):
    parsed, malformed = [], 0
    for row in rows:
        try:
            parsed.append({
                'id': row['id'].strip(),
                'uid': (row.get('uid') or '').strip(),
                'type': row['type'].strip(),
                'point': pg.xyz_ft(row['x_m'], row['y_m'], row['z_m']),
                'count': row['member_count'].strip(),
                'members': row['member_ids'].strip(),
            })
        except Exception:
            malformed += 1
    return parsed, malformed


def place_hub(point, symbol, level):
    """Place a point family instance at `point`, correcting the elevation if
    Revit snaps a level-based family to the level plane."""
    try:
        inst = doc.Create.NewFamilyInstance(point, symbol, level,
                                            StructuralType.NonStructural)
    except Exception:
        inst = doc.Create.NewFamilyInstance(point, symbol,
                                            StructuralType.NonStructural)
    loc = inst.Location
    if isinstance(loc, DB.LocationPoint):
        dz = point.Z - loc.Point.Z
        if abs(dz) > 1e-6:
            DB.ElementTransformUtils.MoveElement(doc, inst.Id,
                                                 DB.XYZ(0, 0, dz))
    return inst


def align_radially(inst, point):
    if abs(point.X) < 1e-9 and abs(point.Y) < 1e-9:
        return   # node on the building axis - no radial direction
    angle = math.atan2(point.Y, point.X)
    axis = DB.Line.CreateBound(point, point + DB.XYZ.BasisZ)
    DB.ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle)


def main():
    path = pg.pick_csv('Select connections.csv exported from the Geometry Dashboard')
    if not path:
        return

    rows = pg.read_csv_rows(path)
    parsed, malformed = parse_rows(rows)
    if not parsed:
        forms.alert('Could not parse any rows - is this a connections.csv export?')
        return

    # one family type per hub type, in order of first appearance
    hub_types = []
    for c in parsed:
        if c['type'] not in hub_types:
            hub_types.append(c['type'])

    type_symbols = {}
    for ht in hub_types:
        sym = pg.pick_symbol(doc, HUB_CATEGORIES,
                             'Node family for "{}" hubs'.format(ht))
        if not sym:
            if not pg.collect_symbols(doc, HUB_CATEGORIES):
                forms.alert('No Structural Connection or Generic Model types '
                            'are loaded in this model.\nLoad a point-based '
                            'node family first (Insert > Load Family), then '
                            're-run.')
            return  # cancelled or nothing loaded - abort cleanly
        type_symbols[ht] = sym

    have_uids = any(c['uid'] for c in parsed)
    existing = {}
    do_sync = False
    if have_uids:
        existing_all = pg.index_by_uid(doc, HUB_CATEGORIES)
        if existing_all:
            choice = forms.alert(
                'Found {} previously imported connection nodes with tracking '
                'IDs.\n\nUPDATE IN PLACE keeps their element IDs and any tags / '
                'schedules.\nDELETE & REPLACE removes them and places a fresh '
                'set.'.format(len(existing_all)),
                options=['Update in place', 'Delete & replace'])
            if choice == 'Update in place':
                do_sync = True
                existing = existing_all
    if not do_sync:
        pg.offer_cleanup(doc, HUB_CATEGORIES, 'connection markers')

    placed, updated, failed, uid_failed = 0, 0, 0, 0
    seen_uids = set()
    with revit.Transaction('pyGherkin - Import Connections'):
        if have_uids:
            pg.ensure_uid_param(doc)
        pg.activate_symbols(doc, type_symbols.values())
        max_value = len(parsed)
        with forms.ProgressBar(title='Placing connections ({value} of {max_value})',
                               cancellable=True) as pbar:
            for i, c in enumerate(parsed):
                if pbar.cancelled:
                    output.print_md(':warning: Cancelled - partial import kept.')
                    break
                try:
                    lvl = pg.nearest_level(doc, c['point'].Z)
                    inst = None
                    is_update = False
                    if do_sync and c['uid'] and c['uid'] in existing:
                        inst = existing[c['uid']]
                        is_update = True
                        loc = inst.Location
                        if isinstance(loc, DB.LocationPoint):
                            delta = c['point'] - loc.Point
                            if delta.GetLength() > 1e-9:
                                DB.ElementTransformUtils.MoveElement(
                                    doc, inst.Id, delta)
                    if inst is None:
                        inst = place_hub(c['point'], type_symbols[c['type']], lvl)
                    if ALIGN_RADIALLY and not is_update:
                        loc = inst.Location
                        pt = loc.Point if isinstance(loc, DB.LocationPoint) else c['point']
                        align_radially(inst, pt)
                    pg.set_comments(inst, '{} Connection - {} - {} members - ids {}'
                                    .format(pg.MARKER, c['type'], c['count'], c['members']))
                    pg.set_mark(inst, c['uid'] or 'PG-C-{}'.format(c['id']))
                    if c['uid']:
                        if not pg.set_uid(inst, c['uid']):
                            uid_failed += 1
                        seen_uids.add(c['uid'])
                    if is_update:
                        updated += 1
                    else:
                        placed += 1
                except Exception as err:
                    failed += 1
                    if failed <= 10:
                        output.print_md(':cross_mark: hub {} - {}'.format(c['id'], err))
                pbar.update_progress(i + 1, max_value)

        orphaned = 0
        if do_sync:
            stale = [e for uid, e in existing.items() if uid not in seen_uids]
            if stale and forms.alert(
                    '{} previously imported nodes are no longer in this '
                    'export.\nDelete them?'.format(len(stale)),
                    yes=True, no=True):
                for e in stale:
                    try:
                        doc.Delete(e.Id)
                        orphaned += 1
                    except Exception:
                        pass

    output.print_md('# pyGherkin - Connections import')
    output.print_md('Source: `{}`'.format(path))
    if do_sync:
        output.print_md('- Nodes updated in place (IDs/tags kept): **{}**'.format(updated))
        output.print_md('- New nodes placed: **{}**'.format(placed))
        if orphaned:
            output.print_md('- Orphaned nodes deleted: **{}**'.format(orphaned))
    else:
        output.print_md('- Hubs placed: **{}**'.format(placed))
    if uid_failed:
        output.print_md('- Tracking ID not writable on: **{}**'.format(uid_failed))
    if malformed:
        output.print_md('- Malformed rows skipped: **{}**'.format(malformed))
    if failed:
        output.print_md('- Failed: **{}**'.format(failed))
    output.print_md('*Each hub carries its stable tracking ID in the '
                    '"pyGherkin UID" parameter (taggable/schedulable) and in '
                    'Mark, plus type/member info in Comments.*')


main()
