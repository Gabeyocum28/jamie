"""The code room's shared screen: code typing itself out on the left, the live app on the right.

  python3 studio.py start            put the Studio on screen (and start watching the working folder)
  python3 studio.py serve <folder>   serve a static app (index.html) on port 8000, shown live on the right
  python3 studio.py preview <url>    show an app you serve yourself (Flask, Vite...) on the right

Every code file saved in the working folder is typed out on the left (only the part that changed), and
the app on the right reloads after each save. The page itself is studio.html.
"""
import asyncio
import http.server
import os
import socket
import subprocess
import sys
import time

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))  # the working folder: room files are copied into it
PAGE = f"file://{HERE}/studio.html"
CDP = "http://localhost:9222"
PORT = 8000
CODE = (".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".css", ".py", ".json", ".sh", ".md")
SKIP = {"studio.html", "studio.py", "CLAUDE.md", "AGENTS.md", "GEMINI.md", "ROOM.md", "transcript.md"}
WATCHER, SERVER = "/tmp/jamie-studio-watch.pid", "/tmp/jamie-studio-serve.pid"
TOO_BIG = 60_000  # bigger files are shown at once, not typed


def code_files():
    for d, dirs, fs in os.walk(HERE):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__", "venv", ".venv")]
        for f in fs:
            rel = os.path.relpath(os.path.join(d, f), HERE)
            if f.endswith(CODE) and rel not in SKIP and not f.startswith("notes"):
                yield rel


def changed_part(old, new):
    """(pre, suf): how much of the start and the end of the file stayed the same."""
    pre = 0
    while pre < min(len(old), len(new)) and old[pre] == new[pre]:
        pre += 1
    suf = 0
    while suf < min(len(old), len(new)) - pre and old[-1 - suf] == new[-1 - suf]:
        suf += 1
    return pre, suf


def alive(pidfile):
    try:
        os.kill(int(open(pidfile).read()), 0)
        return True
    except (OSError, ValueError):
        return False


def detach(*args, pidfile):
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), *args], cwd=HERE, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(pidfile, "w") as f:
        f.write(str(proc.pid))


async def studio_tab(browser):
    return next((pg for c in browser.contexts for pg in c.pages if pg.url.startswith(PAGE)), None)


async def on_page(js, arg=None):
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        page = await studio_tab(b)
        if not page:
            sys.exit("The Studio isn't on screen. Run: python3 studio.py start")
        return await page.evaluate(js, arg)


def start():
    up = asyncio.run(_up())
    if not up:
        out = subprocess.run(["python3", "/app/bot.py", "--show", PAGE], capture_output=True, text=True)
        if out.returncode:
            sys.exit(out.stdout + out.stderr)
    if not alive(WATCHER):
        detach("watch", pidfile=WATCHER)
    print("The Studio is on screen: save code files and they type out on the left; "
          "`python3 studio.py serve <folder>` shows the app on the right.")


async def _up():
    try:
        async with async_playwright() as p:
            return bool(await studio_tab(await p.chromium.connect_over_cdp(CDP)))
    except Exception:
        return False


async def watch():
    """Type out every change to the working folder's code on the Studio, and reload the app after it."""
    known = {}
    for rel in code_files():  # what's already there isn't news
        try:
            known[rel] = (os.path.getmtime(os.path.join(HERE, rel)), open(os.path.join(HERE, rel), errors="replace").read())
        except OSError:
            pass
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        reload_at = None
        while browser.is_connected():
            page = await studio_tab(browser)
            if page:
                for rel in code_files():
                    path = os.path.join(HERE, rel)
                    try:
                        mtime = os.path.getmtime(path)
                        if rel in known and known[rel][0] == mtime:
                            continue
                        text = open(path, errors="replace").read()
                    except OSError:
                        continue
                    old = known.get(rel, (0, ""))[1]
                    known[rel] = (mtime, text)
                    if text == old:
                        continue
                    pre, suf = (len(text), 0) if len(text) > TOO_BIG else changed_part(old, text)
                    try:
                        await page.evaluate("([n, t, p, s]) => studio.type(n, t, p, s)", [rel, text, pre, suf])
                    except Exception:
                        pass  # the page was replaced mid-update: the next change shows again
                    reload_at = time.monotonic() + 0.6  # several files are often saved together: reload once
                if reload_at and time.monotonic() > reload_at:
                    reload_at = None
                    try:
                        await page.evaluate("studio.reload()")
                    except Exception:
                        pass
            await asyncio.sleep(0.25)


class NoCache(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        kind = super().guess_type(path)  # apps without <meta charset> would show "â™" for "♠" otherwise
        return kind + "; charset=utf-8" if kind.startswith("text/") or kind.endswith(("javascript", "json")) else kind

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # every reload gets the latest js and css too
        super().end_headers()

    def log_message(self, *a):
        pass


def serve(folder):
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        sys.exit(f"No folder {folder}")
    if alive(SERVER):
        os.kill(int(open(SERVER).read()), 15)
        time.sleep(0.3)
    detach("_serve", folder, pidfile=SERVER)
    for _ in range(40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                break
        time.sleep(0.1)
    else:
        sys.exit(f"Port {PORT} didn't open (is something else using it?)")
    preview(f"http://localhost:{PORT}/")


def preview(url):
    if not asyncio.run(_up()):
        start()
    asyncio.run(on_page("u => studio.preview(u)", url))
    print(f"Live on the Studio: {url} (reloads whenever you save)")


def main():
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "start":
        start()
    elif cmd == "serve" and args:
        serve(args[0])
    elif cmd == "preview" and args:
        preview(args[0])
    elif cmd == "watch":
        asyncio.run(watch())
    elif cmd == "_serve":
        handler = lambda *a, **k: NoCache(*a, directory=args[0], **k)  # noqa: E731
        http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler).serve_forever()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
