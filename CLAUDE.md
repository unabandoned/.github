# CLAUDE.md — the `unabandoned` org

Guidance for Claude Code working in any `unabandoned/*` repository. This file is
org-level; individual repos may add their own `CLAUDE.md` for package-specific notes.

## What this org is

**Our own projects come first. This org is where their abandoned dependencies get parked.**

Every package here is a dependency one of our projects pulls in — usually transitively — that
upstream stopped maintaining. Once a package is abandoned nobody refreshes its dependency tree,
so stale transitive deps rot and accumulate CVEs; we fork it so **we** own the tree and Renovate
keeps it current. The forks live under the **`unabandoned` GitHub org** and publish to the
**`@unabandoned/*` npm scope** for one reason: there are a lot of them, and they would bury the
main organization where the actual projects live.

Two things follow, and both are easy to get backwards:

- **The trigger is "we depend on it", not "it is abandoned".** This is not an adoption program
  for the ecosystem. An abandoned package nothing of ours reaches is not our problem.
- **A fork is a filing decision, not a commitment ceremony.** Forking one more leaf is cheap and
  routine — the cost that matters is how much *more* rot the tree drags in with it, which is
  what recon is for.

## When to fork — abandoned, ours, and carrying outdated deps

Given a package our projects already depend on:

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

(A third one-time human setting, not 2FA-gated but a repo toggle: in `unabandoned/recon`,
**Settings → Pages → Source: GitHub Actions**, so the build can publish the dashboard. See
the dashboard section below.)

## Central dashboard

The org's status surface is **[`unabandoned/recon`](https://github.com/unabandoned/recon)**,
published to `https://unabandoned.github.io/recon/`. It used to be built from
`scripts/build_dashboard.py` in this repository; that builder has been removed and recon
replaces it. This repo still owns **`scripts/validate_metadata.py`**, because `reusable-ci`
bundles it and runs it against every fork's `.unabandoned.yml` on every pull request.

The design principle recon is built around: **make "we don't know" unrepresentable as a benign
value.** A failed read is a state that reaches the page as `unknown`, counted in every
denominator and carrying its reason — never a default that looks healthy. Every headline number
is cross-checked against an independent derivation or a hand-asserted fact before it renders,
and a build that fails its own checks publishes anyway, with a red banner, because a visibly
broken dashboard gets fixed and a silently stale one does not.

The data split that keeps it from going stale is unchanged:

- **Derivable** (open PRs/issues, pending Renovate updates, latest release, CI status, the
  `security` fast-path, `autorelease: pending`) is pulled **live from the GitHub API** at build
  time. Never record any of it in a file.
- **Editorial** (what the package is, why we forked it, upstream source, where it's used) lives
  in each fork's own **`.unabandoned.yml`** — the single source of truth, co-located with the
  code so it's updated in the same PR. There is **no** central registry to drift.

The one refinement: a fixture that *audits* the derivation is not editorial and does not
co-locate. Sibling-edge assertions used to live per-fork, which cost 27 pull requests to
populate, so nobody wrote one and the check that read them passed vacuously for its whole life.
They live in recon's own `fixtures/org.yml` now — one repository, one pull request.

Classification is the same three-way split, and it is about whether a package *can* rot rather
than whether it is currently behind. "On latest" is not a health signal: a frozen package pinned
to frozen dependencies is still rotting.

- **alive** — released within the abandonment threshold; a maintainer can still respond.
- **inert** — abandoned but **zero runtime deps**. Nothing beneath it to rot; the class the
  shared Renovate preset is entitled to suppress.
- **time bomb** — abandoned **and** carrying its own runtime deps. The only actionable class:
  own it (fork/vendor/replace), never silence it.
- **unknown** — could not be measured. Not the same as healthy, and counted separately.

Beyond what the old dashboard did, recon adds history (snapshots on a `data` branch, so "did
that change help?" is answerable), a **work queue** that ranks interventions by how much rot
each one removes rather than by how often a package appears, **intake** for auditing a tree
before adopting it, and a **comparison** of any two repositories' dependencies. Its docs are
`docs/redesign.md` (the design) and `docs/implementation.md` (what is built, and every bug the
mechanisms have caught).

## Fix forward — don't pin

When a major dependency bump breaks a fork, **adopt the new major and fix the few real
breakages** rather than pinning to an old version. Pinning re-introduces exactly the rot we forked it to remove. (Precedent: xml-js adopting jasmine 6 / TypeScript 7.)

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
- Fork trigger = **we depend on it** + abandoned + any outdated dep (not a CVE). Leave-alone is
  reserved for abandoned repos whose tree is already fully current — and for anything nothing of
  ours reaches, which was never ours to adopt.
- Never hardcode or echo `PAT` / `NPM_SECRET`.
- Fix forward, don't pin.
- The **dashboard is generated, never hand-edited**. Editorial facts live in each fork's
  `.unabandoned.yml` (single source of truth, updated in the same PR as the code); everything
  else is derived live from GitHub. Don't record derivable state in files, and don't build a
  central registry the forks would have to keep in sync.
