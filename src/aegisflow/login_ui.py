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

COOKIE = "aegisflow_session"
BINDING = "aegisflow_login"
CSS = """
:root{color-scheme:light;--ink:#17243d;--muted:#465875;--accent:#1855b8;--line:#d8e0ec;--paper:#fff;--bg:#f2f5fa}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}
main{max-width:960px;margin:auto;padding:32px 24px 64px}header{display:flex;justify-content:space-between;gap:16px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:20px}
.brand{font-weight:750;font-size:20px}.tag{font-size:14px;color:var(--muted)}h1{font-size:clamp(30px,5vw,44px);line-height:1.15;letter-spacing:-.03em;margin:0 0 16px}h2{font-size:22px;margin:0 0 12px}
.hero{padding:52px 0 32px}.lead{max-width:60ch;color:var(--muted)}.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:28px;margin:20px 0}
a{color:var(--accent)}.button,button{display:inline-block;border:0;border-radius:8px;background:var(--accent);color:white;padding:12px 20px;font:600 16px/1.5 system-ui;min-height:48px;text-decoration:none;cursor:pointer}
.button:hover,button:hover{background:#103e88}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #b54d00;outline-offset:4px}dl{display:grid;grid-template-columns:minmax(100px,1fr) 2fr;gap:10px 24px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;background:var(--bg);padding:16px}summary{cursor:pointer;min-height:44px}footer{color:var(--muted);font-size:14px;margin-top:28px}.skip{position:absolute;left:16px;top:0;transform:translateY(-150%);background:white;padding:10px 16px;min-height:44px}.skip:focus{transform:translateY(0)}form{margin:0}select{display:block;max-width:100%;padding:12px;margin:8px 0;font:inherit}select:focus-visible{outline:3px solid #b54d00;outline-offset:4px}.secondary{background:#344861}
@media(max-width:500px){main{padding:20px 16px}header{align-items:flex-start;flex-direction:column}.card{padding:20px}dl{grid-template-columns:1fr;gap:4px}dd{margin-bottom:12px}}
"""


def page(content: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AegisFlow AI · Local pilot</title>
<link rel="stylesheet" href="/auth/style.css"></head><body><a class="skip" href="#content">Skip to content</a>
<main id="content"><header><span class="brand">AegisFlow AI</span><span class="tag">Local pilot · Synthetic data</span></header>"""
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
        return Response(CSS, media_type="text/css", headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        try:
            scope, session = flow.user(request.cookies.get(COOKIE))
        except Unauthenticated:
            response = page(
                '<section class="hero"><h1>Investigate with evidence.</h1><p class="lead">Sign in to explore a synthetic supplier delivery delay, its source evidence and deterministic SLA result.</p></section><section class="card"><h2>Start your local session</h2><p>Your password is entered only on the local Keycloak page.</p><a class="button" href="/auth/login">Sign in with Keycloak</a></section>'
            )
            response.delete_cookie(COOKIE, path="/")
            return response
        return page(
            f'<section class="hero"><h1>Ready to investigate.</h1><p class="lead">Signed in as {escape(scope.subject_id)}. Choose an authorized synthetic purchase order to investigate.</p></section><section class="card"><h2>Supplier delivery delay</h2><p>Read the order, delivery, stock, SLA and procedure evidence. Every finding links to a source snapshot.</p>'
            + csrf_form(
                session.csrf, "/demo/investigate", "Investigate demo case", available_orders(scope)
            )
            + '</section><section class="card"><h2>Session</h2><p>Sign out here, then confirm on Keycloak to end its login session too.</p>'
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
            '<section class="card"><h2>'
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
            '<section class="hero"><h1>Investigation complete.</h1><p class="lead">Synthetic supplier delivery case · Deterministic rules</p></section>'
            + recommendation
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
