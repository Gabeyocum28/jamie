"""Self-check for the code room's Studio. Run inside Jamie's image (it needs Playwright's Chromium):
  docker run --rm -v "$PWD/environments/code:/t" jamie-base python3 /t/test_studio.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import studio  # noqa: E402

# Only the changed middle is typed out
assert studio.changed_part("", "abc") == (0, 0)
assert studio.changed_part("abcXYZdef", "abc123def") == (3, 3)
assert studio.changed_part("aaa", "aaaa") == (3, 0)  # prefix and suffix never overlap
assert studio.changed_part("hello", "hello") == (5, 0)
print("changed_part OK")


async def browser():
    from playwright.async_api import async_playwright
    app = tempfile.mkdtemp()
    with open(os.path.join(app, "index.html"), "w") as f:
        f.write("<h1>v1</h1>")
    server = subprocess.Popen([sys.executable, studio.__file__, "_serve", app])
    try:
        for _ in range(40):
            try:
                headers = urllib.request.urlopen(f"http://localhost:{studio.PORT}/").headers
                break
            except OSError:
                time.sleep(0.1)
        assert headers["Cache-Control"] == "no-store", headers
        assert "charset=utf-8" in headers["Content-Type"], headers
        print("serve OK: no-store")
        async with async_playwright() as p:
            page = await (await p.chromium.launch()).new_page()
            await page.goto(studio.PAGE)
            code = "\n".join(f"line {i}" for i in range(200))
            start = time.monotonic()
            await page.evaluate("t => studio.type('game/index.html', t)", code)
            await page.wait_for_function("!studio.state().typing", timeout=10_000)
            took = time.monotonic() - start
            shown = await page.eval_on_selector("#src", "e => e.innerText")
            assert shown.strip() == code.strip(), shown[-80:]
            assert 0.5 < took < 7, took  # typed out, not instant, never slow
            print(f"typing OK: {len(code)} chars in {took:.1f}s")
            edited = code.replace("line 100", "line one hundred")
            await page.evaluate("([t, p, s]) => studio.type('game/index.html', t, p, s)",
                                [edited, *studio.changed_part(code, edited)])
            await page.wait_for_function("!studio.state().typing", timeout=10_000)
            assert "line one hundred" in await page.eval_on_selector("#src", "e => e.innerText")
            print("edit OK: only the change typed")
            await page.evaluate("u => studio.preview(u)", f"http://localhost:{studio.PORT}/")
            frame = page.frame_locator("#frame")
            assert await frame.locator("h1").inner_text() == "v1"
            with open(os.path.join(app, "index.html"), "w") as f:
                f.write("<h1>v2</h1>")
            await page.evaluate("studio.reload()")
            await page.wait_for_timeout(800)
            assert await frame.locator("h1").inner_text() == "v2"
            print("preview + reload OK")
    finally:
        server.terminate()


asyncio.run(browser())
print("studio OK")
