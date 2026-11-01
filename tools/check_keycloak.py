"""Real-browser local OIDC smoke test; never print credentials or tokens."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import expect, sync_playwright


def main():
    account = json.loads(Path("work/keycloak-local/login.json").read_text())
    output = Path("work/browser-check")
    output.mkdir(parents=True, exist_ok=True)
    channel = os.environ.get("AEGISFLOW_BROWSER_CHANNEL")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        page = browser.new_page(viewport={"width": 1440, "height": 1024})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8000/")
        expect(page.get_by_role("heading", name="Investigate with evidence.")).to_be_visible()
        page.get_by_role("button", name="List", exact=True).click()
        expect(page.locator(".topology")).to_have_class("topology list-mode")
        page.get_by_role("button", name="Map", exact=True).click()
        page.get_by_role("searchbox", name="Search agents").fill("SLA")
        expect(page.locator(".agent-node:visible")).to_have_count(1)
        page.get_by_role("searchbox", name="Search agents").fill("")
        page.get_by_label("Capability status").select_option("available")
        expect(page.locator(".agent-node:visible")).to_have_count(1)
        page.get_by_label("Capability status").select_option("all")
        page.get_by_role("button", name="Zoom in", exact=True).click()
        expect(page.get_by_role("button", name="Reset zoom")).to_have_text("110%")
        page.get_by_role("button", name="Reset zoom").click()
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(output / "agent-map.png"), full_page=False)
        page.goto("http://127.0.0.1:8000/")
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
        page.get_by_role("link", name="Sign in with Keycloak").click()
        page.locator("#username").fill(account["username"])
        page.locator("#password").fill(account["password"])
        page.locator("#kc-login").click()
        page.wait_for_url("http://127.0.0.1:8000/")
        expect(page.get_by_role("heading", name="Ready to investigate.")).to_be_visible()
        cookies = page.context.cookies("http://127.0.0.1:8000/")
        cookie = next(c for c in cookies if c["name"] == "aegisflow_session")
        assert cookie["httpOnly"] and cookie["sameSite"] == "Lax"
        assert "access_token" not in page.content() and account["password"] not in page.content()
        page.get_by_role("button", name="Investigate demo case").click()
        expect(page.get_by_role("heading", name="Investigation complete.")).to_be_visible()
        expect(page.locator("dl")).to_contain_text("25200")
        expect(page.locator("dl")).to_contain_text("True")
        sources = page.locator("details.evidence-item")
        expect(sources).to_have_count(5)
        sources.first.locator("summary").click()
        expect(sources.first.locator("pre")).to_contain_text("PO-001")
        sources.first.locator("summary").click()
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        case_id = page.locator("dd").nth(1).inner_text()
        for order, expected in (
            ("PO-002", "Monitor"),
            ("PO-003", "Collect Evidence"),
            ("PO-004", "Collect Evidence"),
            ("PO-005", "Escalate"),
        ):
            page.goto("http://127.0.0.1:8000/")
            page.get_by_label("Purchase order").select_option(order)
            page.get_by_role("button", name="Investigate demo case").click()
            expect(page.get_by_role("heading", name=expected, exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        old_cookie = cookie["value"]
        subprocess.run(
            [sys.executable, "tools/keycloak_demo.py", "revoke-sessions"],
            capture_output=True,
            check=True,
        )
        revoked = page.request.get("http://127.0.0.1:8000/v1/cases/" + case_id)
        assert revoked.status == 401
        page.goto("http://127.0.0.1:8000/")
        expect(page.get_by_role("heading", name="Investigate with evidence.")).to_be_visible()
        cutoff = json.loads(Path("work/keycloak-local/principals.json").read_text())["principals"][
            0
        ]["tokens_valid_after"]
        delay = cutoff + 1.1 - time.time()
        assert delay < 2, "Unexpected future cutoff in local browser test"
        time.sleep(max(0.0, delay))
        page.get_by_role("link", name="Sign in with Keycloak").click()
        expect(page.get_by_role("heading", name="Ready to investigate.")).to_be_visible()
        new_cookie = next(
            c
            for c in page.context.cookies("http://127.0.0.1:8000/")
            if c["name"] == "aegisflow_session"
        )
        assert new_cookie["value"] != old_cookie
        replay = page.request.get(
            "http://127.0.0.1:8000/v1/cases/" + case_id,
            headers={"Cookie": "aegisflow_session=" + old_cookie},
        )
        assert replay.status == 401

        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(page.get_by_role("heading", name="Application session ended.")).to_be_visible()
        page.get_by_role("link", name="Finish signing out of Keycloak").click()
        page.locator("#kc-logout").click()
        page.wait_for_url("http://127.0.0.1:8000/")
        expect(page.get_by_role("heading", name="Investigate with evidence.")).to_be_visible()
        assert not any(c["name"] == "aegisflow_session" for c in page.context.cookies())
        assert not errors
        browser.close()
    print(
        "PASS: real Keycloak login, investigation, desktop/mobile layout, session revocation/re-login and logout"
    )


if __name__ == "__main__":
    try:
        main()
    except (BrowserError, AssertionError, subprocess.CalledProcessError):
        # Browser diagnostics can include callback URLs or entered values.
        raise SystemExit(
            "FAIL: local browser flow; no credentials or callback diagnostics emitted"
        ) from None
