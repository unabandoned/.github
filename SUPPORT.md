# Support

`@unabandoned/*` packages are **drop-in maintained forks** of upstream npm packages. We keep
their dependency trees current and secure; we do **not** provide general usage support or add
features beyond what upstream offered.

## Where to go

- **Bug in a fork (behaviour differs from upstream, build/publish issue):** open an issue on
  the specific `unabandoned/<package>` repository.
- **Security vulnerability:** do **not** open a public issue — follow
  [`SECURITY.md`](./SECURITY.md).
- **How-to / usage questions about the library's API:** consult the upstream project's docs.
  The public API of each fork matches upstream, so upstream guidance applies.
- **Requesting a new fork:** open an issue on
  [`unabandoned/.github`](https://github.com/unabandoned/.github) describing the abandoned
  package and its outdated dependencies. See the fork trigger in
  [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Response expectations

This is a best-effort maintenance program. Dependency updates flow continuously via Renovate;
security fixes are prioritised on the fast-path. Non-security issues are addressed as
maintainer time allows.
