"""Server-rendered local pilot page; tokens stay in server memory, no client script."""

import secrets
from collections.abc import Callable
from html import escape
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .contracts import Action, AuditEvent, Case, Scope
from .identity import Unauthenticated
from .oidc import BrowserLogin, LoginCapacity, LoginRejected, Session
from .store import NotFound, PolicyDenied
from .triage import triage
from .workspace import CSS as WORKSPACE_CSS
from .workspace import JS as WORKSPACE_JS
from .workspace import agent_map

COOKIE = "aegisflow_session"
BINDING = "aegisflow_login"
CSS = """
:root{color-scheme:dark;--ink:#eef3fb;--muted:#9baac0;--accent:#79e6ca;--line:#273349;--paper:#121c2c;--bg:#0b1220}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:0 48px 48px}header{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:25px 0;border-bottom:1px solid var(--line)}
.brand{font-size:21px;font-weight:750;letter-spacing:-.7px}.brand:before{content:"A";display:inline-grid;place-items:center;background:var(--accent);color:#102b26;border-radius:9px;width:34px;height:36px;margin-right:12px}.tag,.eyebrow{font-size:12px;color:var(--muted);letter-spacing:1px}.tag{border:1px solid var(--line);padding:6px 12px;border-radius:30px}
h1{font-size:clamp(30px,4vw,50px);line-height:1.12;letter-spacing:-1.8px;margin:0 0 18px;font-weight:600}h2{font-size:21px;margin:0 0 15px;letter-spacing:-.4px}p{margin:10px 0}.hero{padding:48px 0 18px}.lead{max-width:70ch;color:var(--muted)}.card{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:28px;margin:22px 0}.decision{border-left:4px solid var(--accent);background:linear-gradient(110deg,#17312f,#121c2c 75%)}.decision>p:first-of-type{font-size:22px;max-width:65ch;line-height:1.5}
a{color:var(--accent)}.button,button{display:inline-block;border:1px solid var(--accent);border-radius:7px;background:var(--accent);color:#0b2922;padding:12px 20px;font:650 15px/1.5 system-ui;min-height:48px;text-decoration:none;cursor:pointer}.button:hover,button:hover{background:#b2f4e3}a:focus-visible,button:focus-visible,summary:focus-visible,select:focus-visible{outline:3px solid #89baff;outline-offset:4px}
dl{display:grid;grid-template-columns:1fr 2fr;gap:12px 24px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 monospace;background:#09101c;padding:18px;border-radius:6px}summary{cursor:pointer;min-height:44px;padding:10px 0}footer{color:var(--muted);font-size:12px;margin-top:28px}.skip{position:absolute;left:16px;top:0;transform:translateY(-150%);background:var(--paper);padding:12px;z-index:3}.skip:focus{transform:translateY(0)}form{margin:0}select{display:block;width:min(100%,420px);padding:14px;margin:8px 0;background:#0b1423;color:var(--ink);border:1px solid #52627a;border-radius:6px;font:inherit}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:24px 0}.metric{border:1px solid var(--line);background:#101a2a;padding:24px;border-radius:10px}.metric strong{display:block;font-size:34px;font-weight:550;letter-spacing:-1px;margin:7px 0}.metric small{color:var(--muted)}.workbench{display:grid;grid-template-columns:1.25fr 1fr;gap:24px;align-items:start}.workbench>.card{margin-top:0}.evidence-item{border-top:1px solid var(--line);padding:14px 0}.evidence-item small{color:var(--muted);overflow-wrap:anywhere;display:block}.timeline{border-left:2px solid #375e61;padding-left:24px;list-style:none}.timeline li{padding:10px 0 18px}.timeline time{display:block;color:var(--muted);font-size:13px}.evidence-item:target{outline:2px solid var(--accent);outline-offset:5px}.claim{border-top:1px solid var(--line);padding:18px 0}.claim small{display:block;color:var(--muted)}.claim a{display:inline-block;padding:6px 10px;margin:8px 8px 0 0;border:1px solid var(--line);border-radius:5px;font-size:12px}.workbench>*{min-width:0}
@media(max-width:800px){main{padding:0 22px 32px}.workbench{grid-template-columns:1fr}.metrics{gap:10px}.metric{padding:18px}.metric strong{font-size:26px}.hero{padding-top:32px}}
@media(max-width:500px){header{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr}.metric strong{font-size:30px}.card{padding:20px}dl{grid-template-columns:1fr;gap:5px}dd{margin-bottom:12px}}
"""


def page(content: str, status: int = 200, active: str = "overview") -> HTMLResponse:
    navigation = (
        ("overview", "/", "Command center"),
        ("cases", "/cases", "Investigations"),
        ("agents", "/agents", "Agent map"),
        ("evidence", "/evidence", "Evidence library"),
        ("activity", "/activity", "Audit trail"),
        ("actions", "/actions", "Action center"),
        ("access", "/access", "Access & session"),
    )
    nav = '<aside class="shell-nav"><span class="brand">AegisFlow</span><span class="nav-group">WORKSPACE</span>'
    for key, href, label in navigation:
        current = ' class="selected" aria-current="page"' if active == key else ""
        nav += f'<a href="{href}"{current}>{label}</a>'
    nav += '<div class="nav-foot">AegisFlow AI<br>Local · Synthetic data</div></aside>'
    label = next((label for key, _, label in navigation if key == active), "Workspace")
    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>"""
        + escape(label)
        + """ · AegisFlow AI</title>
<link rel="stylesheet" href="/auth/style.css"><script src="/auth/workspace.js" defer></script></head><body><a class="skip" href="#content">Skip to content</a>
"""
        + nav
        + """<main id="content"><header><span class="top-path">Control &nbsp; / &nbsp; <strong>"""
        + escape(label)
        + """</strong></span><div class="top-tools">"""
        + (
            '<label class="sr-only" for="workspace-search">Search agents</label><input class="searchbox" id="workspace-search" type="search" placeholder="Search agents, capabilities…">'
            if active == "agents"
            else ""
        )
        + """<span class="tag">Local pilot</span></div></header>"""
        + content
        + "<footer>Deterministic investigation · No model calls · No external business actions</footer></main></body></html>",
        status_code=status,
        headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def order_name(case: Case) -> str:
    order = next((e for e in case.evidence if e.evidence_id.endswith(":order")), None)
    return str(order.snapshot.get("order_id", "Unknown order")) if order else "Unknown order"


def case_table(cases: tuple[Case, ...]) -> str:
    if not cases:
        return '<p class="empty">No matching investigations. Choose an order above to start a case.</p>'
    rows = ""
    for case in cases:
        decision = triage(case)
        values = {c.code: c.value for c in case.claims}
        rows += (
            '<tr><td><a href="/cases/'
            + escape(case.case_id, quote=True)
            + '">'
            + escape(order_name(case))
            + "</a><small>"
            + escape(case.case_id)
            + '</small></td><td><span class="status">'
            + escape(case.status.replace("_", " ").title())
            + "</span></td><td>"
            + escape(str(values.get("DELIVERY_DELAY", "Unresolved")))
            + "</td><td>"
            + escape(decision.disposition.replace("_", " ").title())
            + "</td><td>"
            + escape(case.created_at.isoformat())
            + "</td></tr>"
        )
    return (
        '<div class="table-scroll"><table><thead><tr><th>Order / case</th><th>Status</th><th>Delay (seconds)</th><th>Next step</th><th>Created at</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></div>"
    )


def dashboard(cases: tuple[Case, ...]) -> str:
    decisions = [triage(case) for case in cases]
    escalate = sum(d.disposition == "ESCALATE" for d in decisions)
    gaps = sum(d.disposition == "COLLECT_EVIDENCE" for d in decisions)
    return (
        '<div class="metrics"><article class="metric"><small>VISIBLE INVESTIGATIONS</small><strong>'
        + str(len(cases))
        + "</strong><small>Latest authorized case page</small></article>"
        + '<article class="metric"><small>ESCALATION RECOMMENDED</small><strong>'
        + str(escalate)
        + "</strong><small>Cases exceeding supplier terms</small></article>"
        + '<article class="metric"><small>EVIDENCE GAPS</small><strong>'
        + str(gaps)
        + "</strong><small>Cases requiring more information</small></article></div>"
        + '<div class="quick-links"><a class="button" href="/cases">New investigation ↗</a><a href="/evidence">Browse evidence</a><a href="/activity">Review audit trail</a></div>'
        + '<section class="card"><h2>Recent investigations</h2>'
        + case_table(cases[:10])
        + '</section><div class="workbench"><section class="card"><h2>How to use this workspace</h2><ol><li>Choose a synthetic purchase order in Investigations.</li><li>Run the evidence and SLA checks.</li><li>Review the recommendation and its source records.</li><li>Reopen the case from history and trace its audit events.</li></ol></section><section class="card"><h2>Current capability</h2><p>A21 · Supplier SLA analysis</p><p class="lead">Five synthetic scenarios exercise late delivery, on-time delivery, missing SLA, conflicting records and an outstanding delivery.</p><a href="/agents">Explore the agent map ↗</a></section></div>'
    )


def case_workbench(case: Case) -> str:
    values = {claim.code: claim.value for claim in case.claims}
    delay = values.get("DELIVERY_DELAY")
    hours = f"{float(delay) / 3600:g} h" if isinstance(delay, (int, float)) else "Unresolved"
    breach = values.get("SLA_BREACH")
    sla = "Breached" if breach is True else "Within SLA" if breach is False else "Unresolved"
    metrics = (
        '<div class="metrics"><article class="metric"><small>DELIVERY DELAY</small><strong>'
        + escape(hours)
        + "</strong><small>Elapsed time beyond promise</small></article>"
        + '<article class="metric"><small>SUPPLIER SLA</small><strong>'
        + sla
        + "</strong><small>Based on captured supplier terms</small></article>"
        + '<article class="metric"><small>EVIDENCE</small><strong>'
        + str(len(case.evidence))
        + "</strong><small>Preserved source snapshots</small></article></div>"
    )
    sources = ""
    for item in case.evidence:
        name = item.source_uri.rsplit("/", 1)[-1].replace("_", " ").title().replace("Sla", "SLA")
        sources += (
            '<details class="evidence-item" id="'
            + escape(item.evidence_id, quote=True)
            + '"><summary>'
            + escape(name)
            + "</summary><small>"
            + escape(item.source_uri)
            + "<br>Version: "
            + escape(item.source_version)
            + "<br>SHA-256: "
            + escape(item.checksum)
            + "</small><pre>"
            + escape(item.model_dump_json(indent=2))
            + "</pre></details>"
        )
    findings = ""
    for claim in case.claims:
        findings += (
            '<article class="claim"><strong>'
            + escape(claim.code.replace("_", " ").title())
            + "</strong><small>"
            + escape(str(claim.value))
            + "</small>"
        )
        for ref in claim.evidence_refs:
            findings += (
                '<a href="#'
                + escape(ref, quote=True)
                + '">'
                + escape(ref.rsplit(":", 1)[-1])
                + "</a>"
            )
        findings += "</article>"
    order = next((e.snapshot for e in case.evidence if e.evidence_id.endswith(":order")), {})
    timeline = '<ol class="timeline">'
    for label, value in (
        ("Order placed", order.get("placed_at")),
        ("Promised delivery", order.get("promised_at")),
        ("Investigation cutoff", case.as_of.isoformat()),
    ):
        timeline += "<li>" + label + "<time>" + escape(str(value or "Unavailable")) + "</time></li>"
    timeline += "</ol>"
    return (
        metrics
        + '<div class="workbench"><section class="card"><h2>What the evidence establishes</h2>'
        + findings
        + "<h2>Investigation timeline</h2>"
        + timeline
        + '</section><section class="card"><h2>Source evidence</h2><p class="lead">Follow a finding to its source. Open a record to inspect the captured data.</p>'
        + sources
        + "</section></div>"
    )


def csrf_form(
    session_csrf: str, action: str, label: str, orders: tuple[str, ...] | None = None
) -> str:
    selection = ""
    if orders is not None:
        selection = (
            '<label for="order">Purchase order</label><select id="order" name="order_id" required>'
        )
        selection += "".join(
            f'<option value="{escape(order, quote=True)}">{escape(order)}</option>'
            for order in orders
        )
        selection += "</select><p>Investigation time: 1 November 2026, 18:00 UTC (synthetic scenario clock).</p>"
    return (
        f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{escape(session_csrf, quote=True)}">'
        f'<input type="hidden" name="key" value="ui-{secrets.token_hex(12)}">{selection}<button type="submit">{label}</button></form>'
    )


def report(case: Case, extra: str = "") -> HTMLResponse:
    decision = triage(case)
    recommendation = (
        '<section class="card decision"><span class="eyebrow">RECOMMENDED NEXT STEP</span><h2>'
        + escape(decision.disposition.replace("_", " ").title())
        + "</h2><p>"
        + escape(decision.next_step)
        + "</p><p>"
        + escape(decision.rationale)
        + "</p><ul>"
        + "".join("<li>" + escape(item) + "</li>" for item in decision.missing_evidence)
        + "</ul><details><summary>Decision evidence and policy</summary><pre>"
        + escape(decision.model_dump_json(indent=2))
        + "</pre></details><p>Recommendation only. No supplier has been contacted.</p></section>"
    )
    values = {claim.code: claim.value for claim in case.claims}
    details = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>"
        for label, value in (
            ("Status", case.status),
            ("Case ID", case.case_id),
            ("Delay (seconds)", values.get("DELIVERY_DELAY", "Unknown")),
            ("SLA breach", values.get("SLA_BREACH", "Unknown")),
            ("Evidence snapshots", len(case.evidence)),
        )
    )
    return page(
        '<section class="hero" id="investigation"><h1>Investigation complete.</h1><p class="lead">Evidence-backed supplier investigation</p></section>'
        + recommendation
        + case_workbench(case)
        + '<section class="card"><h2>Findings</h2><dl>'
        + details
        + "</dl><details><summary>View source-linked report</summary><pre>"
        + escape(case.model_dump_json(indent=2))
        + '</pre></details></section><a href="/cases">Back to investigations</a>'
        + extra,
        active="cases",
    )


def mount_login(
    app: FastAPI,
    flow: BrowserLogin,
    investigate: Callable[[Scope, str, str], Case],
    available_orders: Callable[[Scope], tuple[str, ...]],
    list_cases: Callable[[Scope, int], tuple[Case, ...]],
    read_case: Callable[[Scope, str], Case],
    read_events: Callable[[Scope, str], tuple[AuditEvent, ...]],
    read_action: Callable[[Scope, str], Action | None],
    change_action: Callable[[Scope, str, str, str | None], Action],
) -> None:
    @app.exception_handler(HTTPException)
    async def browser_auth_error(request: Request, error: HTTPException) -> Response:
        if (
            error.status_code == 401
            and request.url.path in ("/demo/investigate", "/auth/logout")
            or (error.status_code == 401 and request.url.path.startswith("/actions/"))
        ):
            target = (
                "/access"
                if request.url.path == "/auth/logout"
                else "/cases"
                if request.url.path == "/demo/investigate"
                else request.url.path
            )
            return page(
                '<section class="hero"><h1>Your session has ended.</h1><p class="lead">Sign in again, then review and submit your request. Nothing was automatically retried.</p><a class="button" href="/auth/login?'
                + escape(urlencode({"next": target}), quote=True)
                + '">Sign in again</a></section>',
                401,
            )
        return await http_exception_handler(request, error)

    def current(request: Request) -> tuple[Scope, Session]:
        try:
            return flow.user(request.cookies.get(COOKIE))
        except Unauthenticated as error:
            if request.method == "GET":
                raise HTTPException(
                    303,
                    headers={"Location": "/auth/login?" + urlencode({"next": request.url.path})},
                ) from error
            raise HTTPException(401, detail="UNAUTHENTICATED") from error

    def form(request: Request, payload: bytes) -> dict[str, str]:
        origin = request.headers.get("origin")
        if origin is not None and origin != "http://127.0.0.1:8000":
            raise HTTPException(403, detail="CSRF_DENIED")
        if (
            request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(400, detail="INVALID_FORM")
        data = parse_qs(payload.decode("utf-8", errors="replace"), keep_blank_values=True)
        allowed = (
            ({"csrf", "key"}, {"csrf", "key", "order_id"})
            if request.url.path == "/demo/investigate"
            else ({"csrf", "key"},)
        )
        if request.url.path.startswith("/actions/"):
            allowed = ({"csrf", "key", "operation", "content_digest"},)
        if set(data) not in allowed or any(len(v) != 1 for v in data.values()):
            raise HTTPException(400, detail="INVALID_FORM")
        return {key: value[0] for key, value in data.items()}

    @app.get("/auth/style.css")
    def style() -> Response:
        return Response(
            CSS + WORKSPACE_CSS,
            media_type="text/css",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/auth/workspace.js")
    def workspace_script() -> Response:
        return Response(
            WORKSPACE_JS,
            media_type="text/javascript",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        try:
            scope, _ = flow.user(request.cookies.get(COOKIE))
        except Unauthenticated:
            response = page(
                '<section class="hero" id="investigation"><h1>Investigate with evidence.</h1><p class="lead">Sign in to explore a synthetic supplier delivery delay, its source evidence and deterministic SLA result.</p></section><section class="card"><h2>Start your local session</h2><p>Your password is entered only on the local Keycloak page.</p><a class="button" href="/auth/login">Sign in with Keycloak</a></section>'
            )
            response.delete_cookie(COOKIE, path="/")
            return response
        cases = list_cases(scope, 0)
        return page(
            '<section class="hero"><span class="eyebrow">OPERATIONS WORKSPACE</span><h1>Ready to investigate.</h1><p class="lead">Track supplier exceptions, review evidence and decide what needs attention.</p></section>'
            + dashboard(cases)
        )

    @app.get("/agents", response_class=HTMLResponse)
    def agents() -> HTMLResponse:
        return page(agent_map(), active="agents")

    @app.get("/cases", response_class=HTMLResponse)
    def case_list(request: Request, q: str = "", status: str = "", offset: int = 0) -> HTMLResponse:
        scope, session = current(request)
        if not 0 <= offset <= 100000 or status not in ("", "COMPLETED", "NEEDS_EVIDENCE"):
            raise HTTPException(422, detail="INVALID_PAGE")
        cases = list_cases(scope, offset)
        filtered = tuple(
            c
            for c in cases
            if (not status or c.status == status)
            and q.lower() in (c.case_id + order_name(c)).lower()
        )
        options = "".join(
            '<option value="'
            + value
            + '"'
            + (" selected" if value == status else "")
            + ">"
            + label
            + "</option>"
            for value, label in (
                ("", "All statuses"),
                ("COMPLETED", "Completed"),
                ("NEEDS_EVIDENCE", "Needs evidence"),
            )
        )
        return page(
            '<section class="hero"><h1>Investigations</h1><p class="lead">Create a case, review a result, or return to a previous investigation.</p></section>'
            + '<section class="card launch-panel" id="investigation"><h2>New investigation</h2>'
            + csrf_form(
                session.csrf, "/demo/investigate", "Investigate demo case", available_orders(scope)
            )
            + '</section><section class="card"><h2>Case history</h2>'
            + '<form method="get" class="filters"><label>Find a case<input name="q" placeholder="Order or case ID" value="'
            + escape(q, quote=True)
            + '"></label>'
            + '<div><label for="case-status">Status</label><select id="case-status" name="status">'
            + options
            + "</select></div><button>Filter cases</button></form>"
            + case_table(filtered)
            + "</section>"
            + f'<p class="lead">Page {offset // 100 + 1} · Up to 100 stored cases per page, filtered by your source access.</p>'
            + (
                f'<a class="button" href="/cases?{escape(urlencode({"offset": max(0, offset - 100), "q": q, "status": status}), quote=True)}">Previous page</a> '
                if offset
                else ""
            )
            + f'<a class="button" href="/cases?{escape(urlencode({"offset": min(100000, offset + 100), "q": q, "status": status}), quote=True)}">Next page</a>',
            active="cases",
        )

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_detail(case_id: str, request: Request) -> HTMLResponse:
        scope, _ = current(request)
        case = read_case(scope, case_id)
        link = (
            '<section class="card"><h2>Next: controlled action</h2><p>Review a synthetic procurement action and its exact approval content.</p><a class="button" href="/actions/'
            + escape(case_id, quote=True)
            + '">Open action review</a></section>'
        )
        return report(case, link)

    @app.get("/evidence", response_class=HTMLResponse)
    def evidence_library(request: Request) -> HTMLResponse:
        scope, _ = current(request)
        cases = list_cases(scope, 0)
        rows = "".join(
            '<tr><td><a href="/cases/'
            + escape(c.case_id, quote=True)
            + "#"
            + escape(e.evidence_id, quote=True)
            + '">'
            + escape(order_name(c))
            + "</a></td><td>"
            + escape(e.source_uri)
            + "</td><td>"
            + escape(e.source_version)
            + "</td><td><code>"
            + escape(e.checksum[:16])
            + "…</code></td></tr>"
            for c in cases
            for e in c.evidence
        )
        return page(
            '<section class="hero"><h1>Evidence library</h1><p class="lead">Captured records from your latest authorized case page. Open a case to inspect the full snapshot.</p></section>'
            + '<section class="card table-scroll"><table><thead><tr><th>Order / case</th><th>Source</th><th>Version</th><th>SHA-256 preview</th></tr></thead><tbody>'
            + rows
            + "</tbody></table></section>",
            active="evidence",
        )

    @app.get("/activity", response_class=HTMLResponse)
    def activity(request: Request) -> HTMLResponse:
        scope, _ = current(request)
        cases = list_cases(scope, 0)
        events = sorted(
            (e for c in cases for e in read_events(scope, c.case_id)),
            key=lambda e: (e.occurred_at, e.revision),
            reverse=True,
        )
        rows = "".join(
            "<tr><td>"
            + escape(e.occurred_at.isoformat())
            + "</td><td>"
            + escape(e.event_type)
            + '</td><td><a href="/cases/'
            + escape(e.case_id, quote=True)
            + '">'
            + escape(e.case_id)
            + "</a></td><td>"
            + str(e.revision)
            + "</td></tr>"
            for e in events
        )
        return page(
            '<section class="hero"><h1>Audit trail</h1><p class="lead">Persisted investigation events from your latest authorized case page.</p></section><section class="card table-scroll"><table><thead><tr><th>Occurred at</th><th>Event</th><th>Case</th><th>Revision</th></tr></thead><tbody>'
            + rows
            + "</tbody></table></section>",
            active="activity",
        )

    @app.get("/actions", response_class=HTMLResponse)
    def actions_index(request: Request) -> HTMLResponse:
        scope, _ = current(request)
        cases = list_cases(scope, 0)
        rows = ""
        for case in cases:
            action = read_action(scope, case.case_id)
            if action is not None or triage(case).disposition == "ESCALATE":
                rows += (
                    '<tr><td><a href="/actions/'
                    + escape(case.case_id, quote=True)
                    + '">'
                    + escape(order_name(case))
                    + "</a></td><td>"
                    + (action.status if action else "ELIGIBLE FOR PROPOSAL")
                    + "</td><td>"
                    + escape(case.case_id)
                    + "</td></tr>"
                )
        return page(
            '<section class="hero"><h1>Action center</h1><p class="lead">Review exact content, approve it and record one synthetic execution. No supplier is contacted.</p></section><section class="card table-scroll"><table><thead><tr><th>Order</th><th>Workflow state</th><th>Case</th></tr></thead><tbody>'
            + rows
            + "</tbody></table></section>",
            active="actions",
        )

    @app.get("/actions/{case_id}", response_class=HTMLResponse)
    def action_review(case_id: str, request: Request) -> HTMLResponse:
        scope, session = current(request)
        case = read_case(scope, case_id)
        action = read_action(scope, case_id)
        content = (
            '<section class="hero"><h1>Controlled action review</h1><p class="lead">Synthetic procurement review · '
            + escape(order_name(case))
            + "</p></section>"
        )
        if action is None:
            content += (
                '<section class="card"><h2>No action proposal yet</h2><p>'
                + escape(triage(case).rationale)
                + "</p></section>"
            )
            operation, label = "propose", "Prepare action proposal"
        else:
            content += (
                '<section class="card"><h2>'
                + action.status
                + "</h2><h3>Request procurement review</h3><p>"
                + escape(action.payload.message)
                + "</p><dl><dt>Purchase order</dt><dd>"
                + escape(action.payload.order_id)
                + "</dd><dt>Destination</dt><dd>Local synthetic procurement queue</dd>"
                + "<dt>Supporting evidence</dt><dd>"
                + str(len(action.payload.evidence_refs))
                + " captured records</dd>"
                + "<dt>Proposed by</dt><dd>"
                + escape(action.proposed_by)
                + "</dd>"
                + "<dt>Approved by</dt><dd>"
                + escape(action.approved_by or "Awaiting approval")
                + "</dd></dl>"
                + "<p>Approval authorizes this exact review request. No supplier will be contacted.</p>"
                + "<details><summary>Exact content and integrity record</summary><pre>"
                + escape(action.payload.model_dump_json(indent=2))
                + "</pre><p>Content SHA-256</p><pre>"
                + action.content_digest
                + "</pre></details>"
            )
            if action.receipt_id:
                content += (
                    "<p>Verified synthetic queue receipt</p><pre>"
                    + escape(action.receipt_id)
                    + "</pre>"
                )
            content += "</section>"
            operation, label = (
                ("approve", "Approve this exact action")
                if action.status == "PROPOSED"
                else ("execute", "Execute synthetic action")
            )
        permission = {"propose": "investigate", "approve": "approve", "execute": "execute"}[
            operation
        ]
        if action is None and triage(case).disposition != "ESCALATE":
            content += "<p>Resolve the evidence or SLA outcome before proposing an action.</p>"
        elif action and action.status == "EXECUTED":
            content += (
                "<p>Execution is complete. Repeated execution requests return the same receipt.</p>"
            )
        elif permission in scope.permissions:
            content += (
                '<form method="post" action="/actions/'
                + escape(case_id, quote=True)
                + '"><input type="hidden" name="csrf" value="'
                + escape(session.csrf, quote=True)
                + '"><input type="hidden" name="key" value="action"><input type="hidden" name="operation" value="'
                + operation
                + '"><input type="hidden" name="content_digest" value="'
                + (action.content_digest if action else "")
                + '"><button type="submit">'
                + label
                + "</button></form>"
            )
        else:
            content += (
                "<p>Your account does not have the permission required for the next step.</p>"
            )
        content += (
            '<p><a href="/cases/'
            + escape(case_id, quote=True)
            + '">Return to investigation</a></p>'
        )
        return page(content, active="actions")

    @app.post("/actions/{case_id}")
    async def action_submit(case_id: str, request: Request) -> Response:
        data = form(request, await request.body())
        scope, session = await run_in_threadpool(current, request)
        if not secrets.compare_digest(session.csrf.encode(), data["csrf"].encode()):
            raise HTTPException(403, detail="CSRF_DENIED")
        await run_in_threadpool(
            change_action, scope, case_id, data["operation"], data["content_digest"] or None
        )
        return RedirectResponse("/actions/" + case_id, status_code=303)

    @app.get("/access", response_class=HTMLResponse)
    def access_page(request: Request) -> HTMLResponse:
        scope, session = current(request)
        return page(
            '<section class="hero"><h1>Access &amp; session</h1></section><section class="card"><h2>Current identity</h2><p>Subject: '
            + escape(scope.subject_id)
            + "</p><p>Tenant: "
            + escape(scope.tenant_id)
            + "</p><p>Permissions: "
            + escape(", ".join(sorted(scope.permissions)))
            + "</p>"
            + csrf_form(session.csrf, "/auth/logout", "Sign out")
            + "</section>",
            active="access",
        )

    @app.get("/auth/login")
    def login(next: str = "/") -> RedirectResponse:
        try:
            location, binding = flow.begin(next)
        except LoginCapacity as error:
            raise HTTPException(429, detail="LOGIN_CAPACITY") from error
        response = RedirectResponse(location, status_code=303)
        response.set_cookie(
            BINDING, binding, max_age=300, httponly=True, samesite="lax", path="/auth"
        )
        return response

    @app.get("/auth/callback")
    def callback(request: Request) -> Response:
        fields = request.query_params
        if (
            any(len(fields.getlist(name)) != 1 for name in ("state", "code", "iss"))
            or "error" in fields
        ):
            return page(
                '<section class="hero"><h1>Sign-in did not complete.</h1><p>Please start a new sign-in.</p><a href="/">Return to the pilot</a></section>',
                400,
            )
        try:
            sid = flow.complete(
                fields["state"], request.cookies.get(BINDING, ""), fields["code"], fields["iss"]
            )
        except LoginRejected:
            return page(
                '<section class="hero"><h1>Sign-in could not be verified.</h1><p>Start again from this browser.</p><a href="/">Return to the pilot</a></section>',
                400,
            )
        except LoginCapacity as error:
            raise HTTPException(429, detail="LOGIN_CAPACITY") from error
        response = RedirectResponse(flow.user(sid)[1].return_to, status_code=303)
        response.set_cookie(COOKIE, sid, max_age=600, httponly=True, samesite="lax", path="/")
        response.delete_cookie(BINDING, path="/auth")
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/demo/investigate", response_class=HTMLResponse)
    async def run_demo(request: Request) -> Response:
        data = form(request, await request.body())
        scope, session = await run_in_threadpool(current, request)
        if not secrets.compare_digest(session.csrf.encode(), data["csrf"].encode()):
            raise HTTPException(403, detail="CSRF_DENIED")
        try:
            case = await run_in_threadpool(
                investigate, scope, data["key"], data.get("order_id", "PO-001")
            )
        except (NotFound, PolicyDenied):
            return page(
                '<h1>Scenario access denied.</h1><p>This account does not have the required source permissions.</p><a href="/">Return to the pilot</a>',
                403,
            )
        return RedirectResponse("/cases/" + case.case_id, status_code=303)

    @app.post("/auth/logout")
    async def logout(request: Request) -> HTMLResponse:
        data = form(request, await request.body())
        try:
            await run_in_threadpool(flow.logout, request.cookies.get(COOKIE, ""), data["csrf"])
        except (Unauthenticated, LoginRejected) as error:
            raise HTTPException(403, detail="CSRF_DENIED") from error
        target = (
            flow.provider.issuer
            + "/protocol/openid-connect/logout?"
            + urlencode(
                {
                    "client_id": flow.provider.client_id,
                    "post_logout_redirect_uri": "http://127.0.0.1:8000/",
                }
            )
        )
        response = page(
            '<section class="hero"><h1>Application session ended.</h1><p class="lead">Finish signing out of Keycloak to end its local SSO session too.</p></section>'
            + '<section class="card"><a class="button" href="'
            + escape(target, quote=True)
            + '">Finish signing out of Keycloak</a></section><a href="/">Return to the pilot</a>'
        )
        response.delete_cookie(COOKIE, path="/")
        return response
