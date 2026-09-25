#!/usr/bin/env python3
"""Report forks whose release pipeline is failing.

`path-browserify` published nothing for five weeks. Its `release-please` run
failed on every push in that window, the version in `package.json` moved ahead
of the last tag, and npm stayed on the old version. Nothing said so: a
scheduled job that fails quietly looks exactly like one that has nothing to do.

This checks three things per repo and reports any that disagree:

  1. the latest `release-please` run - a failure means no release can be cut
  2. the latest `publish` run - a failure means a release was cut but not shipped
  3. `package.json#version` against npm - the end state both of the above break

Point 3 is the one that matters, because it is the only check that notices when
a repo is behind for a reason nobody predicted. The two run checks explain why.

A check that fails is never reported as healthy: every repo lands in exactly
one of unhealthy / healthy / skipped / errors, and the script exits non-zero if
anything errored.

Usage:
    python3 release_health.py [--org ORG] [--json PATH] [--markdown PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

ORG = 'unabandoned'


class CheckError(Exception):
    """A repo could not be checked. Never treated as healthy."""


def gh(*args: str, raw: bool = False):
    proc = subprocess.run(('gh',) + args, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        raise CheckError(msg.splitlines()[-1] if msg else 'gh failed')
    return proc.stdout if raw else json.loads(proc.stdout or 'null')


def latest_run(org: str, repo: str, workflow: str) -> dict | None:
    """Conclusion of the most recent run of a workflow, or None if it never ran."""
    try:
        runs = gh('api', f'repos/{org}/{repo}/actions/workflows/{workflow}/runs?per_page=1')
    except CheckError:
        return None                      # workflow file absent is not a failure
    items = (runs or {}).get('workflow_runs') or []
    if not items:
        return None
    r = items[0]
    return {'conclusion': r.get('conclusion'), 'status': r.get('status'),
            'url': r.get('html_url'), 'at': (r.get('created_at') or '')[:16]}


def npm_has(name: str, version: str) -> bool:
    url = f"https://registry.npmjs.org/{name.replace('/', '%2f')}/{version}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise CheckError(f'npm returned {exc.code} for {name}@{version}')
    except Exception as exc:             # noqa: BLE001
        raise CheckError(f'npm lookup failed for {name}@{version}: {exc}')


def check(org: str, repo: str) -> dict:
    try:
        pkg_raw = gh('api', f'repos/{org}/{repo}/contents/package.json',
                     '-H', 'Accept: application/vnd.github.raw', raw=True)
    except CheckError:
        return {'repo': repo, 'state': 'skipped', 'why': 'no package.json'}
    pkg = json.loads(pkg_raw)
    name, version = pkg.get('name', ''), pkg.get('version', '')
    if not name.startswith('@unabandoned/') or pkg.get('private'):
        return {'repo': repo, 'state': 'skipped', 'why': 'not a published package'}

    rp = latest_run(org, repo, 'release-please.yml')
    pub = latest_run(org, repo, 'publish.yml')
    published = npm_has(name, version)

    problems = []
    if rp and rp['conclusion'] not in (None, 'success', 'skipped'):
        problems.append(f"latest `release-please` run **{rp['conclusion']}** ([run]({rp['url']}))")
    if pub and pub['conclusion'] not in (None, 'success', 'skipped'):
        problems.append(f"latest `publish` run **{pub['conclusion']}** ([run]({pub['url']}))")
    if not published:
        problems.append(f'`{name}@{version}` is **not on npm** (repo is ahead of the registry)')

    return {'repo': repo, 'state': 'unhealthy' if problems else 'healthy',
            'package': name, 'version': version, 'problems': problems,
            'release_please': rp, 'publish': pub}


def render(results: list[dict], errors: list[dict], org: str) -> str:
    bad = [r for r in results if r['state'] == 'unhealthy']
    good = [r for r in results if r['state'] == 'healthy']
    skipped = [r for r in results if r['state'] == 'skipped']

    out: list[str] = []
    if bad:
        out.append(f'**{len(bad)} package(s) have a broken release pipeline.**\n')
    elif errors:
        out.append('**Nothing unhealthy, but some repos could not be checked — see below.**\n')
    else:
        out.append('**Every package is releasing and published.**\n')

    for r in bad:
        out.append(f"### `{r['repo']}` — `{r['package']}@{r['version']}`\n")
        for p in r['problems']:
            out.append(f'- {p}')
        out.append('')
        out.append('A failing `release-please` run blocks every later release, not just one: '
                   'the version and manifest move on merge, so the repo drifts ahead of its '
                   'last tag and stays there until the run succeeds.\n')

    if errors:
        out.append(f'### Could not be checked ({len(errors)})\n')
        out.append('These are **not** known to be healthy — the check itself failed.\n')
        for e in errors:
            out.append(f"- `{e['repo']}` — {e['error']}")
        out.append('')

    out.append('<details>')
    out.append(f'<summary>Healthy ({len(good)}) and skipped ({len(skipped)})</summary>\n')
    if good:
        out.append('**Healthy:** ' + ', '.join(f"`{r['repo']}`" for r in good) + '\n')
    if skipped:
        out.append('**Skipped** (not a published package): '
                   + ', '.join(f"`{r['repo']}`" for r in skipped) + '\n')
    out.append('</details>\n')
    out.append('---')
    out.append(f'_Generated by `scripts/release_health.py` in '
               f'[{org}/.github](https://github.com/{org}/.github)._')
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--org', default=ORG)
    ap.add_argument('--json', dest='json_path')
    ap.add_argument('--markdown', dest='md_path')
    args = ap.parse_args()

    try:
        repos = gh('api', f'orgs/{args.org}/repos?per_page=100', '--paginate', '--slurp')
    except CheckError as exc:
        print(f'error: could not list repos for org {args.org}: {exc}', file=sys.stderr)
        return 1
    flat = [r for page in repos for r in page] if repos and isinstance(repos[0], list) else repos
    names = sorted(r['name'] for r in flat if not r.get('archived') and not r.get('private'))

    results, errors = [], []
    for name in names:
        try:
            results.append(check(args.org, name))
        except CheckError as exc:
            errors.append({'repo': name, 'error': str(exc)})
        except Exception as exc:         # noqa: BLE001
            errors.append({'repo': name, 'error': f'{type(exc).__name__}: {exc}'})

    markdown = render(results, errors, args.org)
    if args.md_path:
        open(args.md_path, 'w', encoding='utf-8').write(markdown)
    if args.json_path:
        json.dump({'results': results, 'errors': errors}, open(args.json_path, 'w'), indent=2)
    if not args.md_path and not args.json_path:
        print(markdown)

    unhealthy = [r for r in results if r['state'] == 'unhealthy']
    print(f'checked={len(names)} unhealthy={len(unhealthy)} errors={len(errors)}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
