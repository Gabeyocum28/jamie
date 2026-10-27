"""Self-check for screen sharing: ./jamie.sh test"""
import asyncio
import tempfile

from playwright.async_api import async_playwright

import bot

FAKE_MEET = """<button aria-label="Share screen" onclick="
  navigator.mediaDevices.getDisplayMedia({video: true, audio: true}).then(s => {
    window.share = s;
    window.tracks = s.getTracks().map(t => t.kind + ':' + t.getSettings().displaySurface);
  })">share</button>"""


async def show_cli(url):
    # The way Claude runs it: a separate process attaching over CDP
    proc = await asyncio.create_subprocess_exec("python3", "/app/bot.py", "--show", url)
    assert await proc.wait() == 0


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            tempfile.mkdtemp(), headless=False, args=bot.CHROME_ARGS,
            ignore_default_args=["--enable-automation"])
        meet = ctx.pages[0]
        await meet.route("https://meet.google.com/**", lambda r: r.fulfill(body=FAKE_MEET, content_type="text/html"))
        await meet.goto("https://meet.google.com/abc-defg-hij")

        await show_cli("https://example.com")
        await meet.wait_for_function("window.tracks", timeout=10_000)
        tracks = await meet.evaluate("window.tracks")
        assert tracks == ["audio:undefined", "video:browser"], tracks  # a tab, not the screen, with audio

        await show_cli("off")
        await meet.wait_for_function("window.share.getVideoTracks()[0].readyState == 'ended'", timeout=5_000)
        assert ctx.pages == [meet], ctx.pages  # stage closed, Meet tab untouched
        print("show OK:", tracks)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
