# CLAUDE.md — the `unabandoned` maintained-fork program

Guidance for Claude Code working in any `unabandoned/*` repository. This file is
org-level; individual repos may add their own `CLAUDE.md` for package-specific notes.

## What this org is

`unabandoned` de-risks abandoned npm dependencies by maintaining forks under the
**`unabandoned` GitHub org** and publishing them to the **`@unabandoned/*` npm scope**.
The motivating consumers pull these libraries transitively; once a package is abandoned,
nobody upstream refreshes its dependency tree, so stale transitive deps rot and accumulate
CVEs. We fork so **we** own the tree and keep it current with Renovate.

## Prime directive — fork whatever is abandoned AND has outdated deps

The trigger for forking is **an abandoned repo carrying any outdated dependency**.

- **Abandoned + any outdated dep → fork + publish** (adopt it; Renovate keeps the tree clean).
- **Abandoned + zero outdated deps → leave alone** (truly frozen and clean — forking adds
  maintenance for zero benefit). This is the **only** OK reason to leave an abandoned dep.
- **Replace** (a maintained equivalent) or **vendor in-tree** (a tiny leaf lib) remain valid
  ways to clear the risk without carrying a fork, where they genuinely fit.
- A **live CVE is the urgent fast-path, not the threshold** — it changes the *timeline*
  (publish immediately), not *whether* to intervene.

The goal is a **clean transitive dependency tree, all the way up**. Distinguish the
**shipped/runtime tree** (what consumers get — must be lean) from the **dev tree**
(test/build tooling — matters because it runs in CI beside publish credentials). Prefer
built-in `node:test`/`node:assert` over heavy third-party test runners to keep the dev tree
near zero.

## Release model

- **Squash-merge, title-driven.** Every PR is squash-merged, so the PR **title** is the
  Conventional Commit release-please reads — keep one logical change per PR, and put the
  release signal in the title (`feat!` for a breaking major). Body-only footers (`Release-As:`,
  long-form `BREAKING CHANGE:`) only survive the squash if the repo's squash message is set to
  "title and description", so prefer release-please config (e.g. `bump-minor-pre-major`) for a
  deliberate version override.
- **Renovate merges nightly** — automerge once CI is green, after soaking new releases.
- **Publish monthly** — `release-cut` squash-merges the pending release-please PR (labelled
  `autorelease: pending`) on the 1st of each month (`cron: '0 6 1 * *'`) or on manual dispatch.
- **CVE = immediate** — `release-security` fast-tracks: a merged PR labelled `security`
  refreshes and merges the release PR right away.
- Changelog is **consumer-facing-first**: `feat`/`fix`/`perf`/`revert` on top; all dependency
  churn (`deps`/`build`/`chore`/`ci`/`refactor`/`docs`/`test`/`style`) is routed into a
  "Dependencies & maintenance" section that the release-please post-step folds into a
  collapsible `<details>` in the GitHub release notes.

## Publishing

`publish` runs on `release: published` and is **self-bootstrapping OIDC-or-token**: it checks
`vars.OIDC_ENABLED`, tries OIDC, falls back to a token publish with `NPM_SECRET`, then flips
`OIDC_ENABLED=true` via the `PAT` once OIDC works. The token-holding job is **hardened against
the dev tree**: no `npm install` unless the fork must build to pack (`install-for-publish`),
and every `npm publish` runs with `--ignore-scripts`.

## Secrets (never expose or hardcode)

- **`PAT`** — org-wide personal access token (release-please, release-cut, the OIDC-flag flip).
- **`NPM_SECRET`** — granular npm token (packages read/write; **not** the "organizations"
  permission).

Never echo, log, or commit these values.

## Two steps only a human can do (2FA-gated, not automatable in CI)

1. Install/enable the **Mend (Renovate) GitHub App** on the org / selected repos.
2. **`npm trust`** to configure each package's trusted publisher (npm ≥ 11.5.1, Node ≥ 22.14,
   interactive 2FA).

(A third one-time human setting, not 2FA-gated but a repo toggle: in `unabandoned/.github`,
**Settings → Pages → Source: GitHub Actions**, so the `dashboard` workflow can publish. See
the dashboard section below.)

## Central dashboard

The org's status/documentation surface is the **package dashboard** at
`https://unabandoned.github.io/.github/`, built by **`scripts/build_dashboard.py`** and
published to GitHub Pages by the **`dashboard` workflow** (scheduled daily + `workflow_dispatch`
+ on any change to the builder). It is **never hand-edited** — that is the whole point.

The design splits data into two classes so it can't go stale:

- **Derivable** (open PRs/issues, pending Renovate updates, latest release, CI status, the
  `security` fast-path, `autorelease: pending`) is pulled **live from the GitHub API** at build
  time. Never record any of it in a file.
- **Editorial** (what the package is, why we forked it, upstream source, where it's used) lives
  in each fork's own **`.unabandoned.yml`** — the single source of truth, co-located with the
  code so it's updated in the same PR. The dashboard reads it straight from the fork's default
  branch; there is **no** central registry to drift.

The `.unabandoned.yml` schema is defined once in **`scripts/validate_metadata.py`** (imported by
the builder and run by `reusable-ci` on every fork PR). The template is
`templates/.unabandoned.yml`. When adding a fork, add its `.unabandoned.yml`; when changing what
a fork does or where it's used, update that file in the same PR. Do not add editorial fields that
GitHub can already answer — if the API knows it, it doesn't belong in the file.

The dashboard also renders a **dependency topology** (`scripts/topology.py`) — a panel on the main
page plus a standalone `topology.html` — showing consumers, the forks we own, and the shared
leaves beneath them, coloured by live health. It is a dependency-free **computed SVG** (layered
layout, no JS/library). Its edges are **derived, never hand-drawn**: `fork → fork` from each
fork's `package.json` dependencies filtered to the `@unabandoned/*` scope, and `consumer → fork`
from `used-by`. So the graph stays correct on its own as forks and their trees change.

Alongside it is the **transitive dependency audit** (`scripts/dep_audit.py`) — a panel plus a
standalone `dependencies.html`. Renovate's per-fork dashboards can only flag what appears in a
`package.json`, so an abandoned package reachable only transitively is invisible to every
dashboard in the org; this closes that gap by resolving each fork's full production tree with
`npm install --package-lock-only --omit=dev --ignore-scripts` (registry metadata only — no
tarball is downloaded and no lifecycle script runs) and classifying every node:

- **alive** — released within `abandonmentThreshold`; a maintainer can still respond.
- **inert** — abandoned but **zero runtime deps**. Nothing beneath it to rot; this is exactly the
  class the shared Renovate preset is entitled to suppress.
- **time bomb** — abandoned **and** carrying its own runtime deps, so its subtree ages with nobody
  left to bump it. The only actionable class: own it (fork/vendor/replace), never silence it.

"On latest" is not a health signal — a frozen package pinned to frozen dependencies is still
rotting. That is why the classification turns on whether a package *can* rot, not on whether it
is currently behind. The audit also cross-checks each tree against the packages we already
maintain and reports any fork still resolving a sibling from its **abandoned upstream** instead of
the `@unabandoned` scope — self-inflicted rot, and the cheapest thing to fix. All of it is derived
at build time; none of it is recorded in a file. A fork that fails to resolve (e.g. not yet
published) degrades to one "unresolved" row rather than failing the build.

## Fix forward — don't pin

When a major dependency bump breaks a fork, **adopt the new major and fix the few real
breakages** rather than pinning to an old version. Pinning re-introduces exactly the rot the
program exists to remove. (Precedent: xml-js adopting jasmine 6 / TypeScript 7.)

## Reusable-workflow layout

Shared CI/release/publish logic lives in **`unabandoned/.github/.github/workflows/reusable-*.yml`**
(reusable workflows must live in that repo's `.github/workflows/`). Each fork carries a thin
caller that pins the `uses:` ref and passes per-fork inputs:

```yaml
# <fork>/.github/workflows/ci.yml
on: { push: { branches: [master] }, pull_request: {} }
jobs:
  ci:
    uses: unabandoned/.github/.github/workflows/reusable-ci.yml@main
    with:
      node-versions: '[20, 22, 24]'
      has-build: false
```

Per-fork variation is expressed as inputs: the Node matrix, the default branch (`events` is
`main`, the rest `master`), whether a build runs, and whether publish needs an install. OIDC
needs `permissions: id-token: write` on the **calling** job; a reusable workflow's permissions
are capped by the caller. Pass creds with `secrets: inherit`.

`renovate.json` in each fork stays `{ "extends": ["github>unabandoned/renovate-config"],
"forkProcessing": "enabled" }` — `forkProcessing` must live in the fork's own root config
because the fork-skip decision ignores the preset-inherited value.

## Guardrails

- **Every GitHub PR/comment body ends with the attribution footer:**

  ```
  \n\n---\n_Generated by [Claude Code](https://claude.ai/code)_
  ```

- **Never embed the model identifier** (or any `claude-*` model ID) in commit messages, PR
  titles/bodies, code comments, or anything pushed to a repository. Keep it to chat only.
- Fork trigger = **abandoned + any outdated dep** (not a CVE). Leave-alone is reserved for
  abandoned repos whose tree is already fully current.
- Never hardcode or echo `PAT` / `NPM_SECRET`.
- Fix forward, don't pin.
- The **dashboard is generated, never hand-edited**. Editorial facts live in each fork's
  `.unabandoned.yml` (single source of truth, updated in the same PR as the code); everything
  else is derived live from GitHub. Don't record derivable state in files, and don't build a
  central registry the forks would have to keep in sync.
