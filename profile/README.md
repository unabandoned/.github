# unabandoned

**Maintained forks of abandoned npm packages, kept current so their dependency trees don't rot.**

Abandoned packages don't just stop getting features — they stop getting **dependency
updates**. Every stale transitive dependency underneath an unmaintained package is a CVE
waiting to happen, and nobody upstream will ever refresh it. `unabandoned` adopts these
packages, publishes them under the [`@unabandoned/*`](https://www.npmjs.com/org/unabandoned)
npm scope, and points [Renovate](https://docs.renovatebot.com/) at them so the whole tree
stays green.

## What gets forked

The trigger is **abandonment + any outdated dependency** — not a live CVE. A CVE only
changes the *timeline* (publish immediately), never *whether* we act.

| Situation | Action |
|-----------|--------|
| Abandoned **and** carrying any outdated dependency | **Fork + publish** — we own the tree and Renovate keeps it clean |
| Abandoned but the tree is **already fully current** | Leave alone — forking would add maintenance for zero benefit |
| A maintained drop-in equivalent exists | **Replace** upstream instead of forking |
| A tiny leaf library | **Vendor** it in-tree |

The goal is a **clean transitive dependency tree, all the way up** — de-risking the whole
tree, not just direct dependencies.

## Consuming the packages

Each fork is a drop-in replacement for its upstream. Point your dependency at the
`@unabandoned` scope:

```jsonc
{
  "dependencies": {
    "events": "npm:@unabandoned/events@^3"
  }
}
```

or install directly:

```sh
npm install @unabandoned/events
```

The public API matches upstream; only the maintenance model changes.

## How forks are kept current

- **Renovate** runs against every fork, extending the shared
  [`unabandoned/renovate-config`](https://github.com/unabandoned/renovate-config) preset.
  It bumps dependencies (soaking new releases first) and **auto-merges nightly** once CI is
  green.
- **Releases publish monthly** by default; a merged security fix cuts an **immediate**
  out-of-cycle release.
- Packages publish with **OIDC trusted publishing** (provenance attestations), falling
  back to a scoped token only until OIDC is bootstrapped.
- CI runs on **Node 20 / 22 / 24**, plus **CodeQL** and **OpenSSF Scorecard**.

Shared CI, release, and publish logic lives here in
[`unabandoned/.github`](https://github.com/unabandoned/.github) as **reusable workflows**;
each fork carries only a thin caller. See
[`CONTRIBUTING.md`](https://github.com/unabandoned/.github/blob/main/CONTRIBUTING.md) for
how to add a new fork.

## Package dashboard

Every fork's live status — pending Renovate updates, open PRs and issues, latest release, CI,
any security fast-path in flight, and what each package is used for — is on the
**[package dashboard](https://unabandoned.github.io/.github/)**. It's generated from each fork's
own `.unabandoned.yml` plus the GitHub API and rebuilt on a schedule, so it's never hand-edited
and can't drift. A machine-readable copy lives at
[`data.json`](https://unabandoned.github.io/.github/data.json).

## Reporting a vulnerability

See [`SECURITY.md`](https://github.com/unabandoned/.github/blob/main/SECURITY.md). Reporting
CVEs in these trees — and getting a fix shipped fast — is the whole point of the program.
