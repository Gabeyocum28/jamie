"""Popup test: loads the unpacked extension in Chromium with a mocked controller.

  python3 extension/test_popup.py      (needs Python Playwright: pip install playwright && playwright install chromium)

Screenshots go to extension/screenshots/ (git-ignored), for eyeballing the design.
"""
import hashlib
import json
import os
import sys
import tempfile

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    print("SKIP: Python Playwright is not installed")
    sys.exit(0)

EXT = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(EXT, "screenshots")
# Chrome's id for an unpacked extension: sha256 of its path, first 32 hex digits mapped 0-f -> a-p
EXT_ID = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(EXT.encode()).hexdigest()[:32])
TOKEN = "test-token-1234567890"
OPTIONS = {"environments": ["default", "fun", "math", "study", "work"],
           "personalities": ["chill", "concise", "default", "hype", "pirate", "tutor"],
           "agents": ["claude", "codex", "gemini"]}
MEET = "https://meet.google.com/abc-defg-hij"


def jamie(id, code, env, personality, agent):
    return {"id": id, "state": "running", "meet_url": f"https://meet.google.com/{code}", "env": env,
            "personality": personality, "agent": agent, "google": "main",
            "screen": "http://localhost:32768/vnc.html",
            "apps": {"3000": "http://localhost:32769", "5173": "http://localhost:32770", "8000": "http://localhost:32771"}}


def main():
    os.makedirs(SHOTS, exist_ok=True)
    running = [jamie("jamie-fun-a1b2c3", "abc-defg-hij", "fun", "hype", "claude"),
               jamie("jamie-math-d4e5f6", "xyz-wxyz-xyz", "math", "tutor", "codex")]
    posts, deletes, fail = [], [], {"post": None}

    def controller(route):
        req = route.request
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, DELETE",
                "Access-Control-Allow-Headers": "Authorization, Content-Type"}
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        reply = lambda code, body: route.fulfill(status=code, headers=cors, content_type="application/json", body=json.dumps(body))
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return reply(401, {"error": "bad or missing token"})
        path = req.url.split("7070", 1)[1].rstrip("/")
        if req.method == "GET" and path == "/options":
            return reply(200, OPTIONS)
        if req.method == "GET" and path == "/jamies":
            return reply(200, running)
        if req.method == "POST" and path == "/jamies":
            body = json.loads(req.post_data)
            posts.append(body)
            if fail["post"]:
                return reply(404, {"error": fail["post"]})
            return reply(201, jamie("jamie-new-000000", body["meet_url"].split("/")[-1], body["env"], body["personality"], body["agent"]))
        if req.method == "DELETE" and path.startswith("/jamies/"):
            deletes.append(path.split("/")[-1])
            running[:] = [j for j in running if j["id"] != deletes[-1]]
            return reply(200, {"stopped": deletes[-1]})
        reply(404, {"error": "not found"})

    with sync_playwright() as p, tempfile.TemporaryDirectory() as profile:
        # Playwright's Chromium if installed, else Google Chrome (which needs the feature flag to allow --load-extension)
        channel = None if os.path.exists(p.chromium.executable_path) else "chrome"
        ctx = p.chromium.launch_persistent_context(
            profile, channel=channel, headless=False, viewport={"width": 360, "height": 600},
            args=["--headless=new", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
                  "--disable-features=DisableLoadExtensionCommandLineSwitch"])
        ctx.route("http://localhost:7070/**", controller)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        url = f"chrome-extension://{EXT_ID}/popup.html"
        page.goto(url)

        # Not connected yet: dropdowns disabled, Settings open
        assert page.locator("#env").is_disabled() and "Connect in Settings first" in page.locator("#env").inner_text()
        assert page.locator("#settings").get_attribute("open") is not None
        assert page.locator("#voice").is_checked(), "voice is on by default"
        page.screenshot(path=f"{SHOTS}/1-not-connected.png", full_page=True)

        # Save the token -> dropdowns fill with pretty labels, values unchanged
        page.fill("#token", TOKEN)
        page.click("#save")
        page.wait_for_selector("#env:not([disabled])")
        assert page.locator("#env option").all_inner_texts() == ["Default", "Fun", "Math", "Study", "Work"]
        assert page.locator("#env option").first.get_attribute("value") == "default"
        assert page.locator("#conn").inner_text() == "Connected"
        page.wait_for_selector("#jamies li .links")
        assert page.locator("#jamies li").count() == 2
        first = page.locator("#jamies li").first
        assert first.locator("a.watch").get_attribute("href") == running[0]["screen"]
        assert first.locator(".links a").all_inner_texts()[1:] == [":3000", ":5173", ":8000"]
        assert "Fun · Hype · Claude" in first.inner_text()

        # Pick choices, the meeting we're in, voice off, and a look
        page.fill("#meet", MEET)
        page.select_option("#env", "math")
        page.select_option("#personality", "pirate")
        page.select_option("#agent", "codex")
        page.click("#settings summary")  # close settings
        page.click(".switch")
        assert not page.locator("#voice").is_checked()
        page.click("#lookbox summary")
        assert page.locator("#look-accessory option", has_text="Party hat").count() == 1
        before = page.locator("#preview").screenshot()
        page.select_option("#look-color", "sunset")
        page.select_option("#look-accessory", "party-hat")
        page.wait_for_timeout(200)
        assert page.locator("#preview").screenshot() != before, "preview changed with the look"
        page.wait_for_timeout(600)
        page.screenshot(path=f"{SHOTS}/3-look-open.png", full_page=True)

        # Reload: voice off and choices are remembered
        page.reload()
        page.wait_for_selector("#env:not([disabled])")
        assert not page.locator("#voice").is_checked(), "voice off persists across reload"
        assert page.locator("#look-accessory").input_value() == "party-hat"

        # Send with voice off, then on
        page.fill("#meet", MEET)
        page.select_option("#env", "math")
        page.select_option("#personality", "pirate")
        page.select_option("#agent", "codex")
        page.click("#start")
        expect(page.locator("#status")).to_contain_text("is joining")
        assert posts[-1] == {"meet_url": MEET, "env": "math", "personality": "pirate", "agent": "codex",
                             "look": {"eyes": "disc", "mouth": "smile", "color": "sunset", "motion": "float",
                                      "accessory": "party-hat"}, "voice": False}, posts[-1]
        page.click(".switch")
        page.click("#start")
        expect(page.locator("#start")).to_be_enabled()
        assert posts[-1]["voice"] is True and len(posts) == 2
        page.reload()
        page.wait_for_selector("#env:not([disabled])")
        assert page.locator("#voice").is_checked(), "voice on persists across reload"
        assert page.locator("#env").input_value() == "math", "last choices remembered after sending"

        # The current meeting is highlighted (the meet field is filled before the list renders)
        page.fill("#meet", MEET)
        page.click("#settings summary")
        page.click("#save")
        page.wait_for_selector("#jamies li.here")
        page.click("#settings summary")
        page.wait_for_timeout(300)
        page.screenshot(path=f"{SHOTS}/2-connected-running.png", full_page=True)
        assert page.locator("#jamies li.here").count() == 1

        # Stop sends DELETE and the list updates
        page.locator("#jamies li", has_text="Math · Tutor · Codex").locator("button").click()
        expect(page.locator("#jamies li .links")).to_have_count(1)
        assert deletes == ["jamie-math-d4e5f6"]

        # A controller error shows in the status line
        fail["post"] = "No free Google account. Sign one in: ./jamie.sh google-login <name>"
        page.click("#start")
        page.wait_for_selector("#status.err")
        assert "No free Google account" in page.locator("#status").inner_text()
        page.screenshot(path=f"{SHOTS}/4-error.png", full_page=True)

        assert not errors, errors
        ctx.close()
    print(f"OK: popup test passed ({len(posts)} POSTs, {len(deletes)} DELETE). Screenshots in {SHOTS}")


if __name__ == "__main__":
    main()
