<!--
Org-wide PR template for unabandoned/* repos. Renovate PRs are exempt (they
open automatically). Keep commit messages Conventional — they are linted.
-->

## What & why

<!-- What does this change and why? Link any issue or advisory. -->

## Type of change

- [ ] `fix` / `feat` / `perf` — consumer-facing
- [ ] `deps` — dependency update (add the `security` label if it fixes a CVE)
- [ ] `chore` / `ci` / `build` / `docs` / `test` / `refactor` — maintenance

## Checklist

- [ ] Commits follow Conventional Commits (`commitlint` passes)
- [ ] `npm test` passes on Node 20 / 22 / 24
- [ ] No new runtime dependency (or its addition is justified below)
- [ ] Dev tree kept lean (prefer built-in `node:test` over new runners)
