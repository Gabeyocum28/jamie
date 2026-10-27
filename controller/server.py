"""Jamie controller: an HTTP API that starts one Jamie container per meeting.

Runs in its own container with the host's Docker socket (./jamie.sh controller). Each Jamie gets
a copy of the agent logins, so instances never share an agent session. For Google, each Jamie
borrows a free signed-in profile (a jamie-google-<name> volume) and uses it directly, not a copy:
Google ends sessions whose cookies get replayed from stale copies.

  GET    /options        environments, personalities, agents, projects (for the extension's dropdowns)
  GET    /jamies         running Jamies with their screen and app links
  POST   /jamies         {"meet_url", "env", "personality", "agent", "project"} -> starts one
  DELETE /jamies/<id>    stops it (it drops out of the call)
  POST   /projects       {"repo", "token"} -> clones a git repo into the projects folder
                         {"folder"} -> links a folder where it is (Jamie works on the original)

Projects are your own folders: every folder in the projects folder (~/jamie-projects, mounted at
/projects), plus any listed in JAMIE_PROJECTS (.env, mounted at /linked/<name>). A Jamie started with
one gets that same folder, live, at /workspace/project.

Every request needs "Authorization: Bearer $JAMIE_CONTROLLER_TOKEN".
"""
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = os.environ.get("JAMIE_ROOT", "/jamie")        # this repo: Dockerfile, jamie/, environments/, personalities/
LOGINS = os.environ.get("JAMIE_LOGINS", "/logins")   # login volumes, copied into every new Jamie
PROJECTS = os.environ.get("JAMIE_PROJECTS_DIR", "/projects")  # the projects folder: each folder in it is a project
LINKED = os.environ.get("JAMIE_LINKED_DIR", "/linked")        # JAMIE_PROJECTS folders from elsewhere, one mount each
PROJECTS_SHOWN = os.environ.get("JAMIE_PROJECTS_SHOWN", "")   # where people find the projects folder on their computer
# From ./jamie.sh, which runs on the computer itself: its OS (mac | linux | wsl), the user folders people may
# link folders from (the Linux/Mac home; on WSL also the Windows one), and where WSL mounts Windows drives
HOST_OS = os.environ.get("JAMIE_HOST_OS", "linux")
HOMES = [h for h in os.environ.get("JAMIE_HOST_HOMES", "").split(":") if h.startswith("/")]
WSL_DRIVES = os.environ.get("JAMIE_WSL_DRIVES") or "/mnt"
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
        "projects": project_names(),
        "projects_home": PROJECTS_SHOWN,
        "host_os": HOST_OS,  # the popup's path example and tip
    }


def projects():
    """Project name -> its folder here: the projects folder's folders, plus the JAMIE_PROJECTS links."""
    found = {}
    for base in (PROJECTS, LINKED):
        if os.path.isdir(base):
            found.update({d: f"{base}/{d}" for d in os.listdir(base)
                          if not d.startswith(".") and os.path.isdir(f"{base}/{d}")})
    return found


def links():
    """Folders linked from the extension, where they are: name -> path on the host (not mounted here)."""
    try:
        with open(f"{PROJECTS}/.jamie-links.json") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def project_names():
    return sorted({**links(), **projects()})


EXAMPLE = {"mac": "/Users/you/Documents/sales", "linux": "/home/you/sales",
           "wsl": "C:\\Users\\you\\Documents\\sales"}.get(HOST_OS, "/home/you/sales")


def home_of(path):
    """The user folder (from JAMIE_HOST_HOMES) this path is inside, or None. The user folder itself doesn't count."""
    return next((h for h in HOMES if path.startswith(h.rstrip("/") + "/")), None)


def host_folder(folder):
    """A folder as people paste it -> its path for Docker. On WSL, C:\\Users\\you\\sales and \\\\wsl.localhost\\
    Ubuntu\\home\\you\\sales become WSL paths. Only folders inside the user's own user folder(s): never a whole
    drive, a whole home, a system folder or someone else's home."""
    p = folder.strip().strip('"').strip("'")  # Explorer's "Copy as path" adds quotes
    if HOST_OS == "wsl" and (m := re.fullmatch(r"([A-Za-z]):[\\/](.*)", p)):
        p = f"{WSL_DRIVES.rstrip('/')}/{m[1].lower()}/" + m[2].replace("\\", "/")
    elif HOST_OS == "wsl" and (m := re.fullmatch(r"\\\\wsl(?:\.localhost|\$)\\[^\\]+\\(.*)", p, re.I)):
        p = "/" + m[1].replace("\\", "/")
    elif p.startswith("~/"):
        p = HOMES[0] + p[1:] if HOMES else p
    p = os.path.normpath(p) if p.startswith("/") else ""
    if not home_of(p):
        raise ValueError(f"Paste the full path of a folder inside your user folder, like {EXAMPLE}")
    return p


def exists(host):
    """Is there a folder at this host path? Asked through its user folder, which exists: Docker Desktop creates
    a missing folder you mount, so the folder itself can't be mounted to check."""
    home = home_of(host)
    try:
        docker("run", "--rm", "--mount", f'type=bind,"source={home}",target=/x,readonly', "--entrypoint", "test",
               "jamie-controller", "-d", "/x/" + host[len(home):].lstrip("/"))
        return True
    except RuntimeError:
        return False


def link_folder(raw):
    """Link a folder where it is: Jamie works on the original, live. The link is kept across restarts."""
    try:
        host = host_folder(raw["folder"])
    except (KeyError, TypeError, AttributeError):
        raise ValueError('expected JSON {"folder": "<full path of a folder>"}')
    linked = links()
    for name, path in linked.items():
        if path == host:  # linked already
            return {"project": name, "projects": project_names()}
    if not exists(host):
        raise ValueError(f"Can't find the folder {raw['folder'].strip()}")
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", os.path.basename(host)).strip("-")[:40] or "folder"
    name, n = base, 2
    while name in project_names():
        name, n = f"{base}-{n}", n + 1
    linked[name] = host
    with open(f"{PROJECTS}/.jamie-links.json", "w") as f:
        json.dump(linked, f, indent=2)
    return {"project": name, "projects": project_names()}


def repo_url(repo):
    """github.com/owner/repo, owner/repo or any https git URL -> (clean https URL, project name)."""
    repo = repo.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        repo = f"https://github.com/{repo}"
    elif "://" not in repo:
        repo = f"https://{repo}"
    u = urlsplit(repo)
    path = u.path.rstrip("/").removesuffix(".git")
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", path.split("/")[-1]).strip("-")[:40]
    if u.scheme != "https" or not u.hostname or u.username or u.password or "/" not in path.strip("/") or not name:
        raise ValueError("repo must look like github.com/owner/repo")
    return f"https://{u.netloc}{path}", name


def add_repo(raw):
    """Clone a repo into the projects folder. The token (for private repos) is used for this clone only:
    it isn't saved in the repo, and Jamie never sees it."""
    try:
        url, name = repo_url(raw["repo"])
        token = raw.get("token") or ""
        assert isinstance(token, str)
    except (KeyError, TypeError, AttributeError, AssertionError):
        raise ValueError('expected JSON {"repo": "github.com/owner/repo", "token": optional}')
    if not os.path.isdir(PROJECTS):
        raise LookupError("No projects folder. Restart ./jamie.sh controller")
    if name in project_names():
        raise ValueError(f"There's already a project called {name}")
    auth = ["-c", "http.extraHeader=Authorization: Basic "
            + base64.b64encode(f"x-access-token:{token}".encode()).decode()] if token else []
    dest = f"{PROJECTS}/{name}"
    try:
        r = subprocess.run(["git", *auth, "clone", "--", url, dest], capture_output=True, text=True, timeout=600,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})  # fail instead of asking for a password
    except subprocess.TimeoutExpired:
        r = None
    if not r or r.returncode:
        shutil.rmtree(dest, ignore_errors=True)
        why = "it took over 10 minutes" if not r else r.stderr.strip().splitlines()[-1][:200]
        hint = "" if token else " Private repo? Add a GitHub token in Settings."
        raise ValueError(f"Couldn't clone {url}: {why}.{hint}")
    owner = os.stat(PROJECTS)  # cloned as root here: hand it to whoever owns the projects folder
    subprocess.run(["chown", "-R", f"{owner.st_uid}:{owner.st_gid}", dest], capture_output=True)
    return {"project": name, "projects": project_names()}


def share(host):
    """Jamie runs as another user (pwuser), so make the project group-writable, with new files taking the
    folder's group: Jamie can edit it, and what Jamie writes stays editable by its owner. Returns that group.
    Done in a helper container, since linked folders aren't mounted here. Not on a Mac: Docker Desktop lets
    containers write there anyway, and every Mac account shares the group (staff)."""
    if host in links().values() and not exists(host):  # mounting it would create an empty one
        raise LookupError(f"The project folder {host} is gone. Was it moved or renamed?")
    if HOST_OS == "mac":
        return None
    try:
        return docker("run", "--rm", "--mount", f'type=bind,"source={host}",target=/x', "--entrypoint", "sh",
                      "jamie-controller", "-c",  # (a Windows drive may refuse the chmod: it's open to everyone anyway)
                      "chmod -R g+rwX /x 2>/dev/null; find /x -type d -exec chmod g+s {} + 2>/dev/null; stat -c %g /x")
    except RuntimeError:
        raise LookupError(f"The project folder {host} is gone. Was it moved or renamed?")


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
        project = raw.get("project") or ""
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
    if project and project not in opts["projects"]:  # only folders the owner listed in JAMIE_PROJECTS
        raise ValueError(f"unknown project {project!r}. Available: {', '.join(opts['projects']) or 'none (set JAMIE_PROJECTS)'}")
    req["project"] = project
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


def project_source(path):
    """The host folder behind a project folder here, as the Docker daemon names it (from this controller's
    own mounts). Reusing the daemon's own path works the same on Linux, Mac and Docker Desktop with WSL."""
    mounts = {m["Destination"]: m["Source"] for m in json.loads(docker("inspect", socket.gethostname()))[0]["Mounts"]}
    base, name = os.path.split(path)
    if path in mounts:  # a JAMIE_PROJECTS link
        return mounts[path]
    if base in mounts:  # a folder in the projects folder
        return f"{mounts[base]}/{name}"
    raise LookupError(f"{path} isn't mounted. Restart ./jamie.sh controller")


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
    if req.get("project"):  # their real files, live: what Jamie changes there stays changed
        here = projects().get(req["project"])
        host = project_source(here) if here else links()[req["project"]]
        gid = share(host)
        flags += ["-v", f"{host}:/workspace/project", *(["--group-add", gid] if gid else [])]
    for k in ("meet_url", "env", "personality", "agent", "project"):
        flags += ["--label", f"jamie.{k}={req.get(k, '')}"]
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
    jamie = info(json.loads(docker("inspect", name))[0])
    try:  # Jamie's apps are on random host ports: tell it the links people can actually open
        docker("exec", name, "sh", "-c", f"echo {shlex.quote(json.dumps(jamie['apps']))} > /tmp/jamie-urls.json")
    except RuntimeError as e:
        print("Couldn't tell", name, "its app links:", e, flush=True)
    return jamie


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
        **{k: labels.get(f"jamie.{k}") for k in ("meet_url", "env", "personality", "agent", "project", "google")},
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
            if self.command == "POST" and path in ("/jamies", "/projects"):
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 65536:
                    raise ValueError("bad Content-Length")
                body = self.rfile.read(length)
                if path == "/projects":
                    raw = json.loads(body)
                    return self.reply(201, link_folder(raw) if isinstance(raw, dict) and "folder" in raw else add_repo(raw))
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
