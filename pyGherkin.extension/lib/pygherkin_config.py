# -*- coding: utf-8 -*-
"""Config + path helpers for the pyGherkin update system.

Mirrors the subset of pyMEP's config that the Install Update button needs.
Everything is auto-detected relative to the extension's own folder, so
cloning the repo to
``%APPDATA%\\pyRevit\\Extensions\\pyGherkin.extension\\`` works with no
Settings step. A user settings file
(``%APPDATA%\\pyRevit\\pyGherkin_settings.json``) can override the GitHub
repo/token and the Downloads folder:

  {
    "github_repo":             "OttomanLabsAI/pyGherkin",
    "github_token":            "",     # optional - private repos / API limits
    "update_downloads_folder": "",     # optional - override Downloads
    "auto_close_output":       false
  }
"""

import os
import json

# This file lives at <ext root>/lib/pygherkin_config.py, so the extension
# root is two folders up from __file__.
_THIS_FILE = os.path.abspath(__file__)
_LIB_DIR   = os.path.dirname(_THIS_FILE)
EXT_ROOT   = os.path.dirname(_LIB_DIR)  # pyGherkin.extension/

# User-level settings file (optional overrides).
CONFIG_FILE = os.path.join(
    os.environ.get("APPDATA", ""), "pyRevit", "pyGherkin_settings.json")


def load_settings():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_settings(settings):
    d = os.path.dirname(CONFIG_FILE)
    if not os.path.exists(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)


# ------------------------------------------------------------------ updates
# The GitHub repository the extension is published from. Override with the
# 'github_repo' settings key; for a private repo set 'github_token' to a
# personal-access token with repo read access.
DEFAULT_GITHUB_REPO = "OttomanLabsAI/pyGherkin"

# The deployed version marker, bumped by the release process (see CLAUDE.md).
# Missing file (a dev clone) just reads as "".
VERSION_FILE = os.path.join(EXT_ROOT, "version.txt")


def get_local_version():
    """Contents of <extension root>/version.txt (e.g. 'v1.0'), or '' when
    the file is missing."""
    try:
        with open(VERSION_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def get_github_repo():
    """'owner/repo' the Install Update button talks to ('github_repo'
    settings key, default DEFAULT_GITHUB_REPO)."""
    s = load_settings()
    return (s.get("github_repo") or DEFAULT_GITHUB_REPO).strip()


def get_github_token():
    """Optional GitHub personal-access token ('github_token' settings key)
    for private repos / API rate limits. '' means anonymous access."""
    s = load_settings()
    return (s.get("github_token") or "").strip()


def get_downloads_folder():
    """The user's Downloads folder, where Install Update stages
    pyGherkin.extension.zip.

    Priority: 'update_downloads_folder' settings override, the shell
    known-folder from the registry (handles relocated / OneDrive
    Downloads), then %USERPROFILE%\\Downloads."""
    s = load_settings()
    override = (s.get("update_downloads_folder") or "").strip()
    if override:
        return override
    try:
        from Microsoft.Win32 import Registry
        key = Registry.CurrentUser.OpenSubKey(
            "Software\\Microsoft\\Windows\\CurrentVersion"
            "\\Explorer\\User Shell Folders")
        if key is not None:
            val = key.GetValue("{374DE290-123F-4565-9164-39C4925E467B}")
            if val:
                return os.path.expandvars(str(val))
    except Exception:
        pass
    return os.path.join(
        os.environ.get("USERPROFILE") or os.path.expanduser("~"),
        "Downloads")


def get_auto_close_output():
    """True -> pyGherkin buttons close their output window when they finish
    (never when an error/traceback was logged). Settings key
    'auto_close_output'; default False (window stays open)."""
    s = load_settings()
    v = s.get("auto_close_output")
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on", "y")
    return bool(v)
