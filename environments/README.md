# Environments (rooms)

An environment is a folder here that turns Jamie into a specialist: what it focuses on, what
software it has, which extra tools it can call. Pick one in the Chrome extension (or
`--env NAME`) when you send a Jamie. Every folder with a `ROOM.md` shows up in the dropdown.

`math/` is a complete example. Copy it to start a new room.

## What every room gets for free

You don't need to add these; they come from the shared core (`jamie/` + the root `Dockerfile`):

- Google Meet chat: people type `<trigger> <request>`, Jamie replies in chat
- Internet and a browser it controls (search, click, scroll, play/pause, fullscreen, skip ads)
- Screen sharing: `python3 /app/bot.py --show <url>` and `--show off`
- A shell with Python 3, Node 20 and git
- The agent CLI you picked: Claude Code, Codex or Gemini

## Files in a room

    environments/<name>/
      ROOM.md       required: the room's job, priorities and rules
      Dockerfile    software for this room only
      mcp.json      extra tools (MCP servers) the agent can call
      controls.json instant actions (key presses) that skip the agent
      .env          API keys for this room only (gitignored)
      setup.sh      runs every time a Jamie starts
      anything else copied into Jamie's working folder: scripts, notes, data, skills

Name the folder with letters, digits, `-` and `_` only.

### ROOM.md: behavior and priorities

Plain instructions to the agent. When a Jamie starts, it combines the shared core rules, the
chosen personality (`personalities/<name>.md`) and your `ROOM.md`. Then it writes the result to the
instructions file that the agent reads (`CLAUDE.md`, `AGENTS.md` or `GEMINI.md`). Write:

- what the room is for and what comes first ("correctness first, then clarity")
- how to work ("compute with sympy, never in your head; check every answer")
- which tools to use for what. **If a tool isn't mentioned here, Jamie may never use it.**

Keep it short and concrete. Don't edit the generated `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`;
they're rewritten on every start.

### Dockerfile: software

Must start `FROM jamie-base`. Whatever it installs exists only in this room's image.

```dockerfile
FROM jamie-base
RUN pip install --no-cache-dir --break-system-packages sympy==1.14.0 pandas==2.3.3
RUN npm install -g some-cli@1.2.3
USER root                          # apt needs root...
RUN apt-get update && apt-get install -y --no-install-recommends octave \
 && rm -rf /var/lib/apt/lists/*
USER pwuser                        # ...and Jamie must run as pwuser again
```

- Pin versions, so the room doesn't break when a package updates.
- Always end as `USER pwuser`: Claude refuses to run as root.
- No Dockerfile is fine. The room then runs on `jamie-base` as is.
- The image rebuilds automatically when you change the file. The first start after a change
  waits for the build.

### mcp.json: tools the agent calls

MCP servers are plugins that give the agent new actions (Wolfram Alpha, a database, a calendar...).
Same format Claude Code uses:

```json
{
  "mcpServers": {
    "wolfram": { "command": "npx", "args": ["-y", "<package-from-the-server's-readme>"] }
  }
}
```

- Every agent gets these (Claude, Codex and Gemini), next to the built-in `browser` server.
  Don't name one `browser`.
- Servers written in Python or another language need installing in the Dockerfile first. Then
  use their command here.
- `${VAR}` placeholders are **not** filled in. Put keys in `.env` instead; the server reads them
  from its environment.

### .env: secrets for this room

```
WOLFRAM_APP_ID=xxxx
```

Only this room's Jamies get these variables. The file is gitignored and isn't copied into the
working folder, so each teammate creates their own. In full permission mode, anyone in the call
who can use the trigger can still make Jamie print these keys. Use keys you can revoke.

### controls.json: instant actions

Simple requests skip the agent. The fast judge maps them straight to an **instant control**, and the
bot does it in about half a second instead of several seconds:
- **Built in:** pause, play, fullscreen, exit-fullscreen, mute, unmute, skip-ad, scroll-down,
  scroll-up, top, bottom.
- **Your own:** a room adds controls as key presses in the shared tab:

```json
{
  "next-slide": { "description": "go to the next slide", "keys": ["ArrowRight"] },
  "prev-slide": { "description": "go back a slide", "keys": ["ArrowLeft"] },
  "zoom-in":    { "description": "zoom in on the page", "keys": ["Control+Equal"] }
}
```

"Hey Jamie, next slide" then presses → right away. The judge reads `description` to decide when a
control fits, so make it what people would say. Key names follow
[Playwright's keyboard names](https://playwright.dev/docs/api/class-keyboard#keyboard-press), such
as `PageDown`, `Space`, `Shift+N` or `Control+Equal`. Anything a control can't cover goes to the agent.

### setup.sh: per-start setup

Runs (as `pwuser`, in the working folder) every time a Jamie starts, before it joins. Use it for
quick things: downloading a dataset, `npm install` for a starter project. Put slow installs in
the Dockerfile, not here.

### Everything else: scripts, notes, data, skills

Every other file is copied into Jamie's working folder on start. For example:

- scripts Jamie runs, like `math/board.py` (puts LaTeX and plots on the shared screen) or
  `addons/wolfram/wolfram.py` (asks Wolfram|Alpha). A script is often simpler than an MCP
  server, and every agent can run it.
- reference notes, formula sheets, problem sets, datasets
- Claude Code skills in `.claude/skills/<name>/SKILL.md`. Only Claude reads these, so anything
  essential also belongs in `ROOM.md`

## Making a new room

1. `cp -r environments/math environments/<name>`. Then rewrite `ROOM.md`, and change or delete
   the Dockerfile and scripts.
2. Try it without a call: `./jamie.sh shell --env <name>` gives a shell inside the room's image.
   Check your tools run there.
3. Send a Jamie into a test meeting with the extension, pick your room, and ask it something
   only your room can do.

## Things to know

- **Rooms can't affect each other.** Each has its own image, keys and files. Only edit `jamie/` or
  the root `Dockerfile` (shared by everyone) when the team agrees.
- **Work is temporary when started from the extension.** Each Jamie's working folder is deleted
  when it leaves. Anything worth keeping belongs in the room folder (or have Jamie push it
  somewhere). `./jamie.sh join` keeps its work in `workspace/<name>/`.
- **Which agent reads what:** all three get `ROOM.md` (as their own instructions file),
  `mcp.json` and every file. Only Claude uses `.claude/skills/`.
- **Ports 3000, 5173 and 8000** are reachable from your browser. If your room builds web apps,
  tell Jamie to serve on one of them. In the extension's list, the `:3000`, `:5173` and `:8000`
  links next to each Jamie open them.
