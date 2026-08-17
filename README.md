# unabandoned/.github

Org-level defaults for the [`unabandoned`](https://github.com/unabandoned) org — where the
abandoned dependencies our projects pull in get forked and parked, instead of cluttering the
organization those projects live in. GitHub serves the community-health files here to any
`unabandoned/*` repository that doesn't define its own.

## Contents

- **`profile/README.md`** — the org landing page shown on
  [github.com/unabandoned](https://github.com/unabandoned).
- **`.github/workflows/reusable-*.yml`** — the shared reusable workflows every fork calls:
  `ci`, `commitlint`, `publish`, `release-please`, `release-cut`, `release-security`,
  `codeql`, `scorecard`.
- **`templates/`** — copy-paste thin callers, the canonical `release-please-config.json`, and
  the `.unabandoned.yml` metadata template for standing up a new fork.
- **`scripts/`** — the `.unabandoned.yml` schema validator (`validate_metadata.py`), which
  `reusable-ci` bundles and runs against every fork's metadata on every pull request. The
  central [package dashboard](https://unabandoned.github.io/recon/) used to be built here too;
  it now lives in [`unabandoned/recon`](https://github.com/unabandoned/recon), which derives
  the same facts with error states, double-derivation and integrity checks, and adds history,
  a work queue and repository comparison.
- **`CLAUDE.md`** — org-level guidance for Claude Code in any of these repos.
- **Community-health files** — `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `CODEOWNERS`,
  issue/PR templates, `FUNDING.yml`, inherited org-wide.

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) to add a new fork and [`CLAUDE.md`](./CLAUDE.md)
for the full model.
