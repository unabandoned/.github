# Fork templates

Copy-paste scaffolding for an `@unabandoned/*` fork. Everything shared lives in this repo's
reusable workflows; a fork only needs the thin callers below plus its own source.

Pin the `uses:` ref. These examples use `@main`; tag this repo and pin a version if you want
changes to roll out deliberately (Renovate can bump the pinned ref).

## Per-fork variation

| Input | `events` | `buffer` / `randexp` / `path-browserify` | `xml-js` | `composerize-ts` |
|-------|----------|------------------------------------------|----------|------------------|
| default branch | `main` | `master` | `master` | `main` |
| `node-versions` | `[20, 22, 24]` | `[20, 22, 24]` | `[20, 22, 24]` | `[22, 24]` (engines `>=22`) |
| `has-build` (CI) | `false` | `false` | `false` (TS type-check runs inside `npm test`) | `true` |
| `install-for-publish` | `false` | `false` | `false` | `false` (implied by the build) |
| `build-for-publish` | `false` | `false` | `false` | `true` |

## Workflow callers

Place each under the fork's `.github/workflows/`. Replace `master` with `main` for `events`.

### `ci.yml`

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
jobs:
  ci:
    permissions:
      contents: read
    uses: unabandoned/.github/.github/workflows/reusable-ci.yml@main
    with:
      node-versions: '[20, 22, 24]'
      has-build: false
```

### `commitlint.yml`

```yaml
name: commitlint
on:
  pull_request:
jobs:
  commitlint:
    permissions:
      contents: read
    uses: unabandoned/.github/.github/workflows/reusable-commitlint.yml@main
```

### `publish.yml`

```yaml
name: publish
on:
  release:
    types: [published]
permissions:
  contents: read
  id-token: write   # required for OIDC on the calling job
jobs:
  publish:
    permissions:
      contents: read
      id-token: write
    uses: unabandoned/.github/.github/workflows/reusable-publish.yml@main
    with:
      install-for-publish: false
    secrets: inherit
```

A **compiled** fork (one whose `package.json#files` ships generated output rather
than committed files) passes `build-for-publish: true` instead. `npm publish`
runs with `--ignore-scripts`, so a `prepublishOnly`/`prepack` build never fires —
without that input the fork would publish a tarball with no build output in it.
The input implies the install, so `install-for-publish` stays `false`.

### `release-please.yml`

```yaml
name: release-please
on:
  push:
    branches: [master]
jobs:
  release-please:
    permissions:
      contents: write
      pull-requests: write
    uses: unabandoned/.github/.github/workflows/reusable-release-please.yml@main
    secrets: inherit
```

### `release-cut.yml`

```yaml
name: release-cut
on:
  schedule:
    - cron: '0 6 1 * *'
  workflow_dispatch:
jobs:
  cut:
    permissions:
      contents: write
      pull-requests: write
    uses: unabandoned/.github/.github/workflows/reusable-release-cut.yml@main
    secrets: inherit
```

### `release-security.yml`

```yaml
name: release-security
on:
  pull_request:
    types: [closed]
jobs:
  security-release:
    permissions:
      contents: write
      pull-requests: write
    uses: unabandoned/.github/.github/workflows/reusable-release-security.yml@main
    secrets: inherit
```

### `codeql.yml`

```yaml
name: CodeQL
on:
  push:
    branches: [master]
  pull_request:
  schedule:
    - cron: '0 6 * * 1'
jobs:
  codeql:
    permissions:
      actions: read
      contents: read
      security-events: write
    uses: unabandoned/.github/.github/workflows/reusable-codeql.yml@main
```

### `scorecard.yml`

```yaml
name: Scorecard
on:
  branch_protection_rule:
  schedule:
    - cron: '0 6 * * 1'
  push:
    branches: [master]
jobs:
  scorecard:
    permissions:
      security-events: write
      id-token: write
      contents: read
    uses: unabandoned/.github/.github/workflows/reusable-scorecard.yml@main
```

## Other per-fork files

- **`renovate.json`**

  ```json
  {
    "$schema": "https://docs.renovatebot.com/renovate-schema.json",
    "extends": ["github>unabandoned/renovate-config"],
    "forkProcessing": "enabled"
  }
  ```

- **`release-please-config.json`** — copy [`release-please-config.json`](./release-please-config.json)
  from this directory verbatim (the `changelog-sections` block is canonical).
- **`.release-please-manifest.json`** — `{ ".": "<current version>" }`.
- **`commitlint.config.js`** — `module.exports = { extends: ['@commitlint/config-conventional'] };`
- **`.githooks/commit-msg`** — `npx --no-install commitlint --edit "$1"`, wired via a
  `"prepare": "git config core.hooksPath .githooks || true"` script.
- **`.unabandoned.yml`** — copy [`.unabandoned.yml`](./.unabandoned.yml) and fill in the
  editorial facts (upstream source, summary, why-forked, and optionally where it's used). This
  is the fork's single source of truth for the [central dashboard](https://unabandoned.github.io/recon/);
  `reusable-ci` validates it on every PR, and the dashboard reads it live from the default
  branch, so it never has to be re-typed into a central registry. Everything else the dashboard
  shows (open PRs/issues, pending Renovate updates, releases, CI, security fast-path) is derived
  live from GitHub — don't record any of that here.
