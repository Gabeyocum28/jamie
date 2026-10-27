#!/usr/bin/env python3
"""
Jamie MVP: joins a Google Meet, watches the chat for `/jamie <prompt>`, runs an agent CLI
(Claude Code, Codex or Gemini) headless in /workspace, and posts the reply back to chat.
Runs inside an environment's container; ./jamie.sh on the host builds and starts it.

  python3 bot.py <meet-url> [--personality NAME] [--agent claude|codex|gemini]   # join and listen
  JAMIE_DEBUG=1 python3 bot.py ...  # also dump the Meet DOM to /workspace/meet-dump.html
"""
import argparse
import asyncio
import base64
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time

from difflib import SequenceMatcher
from urllib.parse import urlencode, urlsplit

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

import cdp_filter
import hearing
import notes
import voice

PROFILE = os.environ.get("JAMIE_PROFILE", "/data/chrome-profile")
WORKSPACE = os.environ.get("JAMIE_WORKSPACE", "/workspace")        # workspace/<env> on the host
ENVIRONMENT = os.environ.get("JAMIE_ENVIRONMENT", "/environment")  # environments/<env>, read-only
PERSONALITIES = os.environ.get("JAMIE_PERSONALITIES", "/personalities")
TRIGGER = os.environ.get("JAMIE_TRIGGER", "/jamie")
NAME = os.environ.get("JAMIE_NAME", "Jamie")
PERMS = os.environ.get("JAMIE_PERMISSIONS", "full")  # full | safe
TIMEOUT = int(os.environ.get("JAMIE_TIMEOUT", "900"))
DEBUG = os.environ.get("JAMIE_DEBUG") == "1"
CHUNK = 450        # Meet chat messages get cut off if too long
MAX_CHUNKS = 8

def core_prompt(cwd):
    # Shared by every environment and personality: how Jamie works in a call.
    return (
        f"You are {NAME}, an AI agent sitting in a Google Meet call. People talk to you out loud or in "
        "the meeting chat. Spoken requests reach you through live captions, which can mishear words: "
        "read them generously. The meeting transcript so far is in transcript.md; use it for context, "
        f"notes and summaries. Your working directory is {cwd}; build and run things there. If you start "
        "a web server, bind 0.0.0.0 on port 3000, 5173 or 8000 and run it in the background (nohup ... &) "
        "so the user can open http://localhost:<port>. Reply in plain text, no markdown, as short as "
        "possible (under 1200 characters): say what you did and where to find it.\n"
        "You control your own Chromium with the browser tools. One tab is the Meet call: never navigate, "
        "close or click in it (it's hidden from your browser tools). Open your own tabs to browse. Don't use "
        "Google Search or Google Images in the browser: they show captchas to automated browsers; use DuckDuckGo, "
        "Wikipedia or Wikimedia Commons. To put something on screen for the call, run "
        "`python3 /app/bot.py --show <url>`: it opens the url in a 'stage' tab and screen-shares it with "
        "sound (run it again to switch, `--show off` to stop). For YouTube, `python3 /app/bot.py --play "
        "'<what to search>'` finds the top video, shares it and makes it fullscreen in one step; ads are "
        "skipped automatically while it plays. Both only return once Meet "
        "confirms the share, so don't check it again afterwards. To control the video being shared, run "
        "`python3 /app/bot.py --video play|pause|fullscreen|exit-fullscreen|skip-ad|mute|unmute`: one step, "
        "much faster than clicking through the page. People are waiting in a live call: use "
        "as few steps as possible and reply as soon as it's done. Then select the stage tab with the browser "
        "tools and do whatever people ask there: play/pause, fullscreen, skip ads, scroll, click, search the "
        "site. Find links yourself with your web search tool, the browser, or the site's own search; never "
        "ask people for a URL. "
        "Whenever people ask you to build or code something (an app, a page, a script, a game; 'vibe coding'), "
        "build it live in front of them: first run `python3 /app/bot.py --ide` to put VS Code on screen (it shows "
        "your working directory), write the code, and open each main file as you write it with `python3 /app/bot.py "
        "--ide <file>` so they watch it appear; then run it and --show the result. If they ask about something on the shared screen ('that video', 'this link'), "
        "click it in the stage tab rather than searching again. "
        "Your working directory is wiped when you leave the call: save anything worth keeping (code people "
        "built, documents, exports) to /files/ (kept for this room; meeting notes are saved there automatically). "
        "You can teach yourself shortcuts. When you've done something people will likely ask for again and it "
        "comes down to key presses in the shared tab or one command, save it as an instant control so next time "
        "it happens in a second without you: `python3 /app/bot.py --learn <name> --description '<what people "
        "would say>' --keys <Key> [<Key>...]` or `--run '<command>'` (no shell: no pipes or &&; `{arg}` as a "
        "word of its own becomes what they asked for; put any script it needs in /learned/, which is kept "
        "for this room, unlike your working directory). Also do this "
        "whenever someone asks you to learn or remember a shortcut. "
        "Don't tell people you can't do something on the computer or in the browser: try, and if one way "
        "fails, try another."
    )

CDP = "http://localhost:9222"  # container-only; lets Claude's browser tools and --show drive Jamie's Chromium
STAGE_TITLE = "Jamie Stage"  # the tab Jamie screen-shares; matched by the flag below

TRIGGER_RE = re.compile(rf"(?:^|\n)\s*{re.escape(TRIGGER)}\b[ \t]*(.*)", re.S | re.I)

CHROME_ARGS = [
    "--use-fake-device-for-media-stream",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1280,800",
    f"--auto-select-tab-capture-source-by-title={STAGE_TITLE}",  # share the stage tab, with its audio
    "--autoplay-policy=no-user-gesture-required",                # videos start without a click
    "--remote-debugging-port=9222",
]
# End-to-end test (e2e.py): Jamie's microphone plays this recording, and Jamie listens to itself
TEST_AUDIO = os.environ.get("JAMIE_TEST_AUDIO")
VOICE = os.environ.get("JAMIE_VOICE", "on") != "off"  # speak replies into the call (voice.py)
if TEST_AUDIO:
    CHROME_ARGS.append(f"--use-file-for-fake-audio-capture={TEST_AUDIO}")

# Meet tags each chat message with data-message-id. If Google changes this, run with
# JAMIE_DEBUG=1, open meet-dump.html, and update this selector.
READ_JS = """() => Array.from(document.querySelectorAll('[data-message-id]'))
  .map(n => ({ id: n.getAttribute('data-message-id'), text: n.innerText || '' }))"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def clear_stale_lock():
    # Chromium's profile lock names the container hostname, which changes on every rebuild.
    if subprocess.run(["pgrep", "-x", "chrome"], capture_output=True).returncode == 0:
        sys.exit("Chromium is already running. Close it first.")
    for f in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.remove(os.path.join(PROFILE, f))
        except FileNotFoundError:
            pass


# ---------- login ----------

async def login():
    async with async_playwright() as p:
        exe = p.chromium.executable_path
    os.makedirs(PROFILE, exist_ok=True)
    clear_stale_lock()
    log("Opening Chromium. Go to http://localhost:6080/vnc.html, sign in to the bot's Google account,")
    log("then CLOSE the browser window. The session is saved to", PROFILE)
    # Launched without Playwright attached, so Google's sign-in page doesn't flag it as automated.
    subprocess.run(
        # --password-store=basic matches what Playwright uses, so the saved cookies decrypt in the bot
        [exe, f"--user-data-dir={PROFILE}", "--no-sandbox", "--no-first-run", "--password-store=basic",
         "--no-default-browser-check", "https://accounts.google.com"],
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":99")},
        stderr=subprocess.DEVNULL,  # harmless dbus/GPU noise in Docker
    )
    log("Browser closed. Login saved.")


# ---------- Meet helpers ----------

async def click_first(page, patterns, timeout=3000):
    for pat in patterns:
        loc = page.get_by_role("button", name=re.compile(pat, re.I)).first
        try:
            await loc.click(timeout=timeout)
            return pat
        except PWTimeout:
            continue
    return None


async def in_call(page):  # True, False, or None when the page didn't answer (frozen: not proof of leaving)
    """Meet's Leave button is on the page. A plain DOM check on purpose: get_by_role skips elements
    that a dialog hides from screen readers, which once made a share dialog look like the call ending."""
    try:
        return await asyncio.wait_for(
            page.evaluate("""() => !!document.querySelector('button[aria-label*="leave call" i]')"""), 5)
    except Exception:
        return None


def leave_button(page):
    return page.get_by_role("button", name=re.compile("leave call", re.I))


async def join(page, url):
    log("Opening", url)
    await page.goto(url, wait_until="domcontentloaded")
    # No fixed waits: act the moment Meet's controls exist, and only click popups that are there
    join_btn = page.get_by_role("button", name=re.compile(r"join now|ask to join|join here too|switch here", re.I)).first
    try:
        await join_btn.wait_for(timeout=30_000)
    except PWTimeout:
        raise RuntimeError("Couldn't find a join button. Watch it in noVNC to see what Meet is showing.")
    for pat in (r"^got it$", r"^dismiss$", r"use microphone and camera"):
        popup = page.get_by_role("button", name=re.compile(pat, re.I)).first
        if await popup.count():
            await popup.click()

    name_box = page.get_by_role("textbox", name=re.compile("your name", re.I))
    if await name_box.count():  # not signed in: join as guest
        log("Not signed in, joining as guest named", NAME)
        await name_box.first.fill(NAME)

    if not TEST_AUDIO and not VOICE:  # with a voice, the mic is avatar.js's channel: silent unless Jamie talks
        # Wait for this one: the fake microphone beeps. The camera stays on: it shows the avatar.
        mic = page.get_by_role("button", name=re.compile("turn off microphone", re.I)).first
        await mic.wait_for(timeout=10_000)
        await mic.click()

    clicked = (await join_btn.get_attribute("aria-label")) or (await join_btn.inner_text()).strip()
    await join_btn.click()
    log(f"Clicked '{clicked}'. Waiting to be admitted (up to 10 min)...")
    # "Leave call" also shows in the waiting room; "Share screen" only once admitted
    await page.get_by_role("button", name=re.compile("share screen", re.I)).first.wait_for(timeout=600_000)
    log("In the call.")


async def pin_meet_tab(page):
    """Keep the Meet tab in the call. The agent's browser tools start on this tab and sometimes
    navigate it ("pull up YouTube"), which leaves the call. Such navigations are cancelled and the
    page opens in a new tab instead."""
    cdp = await page.context.new_cdp_session(page)
    main = (await cdp.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]

    async def paused(e):
        url = e["request"]["url"]
        if e.get("frameId") == main and urlsplit(url).hostname != "meet.google.com":
            log("Kept the Meet tab in the call; opening in a new tab instead:", url)
            # "Aborted", not a network error: a failed navigation would replace Meet with an error page
            await cdp.send("Fetch.failRequest", {"requestId": e["requestId"], "errorReason": "Aborted"})
            await (await page.context.new_page()).goto(url)
        else:
            await cdp.send("Fetch.continueRequest", {"requestId": e["requestId"]})

    cdp.on("Fetch.requestPaused", lambda e: background(paused(e)))
    # Only whole-page loads pause here; Meet's own traffic isn't touched
    await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document", "requestStage": "Request"}]})


async def chat_box(page):
    box = page.get_by_role("textbox", name=re.compile("send a message", re.I), include_hidden=True).first
    if await box.count() and await box.is_visible():
        return box
    # Meet closes the chat panel on its own (e.g. once a presentation takes over the layout). JS click:
    # a mouse click doesn't land reliably while the shared tab is in front.
    await page.evaluate("""() => {
        const box = document.querySelector('textarea[aria-label*="send a message" i]');
        if (box && box.offsetParent) return;  // already open: the button toggles, don't close it
        document.querySelector('button[aria-label*="chat with everyone" i], button[aria-label*="open chat" i]')?.click();
    }""")
    await box.wait_for(timeout=10_000)
    return box


async def send(page, text):
    """Post to the meeting chat. A failure is logged, never raised: losing a message beats leaving the call."""
    try:
        await post(page, text)
    except Exception as e:
        log("Couldn't post to chat:", str(e).splitlines()[0], "| message was:", (text or "")[:200])


async def post(page, text):
    # Never echo the trigger, or Jamie would answer itself.
    # (a zero-width space breaks it whatever it looks like: the chat reader must not see it)
    text = re.sub(re.escape(TRIGGER), TRIGGER[:1] + "\u200b" + TRIGGER[1:], text or "", flags=re.I).strip() or "(no output)"
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    if len(chunks) > MAX_CHUNKS:
        chunks = chunks[:MAX_CHUNKS]
        chunks[-1] += " ...(truncated, full output in the terminal)"
    for c in chunks:
        box = await chat_box(page)
        await box.fill(c)
        await box.press("Enter")
        await page.wait_for_timeout(500)
        if await box.input_value():  # Enter can get lost while another tab is in front: use the button
            await page.get_by_role("button", name=re.compile("send", re.I)).first.evaluate("b => b.click()")


# Sites rename their tab (YouTube does, after loading). Chromium picks the tab to share by its
# title, so the stage keeps its title no matter what the site does.
LOCK_TITLE_JS = """(() => {
  const T = %s;
  Object.defineProperty(Document.prototype, "title", { get: () => T, set: () => {}, configurable: true });
  const pin = () => {
    let t = document.querySelector("title");
    if (!t && document.head) document.head.append(t = document.createElement("title"));
    if (t && t.textContent !== T) t.textContent = T;
  };
  new MutationObserver(pin).observe(document, { subtree: true, childList: true, characterData: true });
  document.addEventListener("DOMContentLoaded", pin);
})();""" % json.dumps(STAGE_TITLE)


async def show(page, url):
    """Screen-share url from a separate stage tab and return the tab. 'off' just stops sharing."""
    old = [p for p in page.context.pages if p is not page and await p.title() == STAGE_TITLE]
    for p in old:  # only shared tabs: the agent may be working in its own
        await p.close()  # closing the shared tab ends the presentation
    if url.lower() == "off":
        await avatar_fps(page, 24)
        return None
    if old:
        await page.wait_for_timeout(1500)  # let Meet register the old share ending
    stage = await page.context.new_page()
    await stage.add_init_script(LOCK_TITLE_JS)
    await stage.goto(url, wait_until="domcontentloaded")
    await youtube_hd(stage)
    for _ in range(20):
        if await stage.title() == STAGE_TITLE:
            break
        await stage.wait_for_timeout(250)
    else:
        raise RuntimeError(f"The page wouldn't keep the title {STAGE_TITLE!r}, so it can't be shared")
    # include_hidden: a Meet dialog can hide the rest of the page from screen readers (and get_by_role)
    share = page.get_by_role("button", name=re.compile("share screen|present now", re.I), include_hidden=True).first
    # JS click: a Playwright mouse click hangs while the capture picker opens
    await share.evaluate("b => b.click()")
    await stage.bring_to_front()  # so it's what you see in noVNC too
    # Only report success once Meet says so, so the agent never tells people it's sharing when it isn't
    try:
        await page.get_by_role("button", name=re.compile("stop presenting|you are presenting", re.I),
                                include_hidden=True).first.wait_for(state="attached", timeout=15_000)
    except PWTimeout:
        await stage.close()
        raise RuntimeError("Meet didn't start presenting. Try --show again.")
    await avatar_fps(page, 4)  # its tile is tiny during a presentation; the CPU goes to the shared video
    dialogs = await page.evaluate("""() => [...document.querySelectorAll('[role=dialog], [role=alertdialog]')]
        .filter(d => d.offsetParent).map(d => d.innerText.trim().slice(0, 200))""")
    if any(dialogs):
        log("Meet showed a dialog after sharing:", dialogs)
    return stage


async def youtube_hd(stage):
    if "youtube.com/watch" in stage.url:  # YouTube starts at 360p and ramps up slowly
        try:
            await stage.locator("#movie_player").wait_for(timeout=15_000)
            # 720p: the share is 1280x800 anyway, and decoding 1080p in software starves the capture
            await stage.evaluate("document.getElementById('movie_player').setPlaybackQualityRange?.('hd720', 'hd720')")
        except PWTimeout:
            pass


async def fullscreen(stage, want=True):
    """Fullscreen the video in the stage tab (YouTube: its "f" shortcut, a real key press so it counts
    as a user gesture). Returns whether it worked."""
    if await stage.evaluate("!!document.fullscreenElement") != want:
        await stage.bring_to_front()
        if await stage.locator("#movie_player").count():
            await stage.evaluate("document.activeElement?.blur()")
            await stage.keyboard.press("f")
        elif want:
            await stage.locator("video").first.dblclick()  # most players go fullscreen on double-click
        else:
            await stage.keyboard.press("Escape")
        await stage.wait_for_timeout(500)
    return await stage.evaluate("!!document.fullscreenElement") == want


SKIP_AD = ".ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern"


async def skip_ads(page):
    """Click YouTube's Skip button in the shared tab whenever it shows. The main loop calls this."""
    for p in page.context.pages:
        if p is not page and "youtube.com/watch" in p.url:
            skip = p.locator(SKIP_AD).first
            if await skip.count() and await skip.is_visible():
                await skip.click(timeout=2000)
                log("Skipped an ad.")


async def play(page, query):
    """Share YouTube's search results, then open the top video in the same (shared) tab.
    Returns (title, url)."""
    stage = await show(page, "https://www.youtube.com/results?" + urlencode({"search_query": query}))
    link = stage.locator("a#video-title[href^='/watch']").first
    await link.wait_for(timeout=15_000)
    title = (await link.inner_text()).strip()
    await link.click()  # YouTube swaps in the video without reloading; the share follows the tab
    await stage.wait_for_url(re.compile(r"youtube\.com/watch"), timeout=15_000)
    await youtube_hd(stage)
    await fullscreen(stage)  # what people want when they ask for a video; ads get skipped by the main loop
    return title, stage.url.split("&")[0]


VIDEO_ACTIONS = ("play", "pause", "fullscreen", "exit-fullscreen", "skip-ad", "mute", "unmute")


async def stage_tab(page):
    for p in page.context.pages:
        if p is not page and await p.title() == STAGE_TITLE:
            return p
    raise RuntimeError("Nothing is being shared. Use --play or --show first.")


async def video(page, action):
    """Control the video in the shared tab in one step. Returns what happened, for the agent to relay."""
    stage = await stage_tab(page)
    v = "document.querySelector('#movie_player video, video')"
    if not await stage.evaluate(f"!!{v}"):
        raise RuntimeError("There's no video in the shared tab.")
    if action in ("play", "pause"):
        # YouTube's own controls when it's YouTube: video.play() errors while an ad hands over to the video
        await stage.evaluate("""a => { const p = document.getElementById('movie_player');
            if (p && p.playVideo) a === 'play' ? p.playVideo() : p.pauseVideo();
            else { const v = document.querySelector('video'); a === 'play' ? v.play().catch(() => {}) : v.pause(); } }""", action)
        return "Playing." if action == "play" else "Paused."
    if action in ("mute", "unmute"):
        await stage.evaluate(f"{v}.muted = {str(action == 'mute').lower()}")
        return "Muted." if action == "mute" else "Unmuted."
    if action in ("fullscreen", "exit-fullscreen"):
        want = action == "fullscreen"
        if await fullscreen(stage, want):
            return "Fullscreen." if want else "Out of fullscreen."
        return "Couldn't change fullscreen on this player."
    if action == "skip-ad":
        skip = stage.locator(SKIP_AD).first
        for _ in range(40):  # YouTube shows the Skip button a few seconds into the ad
            if not await stage.locator(".ad-showing").count():
                return "No ad playing."
            if await skip.count() and await skip.is_visible():
                await skip.click()
                return "Skipped the ad."
            await stage.wait_for_timeout(500)
        return "This ad can't be skipped; it ends on its own."
    raise RuntimeError(f"Unknown action {action!r}. Use one of: {', '.join(VIDEO_ACTIONS)}")


async def ide_cli(path):
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        meet = next((pg for c in b.contexts for pg in c.pages if "meet.google.com" in pg.url), None)
        if not meet:
            sys.exit("Jamie isn't in a Meet call.")
        print(await ide(meet, "" if path == "." else path))


async def show_cli(url, query=None):
    # Separate process (run by Claude mid-task): attach to the bot's running Chromium.
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        pages = [pg for c in b.contexts for pg in c.pages]
        meet = next((pg for pg in pages if "meet.google.com" in pg.url), None)
        if not meet:
            sys.exit("Jamie isn't in a Meet call.")
        if url and url.startswith("video:"):
            print(await video(meet, url.removeprefix("video:")))
        elif query:
            title, url = await play(meet, query)
            print(f"Playing {title} {url}")
        else:
            await show(meet, url)
            print("Stopped sharing" if url.lower() == "off" else f"Sharing {url}")


async def read_messages(page):
    try:
        return await asyncio.wait_for(page.evaluate(READ_JS), 5)
    except Exception:
        return []


# ---------- environments, personalities, agents ----------

# Each agent CLI reads its project instructions from its own file in the working directory.
INSTRUCTIONS = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md"}
# The agent's browser tools go through cdp_filter, which hides the Meet tab from them
AGENT_CDP = "http://localhost:9223"
BROWSER_MCP = {"browser": {"command": "playwright-mcp", "args": ["--cdp-endpoint", AGENT_CDP]}}
CLAUDE_MCP = "/tmp/jamie-mcp.json"
CODEX_LAST = "/tmp/codex-last-message.txt"


def pick(base, name, kind):
    names = sorted(n.removesuffix(".md") for n in os.listdir(base) if not n.startswith("."))
    if name not in names:  # also keeps names from escaping the folder
        sys.exit(f"Unknown {kind} '{name}'. Available: {', '.join(names)}")
    return os.path.join(base, name)


def prepare(env, personality, agent):
    """Refresh /workspace from the environment and set the chosen agent CLI up in it."""
    if agent not in INSTRUCTIONS:
        sys.exit(f"Unknown agent '{agent}'. Available: {', '.join(INSTRUCTIONS)}")
    with open(pick(PERSONALITIES, personality, "personality") + ".md") as f:
        persona = f.read()
    # Env files win; whatever Jamie built is kept. Secrets and the image recipe stay out of the workspace.
    shutil.copytree(ENVIRONMENT, WORKSPACE, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".env", "Dockerfile"))
    room = os.path.join(WORKSPACE, "ROOM.md")
    if not os.path.exists(room):
        sys.exit(f"environments/{env}/ROOM.md is missing")
    with open(room) as f:
        instructions = f"{core_prompt(WORKSPACE)}\n\n{persona}\n\n{f.read()}"
    with open(os.path.join(WORKSPACE, INSTRUCTIONS[agent]), "w") as f:
        f.write(f"<!-- Generated by Jamie on every join. Edit environments/{env}/ROOM.md instead. -->\n\n"
                + instructions)

    servers = dict(BROWSER_MCP)
    if os.path.exists(os.path.join(WORKSPACE, "mcp.json")):
        with open(os.path.join(WORKSPACE, "mcp.json")) as f:
            servers.update(json.load(f)["mcpServers"])
    if agent == "claude":
        with open(CLAUDE_MCP, "w") as f:
            json.dump({"mcpServers": servers}, f)
    elif agent == "gemini":  # gemini reads MCP servers from project settings
        os.makedirs(os.path.join(WORKSPACE, ".gemini"), exist_ok=True)
        with open(os.path.join(WORKSPACE, ".gemini", "settings.json"), "w") as f:
            json.dump({"mcpServers": servers}, f)

    if os.path.exists(os.path.join(WORKSPACE, "setup.sh")):
        log(f"Running {env}/setup.sh")
        subprocess.run(["bash", "setup.sh"], cwd=WORKSPACE, check=True)
    log(f"Environment: {env}  Personality: {personality}  Agent: {agent}")
    return Agent(agent, servers)


def codex_mcp(servers):
    # Codex has no MCP config flag, so pass each server as `-c` TOML overrides.
    flags = []
    for name, server in servers.items():
        for key in ("command", "args", "env"):
            if key in server:
                v = server[key]
                toml = "{" + ", ".join(f"{k} = {json.dumps(x)}" for k, x in v.items()) + "}" if key == "env" else json.dumps(v)
                flags += ["-c", f"mcp_servers.{name}.{key}={toml}"]
    return flags


def narrate(tool):
    """A few words on what the agent is doing, for people waiting in the call (None: not worth saying)."""
    name, args = tool.get("name", ""), tool.get("input", {})
    cmd = args.get("command", "")
    if "--ide" in cmd:
        return "Opening the editor."
    if "--play" in cmd:
        return "Finding the video."
    if "--show" in cmd:
        return "Putting it on screen."
    if name in ("Write", "Edit") and args.get("file_path"):
        return f"Writing {os.path.basename(args['file_path'])}."
    if name == "WebSearch" or "search" in name.lower():
        return "Searching the web."
    if name == "WebFetch" or "navigate" in name:
        return "Reading up on it."
    if name == "Bash" and re.search(r"\b(npm|pip|python3?|node)\b", cmd) and "/app/bot.py" not in cmd:
        return "Running it."
    return None


class Agent:
    def __init__(self, name, servers):
        self.name, self.servers = name, servers
        self.has_session = False  # after the first request, continue the same conversation
        self.proc = None          # claude: one process for the whole call; codex/gemini: the current run
        self.running = False      # a request is in progress
        self.stopped = ""         # why the current request was stopped on purpose ("cancel", "reset")
        self.generation = 0       # bumped by reset(): a run that started before it mustn't revive the session

    async def _kill(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def cancel(self):
        """Stop the current request. The conversation is kept: the next request continues it."""
        if self.running:
            self.stopped = "cancel"
            await self._kill()

    async def reset(self):
        """Forget the conversation: the next request starts a new one."""
        self.generation += 1
        self.has_session = False
        if self.running:
            self.stopped = "reset"
        await self._kill()

    def command(self, prompt=None):
        full, cont = PERMS == "full", self.has_session
        if self.name == "claude":  # stays open; requests arrive as stream-json messages on stdin
            cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                   "--verbose", "--mcp-config", CLAUDE_MCP]
            cmd += ["--continue"] if cont else []
            cmd += ["--dangerously-skip-permissions"] if full else ["--allowedTools", "WebSearch,WebFetch,Read,Glob,Grep"]
        elif self.name == "codex":
            cmd = ["codex", "exec", *(["resume", "--last"] if cont else []), "--skip-git-repo-check",
                   "-o", CODEX_LAST, *codex_mcp(self.servers)]
            cmd += ["--dangerously-bypass-approvals-and-sandbox"] if full else ["-c", 'sandbox_mode="read-only"']
            cmd.append("-")  # prompt from stdin
        else:
            cmd = ["gemini", "--skip-trust", "-o", "text", *(["--resume", "latest"] if cont else [])]
            cmd += ["--yolo"] if full else ["--approval-mode", "plan"]
            cmd.append(f"--prompt={prompt}")  # `=` so a prompt starting with "-" isn't read as a flag
        return cmd

    async def start(self):
        """Start Claude and its browser tools now, so the first request doesn't wait for them."""
        if self.name == "claude" and (not self.proc or self.proc.returncode is not None):
            self.proc = await asyncio.create_subprocess_exec(
                *self.command(), cwd=WORKSPACE, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=2**25)  # events carry page snapshots: long lines

    async def run_claude(self, prompt, progress=None):
        await self.start()
        proc = self.proc
        msg = {"type": "user", "message": {"role": "user", "content": prompt}}
        try:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            async with asyncio.timeout(TIMEOUT):
                while line := await proc.stdout.readline():
                    event = json.loads(line)
                    if progress and event.get("type") == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "tool_use" and (step := narrate(block)):
                                progress(step)
                    if event.get("type") == "result":
                        out = (event.get("result") or "").strip()
                        log(self.name, "->", out[:500])
                        return out if not event.get("is_error") else f"claude hit an error: {out[-400:]}"
        except TimeoutError:
            await self._kill()  # can't stop it mid-task otherwise; the next request continues the conversation
            return f"Timed out after {TIMEOUT}s."
        except BaseException:
            # Anything else mid-turn (bad output, a cancelled task): never leave it running, or the next
            # request would read this one's answer
            await self._kill()
            raise
        self.proc = None  # it exited; the next request starts it again (with --continue)
        return "" if self.stopped else "claude stopped unexpectedly. Try again."

    async def run(self, prompt, progress=None):
        log(self.name, "<-", prompt)
        self.running, self.stopped, generation = True, "", self.generation
        try:
            out = await (self.run_claude(prompt, progress) if self.name == "claude" else self.run_once(prompt))
            if self.stopped:
                return ""  # cancelled or reset on purpose: nothing to report
            if generation == self.generation:  # (a reset during the run means: don't continue it)
                self.has_session = True
            return out
        finally:
            self.running = False

    async def run_once(self, prompt):
        """codex / gemini: one process per request."""
        if os.path.exists(CODEX_LAST):
            os.remove(CODEX_LAST)
        self.proc = proc = await asyncio.create_subprocess_exec(
            *self.command(prompt), cwd=WORKSPACE,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdin = b"" if self.name == "gemini" else prompt.encode()
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), TIMEOUT)
        except asyncio.TimeoutError:
            await self._kill()
            return f"Timed out after {TIMEOUT}s."
        finally:
            self.proc = None
        out, err = out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
        if proc.returncode != 0:
            log(self.name, "failed:", err[-1000:] or out[-1000:])
            return f"{self.name} exited with an error: {(err or out)[-400:]}"
        if self.name == "codex" and os.path.exists(CODEX_LAST):  # codex prints progress; the answer is here
            with open(CODEX_LAST) as f:
                out = f.read().strip()
        log(self.name, "->", out[:500])
        return out


# ---------- main loop ----------

async def worker(page, agent, queue, state):
    while True:
        prompt = await queue.get()
        state["busy"] = prompt
        await avatar(page, "thinking")
        said = {"at": time.monotonic(), "last": ""}  # the ack was just said

        def progress(step):  # narrate long jobs, at most every 10s, never the same thing twice in a row
            if step != said["last"] and time.monotonic() - said["at"] > 10:
                said.update(at=time.monotonic(), last=step)
                log("progress:", step)
                speak_soon(page, step)
        try:
            reply = await agent.run(prompt, progress)
            if not reply:  # cancelled
                continue
            state["last_reply"] = reply
            speak_soon(page, voice.spoken(reply))
            await send(page, reply)
        except Exception as e:
            log("worker error:", e)
            try:
                await send(page, f"Something broke: {e}")
            except Exception:
                pass
        finally:
            state["busy"] = ""
            await avatar(page, "listening")
            queue.task_done()


# Instant controls: for simple requests the judge picks one of these and the bot does it right away,
# without the agent (~0.5s instead of several). A room adds its own in controls.json:
#   {"next-slide": {"description": "go to the next slide", "keys": ["ArrowRight"]}}
BUILTIN_CONTROLS = {
    "pause": "pause the video", "play": "play or resume the video", "fullscreen": "make the video fullscreen",
    "exit-fullscreen": "leave fullscreen", "mute": "mute the shared video", "unmute": "unmute the shared video",
    "skip-ad": "skip the ad", "scroll-down": "scroll down the shared page", "scroll-up": "scroll up the shared page",
    "top": "go to the top of the shared page", "bottom": "go to the bottom of the shared page",
    "back": "go back to the previous page on the shared screen",
    "open": "click something visible on the shared screen (\"play that video\", \"open the second link\"); "
            "arg = its name exactly as listed under Visible",
    "play-video": "search YouTube and play the top video fullscreen; arg = what to search for",
    "show": "open a website or page on the shared screen (\"pull up the Wikipedia page for X\"); arg = its full URL, "
            "which you can work out yourself (e.g. https://en.wikipedia.org/wiki/X)",
    "ide": "open the code editor (VS Code) on the shared screen",
    "quiet": "stop talking (Jamie stops speaking right away)",
    "notes": "show the live meeting notes (summary, decisions, action items) on the shared screen",
    "cancel": "stop the task Jamie is working on right now (\"never mind\", \"cancel that\", \"stop, that's wrong\")",
}
SCROLL = {"scroll-down": "scrollBy({top: innerHeight * 0.8, behavior: 'smooth'})",
          "scroll-up": "scrollBy({top: -innerHeight * 0.8, behavior: 'smooth'})",
          "top": "scrollTo({top: 0, behavior: 'smooth'})", "bottom": "scrollTo({top: 1e9, behavior: 'smooth'})"}

# What's visible on the shared tab: things to click get a number (data-jamie-pick) so "open" can click them
ON_SCREEN_JS = """() => {
  document.querySelectorAll('[data-jamie-pick]').forEach(e => e.removeAttribute('data-jamie-pick'));
  const seen = new Set(), found = [];
  for (const e of document.querySelectorAll('a[href], button, [role=button], [role=link]')) {
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    // Really visible here: not in a closed menu, not covered by something else
    const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const top = document.elementFromPoint(x, y);
    if (!top || !(e === top || e.contains(top) || top.contains(e))) continue;
    // The words people see beat tooltips ("Evolution", not "Toggle Evolution subsection")
    const text = (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().replace(/\\s+/g, ' ');
    if (text.length < 3 || text.length > 120 || seen.has(text)) continue;
    seen.add(text);
    const main = !!e.closest('main, article, [role=main], #content, #contents, #primary');
    found.push({ e, text, main });
  }
  found.sort((a, b) => b.main - a.main);  // the page's own content before site navigation
  const items = found.slice(0, 80).map((f, n) => { f.e.dataset.jamiePick = n; return f.text; });
  const h = document.querySelector('h1');
  return { url: location.href, heading: h ? h.innerText.trim().slice(0, 120) : '', items };
}"""


async def on_screen(page):
    """What the shared tab shows, or None when nothing is shared."""
    try:
        return await asyncio.wait_for((await stage_tab(page)).evaluate(ON_SCREEN_JS), 3)
    except Exception:
        return None


def describe(screen):
    if not screen:
        return "Nothing is being shared."
    return (f"Shared tab: {screen['heading'] or '(no heading)'} ({screen['url'][:150]})\n"
            f"Visible: {'; '.join(screen['items']) or '(nothing clickable)'}")


LEARNED = os.environ.get("JAMIE_LEARNED", "/learned")  # a volume per room: what Jamie learned, kept across calls
FILES = os.environ.get("JAMIE_FILES", "/files")        # a volume per room: what's worth keeping after the call


def keep_meeting(started):
    """Save this meeting's notes and transcript to FILES/<date time>/ (the workspace goes when Jamie does)."""
    if not os.path.isdir(FILES):
        return None
    # to the second, plus the container: two Jamies in one room mustn't overwrite each other
    folder = os.path.join(FILES, time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(started)) + f" {socket.gethostname()[:8]}")
    os.makedirs(folder, exist_ok=True)
    if os.path.exists(os.path.join(WORKSPACE, "notes.md")):
        shutil.copy(os.path.join(WORKSPACE, "notes.md"), folder)
    if os.path.exists(os.path.join(WORKSPACE, "transcript.md")):  # just this meeting: the file can span several
        with open(os.path.join(WORKSPACE, "transcript.md")) as f:
            text = f.read()
        start = text.rfind("\n## Meeting ")
        with open(os.path.join(folder, "transcript.md"), "w") as f:
            f.write(text[start + 1:] if start >= 0 else text)
    return folder


def read_controls(path):
    """Controls from a JSON file: {"name": {"description", "keys": [...]} or {"description", "run": "cmd {arg}"}}."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return {k: v for k, v in json.load(f).items()
                    if isinstance(v, dict) and (isinstance(v.get("keys"), list) or isinstance(v.get("run"), str))}
    except Exception as e:
        log(f"Ignoring {path}:", e)
        return {}


def room_controls():
    """The room's controls.json plus what Jamie has learned in this room (the room's own win on a clash)."""
    return {**read_controls(os.path.join(LEARNED, "controls.json")), **read_controls(os.path.join(WORKSPACE, "controls.json"))}


def learn(name, description, keys=None, run=None):
    """Save a new instant control for this room. Returns what was saved."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name or ""):
        raise ValueError("name: lowercase letters, digits and dashes, like next-slide")
    if name in BUILTIN_CONTROLS:
        raise ValueError(f"{name!r} is built in already")
    if bool(keys) == bool(run):
        raise ValueError("give either --keys or --run")
    if run:  # run without a shell: {arg} may only be a whole word, so what people say can't become code
        try:
            words = shlex.split(run)
        except ValueError as e:
            raise ValueError(f"--run: {e}")
        if any("{arg}" in w and w != "{arg}" for w in words):
            raise ValueError("--run: {arg} must be a word of its own (no quotes around it, not inside other text)")
    path = os.path.join(LEARNED, "controls.json")
    learned = read_controls(path)
    learned[name] = {"description": description, **({"keys": keys} if keys else {"run": run})}
    os.makedirs(LEARNED, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(learned, f, indent=2)
    os.replace(path + ".tmp", path)  # the bot may be reading it
    return f"Learned {name!r}: {description}"


def controls():
    """name -> description, for the judge."""
    return {**BUILTIN_CONTROLS, **{k: v.get("description", k) for k, v in room_controls().items()}}


IDE_PORT = 8443


async def ide(page, path=""):
    """VS Code (code-server) on the shared screen, showing the workspace; optionally open a file in it."""
    def up():
        with socket.socket() as sock:
            return sock.connect_ex(("127.0.0.1", IDE_PORT)) == 0
    if not up():
        subprocess.Popen(["code-server", "--auth", "none", "--bind-addr", f"127.0.0.1:{IDE_PORT}", "--disable-telemetry",
                          "--disable-update-check", "--disable-workspace-trust", WORKSPACE],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # outlives --ide
        for _ in range(60):
            if up():
                break
            await asyncio.sleep(0.25)
    stage = await show(page, f"http://localhost:{IDE_PORT}/?folder={WORKSPACE}")
    await stage.locator(".monaco-workbench").wait_for(timeout=20_000)
    if path:
        await stage.keyboard.press("Control+P")  # Quick Open
        await stage.keyboard.type(os.path.relpath(os.path.abspath(path), WORKSPACE))
        await stage.wait_for_timeout(400)
        await stage.keyboard.press("Enter")
    return "The code editor is on screen."


async def control(page, name, arg=""):
    """Do an instant control on the shared tab. Returns what happened."""
    if name in room_controls():
        c = room_controls()[name]
        if "run" in c:  # a command, run without a shell; {arg} (a whole word) becomes one argument
            if PERMS != "full":
                raise RuntimeError("commands are off in safe mode")
            words = [arg or "" if w == "{arg}" else w for w in shlex.split(c["run"])]
            proc = await asyncio.create_subprocess_exec(*words, cwd=WORKSPACE,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            try:
                out = (await asyncio.wait_for(proc.communicate(), 30))[0].decode(errors="replace").strip()
            except (TimeoutError, asyncio.CancelledError):
                proc.kill()
                raise
            if proc.returncode:
                raise RuntimeError(out[-200:] or f"exit {proc.returncode}")
            return out[-300:] or "Done."
        stage = await stage_tab(page)
        await stage.bring_to_front()
        for key in c["keys"]:
            await stage.keyboard.press(key)
        return f"Pressed {' '.join(c['keys'])}."
    if name in SCROLL:
        await (await stage_tab(page)).evaluate(SCROLL[name])
        return "Scrolled."
    if name == "skip-ad":
        await skip_ads(page)
        return "Skipping the ad as soon as YouTube allows."
    if name == "back":
        await (await stage_tab(page)).go_back()
        return "Went back."
    if name == "open":
        stage, screen = await stage_tab(page), await on_screen(page)
        want = arg.lower()
        score = lambda t: SequenceMatcher(None, want, t.lower()).ratio() + (0.5 if want and want in t.lower() else 0)  # noqa: E731
        best = max(range(len(screen["items"])), key=lambda n: score(screen["items"][n]), default=None)
        if best is None or score(screen["items"][best]) < 0.5:
            raise RuntimeError(f"couldn't find {arg!r} on screen")
        await stage.locator(f'[data-jamie-pick="{best}"]').first.click(timeout=5000)
        await stage.wait_for_timeout(1000)
        if "youtube.com/watch" in stage.url:
            await youtube_hd(stage)
            await fullscreen(stage)
        return f"Opened {screen['items'][best]}."
    if name == "play-video":
        title, url = await play(page, arg)
        return f"Playing {title}."
    if name == "show":
        if not re.match(r"https?://", arg):
            raise RuntimeError(f"not a URL: {arg!r}")
        await show(page, arg)
        return f"Showing {arg}."
    if name == "ide":
        return await ide(page)
    if name == "notes":
        if NOTES and NOTES.new:
            await NOTES.update()  # catch up first: people asking for notes want the latest
        await show(page, "file://" + os.path.join(WORKSPACE, "notes.html"))
        return "The meeting notes are on screen."
    if name == "quiet":
        speaking["hush"] += 1
        await page.evaluate("window.__jamieVoice && window.__jamieVoice.stop()")
        return "Quiet."
    return await video(page, name)


async def run_control(page, name, arg):
    try:
        result = await asyncio.wait_for(control(page, name, arg), 40)
        log("control:", name, arg, "->", result)
        if name in ("play-video", "open", "show", "ide", "notes"):  # took a moment: say what's up (pause etc. speak for themselves)
            speak_soon(page, result)
        elif "run" in room_controls().get(name, {}):  # a command's output is the answer
            speak_soon(page, voice.spoken(result))
            await send(page, result)
    except Exception as e:
        log("control failed:", name, arg, e)
        await send(page, f"Couldn't {name} {arg}: {str(e).splitlines()[0]}".replace("  ", " "))


async def act(page, agent, queue, action, request, ack, control_name="", arg=""):
    """Carry out a command from chat or speech. Returns True when Jamie should leave."""
    if action == "control" and control_name == "cancel":
        if agent.running:
            await agent.cancel()
            speak_soon(page, "Okay, I stopped.")
            await send(page, "Okay, I stopped.")
            log("control: cancel -> stopped the agent")
        return False
    if action == "control":  # in the background: listening goes on while e.g. YouTube loads
        background(run_control(page, control_name, arg))
        return False
    if ack:
        speak_soon(page, ack)
        await send(page, ack)
    if action == "leave":
        if NOTES and NOTES.lines:  # leave the notes behind in the chat
            try:
                if NOTES.new:
                    await asyncio.wait_for(NOTES.update(), 25)
                if NOTES.recap():
                    await send(page, "Meeting notes:\n" + NOTES.recap())
                    log("Posted the meeting notes:", NOTES.recap().replace("\n", " | "))
            except Exception as e:
                log("Couldn't post the notes:", e)
        await asyncio.sleep(1.5)  # let the goodbye be heard
        await leave_button(page).first.click()
        return True
    if action == "stop_sharing":
        await show(page, "off")
    elif action == "reset":
        await agent.reset()
    elif action == "request":
        await queue.put(request)

    return False


async def captions_on(page, first=True):
    """Turn Meet's captions on (they're Jamie's ears). Meet can turn them off again, e.g. when Jamie
    starts presenting, so the main loop calls this every few seconds."""
    clicked = await asyncio.wait_for(page.evaluate("""() => {
        const b = document.querySelector('button[aria-label*="turn on captions" i]');
        if (b) b.click();
        return !!b;
    }"""), 5)
    if clicked:
        log("Captions on: listening to the call." if first else "Meet had turned captions off; turned them back on.")
    if not first:
        return
    with open(os.path.join(WORKSPACE, "transcript.md"), "a") as f:
        f.write(f"\n## Meeting {time.strftime('%Y-%m-%d %H:%M')}\n\n")


def transcribe(lines):
    with open(os.path.join(WORKSPACE, "transcript.md"), "a") as f:
        for speaker, text in lines:
            f.write(f"[{time.strftime('%H:%M:%S')}] {speaker}: {text}\n")


async def listen(page, agent):
    global NOTES
    NOTES, started = notes.Notes(WORKSPACE), time.time()
    queue, seen = asyncio.Queue(), set()
    state = {"busy": "", "last_reply": ""}
    caps, judge = hearing.Captions(hear_self=bool(TEST_AUDIO)), hearing.Judge(NAME, controls())
    heard, pending, judging = [], [], None  # judged lines; lines not yet judged; running judge task
    waiting, gave_up = None, False  # when the judge said "wait"; whether this is the last try
    async def warm_up():
        start = time.monotonic()
        await judge.warm_up()
        log(f"judge ready in {time.monotonic() - start:.1f}s")
    warm = asyncio.create_task(warm_up())  # noqa: F841 (runs while Jamie finishes joining)
    await agent.start()
    if VOICE:
        background(VOICE_ENGINE.warm_up())  # load the voice model before the first reply
    await chat_box(page)
    await captions_on(page)
    last_check = last_beat = last_skip = time.monotonic()
    live, hearing_now = {}, False  # caption text per block as of the last check; whether people are talking
    learned_file = os.path.join(LEARNED, "controls.json")
    learned_seen = os.path.exists(learned_file) and os.path.getmtime(learned_file)

    if DEBUG:
        path = os.path.join(WORKSPACE, "meet-dump.html")
        with open(path, "w") as f:
            f.write(await page.content())
        log("DOM dumped to", path)

    # Say it's listening (people should know there's a transcript); never announce the trigger
    await send(page, f"{NAME} here. I'm listening and keeping a transcript.")
    await page.wait_for_timeout(2000)
    seen.update(m["id"] for m in await read_messages(page))  # ignore history + own welcome

    task = asyncio.create_task(worker(page, agent, queue, state))
    log(f"Listening for '{TRIGGER}' in chat and for {NAME}'s name out loud.")
    gone = 0  # consecutive checks without the Leave button
    try:
        while True:
            here = await in_call(page)
            gone = gone + 1 if here is False else 0 if here else gone
            if gone >= 10:  # ~3s: not just a dialog or Meet redrawing
                log("Call ended or Jamie was removed. Meet showed:", page.url)
                try:
                    await page.screenshot(path=os.path.join(WORKSPACE, "left-call.png"))
                except Exception:
                    pass
                return
            for m in await read_messages(page):
                if not m["id"] or m["id"] in seen:
                    continue
                seen.add(m["id"])
                hit = TRIGGER_RE.search(m["text"])
                if not hit:
                    continue
                cmd = hit.group(1).strip()
                if cmd.lower() == "leave":
                    action, ack = "leave", "Bye."
                elif cmd.lower() in ("stop", "stop sharing"):
                    action, ack = "stop_sharing", ""
                elif cmd.lower() == "reset":
                    action, ack = "reset", "Fresh context."
                elif not cmd:
                    action, ack = "none", f"Usage: {TRIGGER} <request>"
                else:
                    action, ack = "request", f"{'Queued' if queue.qsize() or agent_busy(queue) else 'On it'}: {cmd[:100]}"
                if await act(page, agent, queue, action, cmd, ack):
                    return

            # Speech: finished caption lines go to the transcript and, one batch at a time, to the judge
            snapshot = await read_captions(page)
            if time.monotonic() - last_skip > 1:
                last_skip = time.monotonic()
                try:
                    await asyncio.wait_for(skip_ads(page), 5)
                except Exception:
                    pass
            if time.monotonic() - last_check > 5:
                last_check = time.monotonic()
                learned_at = os.path.exists(learned_file) and os.path.getmtime(learned_file)
                if learned_at != learned_seen and not judging:  # Jamie learned a shortcut: the judge should know it
                    learned_seen, judge.controls = learned_at, controls()
                    await judge.close()  # the next judgment starts a judge with the new list
                    log("Learned controls now:", ", ".join(sorted(read_controls(learned_file))) or "none")
                try:
                    await captions_on(page, first=False)
                except Exception as e:
                    log("Couldn't check captions:", e)
            if time.monotonic() - last_beat > 60:
                last_beat = time.monotonic()
                log(f"listening: captions {'on' if snapshot is not None else 'NOT FOUND'}, "
                    f"{len(snapshot or [])} caption block(s) on screen, busy with: {state['busy'][:60] or 'nothing'}")
            # Live caption changes (before a line is finished): barge-in and the avatar's "someone's talking"
            talking = [b for b in snapshot or [] if live.get(b["id"]) != b["text"] and not b["name"].endswith("Presentation")
                       and (b["name"] != "You" or (TEST_AUDIO and not said_by_me(b["text"][-80:])))]
            # Barge-in needs NEW words with its name: Meet keeps re-punctuating the request Jamie is answering
            added = [b["text"][len(os.path.commonprefix([live.get(b["id"], ""), b["text"]])):] for b in talking]
            live = {b["id"]: b["text"] for b in snapshot or []}
            if added and voice_lock.locked() and any(judge.wake.search(a) for a in added):
                await page.evaluate("window.__jamieVoice && window.__jamieVoice.stop()")  # let them talk
                log("Stopped talking: someone said my name.")
            if bool(talking) != hearing_now:
                hearing_now = bool(talking)
                await page.evaluate("h => window.__jamieAvatar && (window.__jamieAvatar.hearing = h)", hearing_now)
            lines = caps.feed(snapshot)
            if TEST_AUDIO:  # Jamie hears itself in tests: what it says while talking isn't a request
                mine = [ln for ln in lines if ln[0] == "You" and said_by_me(ln[1])]
                for _, t in mine:
                    log("heard myself:", t)
                lines = [ln for ln in lines if ln not in mine]
            if lines:
                transcribe(lines)
                for s, t in lines:
                    NOTES.add(s, t)
                NOTES.update_soon()
                for s, t in lines:
                    log("heard", f"{s}: {t}")
                pending += lines
                if not state["busy"] and any(judge.wake.search(t) for _, t in lines):
                    await avatar(page, "thinking")  # show it heard its name before the judge answers
            if judging and judging.done():
                verdict, batch = judging.result()
                judging = None
                log("judge:", verdict)
                if verdict["action"] not in ("wait", "request") and not state["busy"]:  # nothing for the agent: stop "thinking"
                    await avatar(page, "listening")
                if verdict["action"] == "wait" and gave_up:
                    # They stopped talking: a vague request still goes to the agent, which can ask what they meant
                    verdict = {"action": "request", "ack": "On it.", "control": "", "arg": "",
                               "request": verdict["request"] or " ".join(t for _, t in batch)}
                if verdict["action"] == "wait":
                    pending, waiting = batch + pending, time.monotonic()  # judge again with more words
                else:
                    heard += batch
                    request = verdict["request"] or " ".join(t for _, t in batch)  # the judge sometimes leaves it blank
                    if verdict["action"] == "request":
                        request = f"{batch[-1][0]} asked out loud: {request}"
                    if verdict["action"] == "request":  # the agent sees what's on the shared screen too
                        request += f"\n\n(On the shared screen right now: {describe(await on_screen(page))})"
                    if verdict["action"] == "request" and verdict.get("answer"):  # the judge knew it: no agent needed
                        log("quick answer:", verdict["answer"])
                        speak_soon(page, verdict["answer"])
                        await send(page, verdict["answer"])
                        state["last_reply"] = verdict["answer"]
                        if not state["busy"]:
                            await avatar(page, "listening")
                        continue
                    if await act(page, agent, queue, verdict["action"], request, verdict["ack"], verdict["control"],
                                 verdict.get("arg", "")):
                        return
            # After a "wait", judge again when more words come, or give up 3s later
            if pending and not judging and (not waiting or lines or time.monotonic() - waiting > 3):
                gave_up = bool(waiting) and not lines
                batch, pending, waiting = pending, [], None
                people = sorted({s for s, _ in heard + batch if s != "You"})
                judging = asyncio.create_task(judged(judge, heard[-20:], batch, state, people, page))
            await asyncio.sleep(0.3)
    finally:
        task.cancel()
        await agent.reset()
        await judge.close()
        try:
            log("Saved the meeting's notes and transcript to", keep_meeting(started))
        except Exception as e:
            log("Couldn't save the meeting files:", e)


async def judged(judge, context, batch, state, people, page):
    start = time.monotonic()
    screen = describe(await on_screen(page))
    verdict = await judge(context, batch, state["last_reply"], state["busy"], people, screen)
    log(f"judge took {time.monotonic() - start:.1f}s for {len(batch)} line(s)")
    return verdict, batch


# On the Meet page: keep a handle on the call's connections (so tests can read video stats), and
# make screen-shares smooth
STATS_JS = """(() => {
  if (location.hostname !== "meet.google.com" || window.__jamiePCs) return;
  window.__jamiePCs = [];
  const PC = window.RTCPeerConnection;
  window.RTCPeerConnection = function (...a) { const pc = new PC(...a); window.__jamiePCs.push(pc); return pc; };
  window.RTCPeerConnection.prototype = PC.prototype;
  Object.setPrototypeOf(window.RTCPeerConnection, PC);

  // Meet asks for a screen-share at slide-deck frame rates (~4fps measured): Jamie shares video, so
  // ask for 30fps and mark it as motion, so the encoder keeps the frame rate and gives up detail instead
  const gdm = navigator.mediaDevices.getDisplayMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getDisplayMedia = async (c = {}) => {
    const video = { ...(typeof c.video === "object" ? c.video : {}), frameRate: { ideal: 30, max: 30 } };
    const stream = await gdm({ ...c, video });
    for (const t of stream.getVideoTracks()) {
      t.contentHint = "motion";
      const apply = t.applyConstraints.bind(t);  // Meet lowers the frame rate again later: keep it at 30
      t.applyConstraints = (k = {}) => apply({ ...k, frameRate: { ideal: 30, max: 30 } });
      await apply({ frameRate: { ideal: 30, max: 30 } }).catch(() => {});
    }
    return stream;
  };
})();"""

# Outgoing video, one entry per stream Meet sends (camera layers, the shared tab)
SENT_VIDEO_JS = """async () => {
  const out = [];
  for (const pc of window.__jamiePCs || []) {
    const stats = await pc.getStats();
    stats.forEach(s => {
      if (s.type !== "outbound-rtp" || s.kind !== "video" || !s.frameWidth) return;
      const src = stats.get(s.mediaSourceId);
      out.push({ size: s.frameWidth + "x" + s.frameHeight, fps: Math.round(s.framesPerSecond || 0),
                 limit: s.qualityLimitationReason, kbps: Math.round((s.targetBitrate || 0) / 1000),
                 source: src ? src.width + "x" + src.height + "@" + Math.round(src.framesPerSecond || 0) : "",
                 codec: (stats.get(s.codecId) || {}).mimeType });
    });
  }
  return out;
}"""


def avatar_script():
    """avatar.js, preceded by the look picked in the extension (JAMIE_LOOK, JSON)."""
    try:
        look = json.loads(os.environ.get("JAMIE_LOOK") or "{}")
    except json.JSONDecodeError:
        look = {}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar.js")) as f:
        return (f"window.__jamieLook = {json.dumps(look)};\n"
                f"window.__jamieMicPassthrough = {json.dumps(bool(TEST_AUDIO))};\n" + f.read())


async def avatar_fps(page, fps):
    try:
        await page.evaluate("f => window.__jamieAvatar && (window.__jamieAvatar.fps = f)", fps)
    except Exception:
        pass


async def avatar(page, state):
    """Set the camera avatar's state: listening, thinking or talking (see avatar.js)."""
    try:
        await page.evaluate("s => window.__jamieAvatar && (window.__jamieAvatar.state = s)", state)
    except Exception:
        pass


async def read_captions(page):
    try:
        return await asyncio.wait_for(page.evaluate(hearing.CAPTIONS_JS), 5)
    except Exception:
        return None


NOTES = None  # notes.Notes for the current call, set in listen()
VOICE_ENGINE = voice.Voice()
voice_lock = asyncio.Lock()
speaking = {"until": 0.0, "said": [], "hush": 0}  # hush: bumped by "stop talking", drops queued speech too  # test mode: what Jamie said lately, so its own voice isn't a request


def said_by_me(text):
    """Whether a caption is Jamie's own voice: most of its words match something Jamie said in the last 30s."""
    words = set(re.findall(r"[a-z']+", text.lower()))
    for when, said in speaking["said"]:
        if time.monotonic() - when < 30 and words:
            if len(words & set(re.findall(r"[a-z']+", said.lower()))) / len(words) >= 0.6:
                return True
    return False


async def speak(page, text):
    """Say text into the call (one thing at a time). Never raises: speech is a nicety."""
    if not (VOICE and text and VOICE_ENGINE.available()):
        return
    hush = speaking["hush"]
    try:
        speaking["said"] = speaking["said"][-9:] + [(time.monotonic(), text)]
        audio = await VOICE_ENGINE.synth(text)
        async with voice_lock:
            if speaking["hush"] != hush:  # "stop talking" came after this was queued
                return
            speaking["until"] = float("inf")
            await page.evaluate("b => window.__jamieVoice && window.__jamieVoice.ctx && window.__jamieVoice.say(b)",
                                base64.b64encode(audio).decode())
    except Exception as e:
        log("Couldn't speak:", str(e).splitlines()[0])
    finally:
        speaking["until"] = time.monotonic()


TASKS = set()  # fire-and-forget tasks: a reference keeps them from being garbage-collected mid-run


def background(coro):
    task = asyncio.create_task(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return task


def speak_soon(page, text):
    background(speak(page, text))


def agent_busy(queue):
    return queue._unfinished_tasks > 0  # noqa: SLF001 (fine for an MVP)


async def run_bot(url, agent):
    clear_stale_lock()
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE, headless=False, args=CHROME_ARGS,
            ignore_default_args=["--enable-automation"],
            permissions=["microphone", "camera"],
            viewport={"width": 1280, "height": 800},
        )
        await ctx.add_init_script(avatar_script())
        await ctx.add_init_script(STATS_JS)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        filter_server = await cdp_filter.serve(CDP, int(urlsplit(AGENT_CDP).port))  # noqa: F841 (lives with the bot)
        ctx.on("page", lambda pg: pg.on("crash", lambda: log("A browser tab crashed:", pg.url)))
        page.on("crash", lambda: log("The Meet tab crashed."))
        try:
            await join(page, url)
            await pin_meet_tab(page)
            await listen(page, agent)
        finally:
            await ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--show", metavar="URL", help="screen-share URL in the running call ('off' stops)")
    ap.add_argument("--play", metavar="QUERY", help="screen-share the top YouTube result for QUERY")
    ap.add_argument("--video", choices=VIDEO_ACTIONS, help="control the video in the shared tab")
    ap.add_argument("--ide", nargs="?", const=".", metavar="FILE", help="show VS Code on screen (and open FILE)")
    ap.add_argument("--learn", metavar="NAME", help="save a new instant control for this room (with --description and --keys or --run)")
    ap.add_argument("--description", help="for --learn: what people would say to ask for it")
    ap.add_argument("--keys", nargs="+", help="for --learn: keys to press in the shared tab, e.g. ArrowRight")
    ap.add_argument("--run", help="for --learn: a command to run instead; {arg} is replaced by what they asked for")
    ap.add_argument("--env", default=os.environ.get("JAMIE_ENV", "default"),
                    help="folder in environments/ (jamie.sh mounts it; used here for messages)")
    ap.add_argument("--agent", default=os.environ.get("JAMIE_AGENT", "claude"), help="claude | codex | gemini")
    ap.add_argument("--personality", default=os.environ.get("JAMIE_PERSONALITY", "default"),
                    help="file in personalities/ (without .md)")
    a = ap.parse_args()
    if a.learn:
        try:
            print(learn(a.learn, a.description or a.learn, a.keys, a.run))
        except ValueError as e:
            sys.exit(f"Couldn't learn it: {e}")
    elif a.login:
        asyncio.run(login())
    elif a.ide:
        asyncio.run(ide_cli(a.ide))
    elif a.show or a.play or a.video:
        asyncio.run(show_cli(f"video:{a.video}" if a.video else a.show, a.play))
    elif a.url:
        agent = prepare(a.env, a.personality, a.agent)
        try:
            asyncio.run(run_bot(a.url, agent))
        except KeyboardInterrupt:
            pass
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
