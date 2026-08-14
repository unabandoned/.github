#!/usr/bin/env python3
"""Render the fork dependency topology as a static, dependency-free SVG.

The graph shows how de-risking flows up the tree: consumers at the top, the
`@unabandoned/*` forks in dependency layers beneath them, and the shared
leaves (e.g. `ret`) at the bottom. Every edge is DERIVED, never hand-drawn:

- fork -> fork edges come from each fork's package.json `dependencies`, filtered
  to the @unabandoned scope (the real transitive subtree we own);
- consumer -> fork edges come from `used-by` in each `.unabandoned.yml`.

Node colour carries live health (CI / security), so the topology doubles as a
status map. Layout is a compact layered (Sugiyama-lite) algorithm with a
barycenter crossing-reduction sweep — pure Python, emitting SVG that inherits
the page's CSS variables so it themes light/dark with everything else.
"""
from __future__ import annotations

import html
from collections import defaultdict

NODE_W = 168
NODE_H = 46
H_GAP = 34
V_GAP = 88
MARGIN = 28


def _layers(nodes: dict, edges: list[tuple[str, str]]):
    """Assign each node a rank = longest path to a sink (following out-edges)."""
    out = defaultdict(list)
    for s, d in edges:
        if s in nodes and d in nodes:
            out[s].append(d)

    rank: dict[str, int] = {}

    def depth(n: str, seen: frozenset) -> int:
        if n in rank:
            return rank[n]
        children = [c for c in out.get(n, []) if c not in seen]
        r = 0 if not children else 1 + max(depth(c, seen | {n}) for c in children)
        rank[n] = r
        return r

    for n in nodes:
        depth(n, frozenset())
    max_rank = max(rank.values(), default=0)
    # Higher rank = higher on the page (smaller y). Invert into layer index.
    layers: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        layers[max_rank - rank[n]].append(n)
    return layers, out


def _order(layers, edges):
    """One down + one up barycenter sweep to cut edge crossings."""
    adj = defaultdict(list)
    radj = defaultdict(list)
    for s, d in edges:
        adj[s].append(d)
        radj[d].append(s)
    idx = max(layers) if layers else 0

    def sweep(order_key):
        for li in range(1, idx + 1):
            above = {n: i for i, n in enumerate(layers[li - 1])}
            def bary(n):
                ns = order_key(n)
                ps = [above[p] for p in ns if p in above]
                return sum(ps) / len(ps) if ps else len(above) / 2
            layers[li].sort(key=bary)

    sweep(lambda n: radj[n])            # top-down using parents
    for li in range(idx - 1, -1, -1):   # bottom-up using children
        below = {n: i for i, n in enumerate(layers[li + 1])}
        def bary(n):
            cs = [below[c] for c in adj[n] if c in below]
            return sum(cs) / len(cs) if cs else len(below) / 2
        layers[li].sort(key=bary)
    return layers


NODE_CLASS = {
    ("consumer", None): "n-consumer",
    ("fork", "passing"): "n-ok",
    ("fork", "failing"): "n-bad",
    ("fork", "attention"): "n-bad",
    ("fork", "pending"): "n-warn",
    ("fork", "seeking-replacement"): "n-warn",
    ("fork", "unknown"): "n-neutral",
}


def render_topology_svg(nodes: dict, edges: list[tuple[str, str]]) -> str:
    """nodes: {id: {label, kind, state}}; edges: [(src, dst)] meaning src depends on dst."""
    if not nodes:
        return ""
    layers, _ = _layers(nodes, edges)
    layers = _order(layers, edges)

    width = max(
        (len(row) * NODE_W + (len(row) - 1) * H_GAP for row in layers.values()),
        default=NODE_W,
    ) + 2 * MARGIN
    height = (max(layers) + 1) * NODE_H + max(layers) * V_GAP + 2 * MARGIN if layers else NODE_H

    pos: dict[str, tuple[float, float]] = {}
    for li, row in layers.items():
        row_w = len(row) * NODE_W + (len(row) - 1) * H_GAP
        x0 = (width - row_w) / 2
        y = MARGIN + li * (NODE_H + V_GAP)
        for i, n in enumerate(row):
            pos[n] = (x0 + i * (NODE_W + H_GAP), y)

    # Edges first (under nodes): cubic bezier from parent bottom to child top.
    edge_svg = []
    for s, d in edges:
        if s not in pos or d not in pos:
            continue
        sx, sy = pos[s]; dx, dy = pos[d]
        x1, y1 = sx + NODE_W / 2, sy + NODE_H
        x2, y2 = dx + NODE_W / 2, dy
        my = (y1 + y2) / 2
        edge_svg.append(
            f'<path class="edge" d="M{x1:.1f},{y1:.1f} C{x1:.1f},{my:.1f} '
            f'{x2:.1f},{my:.1f} {x2:.1f},{y2:.1f}" />'
        )

    node_svg = []
    for n, meta in nodes.items():
        if n not in pos:
            continue
        x, y = pos[n]
        cls = NODE_CLASS.get((meta.get("kind"), meta.get("state")), "n-neutral")
        label = html.escape(meta.get("label", n))
        node_svg.append(
            f'<g class="node {cls}" transform="translate({x:.1f},{y:.1f})">'
            f'<rect width="{NODE_W}" height="{NODE_H}" rx="9" />'
            f'<text x="{NODE_W/2:.1f}" y="{NODE_H/2:.1f}" '
            f'dominant-baseline="central" text-anchor="middle">{label}</text></g>'
        )

    return (
        f'<svg class="topo" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" '
        f'aria-label="Fork dependency topology">'
        f'{"".join(edge_svg)}{"".join(node_svg)}</svg>'
    )


# Styling shared by the demo and the dashboard (uses the page's CSS variables).
TOPOLOGY_CSS = """
.topo-section { margin: 24px 0; }
.topo-section .topo-title { display: flex; flex-wrap: wrap; gap: 8px 12px;
  align-items: baseline; justify-content: space-between; margin: 0 0 10px; }
.topo-section h2 { margin: 0; font-size: 17px; letter-spacing: -.01em; }
.topo-section .topo-sub { font-size: 12.5px; color: var(--fg-muted); }
.topo-wrap { background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px; box-shadow: var(--shadow); overflow-x: auto; }
.topo { display: block; margin: 0 auto; max-width: 100%; height: auto; font:
  600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.topo .edge { fill: none; stroke: var(--border); stroke-width: 1.6; opacity: .8; }
.topo .node text { fill: var(--fg); }
.topo .node rect { stroke-width: 1.5; }
.topo .n-ok rect       { fill: var(--ok-bg);   stroke: var(--ok); }
.topo .n-bad rect      { fill: var(--bad-bg);  stroke: var(--bad); }
.topo .n-warn rect     { fill: var(--warn-bg); stroke: var(--warn); }
.topo .n-neutral rect  { fill: var(--panel-2); stroke: var(--border); }
.topo .n-consumer rect { fill: var(--chip-bg); stroke: var(--fg-muted);
  stroke-dasharray: 4 3; }
.topo .n-consumer text { fill: var(--fg-muted); }
.topo-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px;
  font-size: 12px; color: var(--fg-muted); }
.topo-legend span { display: inline-flex; align-items: center; gap: 6px; }
.topo-legend i { width: 13px; height: 13px; border-radius: 4px; border: 1.5px solid; }
.lg-ok  { background: var(--ok-bg);  border-color: var(--ok); }
.lg-bad { background: var(--bad-bg); border-color: var(--bad); }
.lg-warn{ background: var(--warn-bg);border-color: var(--warn); }
.lg-con { background: var(--chip-bg);border-color: var(--fg-muted); }
"""

TOPOLOGY_LEGEND = (
    '<div class="topo-legend">'
    '<span><i class="lg-ok"></i>CI green</span>'
    '<span><i class="lg-bad"></i>failing / security</span>'
    '<span><i class="lg-warn"></i>release-pending / seeking-replacement</span>'
    '<span><i class="lg-con"></i>consumer (external)</span>'
    '<span>edges = dependency (derived from package.json + used-by)</span>'
    '</div>'
)

SUBTITLE = ("De-risking flows up the tree — consumers on top, the forks we own "
            "beneath, shared leaves at the bottom. Every edge is derived, never "
            "hand-drawn.")


def topology_panel(svg: str, *, standalone_href: str | None = None) -> str:
    """A dashboard section wrapping the SVG with a heading, legend, and (optional) full-view link."""
    if not svg:
        return ""
    link = (f'<a class="topo-sub" href="{standalone_href}">open full view →</a>'
            if standalone_href else f'<span class="topo-sub">{SUBTITLE}</span>')
    return (
        '<section class="topo-section">'
        f'<div class="topo-title"><h2>Dependency topology</h2>{link}</div>'
        f'<div class="topo-wrap">{svg}{TOPOLOGY_LEGEND}</div>'
        '</section>'
    )


def topology_page(svg: str, palette_css: str) -> str:
    """A standalone, self-contained topology page reusing the dashboard palette."""
    body = (
        '<h1>unabandoned · dependency topology</h1>'
        f'<p class="sub">{SUBTITLE}</p>'
        f'<div class="topo-wrap">{svg}{TOPOLOGY_LEGEND}</div>'
        '<p class="back"><a href="./">← back to the package dashboard</a></p>'
    ) if svg else (
        '<h1>unabandoned · dependency topology</h1>'
        '<p class="sub">No forks published yet — the graph appears once the first '
        '<code>.unabandoned.yml</code> ships.</p>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>unabandoned — dependency topology</title>'
        f'<style>{palette_css}\nbody{{padding:28px;}}'
        'h1{font:650 22px -apple-system,system-ui,sans-serif;margin:0 0 4px;letter-spacing:-.02em;}'
        'p.sub{color:var(--fg-muted);margin:0 0 20px;font:14px -apple-system,system-ui,sans-serif;max-width:70ch;}'
        'p.back{margin-top:18px;font:13px -apple-system,system-ui,sans-serif;}'
        f'{TOPOLOGY_CSS}</style></head><body>{body}</body></html>'
    )
