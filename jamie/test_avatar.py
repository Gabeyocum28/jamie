"""Self-check for the camera avatar: ./jamie.sh test"""
import asyncio
import os
import tempfile

from playwright.async_api import async_playwright

import bot

# Like Meet: ask for camera + mic, show the camera in a <video>
FAKE_MEET = """<video autoplay muted playsinline width=1280 height=720></video><script>
navigator.mediaDevices.getUserMedia({video: true, audio: true}).then(s => {
  window.tracks = s.getTracks().map(t => t.kind);
  document.querySelector('video').srcObject = s;
});
window.frame = () => { const c = document.createElement('canvas'); c.width = 64; c.height = 48;
  c.getContext('2d').drawImage(document.querySelector('video'), 0, 0, 64, 48);
  return c.toDataURL(); };
</script>"""


async def main():
    out = os.environ.get("AVATAR_SHOTS")  # set to a folder to save what the avatar looks like
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            tempfile.mkdtemp(), headless=False, args=bot.CHROME_ARGS, ignore_default_args=["--enable-automation"],
            permissions=["microphone", "camera"])
        os.environ["JAMIE_LOOK"] = '{"eyes": "heart", "mouth": "grin", "color": "sunset", "accessory": "crown"}'
        await ctx.add_init_script(bot.avatar_script())
        meet = ctx.pages[0]
        await meet.route("https://meet.google.com/**", lambda r: r.fulfill(body=FAKE_MEET, content_type="text/html"))
        await meet.goto("https://meet.google.com/abc-defg-hij")
        await meet.wait_for_function("window.tracks && document.querySelector('video').videoWidth > 0", timeout=10_000)
        size = await meet.evaluate("[document.querySelector('video').videoWidth, document.querySelector('video').videoHeight]")
        assert size == [1280, 720], size  # a Meet tile's shape, sharp
        tracks = await meet.evaluate("window.tracks")
        assert sorted(tracks) == ["audio", "video"], tracks  # avatar video, real (fake-device) mic

        async def frames():
            shots = []
            for _ in range(3):
                shots.append(await meet.evaluate("window.frame()"))
                await meet.wait_for_timeout(400)
            return shots

        assert len(set(await frames())) > 1, "avatar isn't animating"
        other = await ctx.new_page()  # like the shared stage tab: Meet goes to the background
        await other.goto("about:blank")
        await other.bring_to_front()
        assert len(set(await frames())) > 1, "avatar froze in the background"
        await meet.bring_to_front()

        for state in ("listening", "thinking", "talking"):
            await bot.avatar(meet, state)
            await meet.wait_for_timeout(600)
            assert await meet.evaluate("window.__jamieAvatar.state") == state
            assert await meet.evaluate("window.__jamieAvatar.look.eyes") == "heart"  # the look got through
            if out:
                await meet.locator("video").screenshot(path=f"{out}/avatar-{state}.png")
        print("avatar OK")
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
