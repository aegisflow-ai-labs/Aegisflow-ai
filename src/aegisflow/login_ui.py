"""Server-rendered local pilot page; tokens stay in server memory, no client script."""

import secrets
from collections.abc import Callable
from html import escape
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .contracts import Case, Scope
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


def page(content: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AegisFlow AI · Local pilot</title>
<link rel="stylesheet" href="/auth/style.css"><script src="/auth/workspace.js" defer></script></head><body><a class="skip" href="#content">Skip to content</a>
<aside class="shell-nav"><span class="brand">AegisFlow</span><span class="nav-group">OVERVIEW</span><a href="/"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>Command center</a><span class="nav-group">CONTROL</span><a class="selected" href="/">◎ &nbsp; Agent map</a><a href="/#investigation">↗ &nbsp; Investigations</a><a href="/#session">◇ &nbsp; Access &amp; session</a><div class="nav-foot">AegisFlow AI<br>Development workspace<br><br>Local · Synthetic data</div></aside><main id="content"><header><span class="top-path">Control &nbsp; / &nbsp; <strong>Agent map</strong></span><div class="top-tools"><label class="sr-only" for="workspace-search">Search agents</label><input class="searchbox" id="workspace-search" type="search" placeholder="Search agents, capabilities…"><span class="tag">Local pilot</span></div></header>"""
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


def mount_login(
    app: FastAPI,
    flow: BrowserLogin,
    investigate: Callable[[Scope, str, str], Case],
    available_orders: Callable[[Scope], tuple[str, ...]],
) -> None:
    def current(request: Request) -> tuple[Scope, Session]:
        try:
            return flow.user(request.cookies.get(COOKIE))
        except Unauthenticated as error:
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
            scope, session = flow.user(request.cookies.get(COOKIE))
        except Unauthenticated:
            response = page(
                agent_map()
                + '<section class="hero" id="investigation"><h1>Investigate with evidence.</h1><p class="lead">Sign in to explore a synthetic supplier delivery delay, its source evidence and deterministic SLA result.</p></section><section class="card"><h2>Start your local session</h2><p>Your password is entered only on the local Keycloak page.</p><a class="button" href="/auth/login">Sign in with Keycloak</a></section>'
            )
            response.delete_cookie(COOKIE, path="/")
            return response
        return page(
            agent_map()
            + f'<section class="hero" id="investigation"><h1>Ready to investigate.</h1><p class="lead">Signed in as {escape(scope.subject_id)}. Choose an authorized synthetic purchase order to investigate.</p></section><section class="card"><h2>Supplier delivery delay</h2><p>Read the order, delivery, stock, SLA and procedure evidence. Every finding links to a source snapshot.</p>'
            + csrf_form(
                session.csrf, "/demo/investigate", "Investigate demo case", available_orders(scope)
            )
            + '</section><section class="card" id="session"><h2>Session</h2><p>Sign out here, then confirm on Keycloak to end its login session too.</p>'
            + csrf_form(session.csrf, "/auth/logout", "Sign out")
            + "</section>"
        )

    @app.get("/auth/login")
    def login() -> RedirectResponse:
        try:
            location, binding = flow.begin()
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
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, sid, max_age=600, httponly=True, samesite="lax", path="/")
        response.delete_cookie(BINDING, path="/auth")
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/demo/investigate", response_class=HTMLResponse)
    async def run_demo(request: Request) -> HTMLResponse:
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
            agent_map(case)
            + '<section class="hero" id="investigation"><h1>Investigation complete.</h1><p class="lead">Evidence-backed supplier investigation</p></section>'
            + recommendation
            + case_workbench(case)
            + '<section class="card"><h2>Findings</h2><dl>'
            + details
            + "</dl><details><summary>View source-linked report</summary><pre>"
            + escape(case.model_dump_json(indent=2))
            + '</pre></details></section><a href="/">Back to the pilot</a>'
        )

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
