# -*- coding: utf-8 -*-
"""Shared helpers for the pyGherkin importer tools.

All geometry coming from the Geometry Dashboard is in METERS, origin at the
building centre, base at Z=0, +Z up. Revit internal units are decimal feet,
so everything is converted on the way in via m_to_ft().
"""

import csv

from pyrevit import DB, forms, revit

# meters -> Revit internal units (decimal feet). 1 ft = 0.3048 m exactly.
M_TO_FT = 1.0 / 0.3048

# Marker written into the Comments parameter of every element placed by
# pyGherkin, so re-imports can find and clean up previous runs.
MARKER = 'pyGherkin'


# ---------------------------------------------------------------- units / io

def m_to_ft(value):
    return float(value) * M_TO_FT


def xyz_ft(x_m, y_m, z_m):
    """Build a Revit XYZ (internal feet) from meter coordinates."""
    return DB.XYZ(m_to_ft(x_m), m_to_ft(y_m), m_to_ft(z_m))


def pick_csv(title):
    """Ask the user for a CSV file. Returns a path or None."""
    return forms.pick_file(file_ext='csv', title=title)


def _clean_field(name):
    if not name:
        return name
    for bom in ('\xef\xbb\xbf', u'\ufeff'):
        try:
            name = name.replace(bom, '')
        except Exception:
            pass
    return name.strip()


def read_csv_rows(path):
    """Read a CSV into a list of dicts; tolerates a UTF-8 BOM in the header
    (added by Excel if the file was opened and re-saved)."""
    rows = []
    with open(path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        if reader.fieldnames:
            reader.fieldnames = [_clean_field(f) for f in reader.fieldnames]
        for row in reader:
            rows.append(row)
    return rows


# ------------------------------------------------------------------- levels

def get_levels(doc):
    return list(DB.FilteredElementCollector(doc)
                .OfClass(DB.Level)
                .ToElements())


def level_by_name(doc, name):
    for lvl in get_levels(doc):
        if revit.query.get_name(lvl) == name:
            return lvl
    return None


def nearest_level(doc, elevation_ft):
    best, best_d = None, None
    for lvl in get_levels(doc):
        d = abs(lvl.Elevation - elevation_ft)
        if best is None or d < best_d:
            best, best_d = lvl, d
    return best


def find_host_level(doc, name, elevation_ft):
    """Prefer an exact name match (levels.csv names), else the level
    nearest to the given elevation."""
    return level_by_name(doc, name) or nearest_level(doc, elevation_ft)


# ------------------------------------------------------------- family types

def symbol_label(sym):
    try:
        fam = sym.FamilyName
    except Exception:
        fam = '?'
    return '{} : {}'.format(fam, revit.query.get_name(sym))


def collect_symbols(doc, builtin_cats):
    syms = []
    for bic in builtin_cats:
        col = (DB.FilteredElementCollector(doc)
               .OfCategory(bic)
               .WhereElementIsElementType())
        for s in col:
            if isinstance(s, DB.FamilySymbol):
                syms.append(s)
    return syms


def pick_symbol(doc, builtin_cats, title):
    """Let the user pick a loaded family type from the given categories.
    Returns the FamilySymbol, or None if cancelled / nothing loaded."""
    syms = collect_symbols(doc, builtin_cats)
    if not syms:
        return None
    labels = {}
    for s in syms:
        labels[symbol_label(s)] = s
    choice = forms.SelectFromList.show(sorted(labels.keys()),
                                       title=title,
                                       button_name='Use this type')
    return labels.get(choice) if choice else None


def activate_symbols(doc, symbols):
    changed = False
    for s in symbols:
        if s and not s.IsActive:
            s.Activate()
            changed = True
    if changed:
        doc.Regenerate()


# ------------------------------------------------------------- floor types

def collect_floor_types(doc):
    """All FloorType elements that are real, modelable floor types (skips
    foundation-slab types, which Floor.Create rejects)."""
    types = []
    for ft in (DB.FilteredElementCollector(doc)
               .OfClass(DB.FloorType)
               .ToElements()):
        try:
            if ft.IsFoundationSlab:
                continue
        except Exception:
            pass
        types.append(ft)
    return types


def pick_floor_type(doc, title):
    """Let the user pick a loaded floor type. Returns a FloorType or None."""
    types = collect_floor_types(doc)
    if not types:
        return None
    labels = {}
    for ft in types:
        labels[revit.query.get_name(ft)] = ft
    choice = forms.SelectFromList.show(sorted(labels.keys()),
                                       title=title,
                                       button_name='Use this type')
    return labels.get(choice) if choice else None


# --------------------------------------------------------------- parameters

def set_param(elem, bip, value):
    try:
        p = elem.get_Parameter(bip)
        if p and not p.IsReadOnly:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


def set_comments(elem, text):
    return set_param(elem, DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, text)


def set_mark(elem, text):
    return set_param(elem, DB.BuiltInParameter.ALL_MODEL_MARK, text)


# ------------------------------------------------------------------ cleanup

def find_marked(doc, builtin_cats, marker=MARKER):
    """Instances in the given categories whose Comments start with marker."""
    found = []
    for bic in builtin_cats:
        col = (DB.FilteredElementCollector(doc)
               .OfCategory(bic)
               .WhereElementIsNotElementType())
        for e in col:
            p = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            v = p.AsString() if p else None
            if v and v.startswith(marker):
                found.append(e)
    return found


def offer_cleanup(doc, builtin_cats, what):
    """If a previous pyGherkin import is found, offer to delete it first.
    Returns the number of deleted elements."""
    old = find_marked(doc, builtin_cats)
    if not old:
        return 0
    if forms.alert('Found {} previously imported pyGherkin {}.\n\n'
                   'Delete them before importing the new set?'.format(len(old), what),
                   yes=True, no=True):
        with revit.Transaction('pyGherkin - Delete old {}'.format(what)):
            deleted = 0
            for e in old:
                try:
                    doc.Delete(e.Id)
                    deleted += 1
                except Exception:
                    pass
        return deleted
    return 0

# ------------------------------------------------------------- uid tracking
#
# Stable round-trip IDs. The dashboard emits a `uid` per element that is
# derived from its place in the structure (e.g. F-3-5-6 for a diagonal, C-3-5
# for a hub, L-2 for a level, FL-7 for a floor) and is therefore stable across
# re-exports. We store that uid in a dedicated instance SHARED parameter named
# "pyGherkin UID" so it is taggable, schedulable and filterable - and so a
# re-import can find the SAME element by uid and update it in place, keeping
# its ElementId (and therefore its tags/dimensions) intact.

UID_PARAM_NAME = 'pyGherkin UID'
UID_PARAM_GUID = '7f9c1d20-9b3a-4c64-8e2a-2f3b8e0c1a77'  # fixed, so the shared
#                 parameter is the same definition across machines/sessions.

# Categories the UID parameter is bound to (instance binding).
_UID_BIND_BICS = [
    DB.BuiltInCategory.OST_StructuralFraming,
    DB.BuiltInCategory.OST_StructConnections,
    DB.BuiltInCategory.OST_GenericModel,
    DB.BuiltInCategory.OST_Floors,
    DB.BuiltInCategory.OST_Levels,
]


def _get_or_create_shared_param_file(app):
    """Return a SharedParameterFile, creating a private one if the app has no
    shared parameter file set. Restores the user's original file afterwards is
    NOT done here - callers use ensure_uid_param which saves/restores."""
    import os
    path = app.SharedParametersFilename
    if path and os.path.exists(path):
        f = app.OpenSharedParameterFile()
        if f is not None:
            return f, path, False
    # create a temporary shared parameter file
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), 'pyGherkin_shared_params.txt')
    if not os.path.exists(tmp):
        open(tmp, 'w').close()
    app.SharedParametersFilename = tmp
    f = app.OpenSharedParameterFile()
    return f, path, True


def ensure_uid_param(doc):
    """Make sure the 'pyGherkin UID' instance shared parameter exists and is
    bound to our categories. Safe to call repeatedly. Returns True on success.
    Must be called inside a Transaction."""
    app = doc.Application

    # already bound?
    bindings = doc.ParameterBindings
    it = bindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        definition = it.Key
        if definition and definition.Name == UID_PARAM_NAME:
            return True  # already present

    original = app.SharedParametersFilename
    try:
        spf, _orig, _created = _get_or_create_shared_param_file(app)
        if spf is None:
            return False

        # find or create our group + definition
        group = None
        for g in spf.Groups:
            if g.Name == 'pyGherkin':
                group = g
                break
        if group is None:
            group = spf.Groups.Create('pyGherkin')

        definition = None
        for d in group.Definitions:
            if d.Name == UID_PARAM_NAME:
                definition = d
                break
        if definition is None:
            # Use the GUID-stamped options so the definition is identical
            # everywhere. SpecTypeId.String.Text is the modern text type;
            # fall back to ParameterType.Text on older API.
            try:
                opts = DB.ExternalDefinitionCreationOptions(
                    UID_PARAM_NAME, DB.SpecTypeId.String.Text)
            except Exception:
                opts = DB.ExternalDefinitionCreationOptions(
                    UID_PARAM_NAME, DB.ParameterType.Text)
            try:
                import System
                opts.GUID = System.Guid(UID_PARAM_GUID)
            except Exception:
                pass
            definition = group.Definitions.Create(opts)

        # build category set for our bind list
        cats = app.Create.NewCategorySet()
        for bic in _UID_BIND_BICS:
            try:
                cats.Insert(DB.Category.GetCategory(doc, bic))
            except Exception:
                pass

        binding = app.Create.NewInstanceBinding(cats)
        # Identity / Data group is a safe, visible parameter group
        try:
            grp = DB.GroupTypeId.IdentityData
            doc.ParameterBindings.Insert(definition, binding, grp)
        except Exception:
            doc.ParameterBindings.Insert(definition, binding,
                                         DB.BuiltInParameterGroup.PG_IDENTITY_DATA)
        return True
    finally:
        # restore the user's original shared parameter file path
        try:
            if original:
                app.SharedParametersFilename = original
        except Exception:
            pass


def _uid_param(elem):
    """Return the 'pyGherkin UID' Parameter on an element, or None."""
    try:
        p = elem.LookupParameter(UID_PARAM_NAME)
        if p is not None:
            return p
    except Exception:
        pass
    return None


def set_uid(elem, uid):
    """Write the stable uid into the element's shared parameter (and mirror it
    into Mark for convenience). Returns True if the shared param was set."""
    ok = False
    p = _uid_param(elem)
    if p is not None and not p.IsReadOnly:
        try:
            p.Set(uid)
            ok = True
        except Exception:
            ok = False
    return ok


def get_uid(elem):
    p = _uid_param(elem)
    if p is not None:
        try:
            return p.AsString()
        except Exception:
            return None
    return None


def index_by_uid(doc, builtin_cats, marker=MARKER):
    """Map uid -> element for previously placed pyGherkin elements in the given
    categories. Only elements that carry both our marker (in Comments) and a
    non-empty UID are included, so we never clobber user content."""
    out = {}
    for bic in builtin_cats:
        col = (DB.FilteredElementCollector(doc)
               .OfCategory(bic)
               .WhereElementIsNotElementType())
        for e in col:
            cp = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            cv = cp.AsString() if cp else None
            if not (cv and cv.startswith(marker)):
                continue
            uid = get_uid(e)
            if uid:
                out[uid] = e
    return out
