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
    dep_dashboard = next(
        (i for i in issues if i.get("title", "").strip().lower() == "dependency dashboard"),
        None,
    )
    security_issues = [i for i in issues if has_label(i, "security")]

    # Latest release.
    release = gh_api(f"/repos/{ORG}/{repo}/releases/latest", allow_404=True)

    return {
        "repo": repo,
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


def render(forks: list[dict], generated_at: str) -> str:
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
        .replace("{{GENERATED_AT}}", e(generated_at))
        .replace("{{STATS}}", render_stats(forks))
        .replace("{{CARDS}}", cards)
    )


def main() -> int:
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    forks = discover()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(render(forks, generated_at), encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUT_DIR / "data.json").write_text(
        json.dumps(
            {"org": ORG, "generated_at": generated_at, "packages": forks},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Built dashboard for {len(forks)} package(s) into {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
