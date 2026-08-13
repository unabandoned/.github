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
