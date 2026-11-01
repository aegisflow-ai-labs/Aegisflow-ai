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

COOKIE = "aegisflow_session"
BINDING = "aegisflow_login"
CSS = """
:root{color-scheme:dark;--bg:#090e16;--paper:#101824;--ink:#edf3fa;--muted:#a0aec0;--line:#263244;--accent:#4be0b2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}button,.button,summary{cursor:pointer}button,.button{display:inline-block;background:var(--accent);color:#07251c;border:0;border-radius:9px;padding:12px 20px;font:600 14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:46px}button:hover,.button:hover{background:#8aefcf;text-decoration:none}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #7bbcff;outline-offset:4px}.skip{position:absolute;z-index:5;left:16px;top:0;transform:translateY(-150%);background:var(--paper);padding:12px}.skip:focus{transform:none}.sidebar{position:fixed;inset:0 auto 0 0;width:230px;padding:30px 22px;border-right:1px solid var(--line);background:#0b111b;display:flex;flex-direction:column}.brand{font-size:23px;font-weight:750;letter-spacing:-1px;color:var(--ink)}.brand b{display:inline-grid;place-items:center;background:var(--accent);color:#09251e;width:34px;height:36px;border-radius:10px;margin-right:10px}.sidebar small,.eyebrow{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted)}nav{margin-top:50px;display:grid;gap:9px}nav a{padding:13px 14px;border-radius:8px;color:#b7c3d4}nav a:hover{background:#12302c;color:var(--accent)}.sidebar-bottom{margin-top:auto;border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}main{margin-left:230px;min-height:100vh;padding:0 40px 28px;max-width:1900px}header{height:86px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);gap:20px}.tag{font-size:12px;color:#b0c1d4;border:1px solid var(--line);border-radius:30px;padding:6px 13px}.crumb{color:var(--muted);font-size:13px}.crumb strong{color:var(--ink);font-weight:500}.hero{padding:40px 0 22px}h1{font-size:clamp(28px,3.2vw,43px);line-height:1.15;letter-spacing:-1.6px;margin:12px 0 14px;font-weight:650}h2{font-size:19px;letter-spacing:-.4px;margin:0 0 12px}p{margin:10px 0}.lead{color:var(--muted);max-width:70ch}.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:26px;margin:20px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:12px;margin:22px 0;overflow:hidden}.stat{padding:20px 24px;background:#0e1621;border-right:1px solid var(--line)}.stat:last-child{border:0}.stat strong{display:block;font-size:29px;letter-spacing:-1px;font-weight:600}.stat span{color:var(--muted);font-size:12px}.stat em{font-style:normal;color:var(--accent);font-size:11px}.map{border:1px solid var(--line);border-radius:14px;background-color:#0b121d;background-image:radial-gradient(#273344 1px,transparent 1px);background-size:22px 22px;padding:26px;margin:24px 0}.map-top{display:flex;justify-content:space-between;gap:16px;margin-bottom:26px}.map-top p{font-size:12px;color:var(--muted);margin:0}.graph{display:grid;grid-template-columns:1fr 70px 1fr 70px 1.5fr;align-items:center;min-height:350px}.graph>*{min-width:0}.node{background:#111c29;border:1px solid #334458;border-radius:12px;padding:22px;box-shadow:0 12px 35px #0003}.node strong{display:block;font-size:17px;margin:12px 0 5px}.node p{font-size:12px;color:var(--muted)}.node-code{color:var(--accent);font-family:monospace;font-size:12px}.connector{height:1px;background:#42645f;position:relative}.connector:after{content:"";position:absolute;right:0;top:-3px;border-left:7px solid var(--accent);border-top:4px solid transparent;border-bottom:4px solid transparent}.sources{display:grid;gap:10px}.source{background:#101a27;border:1px solid var(--line);border-radius:9px;padding:13px 16px}.source summary{min-height:44px;font-size:13px}.source small{display:block;color:var(--muted);font-size:11px;overflow-wrap:anywhere}.source pre{max-height:280px;overflow:auto}.map-caption{border-top:1px solid var(--line);padding-top:17px;margin-top:24px;display:flex;gap:24px;flex-wrap:wrap;color:var(--muted);font-size:12px}.dot{display:inline-block;width:7px;height:7px;background:var(--accent);border-radius:50%;margin-right:7px}.workspace-note{display:flex;justify-content:space-between;gap:20px;align-items:center}.workspace-note p{color:var(--muted);font-size:13px}.pill{align-self:flex-start;display:inline-block;padding:4px 9px;background:#19362e;color:#7defc7;border-radius:5px;font-size:11px}dl{display:grid;grid-template-columns:1fr 2fr;gap:12px 22px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 monospace;background:#080e17;padding:16px;border-radius:8px}summary{min-height:44px;padding:9px 0}footer{font-size:11px;color:var(--muted);padding:25px 0 0}form{margin:0}.secondary{background:var(--paper);color:var(--ink)}
@media(min-width:1200px){body:has(.graph) .hero{padding-top:32px}}
@media(max-width:1100px){.sidebar{width:190px;padding:24px 16px}main{margin-left:190px;padding:0 24px 24px}.graph{grid-template-columns:1fr 35px 1fr}.sources{grid-column:1/-1;margin-top:22px;grid-template-columns:repeat(2,1fr)}.graph>.connector:nth-of-type(4){display:none}.stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.sidebar{position:static;width:auto;padding:16px 20px;border-right:0;border-bottom:1px solid var(--line)}.sidebar nav,.sidebar-bottom{display:none}main{margin-left:0;padding:0 18px 24px}header{height:68px}.crumb{font-size:11px}.tag{font-size:10px;padding:5px 8px}.hero{padding-top:26px}.stats{grid-template-columns:repeat(2,1fr)}.stat{padding:15px}.stat strong{font-size:24px}.map{padding:18px}.graph{display:flex;flex-direction:column;gap:16px;align-items:stretch;min-height:0}.connector{height:20px;width:1px;align-self:center}.connector:after{display:none}.sources{display:grid;grid-template-columns:1fr;margin:0}.workspace-note,.map-top{align-items:flex-start;flex-direction:column}.card{padding:20px}dl{grid-template-columns:1fr;gap:4px}dd{margin-bottom:12px}.lead{font-size:14px}}
"""


def page(content: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AegisFlow AI · Evidence workspace</title>
<link rel="stylesheet" href="/auth/style.css"></head><body><a class="skip" href="#content">Skip to content</a>
<aside class="sidebar"><a class="brand" href="/"><b>A</b>AegisFlow<span class="eyebrow"> AI</span></a><nav aria-label="Workspace"><small>Workspace</small><a href="/">Overview</a><a href="/#investigation">Investigation</a><a href="/#capabilities">Capabilities</a></nav><div class="sidebar-bottom"><span class="dot"></span>Local workspace<br>Evidence-led operations<br><br>Development pilot · v0.1</div></aside><main id="content"><header><span class="crumb">Workspace &nbsp; / &nbsp; <strong>Supply intelligence</strong></span><span class="tag">Synthetic environment</span></header>"""
        + content
        + "<footer>Deterministic investigation · No model calls · No external business actions</footer></main></body></html>",
        status_code=status,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def capability_panel() -> str:
    return '<section id="capabilities" class="card workspace-note"><div><span class="eyebrow">Development status</span><h2>Selective intelligence. Visible boundaries.</h2><p>36 roles registered · 1 capability subset implemented · 1 tested subset.<br>A21 handles synthetic elapsed-time SLA analysis. Other specialist roles are planned.</p></div><span class="pill">Deterministic baseline</span></section>'


def overview_map() -> str:
    return '<div class="map"><div class="map-top"><div><h2>Investigation pathway</h2><p>The available workflow, before a case is run</p></div><span class="pill">Ready to run</span></div><div class="graph"><article class="node"><span class="node-code">01 / INPUT</span><strong>Purchase order</strong><p>PO-001 · Synthetic scenario<br>Fixed investigation time</p></article><div class="connector" aria-hidden="true"></div><article class="node"><span class="node-code">A21 / ANALYSIS</span><strong>Delivery &amp; SLA</strong><p>Elapsed-time rules<br>Evidence-linked findings</p></article><div class="connector" aria-hidden="true"></div><div class="sources"><div class="source">Order &amp; delivery events</div><div class="source">Supplier SLA</div><div class="source">Inventory &amp; procedure</div></div></div><div class="map-caption"><span><span class="dot"></span>Available capability</span><span>0 model calls</span><span>Read-only source analysis</span></div></div>'


def evidence_map(case: Case) -> str:
    sources = "".join(
        '<details class="source"><summary>'
        + escape(item.source_uri.rsplit("/", 1)[-1].replace("_", " ").title().replace("Sla", "SLA"))
        + "</summary><small>"
        + escape(item.source_uri)
        + "<br>Version "
        + escape(item.source_version)
        + "</small><pre>"
        + escape(item.model_dump_json(indent=2))
        + "</pre></details>"
        for item in case.evidence
    )
    return (
        '<section class="map" aria-label="Evidence map"><div class="map-top"><div><h2>Evidence map</h2><p>Trace this investigation back to its captured sources. Open a source to inspect it.</p></div><span class="pill">Persisted case</span></div>'
        + '<div class="stats"><div class="stat"><strong>'
        + str(len(case.evidence))
        + '</strong><span>Evidence snapshots</span></div><div class="stat"><strong>'
        + str(len(case.claims))
        + '</strong><span>Source-linked findings</span></div><div class="stat"><strong>'
        + str(len(case.active_roles))
        + '</strong><span>Activated roles</span></div><div class="stat"><strong>'
        + str(case.model_calls)
        + "</strong><span>Model calls</span></div></div>"
        + '<div class="graph"><article class="node"><span class="node-code">CASE / SYNTHETIC</span><strong>Supplier delivery</strong><p>'
        + escape(case.status)
        + "</p><small>"
        + escape(case.source_version)
        + '</small></article><div class="connector" aria-hidden="true"></div><article class="node"><span class="node-code">'
        + escape(" · ".join(case.active_roles))
        + '</span><strong>SLA investigation</strong><p>Deterministic analysis<br>Source snapshots preserved</p></article><div class="connector" aria-hidden="true"></div><div class="sources">'
        + sources
        + '</div></div><div class="map-caption"><span><span class="dot"></span>Captured evidence</span><span>Case → active role → source snapshots</span></div></section>'
    )


def csrf_form(session_csrf: str, action: str, label: str) -> str:
    return (
        f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{escape(session_csrf, quote=True)}">'
        f'<input type="hidden" name="key" value="ui-{secrets.token_hex(12)}"><button type="submit">{label}</button></form>'
    )


def mount_login(
    app: FastAPI, flow: BrowserLogin, investigate: Callable[[Scope, str], Case]
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
        if set(data) != {"csrf", "key"} or any(len(v) != 1 for v in data.values()):
            raise HTTPException(400, detail="INVALID_FORM")
        return {key: value[0] for key, value in data.items()}

    @app.get("/auth/style.css")
    def style() -> Response:
        return Response(CSS, media_type="text/css", headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        try:
            scope, session = flow.user(request.cookies.get(COOKIE))
        except Unauthenticated:
            response = page(
                '<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Investigate with evidence.</h1><p class="lead">Sign in to explore a synthetic supplier delivery delay, its source evidence and deterministic SLA result.</p></section><section class="card" id="investigation"><h2>Start your local session</h2><p>Your password is entered only on the local Keycloak page.</p><a class="button" href="/auth/login">Sign in with Keycloak</a></section>'
                + overview_map()
                + capability_panel()
            )
            response.delete_cookie(COOKIE, path="/")
            return response
        return page(
            f'<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Ready to investigate.</h1><p class="lead">Signed in as {escape(scope.subject_id)}. This pilot uses synthetic order PO-001.</p></section><section class="card" id="investigation"><h2>Supplier delivery delay</h2><p>Read the order, delivery, stock, SLA and procedure evidence. Every finding links to a source snapshot.</p>'
            + csrf_form(session.csrf, "/demo/investigate", "Investigate demo case")
            + "</section>"
            + overview_map()
            + '<section class="card"><h2>Session</h2><p>Sign out here, then confirm on Keycloak to end its login session too.</p>'
            + csrf_form(session.csrf, "/auth/logout", "Sign out")
            + "</section>"
            + capability_panel()
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
                '<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Sign-in did not complete.</h1><p>Please start a new sign-in.</p><a href="/">Return to the pilot</a></section>',
                400,
            )
        try:
            sid = flow.complete(
                fields["state"], request.cookies.get(BINDING, ""), fields["code"], fields["iss"]
            )
        except LoginRejected:
            return page(
                '<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Sign-in could not be verified.</h1><p>Start again from this browser.</p><a href="/">Return to the pilot</a></section>',
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
            case = await run_in_threadpool(investigate, scope, data["key"])
        except (NotFound, PolicyDenied):
            return page(
                '<h1>Scenario access denied.</h1><p>This account does not have the required source permissions.</p><a href="/">Return to the pilot</a>',
                403,
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
            '<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Investigation complete.</h1><p class="lead">Synthetic supplier delivery case · Deterministic rules</p></section>'
            + evidence_map(case)
            + '<section class="card"><h2>Findings</h2><dl>'
            + details
            + "</dl><details><summary>View source-linked report</summary><pre>"
            + escape(case.model_dump_json(indent=2))
            + "</pre></details></section>"
            + '<a href="/">Back to the pilot</a>'
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
            '<section class="hero"><span class="eyebrow">Operations intelligence</span><h1>Application session ended.</h1><p class="lead">Finish signing out of Keycloak to end its local SSO session too.</p></section>'
            + '<section class="card"><a class="button" href="'
            + escape(target, quote=True)
            + '">Finish signing out of Keycloak</a></section><a href="/">Return to the pilot</a>'
        )
        response.delete_cookie(COOKIE, path="/")
        return response
