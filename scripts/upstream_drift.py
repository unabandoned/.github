#!/usr/bin/env python3
"""Report which `unabandoned/*` forks are behind their upstream.

A fork can be perfectly maintained here and still be missing commits upstream
made after we forked. This walks every repo in the org, resolves its upstream,
and asks GitHub how many upstream commits our default branch does not have.

Resolving the upstream: GitHub's own fork parent when there is one, else
`upstream.repo` from `.unabandoned.yml`. Repos with neither (the org's own
infra) are reported as such rather than silently skipped.

Reading the comparison: for `compare/OURS...upstream:repo:THEIRS`, `ahead_by`
counts commits in the head (upstream) that the base (us) lacks. That is the
number we want. `behind_by` is the opposite direction — our own fork work,
which is expected to be non-zero everywhere and is not drift.

A check that fails is never reported as a clean check. Every repo lands in
exactly one of drifted / clean / no-upstream / errors, and the script exits
non-zero if anything errored, so a broken run cannot read as "all clear".

Usage:
    python3 upstream_drift.py [--org ORG] [--json PATH] [--markdown PATH]

Requires the `gh` CLI, authenticated with read access to the org.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

ORG = 'unabandoned'


class CheckError(Exception):
    """A repo could not be checked. Never silently treated as no drift."""


def gh(*args: str, raw: bool = False) -> Any:
    """Run `gh` and return parsed JSON (or raw text). Raises on failure."""
    proc = subprocess.run(
        ('gh',) + args,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise CheckError((proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else 'gh failed')
    return proc.stdout if raw else json.loads(proc.stdout or 'null')


def list_repos(org: str) -> list[dict]:
    repos = gh('api', f'orgs/{org}/repos?per_page=100', '--paginate', '--slurp')
    flat = [r for page in repos for r in page] if repos and isinstance(repos[0], list) else repos
    return [r for r in flat if not r.get('archived') and not r.get('private')]


def upstream_from_metadata(org: str, repo: str) -> str | None:
    """Read `upstream.repo` out of `.unabandoned.yml`, if the repo has one."""
    try:
        text = gh('api', f'repos/{org}/{repo}/contents/.unabandoned.yml',
                  '-H', 'Accept: application/vnd.github.raw', raw=True)
    except CheckError:
        return None
    try:
        import yaml
        data = yaml.safe_load(text) or {}
        value = (data.get('upstream') or {}).get('repo')
    except ImportError:
        # PyYAML is preinstalled on GitHub runners; fall back to a flat scan so
        # a local run without it degrades rather than dying.
        value = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('repo:'):
                value = stripped.split(':', 1)[1].strip().strip('"\'')
                break
    if isinstance(value, str) and value.count('/') == 1 and ' ' not in value:
        return value
    return None


def check(org: str, repo: dict) -> dict:
    """Resolve one repo's upstream and measure drift."""
    name = repo['name']
    ours = repo.get('default_branch') or 'master'
    parent = (repo.get('parent') or {}).get('full_name')

    if not parent:
        # `orgs/{org}/repos` omits `parent`; ask for the repo directly before
        # concluding there is no upstream.
        parent = (gh('api', f'repos/{org}/{name}') or {}).get('parent', {}).get('full_name')
    source = 'fork parent'
    if not parent:
        parent = upstream_from_metadata(org, name)
        source = 'metadata'
    if not parent:
        return {'repo': name, 'state': 'no-upstream'}

    up_owner, up_name = parent.split('/', 1)
    theirs = (gh('api', f'repos/{parent}') or {}).get('default_branch')
    if not theirs:
        raise CheckError(f'upstream {parent} has no default branch')

    cmp = gh('api', f'repos/{org}/{name}/compare/{ours}...{up_owner}:{up_name}:{theirs}')
    ahead = cmp.get('ahead_by', 0)
    commits = [
        {
            'sha': c['sha'][:8],
            'date': c['commit']['committer']['date'][:10],
            'author': (c['commit']['author'] or {}).get('name', '?'),
            'title': c['commit']['message'].split('\n')[0],
        }
        for c in (cmp.get('commits') or [])
    ]
    return {
        'repo': name,
        'state': 'drifted' if ahead else 'clean',
        'upstream': parent,
        'upstream_branch': theirs,
        'our_branch': ours,
        'behind_by': ahead,
        'commits': commits,
        'resolved_via': source,
    }


def render(results: list[dict], errors: list[dict], org: str) -> str:
    drifted = [r for r in results if r['state'] == 'drifted']
    clean = [r for r in results if r['state'] == 'clean']
    none = [r for r in results if r['state'] == 'no-upstream']

    out: list[str] = []
    if drifted:
        out.append(f'**{len(drifted)} fork(s) behind upstream.**\n')
    elif errors:
        out.append('**No drift found, but some repos could not be checked — see below.**\n')
    else:
        out.append('**No forks are behind upstream.**\n')

    for r in drifted:
        out.append(f'### `{r["repo"]}` — {r["behind_by"]} commit(s) behind [`{r["upstream"]}`](https://github.com/{r["upstream"]})\n')
        out.append('| Date | Commit | Author | Title |')
        out.append('|---|---|---|---|')
        for c in r['commits']:
            title = c['title'].replace('|', '\\|')
            out.append(f'| {c["date"]} | [`{c["sha"]}`](https://github.com/{r["upstream"]}/commit/{c["sha"]}) | {c["author"]} | {title} |')
        out.append('')
        out.append('Review these before pulling: upstream CI, funding and lint config usually '
                   'conflicts with what this org standardises on, and is not worth taking.\n')

    if errors:
        out.append(f'### Could not be checked ({len(errors)})\n')
        out.append('These are **not** known to be clean — the check itself failed.\n')
        for e in errors:
            out.append(f'- `{e["repo"]}` — {e["error"]}')
        out.append('')

    out.append('<details>')
    out.append(f'<summary>Up to date ({len(clean)}) and no upstream ({len(none)})</summary>\n')
    if clean:
        out.append('**Up to date:** ' + ', '.join(f'`{r["repo"]}`' for r in clean) + '\n')
    if none:
        out.append('**No upstream** (org infra, or no fork parent and no `upstream.repo` in '
                   '`.unabandoned.yml`): ' + ', '.join(f'`{r["repo"]}`' for r in none) + '\n')
    out.append('</details>\n')
    out.append('---')
    out.append(f'_Generated by `scripts/upstream_drift.py` in [{org}/.github](https://github.com/{org}/.github)._')
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--org', default=ORG)
    ap.add_argument('--json', dest='json_path')
    ap.add_argument('--markdown', dest='md_path')
    args = ap.parse_args()

    try:
        repos = sorted(list_repos(args.org), key=lambda r: r['name'])
    except CheckError as exc:
        # Listing the org is the one failure that cannot be attributed to a
        # single repo. Say so plainly rather than emitting a traceback that
        # could be mistaken for a clean run.
        print(f'error: could not list repos for org {args.org}: {exc}', file=sys.stderr)
        return 1
    results: list[dict] = []
    errors: list[dict] = []
    for repo in repos:
        try:
            results.append(check(args.org, repo))
        except CheckError as exc:
            errors.append({'repo': repo['name'], 'error': str(exc)})
        except Exception as exc:  # noqa: BLE001 - unexpected shapes are errors, not clean
            errors.append({'repo': repo['name'], 'error': f'{type(exc).__name__}: {exc}'})

    drifted = [r for r in results if r['state'] == 'drifted']
    markdown = render(results, errors, args.org)

    if args.md_path:
        with open(args.md_path, 'w', encoding='utf-8') as fh:
            fh.write(markdown)
    if args.json_path:
        with open(args.json_path, 'w', encoding='utf-8') as fh:
            json.dump({'results': results, 'errors': errors}, fh, indent=2)
    if not args.md_path and not args.json_path:
        print(markdown)

    print(f'checked={len(repos)} drifted={len(drifted)} errors={len(errors)}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
