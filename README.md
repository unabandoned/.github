# unabandoned/.github

Org-level defaults for the [`unabandoned`](https://github.com/unabandoned) maintained-fork
program. GitHub serves the community-health files here to any `unabandoned/*` repository that
doesn't define its own.

## Contents

- **`profile/README.md`** — the org landing page shown on
  [github.com/unabandoned](https://github.com/unabandoned).
- **`.github/workflows/reusable-*.yml`** — the shared reusable workflows every fork calls:
  `ci`, `commitlint`, `publish`, `release-please`, `release-cut`, `release-security`,
  `codeql`, `scorecard`.
- **`templates/`** — copy-paste thin callers, the canonical `release-please-config.json`, and
  the `.unabandoned.yml` metadata template for standing up a new fork.
- **`scripts/`** — the central [package dashboard](https://unabandoned.github.io/.github/)
  builder (`build_dashboard.py` + `dashboard_template.html`) and the `.unabandoned.yml`
  schema validator (`validate_metadata.py`, also run by `reusable-ci`). The `dashboard`
  workflow rebuilds and publishes the site to GitHub Pages on a schedule and on demand.
- **`CLAUDE.md`** — program guidance for Claude Code in any of these repos.
- **Community-health files** — `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `CODEOWNERS`,
  issue/PR templates, `FUNDING.yml`, inherited org-wide.

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) to add a new fork and [`CLAUDE.md`](./CLAUDE.md)
for the full program model.
