#!/usr/bin/env python3
"""Audit the resolved runtime tree beneath every published `@unabandoned/*` fork.

Renovate's dependency dashboard can only flag what it finds in a `package.json`,
so an abandoned package that is reachable only transitively never appears on any
dashboard in the org. This module closes that blind spot: it resolves each fork's
full production tree and classifies every node in it.

Everything here is DERIVED at build time, never recorded in a file:

- the tree comes from `npm install --package-lock-only`, which resolves the real
  semver graph without downloading a single tarball or running a lifecycle script;
- each node's own runtime dependency count comes from that lockfile;
- each node's last release date comes from the npm registry packument.

The classification is the part that decides what to do about a package, and it
turns on whether an abandoned package can still rot:

    alive      released within the threshold — a maintainer is still shipping,
               so anything abandoned beneath it has someone who can respond.
    inert      abandoned but declares zero runtime dependencies. Nothing sits
               under it to go stale, so it is frozen, not rotting.
    time bomb  abandoned AND carrying its own runtime dependencies. Nobody is
               left to bump them, so its subtree ages unwatched.

Only the third class is actionable, and `inert` is exactly the class the shared
Renovate preset is entitled to suppress.

One derived cross-check earns its own section: a fork's tree may contain the
abandoned UPSTREAM copy of a package this org already maintains, because the fork
was never repointed at its sibling. That is self-inflicted rot and is reported
separately from genuinely third-party exposure.

Best-effort by construction, matching the rest of the builder: a package that
fails to resolve (unpublished, registry hiccup) degrades to one "unresolved" row
rather than failing the build.
"""
from __future__ import annotations

import datetime
import html
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REGISTRY = "https://registry.npmjs.org"
SCOPE = "@unabandoned/"

# Matches `abandonments:recommended` in the shared Renovate preset, so this page
# and the per-fork dependency dashboards agree on what "abandoned" means.
ABANDONMENT_DAYS = 365

NPM_TIMEOUT = 120
HTTP_TIMEOUT = 30

_DATE_CACHE: dict[str, str | None] = {}

# Worst-wins ordering when one package name resolves to different versions (and
# so different states) across forks.
_SEVERITY = {"alive": 0, "inert": 1, "bomb": 2}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def last_release(name: str) -> str | None:
    """Publish date (YYYY-MM-DD) of a package's current `latest`, or None."""
    if name in _DATE_CACHE:
        return _DATE_CACHE[name]
    url = f"{REGISTRY}/{urllib.parse.quote(name, safe='@')}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "unabandoned-dashboard")
    date = None
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        latest = (doc.get("dist-tags") or {}).get("latest")
        stamp = (doc.get("time") or {}).get(latest)
        if stamp:
            date = stamp[:10]
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError):
        date = None  # unknown date -> treated as alive, never as a false alarm
    _DATE_CACHE[name] = date
    return date


# --------------------------------------------------------------------------- #
# Tree resolution
# --------------------------------------------------------------------------- #
def npm_available() -> bool:
    return shutil.which("npm") is not None


def _lookup(entries: dict, from_key: str, dep: str) -> str | None:
    """Which lockfile entry satisfies `dep` when required from `from_key`.

    Mirrors node's resolution: try `<dir>/node_modules/<dep>`, then walk up one
    enclosing package at a time. Hoisted trees resolve on the last hop; nested
    copies (a version conflict) resolve on an earlier one, which is exactly the
    distinction that makes a path correct rather than merely plausible.
    """
    prefix = from_key
    while True:
        candidate = (prefix + "/node_modules/" + dep).lstrip("/")
        if candidate in entries:
            return candidate
        if not prefix:
            return None
        cut = prefix.rfind("/node_modules/")
        prefix = prefix[:cut] if cut != -1 else ""


def _shortest_paths(entries: dict, root_key: str, real_name) -> dict[str, list[str]]:
    """BFS from the fork, returning {entry key: [real names, root first]}.

    Shortest wins because it is the most direct explanation of why a package is
    in the tree; a package pulled by several parents gets the tightest one.
    """
    start = root_key if root_key in entries else ""
    paths = {start: [real_name(start)] if start else []}
    queue = [start]
    while queue:
        nxt: list[str] = []
        for key in queue:
            for dep in ((entries.get(key) or {}).get("dependencies") or {}):
                child = _lookup(entries, key, dep)
                if child is None or child in paths:
                    continue
                paths[child] = paths[key] + [real_name(child)]
                nxt.append(child)
        queue = nxt
    return paths


def resolve_tree(package: str) -> tuple[dict, str | None]:
    """Resolve `package`'s production tree.

    Returns ({name: {"version", "ndeps", "direct"}}, error). Uses
    `--package-lock-only`, so nothing is downloaded or executed — npm only walks
    the registry metadata and writes the resolved graph to a lockfile.
    """
    work = tempfile.mkdtemp(prefix="unabandoned-audit-")
    try:
        with open(os.path.join(work, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "audit-probe", "version": "1.0.0", "private": True}, fh)
        proc = subprocess.run(
            ["npm", "install", package, "--package-lock-only", "--omit=dev",
             "--ignore-scripts", "--no-audit", "--no-fund", "--silent"],
            cwd=work, capture_output=True, text=True, timeout=NPM_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            return {}, (detail[-1][:200] if detail else "npm install failed")

        lock_path = os.path.join(work, "package-lock.json")
        if not os.path.exists(lock_path):
            return {}, "no lockfile produced"
        with open(lock_path, encoding="utf-8") as fh:
            lock = json.load(fh)

        entries = lock.get("packages") or {}
        root_key = "node_modules/" + package
        direct = set((entries.get(root_key) or {}).get("dependencies") or {})

        def real_name(key: str) -> str:
            # npm's alias syntax — "buffer": "npm:@unabandoned/buffer@^6" — installs
            # one package under another's directory name. The lockfile key is only
            # WHERE it was placed; `name` is WHAT it actually is. Identifying by the
            # key would read a fork as its abandoned upstream and date it from the
            # wrong packument, so the real name always wins.
            meta = entries.get(key) or {}
            return meta.get("name") or key.split("node_modules/")[-1]

        # Shortest path from the fork down to each package, so the audit can say
        # HOW something arrives and not merely THAT it is present. Node resolution
        # walks up the directory chain, so a dependency reference is satisfied by
        # the nearest enclosing node_modules — same rule `require` uses.
        paths = _shortest_paths(entries, root_key, real_name)

        tree: dict[str, dict] = {}
        for key, meta in entries.items():
            if not key.startswith("node_modules/"):
                continue
            alias = key.split("node_modules/")[-1]
            name = real_name(key)
            if name == package or meta.get("dev") or meta.get("optional"):
                continue
            chain = paths.get(key)
            tree[name] = {
                "version": meta.get("version"),
                "ndeps": len(meta.get("dependencies") or {}),
                # The root's `dependencies` are keyed by alias, so directness is a
                # question about the alias, not the resolved name.
                "direct": alias in direct,
                "alias": alias if alias != name else None,
                # Everything between the fork and this package, exclusive of both.
                "via": chain[1:-1] if chain and len(chain) > 2 else [],
                "parent": chain[-2] if chain and len(chain) > 1 else None,
                "depth": (len(chain) - 1) if chain else None,
            }
        return tree, None
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"[:200]
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(last: str | None, ndeps: int, cutoff: datetime.date) -> str:
    """alive | inert | bomb. An unknown date is treated as alive, never as a bomb."""
    if not last:
        return "alive"
    try:
        released = datetime.date.fromisoformat(last)
    except ValueError:
        return "alive"
    if released >= cutoff:
        return "alive"
    return "bomb" if ndeps else "inert"


def audit(packages: list[str]) -> dict:
    """Resolve and classify every fork's tree. `packages` are npm names.

    Returns a JSON-serialisable report; an empty `forks` list means the audit
    could not run (no npm on PATH) and callers should omit the section.
    """
    if not npm_available() or not packages:
        return {"available": False, "forks": [], "unique": [], "self_hosted": [],
                "totals": {}, "threshold_days": ABANDONMENT_DAYS}

    cutoff = datetime.date.today() - datetime.timedelta(days=ABANDONMENT_DAYS)
    # Short names of packages this org maintains, for the self-inflicted check:
    # "@unabandoned/util" -> "util".
    owned = {p[len(SCOPE):] for p in packages if p.startswith(SCOPE)}

    forks: list[dict] = []
    unique: dict[str, dict] = {}
    self_hosted: dict[str, dict] = {}

    for package in packages:
        tree, error = resolve_tree(package)
        if error:
            forks.append({"package": package, "error": error, "total": 0,
                          "alive": 0, "inert": 0, "bomb": 0, "invisible": 0})
            continue

        counts = {"alive": 0, "inert": 0, "bomb": 0}
        invisible = 0
        for name, node in tree.items():
            last = last_release(name)
            state = classify(last, node["ndeps"], cutoff)
            counts[state] += 1
            if state == "bomb" and not node["direct"]:
                invisible += 1

            slot = unique.setdefault(name, {
                "name": name, "version": node["version"], "last": last,
                "ndeps": node["ndeps"], "state": state,
                "versions": [], "forks": [], "direct_somewhere": False,
                "parents": [], "trail": None, "trail_fork": None,
            })
            slot["forks"].append(package)
            slot["direct_somewhere"] |= node["direct"]
            # Who actually declares it, across every fork — the answer to "why is
            # this here", which tree membership alone cannot give.
            if node.get("parent") and node["parent"] not in slot["parents"]:
                slot["parents"].append(node["parent"])
            # Keep the shortest trail seen anywhere as the worked example.
            if node.get("depth") is not None and (
                slot["trail"] is None or node["depth"] < len(slot["trail"]) + 1
            ):
                slot["trail"] = node.get("via") or []
                slot["trail_fork"] = package
            if node["version"] not in slot["versions"]:
                slot["versions"].append(node["version"])
            # Different forks can resolve different majors of the same name, and
            # those majors can classify differently (readable-stream 4.x carries
            # deps, 2.x carries more, some builds carry none). Keep the WORST
            # state so the rollup reports real exposure — and so the totals do
            # not depend on which fork happened to be audited first.
            if _SEVERITY[state] > _SEVERITY[slot["state"]]:
                slot.update(state=state, version=node["version"],
                            ndeps=node["ndeps"], last=last)

            # Self-inflicted: the abandoned upstream of a package we already own.
            if name in owned and state != "alive":
                sh = self_hosted.setdefault(name, {
                    "upstream": name, "state": state, "last": last,
                    "pulled_by": [], "parents": [],
                })
                sh["pulled_by"].append(package)
                if node.get("parent") and node["parent"] not in sh["parents"]:
                    sh["parents"].append(node["parent"])
                if _SEVERITY[state] > _SEVERITY[sh["state"]]:
                    sh.update(state=state, last=last)

        forks.append({
            "package": package, "error": None, "total": len(tree),
            "alive": counts["alive"], "inert": counts["inert"],
            "bomb": counts["bomb"], "invisible": invisible,
        })

    for slot in unique.values():
        slot["forks"].sort()
        slot["versions"].sort()
        slot["parents"].sort()
    for sh in self_hosted.values():
        sh["pulled_by"].sort()
        sh["parents"].sort()

    bombs = [u for u in unique.values() if u["state"] == "bomb"]
    totals = {
        "forks_audited": sum(1 for f in forks if not f["error"]),
        "forks_unresolved": sum(1 for f in forks if f["error"]),
        "unique": len(unique),
        "bomb": len(bombs),
        "inert": sum(1 for u in unique.values() if u["state"] == "inert"),
        "alive": sum(1 for u in unique.values() if u["state"] == "alive"),
        "invisible": sum(1 for u in bombs if not u["direct_somewhere"]),
        "self_hosted": len(self_hosted),
        "self_hosted_forks": len({p for sh in self_hosted.values() for p in sh["pulled_by"]}),
    }

    return {
        "available": True,
        "threshold_days": ABANDONMENT_DAYS,
        "forks": sorted(forks, key=lambda f: (-f["bomb"], f["package"])),
        "unique": sorted(unique.values(), key=lambda u: (-len(u["forks"]), u["name"])),
        "self_hosted": sorted(self_hosted.values(),
                              key=lambda s: (-len(s["pulled_by"]), s["upstream"])),
        "totals": totals,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def e(text) -> str:
    return html.escape(str(text if text is not None else ""))


AUDIT_CSS = """
.audit-section { margin: 24px 0; }
.audit-title { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: baseline;
  justify-content: space-between; margin: 0 0 10px; }
.audit-section h2 { margin: 0; font-size: 17px; letter-spacing: -.01em; }
.audit-sub { font-size: 12.5px; color: var(--fg-muted); }
.audit-wrap { background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px; box-shadow: var(--shadow); }
.audit-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px; margin-bottom: 14px; }
.audit-tile { background: var(--panel-2); border: 1px solid var(--border-muted);
  border-radius: 9px; padding: 11px 13px; border-top: 3px solid var(--border); }
.audit-tile .n { font: 650 24px/1.1 -apple-system, system-ui, sans-serif;
  letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.audit-tile .l { font-size: 11.5px; color: var(--fg-muted); margin-top: 2px; }
.audit-tile.t-bomb { border-top-color: var(--bad); } .audit-tile.t-bomb .n { color: var(--bad); }
.audit-tile.t-inert { border-top-color: var(--warn); } .audit-tile.t-inert .n { color: var(--warn); }
.audit-tile.t-alive { border-top-color: var(--ok); } .audit-tile.t-alive .n { color: var(--ok); }
.audit-tile.t-key { border-top-color: var(--accent); } .audit-tile.t-key .n { color: var(--accent); }
.audit-lede { font-size: 13.5px; color: var(--fg-muted); margin: 0 0 14px; max-width: 78ch; }
.audit-lede b { color: var(--fg); }
.audit-scroll { overflow-x: auto; border: 1px solid var(--border-muted); border-radius: 9px; }
.audit-table { border-collapse: collapse; width: 100%; font-size: 12.5px; min-width: 520px; }
.audit-table th, .audit-table td { text-align: left; padding: 7px 11px;
  border-bottom: 1px solid var(--border-muted); white-space: nowrap; }
.audit-table thead th { font-size: 10.5px; letter-spacing: .07em; text-transform: uppercase;
  color: var(--fg-muted); background: var(--panel-2); }
.audit-table tbody tr:last-child td { border-bottom: none; }
.audit-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.audit-table td.name { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.audit-table td.wrap { white-space: normal; color: var(--fg-muted); min-width: 200px; }
.audit-table td.zero { color: var(--fg-muted); }
.audit-hot { color: var(--bad); font-weight: 650; }
.audit-chip { display: inline-block; font-size: 10.5px; letter-spacing: .05em;
  text-transform: uppercase; padding: 2px 7px; border-radius: 999px; font-weight: 650; }
.audit-chip.c-bomb { background: var(--bad-bg); color: var(--bad); }
.audit-chip.c-inert { background: var(--warn-bg); color: var(--warn); }
.audit-chip.c-alive { background: var(--ok-bg); color: var(--ok); }
.audit-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px;
  font-size: 12px; color: var(--fg-muted); }
.audit-table td.trail { white-space: normal; min-width: 280px; }
.audit-trail { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 2px 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11.5px; }
.audit-trail span { background: var(--chip-bg); border-radius: 4px; padding: 1px 5px;
  color: var(--fg-muted); }
.audit-trail .audit-root { color: var(--accent); font-weight: 650; }
.audit-trail .audit-leaf { color: var(--bad); font-weight: 650; }
.audit-trail i { color: var(--fg-muted); font-style: normal; opacity: .65; }
.audit-dim { color: var(--fg-muted); }
.audit-h3 { font: 650 13.5px -apple-system, system-ui, sans-serif; margin: 18px 0 8px;
  letter-spacing: -.005em; }
.audit-empty { font-size: 13px; color: var(--fg-muted); }
"""

SUBTITLE = ("Every package in every fork's resolved production tree — including the "
            "ones no dependency dashboard can see, because they appear in no "
            "package.json. Resolved live, never recorded.")

LEGEND = (
    '<div class="audit-legend">'
    '<span><span class="audit-chip c-alive">alive</span> released within a year</span>'
    '<span><span class="audit-chip c-inert">inert</span> abandoned, zero deps — cannot rot</span>'
    '<span><span class="audit-chip c-bomb">time bomb</span> abandoned with its own deps — nobody left to bump them</span>'
    '</div>'
)


def _chip(state: str) -> str:
    label = {"bomb": "time bomb", "inert": "inert", "alive": "alive"}[state]
    return f'<span class="audit-chip c-{e(state)}">{e(label)}</span>'


def _trail(fork: str | None, via: list[str] | None, leaf: str) -> str:
    """The consumption path, fork first: browserify -> browserify-sign -> readable-stream.

    A package deep in a tree is not actionable until you can see which link put
    it there, so the chain is rendered in full rather than summarised.
    """
    if not fork:
        return '<span class="audit-dim">—</span>'
    hops = [f'<span class="audit-root">{e(fork)}</span>']
    hops += [f"<span>{e(v)}</span>" for v in (via or [])]
    hops.append(f'<span class="audit-leaf">{e(leaf)}</span>')
    return '<span class="audit-trail">' + '<i>→</i>'.join(hops) + "</span>"


def _tiles(t: dict) -> str:
    def tile(n, label, cls=""):
        return (f'<div class="audit-tile {cls}"><div class="n">{n}</div>'
                f'<div class="l">{e(label)}</div></div>')
    return (
        '<div class="audit-tiles">'
        + tile(t.get("unique", 0), "packages in the trees", "t-key")
        + tile(t.get("bomb", 0), "time bombs", "t-bomb")
        + tile(t.get("inert", 0), "inert (suppressible)", "t-inert")
        + tile(t.get("alive", 0), "alive", "t-alive")
        + tile(t.get("invisible", 0), "invisible to every dashboard", "t-bomb")
        + "</div>"
    )


def _lede(t: dict) -> str:
    bits = [
        f'<b>{t.get("invisible", 0)}</b> of <b>{t.get("bomb", 0)}</b> time bombs appear in '
        "no fork's <code>package.json</code>, so no dependency dashboard in the org shows them."
    ]
    if t.get("self_hosted"):
        bits.append(
            f'<b>{t["self_hosted"]}</b> package(s) this org already maintains are still being '
            f'pulled from the abandoned upstream by <b>{t.get("self_hosted_forks", 0)}</b> fork(s) '
            "— repointing those at their siblings is the largest single win available."
        )
    if t.get("forks_unresolved"):
        bits.append(f'{t["forks_unresolved"]} fork(s) could not be resolved (unpublished).')
    return '<p class="audit-lede">' + " ".join(bits) + "</p>"


def _fork_table(forks: list[dict]) -> str:
    rows = []
    for f in forks:
        if f["error"]:
            rows.append(
                f'<tr><td class="name">{e(f["package"])}</td>'
                f'<td class="wrap" colspan="5">unresolved — {e(f["error"])}</td></tr>'
            )
            continue
        hot = ' class="num audit-hot"' if f["bomb"] else ' class="num zero"'
        rows.append(
            f'<tr><td class="name">{e(f["package"])}</td>'
            f'<td class="num">{f["total"]}</td>'
            f'<td{hot}>{f["bomb"]}</td>'
            f'<td{hot}>{f["invisible"]}</td>'
            f'<td class="num">{f["inert"]}</td>'
            f'<td class="num">{f["alive"]}</td></tr>'
        )
    return (
        '<div class="audit-scroll"><table class="audit-table"><thead><tr>'
        "<th>Fork</th><th>Tree</th><th>Time bombs</th><th>Invisible</th>"
        "<th>Inert</th><th>Alive</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></div>"
    )


def _self_hosted_table(rows: list[dict]) -> str:
    if not rows:
        return ('<p class="audit-empty">None — every fork resolves its siblings from the '
                "<code>@unabandoned</code> scope.</p>")
    body = "".join(
        f'<tr><td class="name">{e(r["upstream"])}</td>'
        f'<td>{_chip(r["state"])}</td>'
        f'<td class="name">{e(r["last"] or "unknown")}</td>'
        f'<td class="wrap">{e(", ".join(r.get("parents") or [])) or "—"}</td>'
        f'<td class="wrap">{e(", ".join(r["pulled_by"]))}</td></tr>'
        for r in rows
    )
    return (
        '<div class="audit-scroll"><table class="audit-table"><thead><tr>'
        "<th>Upstream package</th><th>State</th><th>Last release</th>"
        "<th>Declared by</th><th>Reaches</th></tr></thead><tbody>"
        + body + "</tbody></table></div>"
    )


def _bomb_table(unique: list[dict], owned: set[str], limit: int | None = None) -> str:
    rows = [u for u in unique if u["state"] == "bomb" and u["name"] not in owned]
    if limit:
        rows = rows[:limit]
    if not rows:
        return '<p class="audit-empty">No third-party time bombs in any tree.</p>'
    body = "".join(
        f'<tr><td class="name">{e(u["name"])}</td>'
        f'<td class="num">{len(u["forks"])}</td>'
        f'<td class="num">{u["ndeps"]}</td>'
        f'<td class="name">{e(u["last"] or "unknown")}</td>'
        f'<td class="trail">{_trail(u.get("trail_fork"), u.get("trail"), u["name"])}</td></tr>'
        for u in rows
    )
    return (
        '<div class="audit-scroll"><table class="audit-table"><thead><tr>'
        "<th>Package</th><th>Forks</th><th>Own deps</th><th>Last release</th>"
        "<th>Shortest path in</th></tr></thead><tbody>" + body + "</tbody></table></div>"
    )


def audit_panel(report: dict, *, standalone_href: str | None = None) -> str:
    """Compact dashboard section: the headline numbers plus a link to the full page."""
    if not report.get("available") or not report.get("forks"):
        return ""
    link = (f'<a class="audit-sub" href="{standalone_href}">open full audit →</a>'
            if standalone_href else f'<span class="audit-sub">{SUBTITLE}</span>')
    return (
        '<section class="audit-section">'
        f'<div class="audit-title"><h2>Transitive dependency audit</h2>{link}</div>'
        f'<div class="audit-wrap">{_tiles(report["totals"])}{_lede(report["totals"])}'
        f'{_self_hosted_table(report["self_hosted"][:6])}{LEGEND}</div>'
        "</section>"
    )


def audit_page(report: dict, palette_css: str) -> str:
    """Standalone, self-contained audit page reusing the dashboard palette."""
    if not report.get("available") or not report.get("forks"):
        body = ('<h1>unabandoned · transitive dependency audit</h1>'
                '<p class="sub">The audit did not run — npm was unavailable at build time.</p>')
    else:
        owned = {f["package"].split("/", 1)[-1] for f in report["forks"]}
        t = report["totals"]
        body = (
            '<h1>unabandoned · transitive dependency audit</h1>'
            f'<p class="sub">{SUBTITLE}</p>'
            f'<div class="audit-wrap">{_tiles(t)}{_lede(t)}{LEGEND}</div>'
            '<h2 class="audit-h3">Already ours, pulled from upstream anyway</h2>'
            '<p class="sub">Packages with a current <code>@unabandoned</code> fork that forks '
            'still resolve from the abandoned original. Self-inflicted, and mechanical to fix.</p>'
            f'{_self_hosted_table(report["self_hosted"])}'
            '<h2 class="audit-h3">Per fork</h2>'
            f'{_fork_table(report["forks"])}'
            '<h2 class="audit-h3">Third-party time bombs</h2>'
            '<p class="sub">Genuinely external exposure, ranked by how many forks each reaches.</p>'
            f'{_bomb_table(report["unique"], owned)}'
            '<p class="back"><a href="./">← back to the package dashboard</a></p>'
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>unabandoned — transitive dependency audit</title>'
        f"<style>{palette_css}\nbody{{padding:28px;}}"
        "h1{font:650 22px -apple-system,system-ui,sans-serif;margin:0 0 4px;letter-spacing:-.02em;}"
        "p.sub{color:var(--fg-muted);margin:0 0 20px;font:14px -apple-system,system-ui,sans-serif;max-width:78ch;}"
        "p.back{margin-top:18px;font:13px -apple-system,system-ui,sans-serif;}"
        f"{AUDIT_CSS}</style></head><body>{body}</body></html>"
    )
