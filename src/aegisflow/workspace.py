"""Product workspace: capability topology, not a claim of live agent execution."""

from html import escape

from .contracts import Case

ROLES = (
    ("A21", "SLA specialist", "Delivery terms & elapsed-time analysis", True),
    ("A15", "Timeline specialist", "Event sequencing & temporal context", False),
    ("A17", "Root cause investigator", "Investigate contributing factors", False),
    ("A18", "Options generator", "Compare possible responses", False),
    ("A28", "Human approval coordinator", "Review proposed actions", False),
)

CSS = """
table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}th{color:#9eafc6;font-weight:500;font-size:11px;letter-spacing:.4px;text-transform:uppercase}td,th{padding:18px 14px;border-bottom:1px solid #263348;vertical-align:top}td small{display:block;font-size:11px;color:#91a0b8;overflow-wrap:anywhere;margin-top:5px}.table-scroll{overflow:auto}.status{display:inline-block;background:#142d2c;padding:4px 8px;border-radius:4px;font-size:11px;white-space:nowrap}.quick-links{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.empty{padding:35px 0;color:#9baac0}.filters{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:15px 0 25px}.filters input{display:block;padding:13px;background:#0b1423;border:1px solid #52627a;color:white;border-radius:6px;font:inherit}.filters select{margin:0}.filters label{font-size:12px}.shell-nav a[aria-current=page]{box-shadow:inset 3px 0 #36d5a7}.shell-nav a:hover{background:#142233;color:white}

.shell-nav{position:fixed;inset:0 auto 0 0;width:224px;background:#080d16;border-right:1px solid #202938;padding:28px 20px;display:flex;flex-direction:column;z-index:4}
.shell-nav .brand{font-size:22px}.nav-group{font-size:10px;letter-spacing:1.8px;color:#8c9bb2;margin:38px 14px 12px}.shell-nav a{display:flex;gap:14px;align-items:center;padding:12px 14px;color:#aab7cb;text-decoration:none;border-radius:7px;font-size:14px}.shell-nav a.selected{color:#45deb4;background:#0c2926}.shell-nav svg{width:19px;height:19px;stroke:currentColor;fill:none;stroke-width:1.6}.nav-foot{margin-top:auto;border-top:1px solid #202938;padding:20px 12px 0;font-size:12px;color:#91a0b8}
body{background:#070c14}main{margin-left:224px;max-width:none;padding:0 30px 30px}header{height:82px;padding:0;border-color:#202938}.top-path{font-size:13px;color:#91a0b8}.top-path strong{color:#eef3fb;font-weight:500}.top-tools{display:flex;align-items:center;gap:15px}.searchbox{background:#0b121e;border:1px solid #293548;border-radius:8px;padding:11px 14px;color:#dfe8f6;font:13px system-ui;width:280px}.searchbox:focus{outline:2px solid #26ce9d}.top-tools a{font-size:12px}
.map-page{position:relative;min-height:calc(100vh - 113px);background-image:radial-gradient(#283344 1px,transparent 1px);background-size:24px 24px;margin:0 -30px;padding:30px}.map-heading{display:flex;justify-content:space-between;gap:20px;align-items:center}.map-heading h2{font-size:26px;letter-spacing:-.8px;margin:0 0 4px;font-weight:550}.map-heading p{font-size:13px;color:#91a0b8;margin:0}.map-actions{display:flex;gap:10px;align-items:center}.view-switch{display:flex;padding:4px;background:#0b111c;border:1px solid #2c3749;border-radius:9px}.view-switch button{background:transparent;color:#a6b3c7;border:0;padding:8px 15px;min-height:36px;font-size:13px}.view-switch button[aria-pressed=true]{background:#1b2940;color:white}.map-actions select{width:145px;margin:0;padding:10px;font-size:12px;min-height:44px}.topology-scroll{overflow:auto;min-height:650px}.topology{position:relative;min-width:850px;max-width:1400px;margin:auto;display:grid;grid-template-columns:220px minmax(260px,1fr) 250px;gap:65px;align-items:center;min-height:660px;padding:35px 0;transform-origin:top left}.edge-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.edge-layer path{fill:none;stroke:#2d4053;stroke-width:1.5}.edge-layer path.live{stroke:#337e70}.agent-stack,.source-stack{display:grid;gap:16px;z-index:1}.agent-node,.system-node,.policy-node{border:1px solid #2b374a;border-radius:12px;background:#0b121e;color:#dce5f4;box-shadow:0 12px 25px #0002}.agent-node{padding:16px 18px;text-align:left;width:100%;min-height:94px;cursor:pointer;display:block;min-width:0}.agent-node:hover,.agent-node:focus-visible{background:#12202b;border-color:#42d8ae}.agent-node small{font-weight:400;display:block;font-size:11px;color:#91a0b8;margin-top:6px}.agent-title{display:flex;align-items:center;gap:11px;font-size:14px;font-weight:550}.role-badge{display:grid;place-items:center;width:34px;height:34px;border-radius:8px;background:#192539;color:#b1c1d7;font:11px monospace;flex-shrink:0}.available .role-badge{background:#0d352d;color:#3ce0ae}.node-state{font-weight:400;font-size:10px;color:#a5b3c8;display:flex;align-items:center;gap:6px;margin-top:10px}.state-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#7b88a0}.available .state-dot{background:#27dba4}.system-node{padding:16px;min-height:84px;display:block}.system-node summary{display:flex;gap:12px;align-items:center;list-style:none;padding:0;min-height:42px;font-size:13px}.system-node summary:before{content:"";width:7px;height:7px;border-radius:50%;background:#26cc9c}.system-node small{color:#91a0b8;font-size:11px;display:block}.system-node pre{max-height:220px;overflow:auto}.source-stack>div>small{color:#91a0b8;font-size:11px;display:block;margin:0 0 8px 5px}.policy-node{padding:26px 20px;position:relative;z-index:1;margin-top:50px}.policy-emblem{width:66px;height:66px;background:#1bd39a;border:6px solid #071812;color:#06251b;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:30px;margin:-63px auto 20px;box-shadow:0 0 32px #16cb9820}.policy-node h3{text-align:center;font-size:20px;font-weight:550;margin:0}.policy-node>p{color:#91a0b8;text-align:center;font-size:12px;margin:3px 0 22px}.policy-row{display:flex;justify-content:space-between;font-size:12px;color:#9baac0;padding:10px 0}.policy-row b{color:white;font-weight:550}.canvas-bottom{display:flex;justify-content:space-between;align-items:center;gap:15px}.map-legend{display:flex;gap:20px;border:1px solid #293548;background:#0c1421;padding:12px 18px;border-radius:10px;font-size:11px;color:#acbad0}.zoom-tools{display:flex;gap:6px}.zoom-tools button{background:#101a29;border:1px solid #2a384e;color:#aab9d0;padding:8px 14px;min-height:40px}.role-inspector{border:1px solid #2c3c51;background:#0f1b2a;border-radius:10px;padding:18px 24px;margin-top:20px}.role-inspector h3{margin:0;font-size:16px}.role-inspector p{font-size:13px;color:#9cacc2}.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.launch-panel{margin-top:24px}.launch-panel form{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.launch-panel form p{flex-basis:100%;font-size:12px;color:#91a0b8}.launch-panel select{width:180px;margin:0}.launch-panel label{font-size:13px}.launch-panel h2{font-size:18px}.topology.list-mode{grid-template-columns:1fr;min-width:0;gap:20px}.list-mode .edge-layer{display:none}.list-mode .policy-node{margin-top:20px}.list-mode .agent-stack,.list-mode .source-stack{grid-template-columns:repeat(2,1fr)}[hidden]{display:none!important}
@media(max-width:1150px){.shell-nav{width:190px;padding:24px 14px}main{margin-left:190px}.topology{gap:35px;grid-template-columns:180px minmax(240px,1fr) 220px;min-width:750px}.searchbox{width:210px}}
@media(max-width:800px){.shell-nav{position:static;width:auto;padding:14px 20px;border-bottom:1px solid #263349}.shell-nav .nav-group,.nav-foot{display:none}.shell-nav{display:flex;flex-direction:row;flex-wrap:wrap;gap:5px}.shell-nav .brand{flex-basis:100%}.shell-nav>a{display:flex;padding:8px;font-size:12px}main{margin-left:0;padding:0 18px 25px}.map-page{margin:0 -18px;padding:22px 18px}.top-tools .searchbox{width:190px}.map-heading{align-items:flex-start;flex-direction:column}.topology-scroll{min-height:0}.topology{grid-template-columns:1fr;min-width:0;gap:25px;min-height:0;padding-top:70px}.edge-layer{display:none}.policy-node{margin-top:0}.agent-stack,.source-stack{grid-template-columns:repeat(2,minmax(0,1fr))}.canvas-bottom,.map-legend{flex-wrap:wrap}.list-mode .agent-stack,.list-mode .source-stack{grid-template-columns:1fr}}
@media(max-width:500px){header{height:auto;min-height:100px;align-items:stretch;padding:14px 0}.top-tools{justify-content:space-between}.searchbox{width:100%!important}.agent-stack,.source-stack{grid-template-columns:1fr}.map-actions{flex-wrap:wrap}.map-legend{gap:12px}}
"""

JS = """
document.addEventListener('DOMContentLoaded', () => {
  const graph = document.querySelector('.topology');
  if (!graph) return;
  const nodes = [...document.querySelectorAll('.agent-node')];
  const query = document.querySelector('#workspace-search');
  const filter = document.querySelector('#role-filter');
  const inspector = document.querySelector('#role-inspector');
  function apply() {
    nodes.forEach(n => {
      n.hidden = !n.textContent.toLowerCase().includes(query.value.toLowerCase()) ||
        (filter.value === 'available' && n.dataset.available !== 'true');
    });
    document.querySelector('.edge-layer').hidden = nodes.some(n => n.hidden);
    document.querySelector('#shown-count').textContent = nodes.filter(n => !n.hidden).length;
  }
  query.addEventListener('input', apply);
  filter.addEventListener('change', apply);
  document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => {
    graph.classList.toggle('list-mode', b.dataset.view === 'list');
    document.querySelectorAll('[data-view]').forEach(x => x.setAttribute('aria-pressed', x === b));
  }));
  nodes.forEach(n => n.addEventListener('click', () => {
    inspector.hidden = false;
    inspector.querySelector('h3').textContent = n.dataset.title;
    inspector.querySelector('p').textContent = n.dataset.description;
  }));
  let zoom = 1;
  document.querySelectorAll('[data-zoom]').forEach(b => b.addEventListener('click', () => {
    zoom = b.dataset.zoom === 'reset' ? 1 : Math.max(.7, Math.min(1.4, zoom + Number(b.dataset.zoom)));
    graph.style.zoom = zoom;
    document.querySelector('#zoom-value').textContent = Math.round(zoom * 100) + '%';
  }));
});
"""


def agent_map(case: Case | None = None) -> str:
    nodes = ""
    for role, name, description, available in ROLES:
        state = (
            "Activated in this case"
            if case and available
            else "Implemented · tested subset"
            if available
            else "Planned capability"
        )
        nodes += (
            f'<button type="button" class="agent-node {"available" if available else ""}" data-available="{str(available).lower()}" data-title="{escape(name)}" data-description="{escape(description)}. {state}.">'
            f'<span class="agent-title"><span class="role-badge">{role}</span>{name}</span>'
            f'<small>{description}</small><span class="node-state"><span class="state-dot"></span>{state}</span></button>'
        )
    sources = ""
    labels = (
        "Purchase orders",
        "Delivery events",
        "Supplier SLA",
        "Inventory",
        "Operating procedure",
    )
    keys = ("order", "deliveries", "sla", "inventory", "procedure")
    for name, key in zip(labels, keys, strict=True):
        item = (
            next((e for e in case.evidence if e.evidence_id.endswith(":" + key)), None)
            if case
            else None
        )
        status = "Captured snapshot" if item else "Not captured" if case else "Synthetic source"
        content = (
            escape(item.model_dump_json(indent=2))
            if item
            else "No case snapshot captured. Run an authorized investigation to inspect evidence."
        )
        sources += f'<div><small>{name}</small><details class="system-node"><summary>{status}</summary><pre>{content}</pre></details></div>'
    paths = '<path class="live" d="M200 330 C260 330 230 85 330 85"/>'
    for y in (85, 210, 335, 460, 585):
        paths += f'<path class="live" d="M650 85 C760 85 720 {y} 860 {y}"/>'
    return (
        '<section class="map-page" aria-label="Agent workspace"><div class="map-heading"><div><h2>Agent map</h2><p>36 registered roles · 1 implemented subset · Synthetic pilot</p></div>'
        '<div class="map-actions"><label class="sr-only" for="role-filter">Capability status</label><select id="role-filter"><option value="all">All statuses</option><option value="available">Implemented</option></select>'
        '<div class="view-switch"><button type="button" data-view="map" aria-pressed="true">Map</button><button type="button" data-view="list" aria-pressed="false">List</button></div><a class="button" href="/cases">Investigate case ↗</a></div></div>'
        '<div class="topology-scroll"><div class="topology"><svg class="edge-layer" viewBox="0 0 1100 660" preserveAspectRatio="none" aria-hidden="true">'
        + paths
        + "</svg>"
        '<article class="policy-node"><div class="policy-emblem">A</div><h3>AegisFlow</h3><p>Decision control layer</p><div class="policy-row">Registered roles<b>36</b></div><div class="policy-row">Implemented subset<b>1</b></div><div class="policy-row">Model calls<b>0</b></div><div class="policy-row">External actions<b>0</b></div></article>'
        '<div class="agent-stack">'
        + nodes
        + '</div><div class="source-stack">'
        + sources
        + "</div></div></div>"
        '<div class="canvas-bottom"><div class="zoom-tools"><button type="button" data-zoom="-0.1" aria-label="Zoom out">−</button><button type="button" data-zoom="reset" id="zoom-value" aria-label="Reset zoom">100%</button><button type="button" data-zoom="0.1" aria-label="Zoom in">+</button></div>'
        '<div class="map-legend"><span>● Teal: implemented subset</span><span>● Gray: planned</span><span><b id="shown-count">5</b> of 36 roles shown</span></div></div>'
        '<section class="role-inspector" id="role-inspector" aria-live="polite" hidden><h3></h3><p></p></section></section>'
    )
