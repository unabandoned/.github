#!/usr/bin/env python3
"""Build the @unabandoned central package dashboard.

Discovers every fork in the org (a repo is a fork iff it carries a valid
`.unabandoned.yml`), pulls its live state from the GitHub API, and renders a
static site — `index.html` + `data.json` — into the output directory for
GitHub Pages to publish.

Design rule: the ONLY hand-authored input is each fork's `.unabandoned.yml`
(editorial context). Everything else — open PRs/issues, pending Renovate
updates, latest release, CI status, security fast-path — is derived live here,
so the dashboard cannot go stale between rebuilds. Nothing on the page is typed
by a human into a central file.

Environment:
    GITHUB_TOKEN / GH_TOKEN   token for the GitHub API (required in CI).
    DASHBOARD_ORG             org to scan (default: unabandoned).
    DASHBOARD_OUT             output directory (default: public).

Best-effort by construction: a failing sub-request for one fork degrades that
one datum to "unknown" rather than failing the whole build.
"""
from __future__ import annotations

import base64
import datetime
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dep_audit
import topology
from validate_metadata import load as load_yaml
from validate_metadata import validate as validate_metadata

ORG = os.environ.get("DASHBOARD_ORG", "unabandoned")
OUT_DIR = Path(os.environ.get("DASHBOARD_OUT", "public"))
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
TEMPLATE = Path(__file__).resolve().parent / "dashboard_template.html"

RENOVATE_LOGINS = {"renovate[bot]", "renovate-bot", "renovate"}
METADATA_FILE = ".unabandoned.yml"


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
def gh_api(path: str, params: dict | None = None, *, allow_404: bool = False):
    """GET a GitHub API path. Returns parsed JSON, or None on an allowed 404."""
    url = path if path.startswith("http") else API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "unabandoned-dashboard")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and allow_404:
            return None
        raise


def gh_paginated(path: str, params: dict | None = None) -> list:
    """Fetch up to a few pages of a list endpoint (forks are small; 300 is ample)."""
    params = dict(params or {})
    params.setdefault("per_page", 100)
    out: list = []
    page = 1
    while page <= 3:
        params["page"] = page
        batch = gh_api(path, params)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < params["per_page"]:
            break
        page += 1
    return out


# --------------------------------------------------------------------------- #
# Discovery + per-fork data gathering
# --------------------------------------------------------------------------- #
def fetch_metadata(repo: str):
    """Return (data, errors) for a repo's .unabandoned.yml, or (None, None) if absent."""
    payload = gh_api(
        f"/repos/{ORG}/{repo}/contents/{METADATA_FILE}", allow_404=True
    )
    if not payload or "content" not in payload:
        return None, None
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8")
        data = load_yaml(text)
    except Exception as exc:  # malformed file — surface, don't crash the build
        return {}, [f"could not read {METADATA_FILE}: {exc}"]
    return data, validate_metadata(data)


def ci_state(repo: str, ref: str) -> str:
    """Aggregate check-runs on the default branch head into one word."""
    try:
        payload = gh_api(
            f"/repos/{ORG}/{repo}/commits/{urllib.parse.quote(ref)}/check-runs"
        )
    except urllib.error.HTTPError:
        return "unknown"
    runs = (payload or {}).get("check_runs", [])
    if not runs:
        return "unknown"
    if any(r.get("status") != "completed" for r in runs):
        return "pending"
    bad = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
    if any(r.get("conclusion") in bad for r in runs):
        return "failing"
    good = {"success", "neutral", "skipped", None}
    if all(r.get("conclusion") in good for r in runs):
        return "passing"
    return "unknown"


def resolve_dep_name(name: str, spec) -> str:
    """The package a dependency entry actually resolves to.

    Forks wire themselves to their siblings with npm's alias syntax —
    `"buffer": "npm:@unabandoned/buffer@^6"` — which keeps `require('buffer')`
    working unchanged while pulling our fork. The scope lives in the SPEC, not
    the key, so reading keys alone makes every fork->fork edge invisible and the
    topology graph renders as isolated nodes.
    """
    spec = str(spec)
    if not spec.startswith("npm:"):
        return name
    target = spec[len("npm:"):]
    at = target.rfind("@")          # rfind: scoped names carry a leading '@'
    return target[:at] if at > 0 else target


def has_label(item: dict, name: str) -> bool:
    return any(
        (lbl.get("name", "").lower() == name.lower())
        for lbl in item.get("labels", [])
    )


def gather(repo_obj: dict, metadata: dict) -> dict:
    """Collect the live + editorial state for one fork."""
    repo = repo_obj["name"]
    default_branch = repo_obj.get("default_branch", "master")

    # Open PRs (Renovate, security, autorelease-pending live here).
    try:
        prs = gh_paginated(f"/repos/{ORG}/{repo}/pulls", {"state": "open"})
    except urllib.error.HTTPError:
        prs = []
    renovate_prs = [p for p in prs if (p.get("user") or {}).get("login") in RENOVATE_LOGINS]
    security_prs = [p for p in prs if has_label(p, "security")]
    autorelease_pending = any(has_label(p, "autorelease: pending") for p in prs)

    # Open issues (the /issues list includes PRs — filter them out).
    try:
        issues_raw = gh_paginated(f"/repos/{ORG}/{repo}/issues", {"state": "open"})
    except urllib.error.HTTPError:
        issues_raw = []
    issues = [i for i in issues_raw if "pull_request" not in i]
    # Renovate's "Dependency Dashboard" is a control surface, not work. It is
    # always open, exists on every fork, and the card already links to it as its
    # own fact — counting it as an issue too put a permanent floor of 1 under
    # every fork and made the org-wide total almost entirely noise. Matched on
    # the bot author as well as the title, so a human-filed issue that happens
    # to share the name still counts as real work.
    dep_dashboard = next(
        (i for i in issues
         if i.get("title", "").strip().lower() == "dependency dashboard"
         and (i.get("user") or {}).get("login") in RENOVATE_LOGINS),
        None,
    )
    if dep_dashboard is not None:
        issues = [i for i in issues if i is not dep_dashboard]
    security_issues = [i for i in issues if has_label(i, "security")]

    # Latest release.
    release = gh_api(f"/repos/{ORG}/{repo}/releases/latest", allow_404=True)

    # package.json runtime dependencies — drives the fork->fork topology edges.
    dep_packages: list[str] = []
    pj = gh_api(f"/repos/{ORG}/{repo}/contents/package.json", allow_404=True)
    if pj and "content" in pj:
        try:
            pkg_json = json.loads(base64.b64decode(pj["content"]).decode("utf-8"))
            dep_packages = sorted(
                {resolve_dep_name(n, s)
                 for n, s in (pkg_json.get("dependencies") or {}).items()}
            )
        except Exception:
            pass  # a fork without a parseable package.json just has no edges

    return {
        "repo": repo,
        "package": metadata.get("package", repo),
        "dep_packages": dep_packages,
        "html_url": repo_obj.get("html_url", f"https://github.com/{ORG}/{repo}"),
        "default_branch": default_branch,
        "pushed_at": repo_obj.get("pushed_at"),
        "metadata": metadata,
        "open_pr_count": len(prs),
        "renovate_pr_count": len(renovate_prs),
        "open_issue_count": len(issues),
        "security_count": len(security_prs) + len(security_issues),
        "autorelease_pending": autorelease_pending,
        "dependency_dashboard_url": (dep_dashboard or {}).get("html_url"),
        "release_tag": (release or {}).get("tag_name"),
        "release_url": (release or {}).get("html_url"),
        "release_date": ((release or {}).get("published_at") or "")[:10] or None,
        "ci": ci_state(repo, default_branch),
    }


def discover() -> list[dict]:
    """Return gathered data for every fork (repo with valid metadata), sorted by name."""
    repos = gh_paginated(f"/orgs/{ORG}/repos", {"type": "public"})
    forks: list[dict] = []
    for repo_obj in repos:
        if repo_obj.get("archived"):
            continue
        metadata, errors = fetch_metadata(repo_obj["name"])
        if metadata is None:
            continue  # not a fork — infra repos have no .unabandoned.yml
        if errors:
            # CI blocks invalid metadata from merging, so this is rare; log and
            # skip rather than render a half-broken card.
            sys.stderr.write(
                f"warning: skipping {repo_obj['name']} — invalid {METADATA_FILE}: "
                f"{'; '.join(errors)}\n"
            )
            continue
        forks.append(gather(repo_obj, metadata))
    forks.sort(key=lambda f: f["metadata"].get("package", f["repo"]).lower())
    return forks


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def e(text) -> str:
    return html.escape(str(text if text is not None else ""))


CI_BADGE = {
    "passing": ("ok", "CI passing"),
    "failing": ("bad", "CI failing"),
    "pending": ("warn", "CI running"),
    "unknown": ("neutral", "CI unknown"),
}


def needs_attention(f: dict) -> bool:
    return bool(
        f["ci"] == "failing"
        or f["security_count"]
        or f["metadata"].get("status") in ("seeking-replacement", "deprecated")
    )


def render_card(f: dict) -> str:
    md = f["metadata"]
    package = md.get("package", f["repo"])
    npm_url = "https://www.npmjs.com/package/" + package
    upstream = (md.get("upstream") or {})
    upstream_repo = upstream.get("repo", "")
    status = md.get("status", "active")

    badges = []
    ci_class, ci_text = CI_BADGE[f["ci"]]
    badges.append(f'<span class="badge {ci_class}">{e(ci_text)}</span>')
    if f["security_count"]:
        badges.append(
            f'<span class="badge bad">{f["security_count"]} security</span>'
        )
    if f["autorelease_pending"]:
        badges.append('<span class="badge warn">release pending</span>')
    if status != "active":
        badges.append(f'<span class="badge warn">{e(status)}</span>')

    facts = []
    if f["release_tag"]:
        facts.append(
            f'<span class="fact"><span class="k">version</span>'
            f'<a class="v" href="{e(f["release_url"])}">{e(f["release_tag"])}</a></span>'
        )
    else:
        facts.append('<span class="fact"><span class="k">version</span><span class="v">unreleased</span></span>')
    pr_v = f'{f["open_pr_count"]}'
    if f["renovate_pr_count"]:
        pr_v += f' ({f["renovate_pr_count"]} Renovate)'
    facts.append(
        f'<span class="fact"><span class="k">open PRs</span>'
        f'<a class="v" href="{e(f["html_url"])}/pulls">{e(pr_v)}</a></span>'
    )
    facts.append(
        f'<span class="fact"><span class="k">open issues</span>'
        f'<a class="v" href="{e(f["html_url"])}/issues">{f["open_issue_count"]}</a></span>'
    )
    if f["dependency_dashboard_url"]:
        facts.append(
            f'<span class="fact"><span class="k">updates</span>'
            f'<a class="v" href="{e(f["dependency_dashboard_url"])}">dependency dashboard</a></span>'
        )

    used_by = md.get("used-by") or []
    usedby_html = ""
    if used_by:
        items = "".join(
            f'<li><span class="who">{e(u.get("consumer",""))}</span> — {e(u.get("purpose",""))}</li>'
            for u in used_by
        )
        usedby_html = (
            f'<details class="usedby"><summary>Used by {len(used_by)} '
            f'consumer{"s" if len(used_by) != 1 else ""}</summary><ul>{items}</ul></details>'
        )

    tags = md.get("tags") or []
    tags_html = ""
    if tags:
        tags_html = '<div class="tags">' + "".join(
            f'<span class="tag">{e(t)}</span>' for t in tags
        ) + "</div>"

    upstream_html = ""
    if upstream_repo:
        upstream_html = (
            f'<p class="why"><b>Upstream:</b> '
            f'<a href="https://github.com/{e(upstream_repo)}">{e(upstream_repo)}</a>'
            f' — {e(upstream.get("reason",""))}</p>'
        )

    search_hay = " ".join(
        str(x).lower()
        for x in [package, f["repo"], upstream_repo, md.get("summary", ""),
                  " ".join(tags)]
    )

    return f"""
    <article class="card" data-name="{e(package)}" data-status="{e(status)}"
             data-ci="{e(f['ci'])}" data-attention="{1 if needs_attention(f) else 0}"
             data-search="{e(search_hay)}">
      <div class="card-head">
        <h2><a href="{e(npm_url)}">{e(package)}</a>
          <span class="repo"><a href="{e(f['html_url'])}">{ORG}/{e(f['repo'])}</a></span></h2>
        <div class="badges">{''.join(badges)}</div>
      </div>
      <p class="summary">{e(md.get('summary',''))}</p>
      {upstream_html}
      <p class="why"><b>Why forked:</b> {e(md.get('why-forked',''))}</p>
      <div class="facts">{''.join(facts)}</div>
      {usedby_html}
      {tags_html}
    </article>"""


def node_state(f: dict) -> str:
    """Collapse a fork's health into one topology node state (precedence: risk first)."""
    if f["security_count"] or f["ci"] == "failing":
        return "attention"
    if f["metadata"].get("status") in ("seeking-replacement", "deprecated"):
        return "seeking-replacement"
    if f["autorelease_pending"] or f["ci"] == "pending":
        return "pending"
    if f["ci"] == "passing":
        return "passing"
    return "unknown"


def _short(pkg: str) -> str:
    return pkg.split("/", 1)[1] if "/" in pkg else pkg


def build_graph(forks: list[dict]):
    """Derive topology nodes + edges from package.json deps and used-by. Nothing hand-drawn."""
    by_pkg = {f["package"]: f for f in forks}
    nodes: dict = {}
    edges: list[tuple[str, str]] = []

    for f in forks:
        nodes[f["package"]] = {
            "label": _short(f["package"]), "kind": "fork", "state": node_state(f)
        }

    for f in forks:
        pkg = f["package"]
        # fork -> fork: this fork depends on another @unabandoned fork (runtime tree).
        for dep in f.get("dep_packages", []):
            if dep in by_pkg and dep != pkg:
                edges.append((pkg, dep))
        # consumer -> fork: from used-by. A consumer that is itself a fork becomes a
        # fork->fork edge; anything else is an external consumer node.
        for u in (f["metadata"].get("used-by") or []):
            cons = (u.get("consumer") or "").strip()
            if not cons:
                continue
            if cons in by_pkg:
                edges.append((cons, pkg))
            else:
                cid = "consumer:" + cons
                nodes.setdefault(cid, {"label": cons, "kind": "consumer", "state": None})
                edges.append((cid, pkg))

    return nodes, list(dict.fromkeys(edges))  # de-dup, preserve order


def render_stats(forks: list[dict]) -> str:
    total = len(forks)
    open_prs = sum(f["open_pr_count"] for f in forks)
    open_issues = sum(f["open_issue_count"] for f in forks)
    security = sum(1 for f in forks if f["security_count"])
    failing = sum(1 for f in forks if f["ci"] == "failing")

    def tile(n, label, cls=""):
        return (f'<div class="stat {cls}"><div class="n">{n}</div>'
                f'<div class="l">{e(label)}</div></div>')

    return "".join([
        tile(total, "packages tracked"),
        tile(open_prs, "open pull requests"),
        tile(open_issues, "open issues"),
        tile(security, "with security work", "bad" if security else ""),
        tile(failing, "CI failing", "warn" if failing else ""),
    ])


def render(forks: list[dict], generated_at: str, topology_html: str,
           audit_html: str) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if forks:
        cards = "\n".join(render_card(f) for f in forks)
    else:
        cards = (
            '<div class="empty"><h2>No forks published yet</h2>'
            "<p>Once an <code>@unabandoned/*</code> fork ships with an "
            "<code>.unabandoned.yml</code>, it appears here automatically — "
            "no edit to this page required.</p></div>"
        )
    return (
        template
        .replace("{{TOPOLOGY_CSS}}", topology.TOPOLOGY_CSS + dep_audit.AUDIT_CSS)
        .replace("{{GENERATED_AT}}", e(generated_at))
        .replace("{{STATS}}", render_stats(forks))
        .replace("{{TOPOLOGY}}", topology_html + audit_html)
        .replace("{{CARDS}}", cards)
    )


def _palette_css() -> str:
    """Lift the dashboard's :root/dark palette from the template for the standalone page."""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    style = tpl[tpl.index("<style>") + len("<style>"): tpl.index("</style>")]
    return style.replace("{{TOPOLOGY_CSS}}", "")


def main() -> int:
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    forks = discover()
    nodes, edges = build_graph(forks)
    svg = topology.render_topology_svg(nodes, edges)
    panel = topology.topology_panel(svg, standalone_href="./topology.html")

    # Resolve what actually ships beneath each fork. Renovate's dashboards only
    # see direct dependencies, so this is the org's only view of the transitive
    # tree; it degrades to an omitted section if npm is unavailable.
    report = dep_audit.audit([f["package"] for f in forks])
    audit_panel = dep_audit.audit_panel(report, standalone_href="./dependencies.html")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(
        render(forks, generated_at, panel, audit_panel), encoding="utf-8"
    )
    (OUT_DIR / "topology.html").write_text(
        topology.topology_page(svg, _palette_css()), encoding="utf-8"
    )
    (OUT_DIR / "dependencies.html").write_text(
        dep_audit.audit_page(report, _palette_css()), encoding="utf-8"
    )
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_DIR / "data.json").write_text(
        json.dumps(
            {
                "org": ORG,
                "generated_at": generated_at,
                "packages": forks,
                "topology": {
                    "nodes": [{"id": k, **v} for k, v in nodes.items()],
                    "edges": [{"from": s, "to": d} for s, d in edges],
                },
                "dependency_audit": report,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    totals = report.get("totals") or {}
    print(
        f"Built dashboard for {len(forks)} package(s), "
        f"{len(nodes)} topology node(s)/{len(edges)} edge(s) into {OUT_DIR}/"
    )
    if report.get("available"):
        print(
            f"  audit: {totals.get('unique', 0)} unique package(s) — "
            f"{totals.get('bomb', 0)} time bomb(s) ({totals.get('invisible', 0)} "
            f"invisible), {totals.get('inert', 0)} inert, {totals.get('alive', 0)} alive; "
            f"{totals.get('self_hosted', 0)} already-forked package(s) pulled from upstream"
        )
    else:
        sys.stderr.write("warning: dependency audit skipped — npm not on PATH\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
