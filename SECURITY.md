# Security Policy

This policy applies org-wide to every `@unabandoned/*` package unless a repository
overrides it with its own `SECURITY.md`.

## Supported versions

Only the **latest major** of each package is supported at any given time. Because the whole
point of the program is a current dependency tree, we do not backport fixes to older majors —
upgrade to the latest major to receive security updates.

## Reporting a vulnerability

Please report vulnerabilities **privately** — do not open a public issue for a security bug.

1. **GitHub private advisory (preferred).** Open a draft security advisory on the affected
   repository via its **Security → Advisories → Report a vulnerability** tab. This keeps the
   report private while we coordinate a fix.
2. **Tidelift.** For packages covered by a Tidelift subscription, use the
   [Tidelift security contact](https://tidelift.com/security); Tidelift coordinates the fix
   and disclosure.

Please include the affected package and version, a description of the issue, and a
reproduction or proof-of-concept if you have one.

## What to expect

- We aim to acknowledge a report within a few days.
- A confirmed vulnerability — including one in a **transitive dependency** — is fixed on the
  **CVE fast-path**: the fix merges and an out-of-cycle release publishes immediately
  (rather than waiting for the monthly release), then a coordinated disclosure follows.
- We credit reporters in the advisory unless you ask us not to.
