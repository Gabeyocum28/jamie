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
import json
import os
import re
import shutil
import subprocess
import sys
import time

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

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
        f"You are {NAME}, an AI agent sitting in a Google Meet call. People talk to you through the "
        f"meeting chat. Your working directory is {cwd}; build and run things there. If you start "
        "a web server, bind 0.0.0.0 on port 3000, 5173 or 8000 and run it in the background (nohup ... &) "
        "so the user can open http://localhost:<port>. Reply in plain text, no markdown, as short as "
        "possible (under 1200 characters): say what you did and where to find it.\n"
        "You control your own Chromium with the browser tools. One tab is the Meet call: never navigate, "
        "close or click in it. To put something on screen for the call, run "
        "`python3 /app/bot.py --show <url>`: it opens the url in a 'stage' tab and screen-shares it with "
        "sound (run it again to switch, `--show off` to stop). Then select the stage tab with the browser "
        "tools and do whatever people ask there: play/pause, fullscreen, skip ads, scroll, click, search the "
        "site. Find links yourself with your web search tool, the browser, or the site's own search; never "
        "ask people for a URL. "
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


def leave_button(page):
    return page.get_by_role("button", name=re.compile("leave call", re.I))


async def join(page, url):
    log("Opening", url)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    await click_first(page, [r"^got it$", r"^dismiss$", r"continue without"], 1500)

    name_box = page.get_by_role("textbox", name=re.compile("your name", re.I))
    if await name_box.count():  # not signed in: join as guest
        log("Not signed in, joining as guest named", NAME)
        await name_box.first.fill(NAME)

    for pat in (r"turn off microphone", r"turn off camera"):
        await click_first(page, [pat], 1500)

    clicked = await click_first(page, [r"join now", r"ask to join", r"join here too", r"switch here"], 5000)
    if not clicked:
        raise RuntimeError("Couldn't find a join button. Watch it in noVNC to see what Meet is showing.")
    log(f"Clicked '{clicked}'. Waiting to be admitted (up to 10 min)...")
    # "Leave call" also shows in the waiting room; "Share screen" only once admitted
    await page.get_by_role("button", name=re.compile("share screen", re.I)).first.wait_for(timeout=600_000)
    log("In the call.")


async def chat_box(page):
    box = page.get_by_role("textbox", name=re.compile("send a message", re.I)).first
    if await box.count() and await box.is_visible():
        return box
    await click_first(page, [r"chat with everyone", r"open chat", r"^chat"], 3000)
    await box.wait_for(timeout=10_000)
    return box


async def send(page, text):
    # Never echo the trigger, or Jamie would answer itself.
    text = re.sub(re.escape(TRIGGER), TRIGGER.lstrip("/"), text or "", flags=re.I).strip() or "(no output)"
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    if len(chunks) > MAX_CHUNKS:
        chunks = chunks[:MAX_CHUNKS]
        chunks[-1] += " ...(truncated, full output in the terminal)"
    for c in chunks:
        box = await chat_box(page)
        await box.fill(c)
        await box.press("Enter")
        await page.wait_for_timeout(500)


async def show(page, url):
    """Screen-share url from a separate stage tab. 'off' just stops sharing."""
    for p in page.context.pages:
        if p is not page:
            await p.close()  # closing the shared tab ends the presentation
    if url.lower() == "off":
        return
    await page.wait_for_timeout(1500)  # let Meet register the old share ending
    stage = await page.context.new_page()
    await stage.goto(url, wait_until="domcontentloaded")
    if "youtube.com/watch" in url:  # YouTube starts at 360p and ramps up slowly
        try:
            await stage.locator("#movie_player").wait_for(timeout=15_000)
            await stage.evaluate("document.getElementById('movie_player').setPlaybackQualityRange?.('hd1080')")
        except PWTimeout:
            pass
    await stage.evaluate("t => document.title = t", STAGE_TITLE)
    share = page.get_by_role("button", name=re.compile("share screen|present now", re.I)).first
    # JS click: a Playwright mouse click hangs while the capture picker opens
    await share.evaluate("b => b.click()")
    await stage.bring_to_front()  # so it's what you see in noVNC too


async def show_cli(url):
    # Separate process (run by Claude mid-task): attach to the bot's running Chromium.
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        pages = [pg for c in b.contexts for pg in c.pages]
        meet = next((pg for pg in pages if "meet.google.com" in pg.url), None)
        if not meet:
            sys.exit("Jamie isn't in a Meet call.")
        await show(meet, url)
        print("Sharing" if url.lower() != "off" else "Stopped sharing", url)


async def read_messages(page):
    try:
        return await page.evaluate(READ_JS)
    except Exception:
        return []


# ---------- environments, personalities, agents ----------

# Each agent CLI reads its project instructions from its own file in the working directory.
INSTRUCTIONS = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md"}
BROWSER_MCP = {"browser": {"command": "playwright-mcp", "args": ["--cdp-endpoint", CDP]}}
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


class Agent:
    def __init__(self, name, servers):
        self.name, self.servers = name, servers
        self.has_session = False  # after the first request, continue the same conversation

    def command(self, prompt):
        full, cont = PERMS == "full", self.has_session
        if self.name == "claude":
            cmd = ["claude", "-p", "--output-format", "text", "--mcp-config", CLAUDE_MCP]
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

    async def run(self, prompt):
        log(self.name, "<-", prompt)
        if os.path.exists(CODEX_LAST):
            os.remove(CODEX_LAST)
        proc = await asyncio.create_subprocess_exec(
            *self.command(prompt), cwd=WORKSPACE,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdin = b"" if self.name == "gemini" else prompt.encode()
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Timed out after {TIMEOUT}s."
        out, err = out.decode(errors="replace").strip(), err.decode(errors="replace").strip()
        if proc.returncode != 0:
            log(self.name, "failed:", err[-1000:] or out[-1000:])
            return f"{self.name} exited with an error: {(err or out)[-400:]}"
        if self.name == "codex" and os.path.exists(CODEX_LAST):  # codex prints progress; the answer is here
            with open(CODEX_LAST) as f:
                out = f.read().strip()
        log(self.name, "->", out[:500])
        self.has_session = True
        return out


# ---------- main loop ----------

async def worker(page, agent, queue):
    while True:
        prompt = await queue.get()
        try:
            await send(page, f"On it: {prompt[:100]}")
            await send(page, await agent.run(prompt))
        except Exception as e:
            log("worker error:", e)
            try:
                await send(page, f"Something broke: {e}")
            except Exception:
                pass
        finally:
            queue.task_done()


async def listen(page, agent):
    queue, seen = asyncio.Queue(), set()
    await chat_box(page)

    if DEBUG:
        path = os.path.join(WORKSPACE, "meet-dump.html")
        with open(path, "w") as f:
            f.write(await page.content())
        log("DOM dumped to", path)

    await send(page, f"{NAME} here.")  # don't announce the trigger: it's the only access control
    await page.wait_for_timeout(2000)
    seen.update(m["id"] for m in await read_messages(page))  # ignore history + own welcome

    task = asyncio.create_task(worker(page, agent, queue))
    log(f"Listening for '{TRIGGER}' in chat.")
    try:
        while True:
            if not await leave_button(page).count():
                log("Call ended or Jamie was removed.")
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
                    await send(page, "Bye.")
                    await leave_button(page).first.click()
                    return
                if cmd.lower() in ("stop", "stop sharing"):
                    await show(page, "off")
                elif cmd.lower() == "reset":
                    agent.has_session = False
                    await send(page, "Fresh context.")
                elif not cmd:
                    await send(page, f"Usage: {TRIGGER} <request>")
                else:
                    if queue.qsize() or agent_busy(queue):
                        await send(page, f"Queued: {cmd[:80]}")
                    await queue.put(cmd)
            await asyncio.sleep(1)
    finally:
        task.cancel()


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
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await join(page, url)
            await listen(page, agent)
        finally:
            await ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--show", metavar="URL", help="screen-share URL in the running call ('off' stops)")
    ap.add_argument("--env", default=os.environ.get("JAMIE_ENV", "default"),
                    help="folder in environments/ (jamie.sh mounts it; used here for messages)")
    ap.add_argument("--agent", default=os.environ.get("JAMIE_AGENT", "claude"), help="claude | codex | gemini")
    ap.add_argument("--personality", default=os.environ.get("JAMIE_PERSONALITY", "default"),
                    help="file in personalities/ (without .md)")
    a = ap.parse_args()
    if a.login:
        asyncio.run(login())
    elif a.show:
        asyncio.run(show_cli(a.show))
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
