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

## Merging

PRs are **squash-merged**, and release-please is **title-driven**: the squash commit's
subject is the PR title, so the title *is* the Conventional Commit that release-please reads
to compute the next version and changelog entry. Two rules follow:

- **One logical change per PR.** A squash collapses every commit on the branch into a single
  changelog entry keyed off the title, so a PR that bundles (say) a `fix(deps)` bump with a
  `feat!` change silently loses the bump's entry. Split unrelated changes into separate PRs.
- **Put the release signal in the title, not just the body.** Mark breaking changes with `!`
  in the title (`feat!: …`) — that is what release-please reads. Body-only footers such as
  `Release-As:` and the long-form `BREAKING CHANGE:` description survive the squash *only* if
  the repo's squash message is set to "Pull request title and description"; when you need a
  deliberate version, steer it through release-please config (e.g. `bump-minor-pre-major`)
  rather than relying on a footer.

> **Repo setting.** Under **Settings → General → Pull Requests**, allow only **squash
> merging** and set the default squash commit message to **"Pull request title and
> description"** so description footers reach release-please.

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
