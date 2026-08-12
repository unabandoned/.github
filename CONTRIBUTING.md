# Contributing to `unabandoned`

Thanks for helping keep these trees green. This guide is org-wide; a repo may add its own
`CONTRIBUTING.md` for package-specific notes.

## Ground rules

- **Conventional Commits are required.** Commit messages are linted (`commitlint` with
  `@commitlint/config-conventional`) on every PR. Run `npm install` once so the `commit-msg`
  git hook lints locally before you push.
- **Keep the runtime tree lean.** New runtime dependencies are rarely justified in a fork —
  the program exists to shrink dependency risk, not grow it.
- **Keep the dev tree lean too.** Prefer built-in `node:test` / `node:assert` over adding a
  third-party test runner. The dev tree runs in CI beside publish credentials.
- **Fix forward, don't pin.** If a dependency major breaks a fork, adopt the new major and fix
  the real breakages rather than pinning to an old version.

## Commit types and the changelog

`feat` / `fix` / `perf` / `revert` are consumer-facing and appear at the top of release notes.
Everything else (`deps` / `build` / `chore` / `ci` / `refactor` / `docs` / `test` / `style`)
is folded into a collapsible "Dependencies & maintenance" section. Use `deps` for dependency
bumps; a bump that fixes a CVE should carry the `security` label so it ships on the fast-path.

## Opening a pull request

1. Branch from the repo's default branch.
2. Make your change; add or update tests (`npm test` must pass on Node 20 / 22 / 24).
3. Write Conventional-Commit messages.
4. Open the PR; CI (test matrix, commitlint, CodeQL, Scorecard) runs automatically.

## Adding a new fork

New forks follow the shared template so they inherit the whole pipeline:

1. **Trigger check.** Only fork a package that is **abandoned _and_ carries at least one
   outdated dependency**. An abandoned-but-already-current tree is left alone.
2. **Rename** the package to the `@unabandoned/*` scope in `package.json`.
3. **Add the thin workflow callers** that reference this repo's reusable workflows
   (`unabandoned/.github/.github/workflows/reusable-*.yml@main`) — see the
   [`templates/`](./templates) directory for copy-paste callers and the canonical
   `release-please-config.json`.
4. **Add `renovate.json`**: `{ "extends": ["github>unabandoned/renovate-config"],
   "forkProcessing": "enabled" }`.
5. **Add release-please files**: copy `templates/release-please-config.json` and set a
   `.release-please-manifest.json` with the package's current version.
6. A human then enables the **Renovate GitHub App** and runs **`npm trust`** to configure the
   trusted publisher (both are 2FA-gated and can't be automated).

See [`CLAUDE.md`](./CLAUDE.md) for the full program model.
