#!/usr/bin/env python3
"""Cogit read-only web viewer (COG-038): stdlib HTTP, zero dependencies.

Serves a single-page UI over one journal: thought DAG across all branch
tips with colored lanes (COG-054), per-writer avatars and an actor legend,
project threads (dim everything outside the selected project), active
beliefs with filters and expandable long values, per-fact introducers
(blame), anchors, annotations, and the no-arg recap. Strictly read-only —
this module never calls a mutating Repository method (ADR-0009 analogy
with the MCP surface).

    python3 web_viewer.py --repo ~/.cogit-journal/cogit           # serve
    python3 web_viewer.py --repo ... --snapshot journal.html      # export

The server exposes exactly two paths: `/` (the page) and `/api/state`
(one JSON document with everything decoded). `--snapshot` embeds the same
JSON into the page, producing one self-contained shareable file.
Binds 127.0.0.1 by default; there is no auth, so a non-local `--host`
is a deliberate decision by the operator.
"""

import argparse
import http.server
import json
import os
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cogit import __version__  # noqa: E402
from cogit.errors import CogitError, CorruptionError  # noqa: E402
from cogit.repo import Repository, now_utc  # noqa: E402


def _topo_oldest_first(thoughts: dict) -> list:
    """Kahn topological order, oldest first; ties broken by (timestamp, oid).

    Local copy of the ordering contract so the viewer stays on public
    porcelain and never reaches into Repository internals.
    """
    pending = {oid: [p for p in t["parents"] if p in thoughts] for oid, t in thoughts.items()}
    done, emitted = set(), []
    while pending:
        ready = sorted(
            (oid for oid, parents in pending.items() if all(p in done for p in parents)),
            key=lambda oid: (thoughts[oid]["timestamp"], oid),
        )
        if not ready:
            raise CorruptionError("viewer: cycle detected in thought graph")
        for oid in ready:
            emitted.append(oid)
            done.add(oid)
            del pending[oid]
    return emitted


def build_state(repo: Repository) -> dict:
    """Decode the whole journal into one JSON-ready snapshot."""
    status = repo.status()
    branches = repo.list_branches()
    anchors = repo.list_anchors()

    tips = [b["target"] for b in branches]
    if status["thought"] and status["thought"] not in tips:
        tips.append(status["thought"])

    thoughts = {}
    for tip in tips:
        for entry in repo.log(tip):
            thoughts.setdefault(entry["id"], entry)
    order = _topo_oldest_first(thoughts)

    # Active assertion sets and decoded rows per thought (public facts()).
    active = {}
    rows = {}
    for oid in order:
        fact_rows = repo.facts(oid)["facts"]
        active[oid] = {row["assertion"] for row in fact_rows}
        for row in fact_rows:
            rows.setdefault(row["assertion"], row)

    # First introducer per assertion == blame-fact semantics: oldest thought
    # whose mindset holds the fact while no parent mindset does.
    introducer = {}
    deltas = {}
    for oid in order:
        parent_union = set()
        for parent in thoughts[oid]["parents"]:
            parent_union |= active.get(parent, set())
        added = sorted(active[oid] - parent_union)
        removed = sorted(parent_union - active[oid])
        deltas[oid] = (added, removed)
        for aid in added:
            introducer.setdefault(aid, oid)

    branch_names = {}
    for branch in branches:
        branch_names.setdefault(branch["target"], []).append(branch["name"])
    anchor_names = {}
    for anchor in anchors:
        anchor_names.setdefault(anchor["target"], []).append(anchor["name"])

    nodes = []
    for oid in reversed(order):  # newest first, matching `log`
        thought = thoughts[oid]
        added, removed = deltas[oid]
        # Project threads (COG-054): which projects this thought touched,
        # from the project qualifier of every belief it added or removed.
        projects = set()
        for aid in list(added) + list(removed):
            value = (rows[aid].get("qualifiers") or {}).get("project")
            if value:
                projects.add(str(value))
        nodes.append(
            {
                "id": oid,
                "parents": thought["parents"],
                "message": thought["message"],
                "author": thought["author"],
                "timestamp": thought["timestamp"],
                "operation": thought["operation"],
                "branches": branch_names.get(oid, []),
                "anchors": anchor_names.get(oid, []),
                "projects": sorted(projects),
                "added": added,
                "removed": removed,
            }
        )

    head = status["thought"]
    head_facts = [rows[aid] for aid in sorted(active.get(head, set()))] if head else []

    try:
        recap = repo.recap()
    except CogitError as exc:
        recap = {"error": str(exc)}

    return {
        "version": __version__,
        "generated_at": now_utc(),
        "repo": repo.cogit_dir,
        "status": status,
        "branches": branches,
        "anchors": anchors,
        "graph": nodes,
        "head_facts": head_facts,
        "assertions": rows,
        "introducer": introducer,
        "annotations": repo.annotations_index(),
        "recap": recap,
        "counts": {
            "thoughts": len(order),
            "active_facts": len(head_facts),
            "assertions_seen": len(rows),
            "branches": len(branches),
            "anchors": len(anchors),
        },
    }


def render_page(state_json: str = None) -> str:
    """Live page when state_json is None; self-contained snapshot otherwise."""
    inject = ""
    if state_json is not None:
        # '<' is escaped so fact text can never break out of the script tag.
        inject = "<script>window.COGIT_STATE = %s;</script>" % state_json.replace("<", "\\u003c")
    return PAGE.replace("<!--STATE-->", inject)


def write_snapshot(repo: Repository, out_path: str) -> str:
    html = render_page(json.dumps(build_state(repo)))
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return out_path


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    server_version = "cogit-viewer/" + __version__

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server contract
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, "text/html; charset=utf-8", render_page().encode("utf-8"))
        elif path == "/api/state":
            try:
                repo = Repository.open(self.server.repo_path)
                body = json.dumps(build_state(repo)).encode("utf-8")
                self._send(200, "application/json", body)
            except CogitError as exc:
                self._send(400, "application/json", json.dumps({"error": str(exc)}).encode("utf-8"))
        else:
            self._send(404, "application/json", b'{"error": "not found"}')

    def log_message(self, fmt, *args):
        if os.environ.get("COGIT_VIEWER_DEBUG"):
            super().log_message(fmt, *args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cogit read-only web viewer (COG-038)")
    parser.add_argument("--repo", default=os.environ.get("COGIT_REPO", "."),
                        help="journal path (default: $COGIT_REPO or cwd)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8323)
    parser.add_argument("--snapshot", metavar="OUT_HTML",
                        help="write a self-contained HTML snapshot and exit")
    args = parser.parse_args(argv)
    try:
        repo = Repository.open(args.repo)
        if args.snapshot:
            print(write_snapshot(repo, args.snapshot))
            return 0
    except CogitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    server = http.server.ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    server.repo_path = args.repo
    print(f"cogit viewer: http://{args.host}:{args.port}/ (read-only, {repo.cogit_dir})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cogit viewer</title>
<link rel="icon" href="data:,">
<style>
:root {
  --bg:#0e1116; --panel:#161b22; --border:#242c36; --fg:#dbe2ea; --muted:#8b98a5;
  --accent:#4da3ff; --green:#3fb950; --amber:#d29922; --red:#f85149; --purple:#bc8cff;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:#f6f8fa; --panel:#ffffff; --border:#d8dee4; --fg:#1f2328; --muted:#59636e;
    --accent:#0969da; --green:#1a7f37; --amber:#9a6700; --red:#cf222e; --purple:#8250df;
  }
}
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--fg);
  font:14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; }
header { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
  padding:10px 16px; border-bottom:1px solid var(--border);
  position:sticky; top:0; background:var(--bg); z-index:2; }
.brand { font-weight:700; letter-spacing:.4px; }
main { display:grid; grid-template-columns:minmax(360px,1fr) minmax(420px,1.4fr);
  gap:14px; padding:14px 16px; align-items:start; }
@media (max-width:960px) { main { grid-template-columns:1fr; } }
.card { background:var(--panel); border:1px solid var(--border); border-radius:10px;
  padding:12px 14px; }
.card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.8px;
  color:var(--muted); margin-bottom:10px; }
.cardhead { display:flex; justify-content:space-between; align-items:baseline; }
.col { display:flex; flex-direction:column; gap:14px; }
.mono { font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
.muted { color:var(--muted); }
.pos { color:var(--green); } .neg { color:var(--red); }
.chip { border-radius:999px; padding:1px 8px; font-size:11px;
  border:1px solid var(--border); white-space:nowrap; }
.chip.branch { color:var(--green); border-color:var(--green); }
.chip.anchor { color:var(--amber); border-color:var(--amber); }
.chip.kind { color:var(--accent); border-color:var(--accent); }
.chip.negs { color:var(--red); border-color:var(--red); margin-left:6px; }
.chip.ok { color:var(--green); border-color:var(--green); }
.chip.err { color:var(--red); border-color:var(--red); }
.chip.snap { color:var(--purple); border-color:var(--purple); }
.chip.warn { color:var(--red); border-color:var(--red); }
#graph { position:relative; overflow:auto; max-height:calc(100vh - 200px); }
.rail { position:absolute; top:0; left:0; }
.edge { fill:none; stroke:var(--muted); stroke-width:2; opacity:.6; }
.dot.commit { fill:var(--accent); } .dot.merge { fill:var(--purple); }
.dot { transition:opacity .2s ease; }
.dot.dimmed { opacity:.2; }
.ring { fill:none; stroke:var(--amber); stroke-width:1.5; }
.rows { position:relative; }
.thought { padding:4px 8px; border-radius:8px; cursor:pointer; overflow:hidden;
  transition:background .15s ease, opacity .2s ease; }
.thought:hover { background:rgba(125,165,255,.08); }
.thought.sel { background:rgba(125,165,255,.16); }
.thought.dimmed { opacity:.35; }
.avatar { width:16px; height:16px; border-radius:50%; flex:none;
  display:inline-flex; align-items:center; justify-content:center;
  font-size:8.5px; font-weight:700; color:#fff; letter-spacing:.2px; }
#actors { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
.actorchip { display:inline-flex; gap:6px; align-items:center; cursor:pointer;
  border:1px solid var(--border); border-radius:999px; padding:2px 8px 2px 3px;
  font-size:12px; transition:border-color .15s ease, background .15s ease; }
.actorchip:hover { border-color:var(--accent); }
.actorchip.active { border-color:var(--accent); background:rgba(125,165,255,.12); }
.chip.proj { cursor:pointer; }
.l1 { display:flex; gap:6px; align-items:center; white-space:nowrap; overflow:hidden; }
.l1 .msg { overflow:hidden; text-overflow:ellipsis; font-weight:600; font-size:13.5px; }
.l2 { display:flex; gap:10px; font-size:12px; margin-top:1px; }
.filters { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
input, select { background:var(--bg); color:var(--fg); border:1px solid var(--border);
  border-radius:6px; padding:4px 8px; font-size:13px; }
input:focus-visible, select:focus-visible, button:focus-visible {
  outline:2px solid var(--accent); outline-offset:1px; }
.tablewrap { overflow:auto; max-height:44vh; }
table { width:100%; border-collapse:collapse; }
th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.6px;
  color:var(--muted); padding:4px 8px; position:sticky; top:0; background:var(--panel); }
td { padding:5px 8px; border-top:1px solid var(--border); vertical-align:top; }
tbody tr { cursor:pointer; transition:background .15s ease; }
tbody tr:hover { background:rgba(125,165,255,.08); }
tbody tr.sel { background:rgba(125,165,255,.16); }
tbody tr.expand, tbody tr.expand:hover { background:none; cursor:default; }
tr.expand td { border-top:none; padding-top:0; }
.fulltext { white-space:pre-wrap; word-break:break-word; font-size:13px;
  padding:6px 10px; background:rgba(125,165,255,.06); border-radius:6px; }
.expander { background:none; border:none; color:var(--muted); cursor:pointer;
  font-size:11px; padding:0 4px 0 0; }
.expander:hover { color:var(--accent); }
.obj { max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.bar { width:56px; height:6px; background:var(--border); border-radius:3px;
  display:inline-block; margin-right:6px; vertical-align:middle; }
.fill { height:100%; background:var(--accent); border-radius:3px; display:block; }
.kv { display:flex; gap:8px; padding:2px 0; font-size:13px; }
.kv .k { width:120px; flex:none; }
.kv .v { word-break:break-all; white-space:pre-wrap; }
.kv .v.copy { cursor:pointer; }
.kv .v.copy:hover { color:var(--accent); }
.msg-big { font-size:15px; font-weight:600; margin-bottom:8px;
  white-space:pre-wrap; word-break:break-word; }
#toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
  background:var(--panel); border:1px solid var(--border); border-radius:8px;
  padding:6px 12px; font-size:13px; opacity:0; pointer-events:none;
  transition:opacity .2s ease; z-index:5; }
#toast.show { opacity:1; }
#detail h3 { font-size:11px; text-transform:uppercase; letter-spacing:.6px;
  margin:12px 0 6px; color:var(--muted); }
.fact-line { padding:3px 6px; border-radius:6px; cursor:pointer; font-size:13px; }
.fact-line:hover { background:rgba(125,165,255,.08); }
.fact-line.removed { opacity:.55; text-decoration:line-through; }
.anno { border-left:2px solid var(--border); padding:4px 8px; margin:6px 0; }
.empty { color:var(--muted); padding:24px; text-align:center; }
.recap-row { display:flex; gap:8px; padding:2px 0; cursor:pointer; border-radius:6px; }
.recap-row:hover { background:rgba(125,165,255,.08); }
#detail-close { background:none; border:none; color:var(--muted); cursor:pointer;
  font-size:15px; }
#detail-close:hover { color:var(--fg); }
</style>
</head>
<body>
<header>
  <span class="brand">&#8980; cogit</span>
  <span id="repo" class="mono muted"></span>
  <span id="pos"></span>
  <span id="counts" class="muted"></span>
  <span id="live" class="chip">connecting&#8230;</span>
</header>
<main>
  <section class="card">
    <h2>Thoughts</h2>
    <div id="actors"></div>
    <div id="graph"></div>
  </section>
  <div class="col">
    <section class="card"><h2>Recap</h2><div id="recap"></div></section>
    <section class="card">
      <h2>Active beliefs <span id="beliefs-n" class="muted"></span></h2>
      <div class="filters">
        <input id="f-subject" placeholder="subject&#8230;">
        <input id="f-predicate" placeholder="predicate&#8230;">
        <select id="f-project"></select>
        <select id="f-kind"></select>
      </div>
      <div class="tablewrap">
        <table id="beliefs">
          <thead><tr><th>subject</th><th>predicate</th><th>object</th>
            <th>confidence</th><th>kind</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
    <section class="card" id="detail-card" hidden>
      <div class="cardhead"><h2 id="detail-title"></h2>
        <button id="detail-close" title="close">&#10005;</button></div>
      <div id="detail"></div>
    </section>
  </div>
</main>
<div id="toast" role="status"></div>
<!--STATE-->
<script>
'use strict';
const $ = s => document.querySelector(s);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
const short = oid => oid ? oid.replace('sha256:', '').slice(0, 10) : '—';
const fmtTs = t => t ? t.replace('T', ' ').replace('Z', '').replace('+00:00', '') : '';
const pct = bps => (bps / 100).toFixed(0) + '%';
const distinct = a => [...new Set(a)];

let STATE = null, SIG = '', SEL = null, URL_FILTERS_APPLIED = false;
let ACTOR_SEL = null, LIVE_MODE = true, DOTS = {}, TOAST_TIMER = null;
const EXPANDED = new Set();

// Lane palette: one stable color per graph column, git-graph style.
const PALETTE = ['#4da3ff', '#3fb950', '#d29922', '#bc8cff',
                 '#f85149', '#39c5cf', '#e27fab', '#9e8cfc'];
const laneColor = c => PALETTE[c % PALETTE.length];

function hashCode(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}
const actorHue = a => hashCode(String(a)) % 360;

function initials(a) {
  const parts = String(a).split(/[^a-zA-Z0-9]+/).filter(Boolean);
  const two = parts.length > 1 ? parts[0][0] + parts[1][0] : String(a).slice(0, 2);
  return two.toUpperCase();
}

function avatar(a) {
  const d = el('span', 'avatar', initials(a));
  d.style.background = 'hsl(' + actorHue(a) + ' 45% 42%)';
  d.title = a;
  return d;
}

const projColor = p => 'hsl(' + (hashCode(String(p)) % 360) + ' 60% 62%)';

function projChip(p) {
  const c = el('span', 'chip proj', p);
  c.style.color = projColor(p);
  c.style.borderColor = projColor(p);
  c.title = 'filter beliefs and highlight the ' + p + ' thread';
  c.addEventListener('click', ev => {
    ev.stopPropagation();
    const sel = $('#f-project');
    sel.value = sel.value === p ? '' : p;
    onFilterChange();
  });
  return c;
}

function relTime(t) {
  const ms = Date.now() - Date.parse(t);
  if (!isFinite(ms) || ms < 0) return fmtTs(t);
  const s = Math.round(ms / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return m + 'm ago';
  const h = Math.round(m / 60);
  if (h < 48) return h + 'h ago';
  const d = Math.round(h / 24);
  if (d < 14) return d + 'd ago';
  return fmtTs(t).slice(0, 10);
}

function tsEl(t) {
  const e = el('span', 'rel', LIVE_MODE ? relTime(t) : fmtTs(t));
  e.dataset.ts = t;
  e.title = fmtTs(t) + ' UTC';
  return e;
}

function refreshTimes() {
  if (!LIVE_MODE) return;
  document.querySelectorAll('.rel').forEach(e => { e.textContent = relTime(e.dataset.ts); });
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(TOAST_TIMER);
  TOAST_TIMER = setTimeout(() => t.classList.remove('show'), 1200);
}

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => toast('copied'), () => toast('copy failed'));
  } else { toast('copy unavailable'); }
}

function setLive(ok) {
  const e = $('#live');
  e.className = 'chip ' + (ok ? 'ok' : 'err');
  e.textContent = ok ? 'live' : 'offline';
}

async function poll() {
  try {
    const res = await fetch('/api/state', {cache: 'no-store'});
    if (!res.ok) throw new Error('http ' + res.status);
    const s = await res.json();
    setLive(true);
    const {generated_at, ...rest} = s;
    const sig = JSON.stringify(rest);
    if (sig !== SIG) { SIG = sig; STATE = s; renderAll(); }
  } catch (e) { setLive(false); }
}

function renderAll() {
  // filters go first: URL-provided values must exist before graph dimming
  renderHeader(); renderRecap(); populateFilters(); renderGraph(); renderBeliefs();
  renderDetail();
}

function renderHeader() {
  $('#repo').textContent = STATE.repo;
  const pos = $('#pos'); pos.innerHTML = '';
  const st = STATE.status;
  pos.append(el('span', 'chip branch', st.detached ? 'detached' : (st.branch || '—')));
  if (st.merge_in_progress) pos.append(el('span', 'chip warn', 'merge in progress'));
  const c = STATE.counts;
  $('#counts').textContent = c.thoughts + ' thoughts · ' + c.active_facts +
    ' beliefs · ' + c.branches + ' branches · ' + c.anchors + ' anchors';
}

function renderRecap() {
  const box = $('#recap'); box.innerHTML = '';
  const r = STATE.recap;
  if (!r || r.error) { box.append(el('div', 'muted', r && r.error ? r.error : 'no recap')); return; }
  if (r.same_point) {
    box.append(el('div', 'muted', 'HEAD stands exactly at ' +
      (r.from_anchor ? 'anchor “' + r.from_anchor + '”' : short(r.from)) +
      ' — nothing new to recap.'));
    return;
  }
  const head = el('div');
  head.append('since ', el('span', 'chip anchor',
    r.from_anchor ? '⚓ ' + r.from_anchor : short(r.from)),
    ' : ' + r.thoughts.length + ' thoughts, ',
    el('span', 'pos', '+' + r.added.length), ' / ',
    el('span', 'neg', '−' + r.removed.length), ' beliefs');
  box.append(head);
  const list = el('div');
  r.thoughts.slice(-6).reverse().forEach(t => {
    const d = el('div', 'recap-row');
    d.append(el('span', 'mono muted', short(t.id)), el('span', null, t.message));
    d.addEventListener('click', () => select({type: 'thought', id: t.id}));
    list.append(d);
  });
  box.append(list);
}

function renderActors() {
  const box = $('#actors'); box.innerHTML = '';
  const counts = {};
  STATE.graph.forEach(n => { counts[n.author] = (counts[n.author] || 0) + 1; });
  const actors = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  if (ACTOR_SEL && !counts[ACTOR_SEL]) ACTOR_SEL = null;
  if (actors.length < 2) return;  // a single writer needs no legend
  actors.forEach(a => {
    const c = el('span', 'actorchip' + (ACTOR_SEL === a ? ' active' : ''));
    c.append(avatar(a), el('span', null, a), el('span', 'muted', counts[a]));
    c.title = 'highlight thoughts by ' + a;
    c.addEventListener('click', () => {
      ACTOR_SEL = ACTOR_SEL === a ? null : a;
      renderActors();
      applyDim();
    });
    box.append(c);
  });
}

function applyDim() {
  const proj = $('#f-project').value;
  document.querySelectorAll('#graph .thought').forEach(d => {
    const n = nodeById(d.dataset.id);
    if (!n) return;
    const dim = (proj && !(n.projects || []).includes(proj)) ||
      (ACTOR_SEL && n.author !== ACTOR_SEL);
    d.classList.toggle('dimmed', !!dim);
    if (DOTS[n.id]) DOTS[n.id].classList.toggle('dimmed', !!dim);
  });
}

function renderGraph() {
  const box = $('#graph');
  const scroll = box.scrollTop;
  box.innerHTML = '';
  DOTS = {};
  renderActors();
  const nodes = STATE.graph;
  if (!nodes.length) {
    box.append(el('div', 'empty', 'journal is empty — no thoughts yet'));
    return;
  }
  const H = 46, XW = 14, PAD = 12;
  const row = {}; nodes.forEach((n, i) => { row[n.id] = i; });
  const lanes = [], col = {};
  for (const n of nodes) {
    let c = lanes.indexOf(n.id);
    if (c === -1) {
      const f = lanes.indexOf(null);
      if (f === -1) { c = lanes.length; lanes.push(n.id); } else { c = f; lanes[f] = n.id; }
    }
    for (let i = 0; i < lanes.length; i++) if (lanes[i] === n.id && i !== c) lanes[i] = null;
    col[n.id] = c;
    const ps = n.parents || [];
    ps.forEach((p, j) => {
      if (j === 0) { lanes[c] = p; }
      else if (!lanes.includes(p)) {
        const f = lanes.indexOf(null);
        if (f === -1) lanes.push(p); else lanes[f] = p;
      }
    });
    if (!ps.length) lanes[c] = null;
  }
  let maxc = 0; for (const k in col) maxc = Math.max(maxc, col[k]);
  const railW = PAD * 2 + (maxc + 1) * XW;
  const x = id => PAD + col[id] * XW + 4;
  const y = id => row[id] * H + H / 2;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', railW);
  svg.setAttribute('height', nodes.length * H);
  svg.setAttribute('class', 'rail');
  for (const n of nodes) {
    for (const p of (n.parents || [])) {
      if (!(p in row)) continue;
      const x1 = x(n.id), y1 = y(n.id), x2 = x(p), y2 = y(p), m = (y1 + y2) / 2;
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', `M ${x1} ${y1} C ${x1} ${m}, ${x2} ${m}, ${x2} ${y2}`);
      path.setAttribute('class', 'edge');
      // forks and merges take the color of the deeper (branch-side) lane
      path.style.stroke = laneColor(Math.max(col[n.id], col[p]));
      svg.append(path);
    }
  }
  for (const n of nodes) {
    if (n.anchors.length) {
      const ring = document.createElementNS(NS, 'circle');
      ring.setAttribute('cx', x(n.id)); ring.setAttribute('cy', y(n.id));
      ring.setAttribute('r', 8); ring.setAttribute('class', 'ring');
      svg.append(ring);
    }
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('cx', x(n.id)); dot.setAttribute('cy', y(n.id));
    dot.setAttribute('r', n.operation === 'merge' ? 5.5 : 4.5);
    dot.setAttribute('class', 'dot ' + (n.operation === 'merge' ? 'merge' : 'commit'));
    dot.style.fill = laneColor(col[n.id]);
    if (n.operation === 'merge') {
      dot.style.stroke = 'var(--fg)';
      dot.style.strokeWidth = '1.2';
    }
    DOTS[n.id] = dot;
    svg.append(dot);
  }
  box.append(svg);
  const list = el('div', 'rows');
  list.style.marginLeft = railW + 'px';
  nodes.forEach(n => {
    const d = el('div', 'thought');
    d.dataset.id = n.id;
    d.style.height = H + 'px';
    if (SEL && SEL.type === 'thought' && SEL.id === n.id) d.classList.add('sel');
    const l1 = el('div', 'l1');
    l1.append(avatar(n.author), el('span', 'msg', n.message));
    l1.title = n.message;
    n.branches.forEach(b => l1.append(el('span', 'chip branch', b)));
    n.anchors.forEach(a => l1.append(el('span', 'chip anchor', '⚓ ' + a)));
    const l2 = el('div', 'l2 muted');
    const who = el('span', null, n.author);
    who.style.color = 'hsl(' + actorHue(n.author) + ' 55% 60%)';
    l2.append(el('span', 'mono', short(n.id)), who, tsEl(n.timestamp));
    (n.projects || []).slice(0, 2).forEach(p => l2.append(projChip(p)));
    if ((n.projects || []).length > 2) {
      l2.append(el('span', 'chip', '+' + (n.projects.length - 2)));
    }
    if (n.added.length) l2.append(el('span', 'pos', '+' + n.added.length));
    if (n.removed.length) l2.append(el('span', 'neg', '−' + n.removed.length));
    d.append(l1, l2);
    d.addEventListener('click', () => select({type: 'thought', id: n.id}));
    list.append(d);
  });
  box.append(list);
  box.scrollTop = scroll;
  applyDim();
}

const URL_KEYS = {project: 'f-project', kind: 'f-kind',
                  subject: 'f-subject', predicate: 'f-predicate'};

function populateFilters() {
  fillSelect($('#f-project'),
    distinct(STATE.head_facts.map(r => (r.qualifiers || {}).project).filter(Boolean)), 'project');
  fillSelect($('#f-kind'), distinct(STATE.head_facts.map(r => r.kind)), 'kind');
  if (!URL_FILTERS_APPLIED) {
    // bookmarkable views: /?project=<slug>&subject=…&kind=… preselect filters
    const q = new URLSearchParams(location.search);
    for (const [key, id] of Object.entries(URL_KEYS)) {
      const want = q.get(key), e = document.getElementById(id);
      if (!want) continue;
      if (e.tagName === 'SELECT' && ![...e.options].some(o => o.value === want)) continue;
      e.value = want;
    }
    URL_FILTERS_APPLIED = true;
  }
}

function syncUrl() {
  const q = new URLSearchParams(location.search);
  for (const [key, id] of Object.entries(URL_KEYS)) {
    const v = document.getElementById(id).value.trim();
    if (v) q.set(key, v); else q.delete(key);
  }
  const qs = q.toString();
  history.replaceState(null, '', qs ? '?' + qs : location.pathname);
}

function onFilterChange() {
  syncUrl();
  renderBeliefs();
  applyDim();
}

function fillSelect(sel, values, label) {
  const cur = sel.value;
  sel.innerHTML = '';
  const all = el('option', null, label + ': all'); all.value = '';
  sel.append(all);
  values.sort().forEach(v => { const o = el('option', null, v); o.value = v; sel.append(o); });
  if (values.includes(cur)) sel.value = cur;
}

function beliefRows() {
  const fs = $('#f-subject').value.trim(), fp = $('#f-predicate').value.trim();
  const proj = $('#f-project').value, kind = $('#f-kind').value;
  return STATE.head_facts.filter(r =>
    (!fs || r.subject.includes(fs)) &&
    (!fp || r.predicate.includes(fp)) &&
    (!proj || (r.qualifiers || {}).project === proj) &&
    (!kind || r.kind === kind));
}

function renderBeliefs() {
  const tbody = $('#beliefs tbody'); tbody.innerHTML = '';
  const rows = beliefRows();
  $('#beliefs-n').textContent = rows.length === STATE.head_facts.length
    ? '(' + rows.length + ')' : '(' + rows.length + ' / ' + STATE.head_facts.length + ')';
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = el('td', 'empty', STATE.head_facts.length
      ? 'no beliefs match the filters' : 'no active beliefs yet');
    td.colSpan = 5;
    tr.append(td);
    tr.className = 'expand';
    tbody.append(tr);
    return;
  }
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.dataset.id = r.assertion;
    if (SEL && SEL.type === 'fact' && SEL.id === r.assertion) tr.classList.add('sel');
    tr.append(el('td', 'mono', r.subject));
    tr.append(el('td', null, r.predicate));
    const objText = (r.negates ? 'NOT ' : '') + String(r.object);
    const objTd = el('td', 'obj');
    objTd.title = objText;
    const long = objText.length > 60 || objText.includes('\n');
    if (long) {
      const open = EXPANDED.has(r.assertion);
      const btn = el('button', 'expander', open ? '▾' : '▸');
      btn.title = open ? 'collapse' : 'expand full text';
      btn.setAttribute('aria-expanded', String(open));
      btn.addEventListener('click', ev => {
        ev.stopPropagation();
        if (open) EXPANDED.delete(r.assertion); else EXPANDED.add(r.assertion);
        renderBeliefs();
      });
      objTd.append(btn);
    }
    objTd.append(el('span', null, objText));
    if (r.negates) objTd.append(el('span', 'chip negs', '⊘ negation'));
    tr.append(objTd);
    const conf = el('td');
    const bar = el('span', 'bar'), fill = el('span', 'fill');
    fill.style.width = Math.max(2, r.confidence_bps / 100) + '%';
    bar.append(fill);
    conf.append(bar, el('span', 'muted', pct(r.confidence_bps)));
    tr.append(conf);
    const kindTd = el('td');
    kindTd.append(el('span', 'chip kind', r.kind));
    tr.append(kindTd);
    tr.addEventListener('click', () => select({type: 'fact', id: r.assertion}));
    tbody.append(tr);
    if (long && EXPANDED.has(r.assertion)) {
      const xr = document.createElement('tr');
      xr.className = 'expand';
      const td = document.createElement('td');
      td.colSpan = 5;
      td.append(el('div', 'fulltext', objText));
      xr.append(td);
      tbody.append(xr);
    }
  });
}

function markSel() {
  document.querySelectorAll('.sel').forEach(e => e.classList.remove('sel'));
  if (!SEL) return;
  const e = document.querySelector('[data-id="' + SEL.id + '"]');
  if (e) e.classList.add('sel');
}

function select(sel) {
  SEL = sel;
  markSel();
  renderDetail();
}

function nodeById(id) { return STATE.graph.find(n => n.id === id); }

function kv(box, key, value, mono) {
  const d = el('div', 'kv');
  const v = el('span', 'v' + (mono ? ' mono copy' : ''), value);
  if (mono) {
    v.title = 'click to copy';
    v.addEventListener('click', () => copyText(String(value)));
  }
  d.append(el('span', 'k muted', key), v);
  box.append(d);
}

function factLine(aid, cls) {
  const r = STATE.assertions[aid];
  const d = el('div', 'fact-line' + (cls ? ' ' + cls : ''));
  if (!r) { d.textContent = short(aid); return d; }
  d.append(el('span', 'mono', r.subject),
    el('span', 'muted', ' ' + r.predicate + ' = '),
    el('span', null, (r.negates ? 'NOT ' : '') + String(r.object)),
    el('span', 'muted', ' · ' + pct(r.confidence_bps)));
  d.addEventListener('click', () => select({type: 'fact', id: aid}));
  return d;
}

function annotationsBlock(box, ids) {
  const entries = [];
  ids.forEach(id => (STATE.annotations[id] || []).forEach(a => entries.push(a)));
  if (!entries.length) return;
  box.append(el('h3', null, 'Annotations'));
  entries.forEach(a => {
    const d = el('div', 'anno');
    d.append(el('div', 'muted', (a.namespace || 'notes') + ' · ' + (a.author || '') +
      ' · ' + fmtTs(a.created_at)));
    d.append(el('div', null, a.body));
    box.append(d);
  });
}

function renderDetail() {
  const card = $('#detail-card'), box = $('#detail'), title = $('#detail-title');
  if (!SEL) { card.hidden = true; return; }
  card.hidden = false;
  box.innerHTML = '';
  if (SEL.type === 'thought') renderThoughtDetail(box, title);
  else renderFactDetail(box, title);
}

function renderThoughtDetail(box, title) {
  const n = nodeById(SEL.id);
  title.textContent = 'Thought ' + short(SEL.id);
  if (!n) { box.append(el('div', 'muted', 'not found in current state')); return; }
  box.append(el('div', 'msg-big', n.message));
  kv(box, 'author', n.author);
  kv(box, 'time', fmtTs(n.timestamp));
  kv(box, 'operation', n.operation);
  if ((n.projects || []).length) kv(box, 'projects', n.projects.join(', '));
  kv(box, 'id', n.id, true);
  n.parents.forEach(p => kv(box, 'parent', short(p), true));
  if (n.added.length) {
    box.append(el('h3', null, 'Added beliefs (' + n.added.length + ')'));
    n.added.forEach(a => box.append(factLine(a)));
  }
  if (n.removed.length) {
    box.append(el('h3', null, 'Removed beliefs (' + n.removed.length + ')'));
    n.removed.forEach(a => box.append(factLine(a, 'removed')));
  }
  annotationsBlock(box, [n.id]);
}

function renderFactDetail(box, title) {
  const r = STATE.assertions[SEL.id];
  title.textContent = 'Belief ' + short(SEL.id);
  if (!r) { box.append(el('div', 'muted', 'not found in current state')); return; }
  const line = el('div', 'msg-big');
  line.append(el('span', 'mono', r.subject),
    el('span', 'muted', '  ' + r.predicate + ' = '),
    el('span', null, (r.negates ? 'NOT ' : '') + String(r.object)));
  box.append(line);
  if (r.negates) box.append(el('div', 'muted',
    'This is a negation: it asserts the claim below is FALSE — no replacement value is implied.'));
  kv(box, 'kind', r.kind);
  kv(box, 'status', r.status);
  kv(box, 'confidence', pct(r.confidence_bps) + ' (' + r.confidence_bps + ' bps)');
  kv(box, 'source', r.source + (r.source_uri ? ':' + r.source_uri : ''));
  kv(box, 'actor', r.actor);
  const q = r.qualifiers || {};
  Object.keys(q).forEach(k => kv(box, 'qualifier · ' + k, String(q[k])));
  kv(box, 'assertion', r.assertion, true);
  kv(box, 'claim', r.claim, true);
  if (r.negates) {
    const neg = Object.values(STATE.assertions).find(o => o.claim === r.negates);
    kv(box, 'negates', neg
      ? neg.subject + ' ' + neg.predicate + ' = ' + String(neg.object) : r.negates, !neg);
  }
  if ((r.premises || []).length) {
    box.append(el('h3', null, 'Premises (derived from)'));
    r.premises.forEach(pid => box.append(factLine(pid)));
  }
  const tid = STATE.introducer[r.assertion];
  if (tid) {
    box.append(el('h3', null, 'Introduced by'));
    const n = nodeById(tid);
    const d = el('div', 'fact-line');
    d.append(el('span', 'mono muted', short(tid)),
      el('span', null, n ? ' ' + n.message + ' · ' + fmtTs(n.timestamp) : ''));
    d.addEventListener('click', () => {
      select({type: 'thought', id: tid});
      const e = document.querySelector('.thought[data-id="' + tid + '"]');
      if (e) e.scrollIntoView({behavior: 'smooth', block: 'center'});
    });
    box.append(d);
  }
  annotationsBlock(box, [r.assertion, r.claim]);
}

function init() {
  ['f-subject', 'f-predicate', 'f-project', 'f-kind'].forEach(id =>
    document.getElementById(id).addEventListener('input', onFilterChange));
  $('#detail-close').addEventListener('click', () => select(null));
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && SEL) select(null);
  });
  if (window.COGIT_STATE) {
    LIVE_MODE = false;  // snapshot: absolute timestamps, no polling
    STATE = window.COGIT_STATE;
    const live = $('#live');
    live.className = 'chip snap';
    live.textContent = 'snapshot · ' + fmtTs(STATE.generated_at);
    renderAll();
  } else {
    poll();
    setInterval(poll, 3000);
    setInterval(refreshTimes, 30000);
  }
}
init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
