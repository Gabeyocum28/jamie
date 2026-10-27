"""Self-check for screen sharing: ./jamie.sh test"""
import asyncio
import tempfile

from playwright.async_api import async_playwright

import bot

FAKE_MEET = """<button aria-label="Share screen" onclick="
  navigator.mediaDevices.getDisplayMedia({video: true, audio: true}).then(s => {
    window.share = s;
    window.tracks = s.getTracks().map(t => t.kind + ':' + t.getSettings().displaySurface);
    document.body.insertAdjacentHTML('beforeend', `<button aria-label='Stop presenting'>stop</button>`);
  })">share</button>
<button aria-label="Chat with everyone" onclick="const p = document.getElementById('chat'); p.hidden = !p.hidden">chat</button>
<div id="chat" hidden><textarea aria-label="Send a message" onkeydown="
  if (event.key === 'Enter') { event.preventDefault(); (window.sent ||= []).push(this.value); this.value = ''; }"></textarea></div>"""


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

        # Chat still works when Meet has closed the chat panel and another tab is in front
        front = await ctx.new_page()
        await front.bring_to_front()
        await bot.send(meet, "hello")
        await bot.send(meet, "again")  # panel open now: must not toggle it shut
        assert await meet.evaluate("window.sent") == ["hello", "again"], await meet.evaluate("window.sent")
        await front.close()

        # The agent's browser tools navigating the Meet tab must not take Jamie out of the call
        await bot.pin_meet_tab(meet)
        async with async_playwright() as p2:
            agent = await p2.chromium.connect_over_cdp(bot.CDP)
            tab = next(pg for pg in agent.contexts[0].pages if "meet.google.com" in pg.url)
            try:
                await tab.goto("https://example.com", timeout=5_000)
            except Exception:
                pass  # the cancelled navigation errors for whoever asked; that's fine
        await meet.wait_for_timeout(3000)
        assert "meet.google.com" in meet.url, meet.url
        assert await meet.get_by_role("button", name="Share screen").count()  # still the same page
        assert any("example.com" in pg.url for pg in ctx.pages), [pg.url for pg in ctx.pages]
        # The agent's browser tools connect through cdp_filter: the Meet tab must be invisible to them
        server = await bot.cdp_filter.serve(bot.CDP, 9223)
        async with async_playwright() as p3:
            agent = await p3.chromium.connect_over_cdp(bot.AGENT_CDP)
            seen = [pg.url for c in agent.contexts for pg in c.pages]
            assert not any("meet.google.com" in u for u in seen), seen
            mine = await agent.contexts[0].new_page()
            await mine.goto("https://example.com")
            assert "Example Domain" in await mine.title()
            await mine.close()
        server.close()
        assert await meet.get_by_role("button", name="Share screen").count()  # Meet untouched
        print("show OK:", tracks)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
