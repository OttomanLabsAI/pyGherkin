# -*- coding: utf-8 -*-
"""Install Update - fetch the current `main` branch of the pyGherkin repo
from GitHub and deploy it over the live extension, in one go.

The extension tracks the tip of `main` (rolling), not tagged releases.

Flow:
  1. Ask the GitHub API for the tip of `main` (short SHA + date, for the
     confirmation prompt).
  2. Download the branch zip and repackage JUST the pyGherkin.extension/
     folder into Downloads/pyGherkin.extension.zip (staged write - a
     failed download can never leave a truncated zip). If the download
     fails but Downloads already holds a pyGherkin.extension.zip, offers
     to install that instead.
  3. Deploy: the live folder moves to <extensions root>/00 - Superseded/
     pyGherkin/pyGherkin.extension_<timestamp> (atomic same-volume
     rename), the zip is extracted into place (single-top-folder and
     loose-file layouts both handled), then archived alongside; every
     failure after the move rolls the previous version back.
  4. Offers to reload pyRevit so the new version is live.

Settings keys (pyGherkin_settings.json): 'github_repo' ("owner/repo"),
'github_branch' (default "main"), 'github_token' (optional - private
repos / API rate limits), 'update_downloads_folder' (optional override of
the Downloads folder).
"""

__title__  = "Install\nUpdate"
__author__ = "pyGherkin"

import datetime
import json
import os
import shutil
import sys
import tempfile
import zipfile

# Force-reload pygherkin_* libs so edits on disk always take effect.
for _mod in [m for m in list(sys.modules.keys()) if m.startswith("pygherkin_")]:
    del sys.modules[_mod]

from pyrevit import forms, script

from pygherkin_config import (
    EXT_ROOT, get_github_repo, get_github_branch, get_github_token,
    get_downloads_folder, get_local_version,
)
from pygherkin_log import Logger

import clr
clr.AddReference("System")
from System.Net import ServicePointManager, SecurityProtocolType, WebClient

output = script.get_output()
log = Logger(output, "InstallUpdate")

# GitHub requires TLS 1.2+; older .NET runtimes don't enable it by default.
try:
    ServicePointManager.SecurityProtocol = (
        ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12)
except Exception:
    pass

# Store, don't compress, if this engine has no zlib (rare).
try:
    import zlib  # noqa: F401
    _COMPRESSION = zipfile.ZIP_DEFLATED
except ImportError:
    _COMPRESSION = zipfile.ZIP_STORED


# ---------------------------------------------------------------------------
# GitHub download helpers
# ---------------------------------------------------------------------------
def _client(token, accept=None):
    """A WebClient with the headers GitHub wants (fresh per request -
    WebClient clears headers after each call)."""
    wc = WebClient()
    wc.Headers.Add("User-Agent", "pyGherkin-updater")
    if accept:
        wc.Headers.Add("Accept", accept)
    if token:
        wc.Headers.Add("Authorization", "token " + token)
    return wc


def _api_json(repo, path, token):
    url = "https://api.github.com/repos/{}/{}".format(repo, path)
    wc = _client(token, accept="application/vnd.github+json")
    return json.loads(wc.DownloadString(url))


def _resolve_branch(repo, branch, token):
    """-> (label, zip_url): the tip of `branch` (e.g. main). The label
    carries the short commit SHA + date when reachable, else just the
    branch name; the zip is the branch zipball either way."""
    label = branch
    try:
        info = _api_json(repo, "commits/{}".format(branch), token)
        sha = (info.get("sha") or "")[:7]
        commit = info.get("commit") or {}
        committer = commit.get("committer") or {}
        date = (committer.get("date") or "")[:10]
        if sha:
            label = "{} @ {}{}".format(
                branch, sha, " ({})".format(date) if date else "")
    except Exception:
        pass
    return label, "https://api.github.com/repos/{}/zipball/{}".format(
        repo, branch)


def _download_zip(repo, token, label, zip_url, downloads):
    """Download + repackage into Downloads/pyGherkin.extension.zip.
    Returns the zip path, or None when the download failed (logged)."""
    dest_zip = os.path.join(downloads, "pyGherkin.extension.zip")
    work = tempfile.mkdtemp(prefix="pygherkin_update_")
    try:
        repo_zip = os.path.join(work, "repo.zip")
        log("Downloading {} ...".format(zip_url))
        try:
            _client(token).DownloadFile(zip_url, repo_zip)
        except Exception as ex:
            log("Download failed: {}".format(ex))
            return None

        unpack = os.path.join(work, "unpacked")
        with zipfile.ZipFile(repo_zip) as zf:
            zf.extractall(unpack)

        ext_src = None
        for entry in sorted(os.listdir(unpack)):
            p = os.path.join(unpack, entry)
            if not os.path.isdir(p):
                continue
            inner = os.path.join(p, "pyGherkin.extension")
            if os.path.isdir(inner):
                ext_src = inner
                break
            if os.path.isdir(os.path.join(p, "pyGherkin.tab")):
                ext_src = p
                break
        if ext_src is None:
            log("The downloaded zip has no pyGherkin.extension folder - check "
                "the 'github_repo' setting (currently '{}').".format(repo))
            return None

        # Staged write: only moved onto Downloads when complete.
        count = 0
        staged_zip = os.path.join(work, "pyGherkin.extension.zip")
        zf_out = zipfile.ZipFile(staged_zip, "w", _COMPRESSION)
        try:
            for root, dirs, files in os.walk(ext_src):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, ext_src).replace(os.sep, "/")
                    zf_out.write(full, "pyGherkin.extension/" + rel)
                    count += 1
        finally:
            zf_out.close()
        if os.path.exists(dest_zip):
            os.remove(dest_zip)
        shutil.move(staged_zip, dest_zip)
        log("Downloaded {} - repackaged **{}** files into {}.".format(
            label, count, dest_zip))
        return dest_zip
    finally:
        shutil.rmtree(work, ignore_errors=True)


def unique_destination(parent, stem, suffix=""):
    """Non-clashing path at parent/<stem><suffix>, appending _N if taken."""
    dest = os.path.join(parent, stem + suffix)
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(parent, "{}_{}{}".format(stem, counter, suffix))
        counter += 1
    return dest


# ---------------------------------------------------------------------------
# 1. Resolve main + download
# ---------------------------------------------------------------------------
repo = get_github_repo()
branch = get_github_branch()
token = get_github_token()
downloads = get_downloads_folder()
local_ver = get_local_version()

log("### Install Update")
log("Repo: **{}**  (branch **{}**)".format(repo, branch))
log("Installed version: **{}**".format(local_ver or "(no version.txt)"))

if not os.path.isdir(downloads):
    forms.alert(
        "Downloads folder not found:\n{}\n\nSet the "
        "'update_downloads_folder' key in pyGherkin_settings.json to the "
        "folder you want updates staged in.".format(downloads),
        exitscript=True)

label, zip_url = _resolve_branch(repo, branch, token)
log("Latest on GitHub: **{}**".format(label))

zip_path = _download_zip(repo, token, label, zip_url, downloads)
if zip_path is None:
    fallback = os.path.join(downloads, "pyGherkin.extension.zip")
    if os.path.exists(fallback):
        fb_ts = datetime.datetime.fromtimestamp(
            os.path.getmtime(fallback)).strftime("%Y-%m-%d %H:%M")
        if forms.alert(
                "The download failed (full details in the output window).\n\n"
                "Downloads already contains a pyGherkin.extension.zip from "
                "{}.\n\nInstall that one instead?".format(fb_ts),
                title="Download failed",
                options=["Install existing zip", "Cancel"]) == \
                "Install existing zip":
            zip_path = fallback
            label = "(existing zip, {})".format(fb_ts)
    if zip_path is None:
        log.close()
        forms.alert(
            "Download failed - nothing was changed.\n\nIf the repository "
            "is private, set the 'github_token' key in pyGherkin_settings.json "
            "to a GitHub personal-access token with repo read access.",
            exitscript=True)

# ---------------------------------------------------------------------------
# 2. Confirm + deploy (supersede -> extract -> archive, with rollback)
# ---------------------------------------------------------------------------
ext_dir = EXT_ROOT                                  # ...\pyGherkin.extension
base = os.path.dirname(ext_dir)                     # pyRevit extensions root
source_name = os.path.basename(ext_dir)             # 'pyGherkin.extension'
short = (source_name[:-len(".extension")]
         if source_name.endswith(".extension") else source_name)

if forms.alert(
        "Install {} over the live extension?\n\nInstalled version: {}\n\n"
        "The current folder is kept: it moves to\n"
        "00 - Superseded\\{}\\{}_<timestamp>".format(
            label, local_ver or "(no version.txt)", short, source_name),
        title="Install Update",
        options=["Install", "Cancel"]) != "Install":
    log("Cancelled.")
    log.close()
    script.exit()

ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
superseded_dir = os.path.join(base, "00 - Superseded", short)
try:
    if not os.path.exists(superseded_dir):
        os.makedirs(superseded_dir)
except Exception as ex:
    log("makedirs failed: {}".format(ex))
    log.close()
    forms.alert(
        "Couldn't create the superseded folder:\n{}\n\n{}\n\nNothing was "
        "changed.".format(superseded_dir, ex), exitscript=True)

# os.rename, NOT shutil.move: superseded_dir is under the same parent, so
# this is an atomic same-volume rename - it either fully succeeds or does
# nothing, which is what makes the 'Nothing was changed' promise true.
moved_to = unique_destination(superseded_dir,
                              "{}_{}".format(source_name, ts))
try:
    os.rename(ext_dir, moved_to)
except Exception as ex:
    log("Move failed: {}".format(ex))
    log.close()
    forms.alert(
        "Couldn't move the live extension folder (a file in it is probably "
        "locked by Revit):\n\n{}\n\nNothing was changed. Close Revit and try "
        "the update again.".format(ex),
        exitscript=True)
log("Superseded: {} -> {}".format(source_name, moved_to))

temp_dir = os.path.join(base, ".__extract_" + source_name)
try:
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(temp_dir)

    extracted = [os.path.join(temp_dir, n) for n in os.listdir(temp_dir)]
    if len(extracted) == 1 and os.path.isdir(extracted[0]):
        os.rename(extracted[0], ext_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        os.rename(temp_dir, ext_dir)

    if not os.path.isdir(os.path.join(ext_dir, "pyGherkin.tab")):
        raise RuntimeError(
            "the extracted zip has no pyGherkin.tab folder - not a "
            "pyGherkin.extension zip?")
except Exception as ex:
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        if os.path.exists(ext_dir):
            shutil.rmtree(ext_dir)          # discard the bad extract
        os.rename(moved_to, ext_dir)        # put the old version back
        outcome = "The previous version was RESTORED."
    except Exception as ex2:
        outcome = ("Restoring the previous version ALSO failed ({}) - "
                   "recover it manually from:\n{}".format(ex2, moved_to))
    log("Install failed: {}".format(ex))
    log.close()
    forms.alert("Install failed:\n\n{}\n\n{}".format(ex, outcome),
                exitscript=True)
log("Extracted -> {}".format(ext_dir))

try:
    archived = unique_destination(superseded_dir,
                                  "{}_{}".format(source_name, ts), ".zip")
    shutil.move(zip_path, archived)
    log("Archived zip: {} -> {}".format(os.path.basename(zip_path), archived))
except Exception as ex:
    log("Couldn't archive the zip (non-fatal): {}".format(ex))

new_ver = get_local_version()
log("### Installed **{}** (from {})".format(
    new_ver or "(no version.txt in zip)", label))

# ---------------------------------------------------------------------------
# 3. Reload pyRevit
# ---------------------------------------------------------------------------
if forms.alert(
        "Installed {}.\n\nReload pyRevit now so the new version is live?"
        .format(new_ver or "the update"),
        title="Installed",
        options=["Reload pyRevit", "Later"]) == "Reload pyRevit":
    log.close()
    try:
        from pyrevit.loader import sessionmgr
        sessionmgr.reload_pyrevit()
    except Exception as ex:
        forms.alert(
            "Automatic reload failed ({}).\n\nReload manually: pyRevit tab "
            "> Reload.".format(ex))
else:
    log("Reload skipped - use pyRevit tab > Reload when ready.")
    log.close()
