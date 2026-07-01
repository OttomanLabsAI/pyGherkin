# -*- coding: utf-8 -*-
"""Place structural framing (diagrid beams) from a Geometry Dashboard
framing.csv.

CSV columns:
  id, group, level_index, level_name,
  start_x_m, start_y_m, start_z_m, end_x_m, end_y_m, end_z_m,
  length_m, rotation_deg, rotation_rad, up_x, up_y, up_z

For each distinct value in the `group` column (currently just "Diagonal")
the user is asked to pick a loaded Structural Framing type. Beams are placed
start -> end (meters converted to feet), referenced to their host level,
centred on the location line (yz/y/z Justification = Center), and their
Cross-Section Rotation is set from `rotation_rad` so the beam bottom faces
the building centre.

ROTATION CAVEAT: rotation_rad assumes the common "default up = global +Z"
family convention. If beams come in rotated or mirrored, adjust
ROTATION_SIGN / ROTATION_OFFSET_DEG below (the CSV also carries the desired
up vector in up_x/y/z if you ever want to orient against that directly).
"""

__title__ = 'Import\nFraming'
__author__ = 'pyGherkin'
__doc__ = ('Reads framing.csv exported from the Geometry Dashboard and '
           'places diagrid beams (one type prompt per group), setting '
           'Cross-Section Rotation so the beam bottom faces the centre.')

import math

from pyrevit import DB, forms, revit, script
from Autodesk.Revit.DB.Structure import StructuralType, StructuralFramingUtils

import pygherkin as pg

output = script.get_output()
doc = revit.doc

# ---- rotation tuning (see module docstring) --------------------------------
ROTATION_SIGN = 1.0          # set to -1.0 if beams come in mirrored
ROTATION_OFFSET_DEG = 0.0    # add a fixed offset (e.g. 90 / 180) if needed
# ---- overshoot control ------------------------------------------------------
# Revit auto-joins framing whose endpoints coincide and applies miter/extension
# geometry that pushes a beam PAST its endpoint at multi-member diagrid hubs.
# Disallowing the join at each end terminates the beam on its endpoint.
# (Revit re-runs join logic when an element is added, so we disallow joins
# AFTER placement.) If a particular family still shows a stub, FORCE_CUTBACK
# additionally uses FamilyInstance.ExtensionUtility to set both ends to
# cutback (Extended=False) rather than extended.
DISALLOW_JOINS = True
FORCE_CUTBACK = True
# ---- justification ----------------------------------------------------------
# Place each beam with its cross-section centred on the diagrid location line
# (yz Justification = Uniform, y = Center, z = Center) instead of the family's
# default (often top-of-steel / origin), which makes the section hang off the
# line. Enum integer values below match Revit's Geometric Position options.
CENTER_JUSTIFY = True
YZ_UNIFORM = 0     # yz Justification: Uniform (0) / Independent (1)
J_CENTER = 2       # y: Origin0 Left1 Center2 Right3 ; z: Origin0 Top1 Center2 Bottom3
# -----------------------------------------------------------------------------

MIN_LENGTH_FT = 1.0 / 256.0  # Revit's short-curve tolerance


def parse_rows(rows):
    parsed, malformed = [], 0
    for row in rows:
        try:
            parsed.append({
                'id': row['id'].strip(),
                'uid': (row.get('uid') or '').strip(),
                'group': row['group'].strip(),
                'level_name': row['level_name'].strip(),
                'start': pg.xyz_ft(row['start_x_m'], row['start_y_m'], row['start_z_m']),
                'end': pg.xyz_ft(row['end_x_m'], row['end_y_m'], row['end_z_m']),
                'rot_rad': float(row['rotation_rad']),
            })
        except Exception:
            malformed += 1
    return parsed, malformed


def kill_overshoot(beam):
    """Stop the beam solid from extending past its endpoints.

    The overshoot at diagrid hubs is Revit's automatic miter/extension when
    coincident beam ends join. Disallowing the join at each end makes the beam
    terminate on its location-line endpoint. Revit re-evaluates joins when an
    element is first added, so this MUST run after the beam is in the document
    (it does - we call it right after NewFamilyInstance).

    Returns True if both ends were handled.
    """
    if not DISALLOW_JOINS:
        return True
    ok = True
    for end in (0, 1):
        try:
            StructuralFramingUtils.DisallowJoinAtEnd(beam, end)
        except Exception:
            ok = False
    # Belt-and-braces: if the family exposes setback control, force both ends
    # to cutback (Extended=False) so no miter/extension stub remains.
    if FORCE_CUTBACK:
        try:
            ext = beam.ExtensionUtility
            if ext is not None:
                for end in (0, 1):
                    try:
                        ext.set_Extended(end, False)
                    except Exception:
                        try:
                            ext.Extended[end] = False
                        except Exception:
                            pass
        except Exception:
            pass
    return ok


def center_justify(beam):
    """Center the beam cross-section on its location line (yz = Uniform,
    y = Center, z = Center). Integer enum values: yz {Uniform 0, Independent
    1}; y {Origin 0, Left 1, Center 2, Right 3}; z {Origin 0, Top 1, Center 2,
    Bottom 3}. Set yz Uniform first so a single y/z applies to both ends.
    Whether the section truly centers also depends on the family having a
    Center reference, but this is the standard, correct way to request it.
    Returns True if y and z were both set."""
    if not CENTER_JUSTIFY:
        return True
    # yz Justification -> Uniform (best-effort; not fatal if absent)
    pg.set_param(beam, DB.BuiltInParameter.YZ_JUSTIFICATION, YZ_UNIFORM)
    y_ok = pg.set_param(beam, DB.BuiltInParameter.Y_JUSTIFICATION, J_CENTER)
    z_ok = pg.set_param(beam, DB.BuiltInParameter.Z_JUSTIFICATION, J_CENTER)
    return y_ok and z_ok


def main():
    path = pg.pick_csv('Select framing.csv exported from the Geometry Dashboard')
    if not path:
        return

    rows = pg.read_csv_rows(path)
    parsed, malformed = parse_rows(rows)
    if not parsed:
        forms.alert('Could not parse any rows - is this a framing.csv export?')
        return

    # one beam type per distinct group, in order of first appearance
    groups = []
    for m in parsed:
        if m['group'] not in groups:
            groups.append(m['group'])

    group_symbols = {}
    for grp in groups:
        sym = pg.pick_symbol(doc, [DB.BuiltInCategory.OST_StructuralFraming],
                             'Beam type for group "{}"'.format(grp))
        if not sym:
            syms_exist = pg.collect_symbols(
                doc, [DB.BuiltInCategory.OST_StructuralFraming])
            if not syms_exist:
                forms.alert('No Structural Framing types are loaded in this '
                            'model.\nLoad a beam family first (Insert > Load '
                            'Family), then re-run.')
            return  # cancelled or nothing loaded - abort cleanly
        group_symbols[grp] = sym

    # --- decide sync vs clean replace -------------------------------------
    have_uids = any(m['uid'] for m in parsed)
    existing = {}
    do_sync = False
    if have_uids:
        existing_all = pg.index_by_uid(
            doc, [DB.BuiltInCategory.OST_StructuralFraming])
        if existing_all:
            do_sync = forms.alert(
                'Found {} previously imported beams with tracking IDs.\n\n'
                'UPDATE IN PLACE keeps their Revit element IDs (and any tags / '
                'dimensions / schedules attached) and just moves/updates the '
                'ones that changed.\n\nDELETE & REPLACE removes them all and '
                'places a fresh set (tags will be lost).'.format(len(existing_all)),
                options=['Update in place', 'Delete & replace'])
            if do_sync == 'Update in place':
                do_sync = True
                existing = existing_all
            else:
                do_sync = False
    if not do_sync:
        pg.offer_cleanup(doc, [DB.BuiltInCategory.OST_StructuralFraming], 'beams')

    rot_offset = math.radians(ROTATION_OFFSET_DEG)
    placed, updated, skipped_short, failed = 0, 0, 0, 0
    rot_failed, join_failed, just_failed, uid_failed = 0, 0, 0, 0
    seen_uids = set()

    with revit.Transaction('pyGherkin - Import Framing'):
        if have_uids:
            pg.ensure_uid_param(doc)
        pg.activate_symbols(doc, group_symbols.values())
        max_value = len(parsed)
        with forms.ProgressBar(title='Placing beams ({value} of {max_value})',
                               cancellable=True) as pbar:
            for i, m in enumerate(parsed):
                if pbar.cancelled:
                    output.print_md(':warning: Cancelled - partial import kept.')
                    break
                try:
                    if m['start'].DistanceTo(m['end']) < MIN_LENGTH_FT:
                        skipped_short += 1
                        continue
                    line = DB.Line.CreateBound(m['start'], m['end'])
                    lvl = pg.find_host_level(doc, m['level_name'], m['start'].Z)

                    beam = None
                    is_update = False
                    if do_sync and m['uid'] and m['uid'] in existing:
                        beam = existing[m['uid']]
                        is_update = True
                        # move the existing beam's location line to new ends
                        try:
                            beam.Location.Curve = line
                        except Exception:
                            # fall back to recreate if the curve can't be reset
                            try:
                                doc.Delete(beam.Id)
                            except Exception:
                                pass
                            beam = None
                            is_update = False

                    if beam is None:
                        beam = doc.Create.NewFamilyInstance(
                            line, group_symbols[m['group']], lvl,
                            StructuralType.Beam)

                    if not kill_overshoot(beam):
                        join_failed += 1
                    if not center_justify(beam):
                        just_failed += 1
                    rot_ok = pg.set_param(
                        beam, DB.BuiltInParameter.STRUCTURAL_BEND_DIR_ANGLE,
                        ROTATION_SIGN * m['rot_rad'] + rot_offset)
                    if not rot_ok:
                        rot_failed += 1
                    pg.set_comments(beam, '{} Framing - {}'.format(pg.MARKER, m['group']))
                    pg.set_mark(beam, m['uid'] or 'PG-F-{}'.format(m['id']))
                    if m['uid']:
                        if not pg.set_uid(beam, m['uid']):
                            uid_failed += 1
                        seen_uids.add(m['uid'])

                    if is_update:
                        updated += 1
                    else:
                        placed += 1
                except Exception as err:
                    failed += 1
                    if failed <= 10:
                        output.print_md(':cross_mark: member {} - {}'.format(m['id'], err))
                pbar.update_progress(i + 1, max_value)

        # remove orphans: previously-synced beams whose uid is gone from export
        orphaned = 0
        if do_sync:
            stale = [e for uid, e in existing.items() if uid not in seen_uids]
            if stale and forms.alert(
                    '{} previously imported beams are no longer in this '
                    'export.\nDelete them?'.format(len(stale)),
                    yes=True, no=True):
                for e in stale:
                    try:
                        doc.Delete(e.Id)
                        orphaned += 1
                    except Exception:
                        pass

    output.print_md('# pyGherkin - Framing import')
    output.print_md('Source: `{}`'.format(path))
    if do_sync:
        output.print_md('- Beams updated in place (IDs/tags kept): **{}**'.format(updated))
        output.print_md('- New beams placed: **{}**'.format(placed))
        if orphaned:
            output.print_md('- Orphaned beams deleted: **{}**'.format(orphaned))
    else:
        output.print_md('- Beams placed: **{}**'.format(placed))
    if skipped_short:
        output.print_md('- Skipped (too short): **{}**'.format(skipped_short))
    if uid_failed:
        output.print_md('- Tracking ID not writable on: **{}**'.format(uid_failed))
    if rot_failed:
        output.print_md('- Cross-Section Rotation not settable: **{}**'.format(rot_failed))
    if join_failed:
        output.print_md('- Could not disable joins on: **{}**'.format(join_failed))
    if just_failed:
        output.print_md('- Could not centre-justify: **{}**'.format(just_failed))
    if malformed:
        output.print_md('- Malformed rows skipped: **{}**'.format(malformed))
    if failed:
        output.print_md('- Failed: **{}**'.format(failed))
    output.print_md('*Beam joins are disabled so members end on their nodes '
                    'rather than mitering past them. If any family still '
                    'overshoots, confirm FORCE_CUTBACK is on; if beams look '
                    'rotated/mirrored, tweak ROTATION_SIGN / '
                    'ROTATION_OFFSET_DEG at the top of this script.*')


main()
