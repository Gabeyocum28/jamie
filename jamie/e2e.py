"""End-to-end check in a real Google Meet: ./jamie.sh e2e

Jamie starts its own meeting and joins it alone. Its microphone plays a recorded request
("Hey Jamie, pull up a YouTube video about funny cats, with people talking in it, and share it"), so the
whole path runs for real: captions -> judge -> agent -> screen share. Passes when Jamie is
presenting. Needs Jamie's Google account (google-login) and an agent login; takes 1-3 minutes.
"""
import asyncio
import os
import re
import sys
import time
import wave

from playwright.async_api import async_playwright

import bot

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 420


def timeline(out, parts):
    """One recording from [(seconds of silence, wav file), ...]. Chromium loops it, so it ends in a long silence."""
    with wave.open(out, "wb") as w:
        for i, (pause, src) in enumerate(parts):
            with wave.open(src) as r:
                if not i:
                    w.setparams(r.getparams())
                gap = int(pause * r.getframerate()) * r.getsampwidth() * r.getnchannels()
                w.writeframes(b"\0" * gap + r.readframes(r.getnframes()))
        w.writeframes(b"\0" * (120 * 16000 * 2))


async def new_meeting():
    bot.clear_stale_lock()
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            bot.PROFILE, headless=False, args=bot.CHROME_ARGS, ignore_default_args=["--enable-automation"],
            permissions=["microphone", "camera"])
        page = ctx.pages[0]
        await page.goto("https://meet.google.com/new")
        await bot.click_first(page, [r"use microphone and camera"], 8000)
        try:
            await page.wait_for_url(re.compile(r"meet\.google\.com/(meet/)?[a-z]{3}-[a-z]{4}-[a-z]{3}"), timeout=30_000)
        except Exception:
            await page.screenshot(path="/workspace/e2e-failed.png")
            sys.exit(f"Couldn't start a meeting (landed on {page.url}, see workspace/<env>/e2e-failed.png). "
                     "Is Jamie signed in? ./jamie.sh google-login")
        url = "https://meet.google.com/" + page.url.split("?")[0].rstrip("/").split("/")[-1]
        await ctx.close()
        return url


async def presenting():
    """Whether Meet shows Jamie presenting the stage tab."""
    try:
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(bot.CDP)
            pages = b.contexts[0].pages
            meet = next(pg for pg in pages if "meet.google.com" in pg.url)
            stage = [pg for pg in pages if pg is not meet and await pg.title() == bot.STAGE_TITLE]
            labels = await meet.eval_on_selector_all("button[aria-label]", "bs => bs.map(b => b.getAttribute('aria-label'))")
            return bool(stage) and any(re.search(r"stop presenting|you are presenting", lb, re.I) for lb in labels), labels
    except Exception as e:
        return False, [str(e)]


def timing(lines):
    """How long each step took, from the bot's timestamped log."""
    def at(marker):
        for line in lines:
            if marker in line and re.match(r"\d\d:\d\d:\d\d", line):
                h, m, sec = map(int, line[:8].split(":"))
                return h * 3600 + m * 60 + sec
    marks = [("opening Meet", "Opening https"), ("clicked join", "Clicked '"), ("heard", "heard You:"), ("judged", "judge: {"), ("done", " -> ")]  # first request
    times = [(name, at(m)) for name, m in marks]
    for (a, ta), (b, tb) in zip(times, times[1:]):
        if ta is not None and tb is not None:
            print(f"e2e: {tb - ta:3d}s  {a} -> {b}")


async def stage_eval(js):
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(bot.CDP)
        stage = [pg for pg in b.contexts[0].pages if await pg.title() == bot.STAGE_TITLE]
        return bool(stage) and await stage[0].evaluate(js)


async def video_controls():
    """The one-step --video commands, timed, checked against the shared tab."""
    results = {}
    for action, check in [("fullscreen", "!!document.fullscreenElement"), ("pause", "document.querySelector('video').paused"),
                          ("play", "!document.querySelector('video').paused"), ("exit-fullscreen", "!document.fullscreenElement")]:
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec("python3", os.path.join(HERE, "bot.py"), "--video", action,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out = (await proc.communicate())[0].decode().strip().splitlines()[-1:]
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(bot.CDP)
            stage = [pg for pg in b.contexts[0].pages if await pg.title() == bot.STAGE_TITLE]
            ok = bool(stage) and await stage[0].evaluate(check)
        results[action] = ok
        print(f"e2e: {'ok ' if ok else 'NO '} --video {action} in {time.monotonic() - start:.1f}s: {out}", flush=True)
    return all(results.values())


async def sent_video():
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(bot.CDP)
        meet = next(pg for pg in b.contexts[0].pages if "meet.google.com" in pg.url)
        return await meet.evaluate(bot.SENT_VIDEO_JS)


async def main():
    audio = "/tmp/jamie-test-request.wav"
    # The request, then a follow-up while the video is being shared (hearing once stopped during shares)
    timeline(audio, [(25, os.path.join(HERE, "test-request.wav")), (35, os.path.join(HERE, "test-followup.wav")),
                     (30, os.path.join(HERE, "test-ide.wav")), (25, os.path.join(HERE, "test-question.wav")),
                     (20, os.path.join(HERE, "test-decision.wav")), (6, os.path.join(HERE, "test-notes.wav")),
                     (30, os.path.join(HERE, "test-leave.wav"))])
    url = await new_meeting()
    print("e2e: meeting", url, flush=True)
    proc = await asyncio.create_subprocess_exec(
        "python3", os.path.join(HERE, "bot.py"), url, env={**os.environ, "JAMIE_TEST_AUDIO": audio},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    seen, start, ok, labels, stayed, controls, followup, auto_fullscreen, editor = [], time.monotonic(), False, [], False, False, False, False, False
    notes_page, left = "", False

    async def pump():
        async for line in proc.stdout:
            line = line.decode(errors="replace").rstrip()
            seen.append(line)
            print("  bot |", line, flush=True)

    reader = asyncio.create_task(pump())
    try:
        answers = lambda: sum(" -> " in s for s in seen)  # noqa: E731
        while time.monotonic() - start < TIMEOUT and proc.returncode is None and not answers():
            await asyncio.sleep(2)
        ok, labels = await presenting()
        await asyncio.sleep(3)
        auto_fullscreen = await stage_eval("!!document.fullscreenElement")  # --play goes fullscreen by itself
        # The follow-up ("pause the video") is spoken while sharing: hearing once stopped then
        shared_at = time.monotonic()
        instant = lambda: any("control: pause" in s for s in seen)  # noqa: E731
        while time.monotonic() - shared_at < 90 and proc.returncode is None and answers() < 2 and not instant():
            await asyncio.sleep(2)
        followup = await stage_eval("document.querySelector('video').paused")
        print("e2e: video Meet is sending:", await sent_video(), flush=True)
        controls = await video_controls()
        stayed = proc.returncode is None and (await presenting())[0]
        # Third request: "open the code editor", an instant control that puts VS Code on screen
        asked = time.monotonic()
        while time.monotonic() - asked < 90 and proc.returncode is None and not any("control: ide" in s for s in seen):
            await asyncio.sleep(2)
        editor = await stage_eval("!!document.querySelector('.monaco-workbench')")
        # Fourth: a question only the agent can answer, said back out loud
        asked = time.monotonic()
        while time.monotonic() - asked < 120 and proc.returncode is None and not any("Canberra" in s and "heard myself" in s for s in seen):
            await asyncio.sleep(2)
        # Then a decision is made out loud, "show the meeting notes", and "you can leave now"
        asked = time.monotonic()
        while time.monotonic() - asked < 120 and proc.returncode is None and not any("control: notes" in s for s in seen):
            await asyncio.sleep(2)
        notes_page = await stage_eval("document.body.innerText")
        while time.monotonic() - asked < 200 and proc.returncode is None:  # leaving ends the bot
            await asyncio.sleep(2)
        left = proc.returncode is not None
    finally:
        if proc.returncode is None:  # (it has left on its own if the leave step worked)
            proc.terminate()
        await proc.wait()
        reader.cancel()

    steps = {
        "joined": ["In the call."],
        "heard the request": ["heard You:"],
        "judge acted on it (instant control or agent)": ["'action': 'control'", "'action': 'request'"],
        "it got done": [" -> "],
    }
    for name, markers in steps.items():
        print(f"e2e: {'ok ' if any(m in s for s in seen for m in markers) else 'NO '} {name}")
    print(f"e2e: {'ok ' if ok else 'NO '} presenting the stage tab")
    heard = sum("heard You:" in s for s in seen)
    print(f"e2e: {'ok ' if heard >= 2 else 'NO '} heard the follow-up while sharing")
    print(f"e2e: {'ok ' if auto_fullscreen else 'NO '} the video went fullscreen without being asked")
    print(f"e2e: {'ok ' if followup else 'NO '} the follow-up paused the video")
    print(f"e2e: {'ok ' if any('control: pause' in s for s in seen) else 'NO '} ...instantly, without the agent")
    print(f"e2e: {'ok ' if editor else 'NO '} \"open the code editor\" put VS Code on screen")
    spoke = [s.split("heard myself:", 1)[1].strip() for s in seen if "heard myself:" in s]
    print(f"e2e: {'ok ' if spoke else 'NO '} Jamie's voice reached the call (Meet captioned it: {spoke[:2]})")
    answered = any("Canberra" in s for s in spoke)
    print(f"e2e: {'ok ' if answered else 'NO '} the agent answered a question out loud (Canberra)")
    shown = "fun room" in (notes_page or "").lower()
    print(f"e2e: {'ok ' if shown else 'NO '} the live notes on screen caught the decision (fun room)")
    posted = [s for s in seen if "Posted the meeting notes:" in s]
    print(f"e2e: {'ok ' if posted and left else 'NO '} \"you can leave\": posted the notes to chat and left {posted[:1]}")
    stayed = stayed and bool(spoke) and answered and shown and bool(posted) and left
    stayed = stayed and editor
    stayed = stayed and followup and auto_fullscreen
    print(f"e2e: {'ok ' if stayed else 'NO '} still in the call and presenting 20s later")
    chat_ok = not any("Couldn't post to chat" in s for s in seen)
    print(f"e2e: {'ok ' if chat_ok else 'NO '} every chat message posted")
    stayed = stayed and chat_ok and controls
    timing(seen)
    if not (ok and stayed):
        print("e2e: Meet buttons at the end:", [lb for lb in labels if re.search("present|share", lb, re.I)])
        sys.exit(1)
    print("e2e OK")


if __name__ == "__main__":
    asyncio.run(main())
