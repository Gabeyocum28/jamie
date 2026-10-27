"""Jamie controller: an HTTP API that starts one Jamie container per meeting.

Runs in its own container with the host's Docker socket (./jamie.sh controller). Each Jamie gets
a copy of the agent logins, so instances never share an agent session. For Google, each Jamie
borrows a free signed-in profile (a jamie-google-<name> volume) and uses it directly, not a copy:
Google ends sessions whose cookies get replayed from stale copies.

  GET    /options        environments, personalities, agents (for the extension's dropdowns)
  GET    /jamies         running Jamies with their screen and app links
  POST   /jamies         {"meet_url", "env", "personality", "agent"} -> starts one
  DELETE /jamies/<id>    stops it (it drops out of the call)

Every request needs "Authorization: Bearer $JAMIE_CONTROLLER_TOKEN".
"""
import json
import os
import re
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = os.environ.get("JAMIE_ROOT", "/jamie")        # this repo: Dockerfile, jamie/, environments/, personalities/
LOGINS = os.environ.get("JAMIE_LOGINS", "/logins")   # login volumes, copied into every new Jamie
TOKEN = os.environ.get("JAMIE_CONTROLLER_TOKEN", "")
# shortcut: ports listen on the host's localhost; on the homelab set JAMIE_BIND/JAMIE_HOST to its Tailscale IP
BIND = os.environ.get("JAMIE_BIND", "127.0.0.1")
HOST = os.environ.get("JAMIE_HOST", "localhost")
AGENTS = ("claude", "codex", "gemini")
LOOK_KEYS = ("eyes", "mouth", "color", "motion", "accessory")
PORTS = (6080, 3000, 5173, 8000)
LOGIN_DIRS = {"claude": "/home/pwuser/.claude", "codex": "/home/pwuser/.codex",
              "gemini": "/home/pwuser/.gemini"}
build_lock = threading.Lock()
start_lock = threading.Lock()  # two starts must not borrow the same Google profile


def docker(*args):
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"docker {args[0]}: {r.stderr.strip()[-500:]}")
    return r.stdout.strip()


def options():
    envs = f"{ROOT}/environments"
    return {
        "environments": sorted(d for d in os.listdir(envs) if os.path.isfile(f"{envs}/{d}/ROOM.md")),
        "personalities": sorted(f[:-3] for f in os.listdir(f"{ROOT}/personalities") if f.endswith(".md")),
        "agents": list(AGENTS),
    }


def parse(body):
    """Validate a start request; the names end up in docker args and paths."""
    opts = options()
    try:
        raw = json.loads(body)
        u = urlsplit(raw["meet_url"])
        req = {k: raw.get(k, d) for k, d in
               (("env", "default"), ("personality", "default"), ("agent", "claude"))}
        look = raw.get("look") or {}
        voice = raw.get("voice", True)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('expected JSON {"meet_url": ..., "env": ..., "personality": ..., "agent": ...}')
    code = re.fullmatch(r"(?:/meet)?/([a-z]{3}-[a-z]{4}-[a-z]{3})", u.path)  # some Meet tabs show /meet/<code>
    if u.scheme != "https" or u.netloc != "meet.google.com" or not code:
        raise ValueError("meet_url must look like https://meet.google.com/abc-defg-hij")
    for key, allowed in (("env", opts["environments"]), ("personality", opts["personalities"]),
                         ("agent", opts["agents"])):
        if req[key] not in allowed:
            raise ValueError(f"unknown {key} {req[key]!r}. Available: {', '.join(allowed)}")
    # The avatar's look: avatar.js ignores names it doesn't know, so only the shape is checked here
    if not isinstance(look, dict) or not all(
            k in LOOK_KEYS and isinstance(v, str) and re.fullmatch(r"[a-z0-9-]{1,20}", v) for k, v in look.items()):
        raise ValueError(f"look must be an object with any of {', '.join(LOOK_KEYS)}")
    req["look"] = look
    if not isinstance(voice, bool):
        raise ValueError("voice must be true or false")
    req["voice"] = voice
    req["meet_url"] = f"https://meet.google.com/{code[1]}"
    return req


def image(env):
    with build_lock:  # parallel starts would build the same images twice
        docker("build", "-q", "-t", "jamie-base", ROOT)
        if os.path.isfile(f"{ROOT}/environments/{env}/Dockerfile"):
            docker("build", "-q", "-t", f"jamie-env-{env}", f"{ROOT}/environments/{env}")
            return f"jamie-env-{env}"
    return "jamie-base"


def free_google():
    accounts = [v.removeprefix("jamie-google-") for v in docker("volume", "ls", "-q").split()
                if v.startswith("jamie-google-")]
    used = docker("ps", "-a", "--filter", "label=jamie.google", "--filter", "status=created", "--filter", "status=running",
                  "--format", '{{.Label "jamie.google"}}').split()
    free = [a for a in accounts if a not in used]
    if not free:
        raise LookupError("No free Google account. Sign one in: ./jamie.sh google-login <name>" if not accounts else
                          f"All Google accounts are in use ({', '.join(accounts)}). Add one: ./jamie.sh google-login <name>")
    return free[0]


def start(req):
    env = req["env"]
    img = image(env)
    with start_lock:
        prune()
        return create(req, img, free_google())


def prune(keep=5):
    """Exited Jamies are kept so `docker logs <id>` shows why they ended; remove all but the latest few."""
    old = docker("ps", "-aq", "--filter", "label=jamie=1", "--filter", "status=exited").split()[keep:]  # newest first
    if old:
        docker("rm", *old)


def create(req, img, google):
    env = req["env"]
    name = f"jamie-{env}-{secrets.token_hex(3)}"
    flags = ["--env-file", f"{ROOT}/.env", "--label", f"jamie.google={google}", "-v", f"jamie-google-{google}:/data",
             "-v", f"jamie-learned-{env}:/learned",  # shortcuts Jamie taught itself in this room
             "-v", f"jamie-files-{env}:/files"]  # what's kept after calls: meeting notes, things Jamie built
    if os.path.isfile(f"{ROOT}/environments/{env}/.env"):
        flags += ["--env-file", f"{ROOT}/environments/{env}/.env"]
    for p in PORTS:
        flags += ["-p", f"{BIND}::{p}"]  # Docker picks a free host port, so many Jamies can run at once
    for k in ("meet_url", "env", "personality", "agent"):
        flags += ["--label", f"jamie.{k}={req[k]}"]
    # shortcut: the workspace lives in the container and is deleted when Jamie leaves; add a volume per instance to keep work
    docker("create", "--init", "--shm-size", "2g", "--name", name, "--label", "jamie=1",
           "-e", f"JAMIE_ENV={env}", "-e", f"JAMIE_LOOK={json.dumps(req['look'])}",
           "-e", f"JAMIE_VOICE={'on' if req.get('voice', True) else 'off'}", *flags, img,
           "python3", "/app/bot.py", req["meet_url"], "--env", env,
           "--personality", req["personality"], "--agent", req["agent"])
    try:
        for src, dst in LOGIN_DIRS.items():
            if os.path.isdir(f"{LOGINS}/{src}"):
                docker("cp", "-a", f"{LOGINS}/{src}/.", f"{name}:{dst}")  # -a keeps pwuser as owner
        docker("cp", f"{ROOT}/environments/{env}/.", f"{name}:/environment")
        docker("cp", f"{ROOT}/personalities/.", f"{name}:/personalities")
        docker("start", name)
    except Exception:
        docker("rm", "-f", name)
        raise
    return info(json.loads(docker("inspect", name))[0])


def status(log_lines):
    """What a Jamie is doing, from its log: the last milestone wins."""
    state = "starting"
    for line in log_lines:
        if "Opening https://meet.google.com" in line:
            state = "joining"
        elif "Waiting to be admitted" in line:
            state = "waiting to be admitted"
        elif "Listening for" in line or " -> " in line or "control:" in line:
            state = "listening"
        elif " <- " in line:
            state = "working on a request"
        elif "Call ended or Jamie was removed" in line or "Saved the meeting" in line:
            state = "left the call"
    return state


def logs(name):
    try:
        return docker("logs", "--tail", "200", name).splitlines()
    except RuntimeError:  # it went away between listing and reading
        return []


def last(log_lines, marker):
    """The text after marker on the last log line that has it ("" if none)."""
    for line in reversed(log_lines):
        if marker in line:
            return line.split(marker, 1)[1].strip()[:160]
    return ""


def info(c):
    labels = c["Config"]["Labels"]
    port = {int(k.split("/")[0]): v[0]["HostPort"] for k, v in (c["NetworkSettings"]["Ports"] or {}).items() if v}
    return {
        "id": c["Name"].lstrip("/"),
        "state": c["State"]["Status"],
        **(lambda lines: {"status": status(lines), "heard": last(lines, " heard "),
                          "said": last(lines, " -> ")})(logs(c["Name"].lstrip("/"))),
        **{k: labels.get(f"jamie.{k}") for k in ("meet_url", "env", "personality", "agent", "google")},
        "screen": f"http://{HOST}:{port[6080]}/vnc.html" if 6080 in port else None,
        "apps": {p: f"http://{HOST}:{port[p]}" for p in PORTS[1:] if p in port},
    }


def jamies():
    ids = docker("ps", "-q", "--filter", "label=jamie=1").split()
    return [info(c) for c in json.loads(docker("inspect", *ids))] if ids else []


def stop(name):
    if name not in {j["id"] for j in jamies()}:  # only ever touch containers this controller started
        raise LookupError(f"no Jamie {name!r}")
    docker("stop", "-t", "10", name)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # CORS preflight from the extension
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def handle_api(self):
        # (as bytes: compare_digest raises on non-ASCII text, and a bad header must just be refused)
        if not secrets.compare_digest(self.headers.get("Authorization", "").encode("utf-8", "replace"),
                                      f"Bearer {TOKEN}".encode()):
            return self.reply(401, {"error": "bad or missing token"})
        path = self.path.rstrip("/")
        try:
            if self.command == "GET" and path == "/options":
                return self.reply(200, options())
            if self.command == "GET" and path == "/jamies":
                return self.reply(200, jamies())
            if self.command == "POST" and path == "/jamies":
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 65536:
                    raise ValueError("bad Content-Length")
                body = self.rfile.read(length)
                return self.reply(201, start(parse(body)))
            if self.command == "DELETE" and path.startswith("/jamies/"):
                stop(path.split("/", 2)[2])
                return self.reply(200, {"stopped": path.split("/", 2)[2]})
            self.reply(404, {"error": "not found"})
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except LookupError as e:
            self.reply(404, {"error": str(e)})
        except RuntimeError as e:
            self.reply(500, {"error": str(e)})

    do_GET = do_POST = do_DELETE = handle_api


if __name__ == "__main__":
    if len(TOKEN) < 16:
        raise SystemExit("Set JAMIE_CONTROLLER_TOKEN (16+ characters) in .env")
    print("Jamie controller on :7070", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 7070), Handler).serve_forever()
