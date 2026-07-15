# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository.

## Project

**pyGherkin** is a [pyRevit](https://github.com/eirannejad/pyRevit) extension
that imports the Geometry Dashboard's CSV exports into a Revit model. The
extension lives in [`pyGherkin.extension/`](pyGherkin.extension):

- `lib/pygherkin/__init__.py` — shared CSV / units / level / uid-tracking helpers
- `lib/pygherkin_config.py`, `lib/pygherkin_log.py` — helpers for the update
  system (version marker, GitHub repo/token, Downloads folder, logger)
- `version.txt` — the deployed version marker read by the Install Update button
- `pyGherkin.tab/` — the ribbon tab (Levels, Floors, Structural: Framing +
  Connections; Data reserved; `Updates` panel — version display + Install Update)

Scripts target pyRevit 4.8+ and must stay IronPython- **and** CPython3-compatible.
Ribbon panel order is pinned in the `bundle.yaml` `layout:` keys.

## Update system (Install Update button)

The `Updates` panel (`pyGherkin.tab/Updates.panel/`) is titled with the current
version (e.g. **`pyGherkin v1.0`**) and holds the **Install Update** button. It
fetches the newest published `pyGherkin.extension` from GitHub (latest release,
else newest tag, else the default branch), compares it to `version.txt`, then
supersedes the live folder and extracts the new one, with automatic rollback on
failure. Ported from pyMEP; repo/token/Downloads overrides live in
`pyGherkin_settings.json` (`github_repo`, `github_token`,
`update_downloads_folder`). Default repo: `OttomanLabsAI/pyGherkin`.

The version shown on the panel is **static YAML**, so it does not auto-update —
it is bumped as part of cutting a release (below).

## Releasing (push & tag)

When asked to cut a release:

1. Pick the new version — see **Versioning** below.
2. Bump the version in **both** places so the Install Update button and the
   panel title match the tag you are about to push:
   - `pyGherkin.extension/version.txt` → the new `vX.Y.Z`
   - `pyGherkin.extension/pyGherkin.tab/Updates.panel/bundle.yaml` →
     `title: pyGherkin vX.Y.Z`
3. Commit the changes and push the branch:
   ```bash
   git push -u origin <branch>
   ```
4. Create an **annotated** tag on the release commit and push it (the tag name
   must match `version.txt` exactly, or Install Update always reports an update
   available):
   ```bash
   git tag -a vX.Y.Z -m "pyGherkin vX.Y.Z"
   git push origin vX.Y.Z
   ```

Fallback: if a tag push is rejected (some environments' git proxy returns
`403 Forbidden` on `refs/tags/*`), create the tag via the GitHub Releases UI
(Releases → Draft a new release → Choose a tag → type the version → target the
release commit → Publish) or report the block. Never substitute a branch ref
(e.g. `refs/heads/v1.0`) for a tag.

## Versioning

Tags are `vMAJOR.MINOR.PATCH`. Current release: **v1.0**.

| Kind of change   | Which number moves        | Pattern   | Example           |
| ---------------- | ------------------------- | --------- | ----------------- |
| **Major update** | first number `+1`         | `vX.1.1`  | `v1.2.1 → v2.1.1` |
| **Smaller update** | middle number `+1`      | `v1.X.1`  | `v1.1.1 → v1.2.1` |
| **Minor change** | last number `+1`          | `v1.1.X`  | `v1.1.1 → v1.1.2` |

- Major update: increase the **first** number by 1.
- Smaller update: increase the **middle** number by 1.
- Minor change: increase the **last** number by 1.
