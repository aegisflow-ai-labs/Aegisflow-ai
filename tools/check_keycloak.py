"""Real-browser local OIDC smoke test; never print credentials or tokens."""

import json
import os
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
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8000/")
        expect(page.get_by_role("heading", name="Investigate with evidence.")).to_be_visible()
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
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.get_by_role("link", name="Back to the pilot").click()
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
        "PASS: real Keycloak login, investigation, desktop/mobile layout, keyboard entry and logout"
    )


if __name__ == "__main__":
    try:
        main()
    except (BrowserError, AssertionError):
        # Browser diagnostics can include callback URLs or entered values.
        raise SystemExit(
            "FAIL: local browser flow; no credentials or callback diagnostics emitted"
        ) from None
