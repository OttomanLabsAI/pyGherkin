# -*- coding: utf-8 -*-
"""Create or update Revit Levels from a Geometry Dashboard levels.csv.

CSV columns: index, name, elevation_m, radius_m
Elevations are meters above the building base (Z=0).

Behaviour:
- a level whose NAME already exists gets its elevation updated (so you can
  iterate: tweak the spline, re-export, re-run)
- anything else is created fresh
- nothing is ever deleted

Note: Level.Create does not create plan views. Use the View tab
(Plan Views > Structural Plan) afterwards if you need them.
"""

__title__ = 'Import\nLevels'
__author__ = 'pyGherkin'
__doc__ = ('Reads levels.csv exported from the Geometry Dashboard and '
           'creates Revit Levels (name + elevation, meters to feet). '
           'Levels with a matching name are updated in place.')

from pyrevit import DB, forms, revit, script

import pygherkin as pg

output = script.get_output()
doc = revit.doc

ELEV_TOL_FT = 1e-6   # treat smaller elevation deltas as "unchanged"


def main():
    path = pg.pick_csv('Select levels.csv exported from the Geometry Dashboard')
    if not path:
        return

    rows = pg.read_csv_rows(path)
    if not rows:
        forms.alert('No rows found in:\n{}'.format(path))
        return

    parsed, malformed = [], 0
    for row in rows:
        try:
            parsed.append((row['name'].strip(), pg.m_to_ft(row['elevation_m']),
                           (row.get('uid') or '').strip()))
        except Exception:
            malformed += 1
    if not parsed:
        forms.alert('Could not parse any rows - is this a levels.csv export?\n'
                    'Expected columns: index, name, elevation_m, radius_m.')
        return
    parsed.sort(key=lambda nv: nv[1])   # bottom-up

    have_uids = any(p[2] for p in parsed)
    created, updated, unchanged, failed = 0, 0, 0, 0
    with revit.Transaction('pyGherkin - Import Levels'):
        if have_uids:
            pg.ensure_uid_param(doc)
        for name, elev_ft, uid in parsed:
            try:
                lvl = pg.level_by_name(doc, name)
                if lvl:
                    if abs(lvl.Elevation - elev_ft) > ELEV_TOL_FT:
                        lvl.Elevation = elev_ft
                        updated += 1
                    else:
                        unchanged += 1
                else:
                    lvl = DB.Level.Create(doc, elev_ft)
                    lvl.Name = name
                    created += 1
                if uid:
                    pg.set_uid(lvl, uid)
            except Exception as err:
                failed += 1
                output.print_md(':cross_mark: **{}** - {}'.format(name, err))

    output.print_md('# pyGherkin - Levels import')
    output.print_md('Source: `{}`'.format(path))
    output.print_md('- Created: **{}**'.format(created))
    output.print_md('- Updated elevation: **{}**'.format(updated))
    output.print_md('- Unchanged: **{}**'.format(unchanged))
    if malformed:
        output.print_md('- Malformed rows skipped: **{}**'.format(malformed))
    if failed:
        output.print_md('- Failed: **{}**'.format(failed))
    output.print_md('*Levels are created without plan views; add Structural '
                    'Plans from the View tab if needed.*')


main()
