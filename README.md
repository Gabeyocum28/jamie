# Jamie

An AI teammate that joins your Google Meet calls. From a Chrome extension you pick three things:

- an **environment**: a "room" with its own focus, software and tools, such as `math`
- a **personality**: how it talks
- an **agent**: the AI that does the work, either Claude Code, Codex or Gemini, on your own subscription

Jamie then joins the meeting. Anyone in the call types a request in the Meet chat, and Jamie does
it. It can answer, research the web, drive its own browser (play, pause, fullscreen, skip ads),
screen-share pages and videos, write and run code, and build small web apps you can open.

```
Chrome extension ──► controller (one container on your machine)
                        └─► builds the room's image, starts a Jamie container per meeting
                               └─► Chromium on a virtual screen joins Meet, reads chat,
                                   hands each request to the agent CLI, replies in chat
```

Every Jamie is a fresh container, and it's deleted when Jamie leaves. Logins live in Docker
volumes on your machine, never in the repo.

---

## 1. What you need

- **Docker Desktop**, running. Each Jamie needs about 2 GB of RAM, and the first build downloads
  about 6 GB.
- **Google Chrome**, for the extension.
- **A Google account for Jamie** to join meetings as. A separate account is safest; see
  [Security](#security). Meet turns away signed-out guests, so Jamie must be signed in.
- **A subscription for at least one agent**: Claude (Pro/Max), ChatGPT (for Codex), or a Google
  account for Gemini.

Works on Mac (Apple Silicon or Intel) and Linux.

## 2. Set up (once per machine)

All commands run from the repo folder.

### 2.1 Create your `.env`

```bash
cp .env.example .env
```

`.env` holds your settings and secrets. It's gitignored, so it never gets committed. The main
settings:

| Setting | What it does |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude login (see 2.2) |
| `CODEX_API_KEY`, `GEMINI_API_KEY` | Optional: use API keys instead of signing in |
| `JAMIE_TRIGGER` | What people type before a request in chat. Default `/jamie`; **pick something unguessable** |
| `JAMIE_NAME` | Jamie's display name |
| `JAMIE_PERMISSIONS` | `full` (can run anything in its container) or `safe` (web search and read files only) |
| `JAMIE_TIMEOUT` | Max seconds per request |
| `JAMIE_ENV`, `JAMIE_PERSONALITY`, `JAMIE_AGENT` | Defaults for `./jamie.sh join` |
| `JAMIE_CONTROLLER_TOKEN` | Password between the extension and the controller. It's created for you in 2.4 |

### 2.2 Log in to the agent(s)

You only need the agent(s) you'll use.

**Claude Code.** Use either one of these:
- On your computer, with Claude Code installed (`npm install -g @anthropic-ai/claude-code`), run
  `claude setup-token`. Paste the token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN=...`.
- Or run `./jamie.sh agent-login claude`, type `/login`, and follow the link.

**Codex (ChatGPT):**
```bash
./jamie.sh agent-login codex
```
It prints a link and a code. Open the link, sign in to ChatGPT, and enter the code.
Or set `CODEX_API_KEY` in `.env` instead.

**Gemini:**
```bash
./jamie.sh agent-login gemini
```
Choose **Login with Google** and follow the prompts, then exit with `/quit`.
Or set `GEMINI_API_KEY` in `.env` instead.

These logins are saved in the Docker volumes `jamie-claude`, `jamie-codex` and `jamie-gemini`. Every
Jamie gets a copy when it starts.

### 2.3 Log in to Jamie's Google account

```bash
./jamie.sh google-login
```

1. Open http://localhost:6080/vnc.html and click **Connect**. You'll see Jamie's screen with
   Chromium on the Google sign-in page.
2. Sign in to the account Jamie should join meetings as, 2-step verification included.
3. **Close the Chromium window**. That saves the login and the command finishes.

That account can now run **one Jamie at a time**. To run more Jamies at once, sign in more
accounts, giving each a name:

```bash
./jamie.sh google-login second
./jamie.sh google-login third
```

Each account is saved in its own Docker volume (`jamie-google-main`, `jamie-google-second`, ...).
A running Jamie uses that saved profile directly, so the login stays valid. If Jamie ever shows
up signed out, run the same `google-login` again.

### 2.4 Start the controller

```bash
./jamie.sh controller
```

Leave it running in its own terminal. The first run creates `JAMIE_CONTROLLER_TOKEN` in `.env`.
Find it with:

```bash
sed -n 's/^JAMIE_CONTROLLER_TOKEN=//p' .env
```

### 2.5 Install the Chrome extension

The extension isn't in the Chrome Web Store. Load it from this repo:

1. Go to `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick the `extension/` folder in this repo.
4. Pin it: click the puzzle-piece icon, then the pin next to **Jamie**.
5. Click the Jamie icon, open **Settings**, paste the controller token, and click **Save**.
   Keep the controller URL as `http://localhost:7070` unless the controller runs on another
   machine.

The dropdowns should now fill in. After pulling changes to `extension/`, click the reload arrow on
the Jamie card in `chrome://extensions`.

## 3. Use it

1. Join your Google Meet as usual.
2. Click the Jamie icon. The meeting link is filled in. Pick the **Environment**,
   **Personality** and **Agent**, then click **Send Jamie**. The first start of a room builds its
   image and can take a few minutes; after that it takes seconds.
3. **Admit Jamie** when Meet asks. It posts "Jamie here." in chat.
4. Talk to it in the Meet chat by typing the trigger, then your request:

```
/jamie pull up a video of a cat playing piano and make it fullscreen
/jamie pause it                      (anything in its browser: skip ads, scroll, click...)
/jamie make a pomodoro timer web app and run it on port 3000
/jamie stop                          (stop screen sharing)
/jamie reset                         (forget the conversation so far)
/jamie leave                         (leave the call)
```

Use your own `JAMIE_TRIGGER` in place of `/jamie`.

From the extension's **Running** list you can:
- **watch** Jamie's screen live
- open apps it serves with the **:3000 / :5173 / :8000** links
- **Stop** it

The meeting you're in is shown in bold.

Each Jamie keeps its conversation for as long as it's in the call. Files it makes are deleted when
it leaves. Anything worth keeping goes in the room folder, or ask Jamie to push it somewhere.

### Without the extension

```bash
./jamie.sh join https://meet.google.com/abc-defg-hij --env math --personality hype --agent claude
```

This runs a single Jamie in your terminal, with its screen at http://localhost:6080/vnc.html and
apps at localhost:3000/5173/8000. Its files are kept in `workspace/<env>/`. Ctrl+C stops it. Don't
run it while the controller is using the same Google account.

The controller's API, which the extension uses, also works with `curl`:

```bash
T=$(sed -n 's/^JAMIE_CONTROLLER_TOKEN=//p' .env)
curl -H "Authorization: Bearer $T" localhost:7070/options
curl -H "Authorization: Bearer $T" -X POST localhost:7070/jamies \
     -d '{"meet_url":"https://meet.google.com/abc-defg-hij","env":"math","personality":"hype","agent":"claude"}'
curl -H "Authorization: Bearer $T" localhost:7070/jamies                  # running Jamies + links
curl -H "Authorization: Bearer $T" -X DELETE localhost:7070/jamies/<id>
```

## 4. Make it yours (the team's work)

Each teammate owns a room, a personality, or an addon. None of these need code changes, and new
ones show up in the extension's dropdowns on their own.

- **Rooms** (`environments/<name>/`): a room's focus, software and tools. Read
  **[environments/README.md](environments/README.md)**. `environments/math/` is a full example.
  - `ROOM.md` holds the math-first rules.
  - The `Dockerfile` installs sympy, numpy, scipy and matplotlib.
  - `board.py` screen-shares LaTeX and plots.
- **Personalities** (`personalities/<name>.md`): a few lines on how Jamie talks. See `hype.md`.
- **Addons** (`addons/<name>/`): ready-made tools a room can choose to add, such as Wolfram|Alpha.
  Read **[addons/README.md](addons/README.md)**.

Try a room without a call: `./jamie.sh shell --env <name>` opens a shell inside its image.

Only change the shared core (`jamie/`, the root `Dockerfile`, `controller/`, `extension/`) when the
team agrees. Every room depends on it.

## 5. What's in the repo

```
README.md               this file
.env.example            template for your .env (settings and secrets, gitignored)
jamie.sh                the command for everything: setup, logins, controller, join, test, shell
Dockerfile              jamie-base: Chromium, virtual screen, the bot, and the three agent CLIs.
                        Every room builds FROM it
start.sh                starts the virtual screen and the web viewer (noVNC) in each container
jamie/
  bot.py                the bot: joins Meet, reads chat, sets up the room, runs the agent,
                        replies, screen-shares (--show)
  test_env.py           self-check: rooms, personalities, agent setup
  test_show.py          self-check: screen sharing against a fake Meet page
controller/
  server.py             the API the extension calls: builds images, starts and stops Jamies,
                        hands out Google accounts
  test_server.py        self-check: request validation
  Dockerfile            the controller's image (Python and the Docker CLI)
extension/              the Chrome extension (manifest, popup.html, popup.js)
environments/           rooms; each folder is one. README.md explains everything about them
  default/              general-purpose room
  math/                 math room: the example to copy
personalities/          one .md file per personality
addons/                 tools waiting to be added to a room; README.md explains them
workspace/              files from ./jamie.sh join runs (gitignored)
.devcontainer/          open jamie-base in VS Code Dev Containers, for working on the core
```

Docker things this creates on your machine:

| Name | What it is |
|---|---|
| `jamie-base`, `jamie-env-<room>` | images: the shared core, plus one per room that has a Dockerfile |
| `jamie-controller` | the controller image and container |
| `jamie-<room>-<id>` | one running Jamie |
| volumes `jamie-google-<name>` | a signed-in Google account each |
| volumes `jamie-claude`, `jamie-codex`, `jamie-gemini` | agent logins |

## 6. Command reference

```
./jamie.sh controller                 start the API the extension talks to (localhost:7070)
./jamie.sh google-login [NAME]        sign a Google account in for Jamie (screen at localhost:6080)
./jamie.sh agent-login claude|codex|gemini
./jamie.sh join <meet-url> [--env NAME] [--personality NAME] [--agent NAME]
./jamie.sh debug <meet-url> [...]     join and dump Meet's page to workspace/<env>/meet-dump.html
./jamie.sh shell [--env NAME]         a shell inside a room's image
./jamie.sh test                       run all self-checks
```

## 7. When something goes wrong

- **Extension dropdowns say "Connect in Settings first"**: the controller isn't running, or the
  token is wrong. Start `./jamie.sh controller`, then paste the token again in Settings.
- **"No free Google account" / "All Google accounts are in use"**: sign one in, or another one
  in, with `./jamie.sh google-login <name>`. Or stop a running Jamie.
- **"You can't join this video call"**: Jamie isn't signed in. Run `./jamie.sh google-login`
  again for that account.
- **Stuck before joining**: click **watch** to see its screen. Meet may have renamed a button;
  the labels are in `join()` in `jamie/bot.py`.
- **In the call but ignores the trigger**: run `./jamie.sh debug <url>`. Open
  `workspace/<env>/meet-dump.html`, find a chat message element, and update `READ_JS` in
  `jamie/bot.py`.
- **Agent says it isn't logged in**: redo that agent's step in 2.2.
- **See what a Jamie is doing**: `docker logs -f <id>`, with the id from the extension's list or
  `docker ps`.
- **Make sure the core still works**: `./jamie.sh test`.

## Security

- **Anyone who can type the trigger in the chat can run commands as Jamie.** With
  `JAMIE_PERMISSIONS=full`, anyone in the call who knows the trigger can make Jamie do
  anything inside its container. That includes reading the agent login and using its Google
  account session for as long as Jamie is in the call. So:
  - set `JAMIE_TRIGGER` to something unguessable
  - only bring Jamie to calls with people you trust
  - use a separate Google account for Jamie
  - or set `JAMIE_PERMISSIONS=safe`
- **Containers can't touch each other.** Each Jamie is its own container, and the copy of the agent
  logins inside it is deleted when it leaves. Only the controller can reach Docker; Jamies can't.
- **The controller token is a password.** Anyone with it who can reach the controller can start
  Jamies on your subscriptions. The controller only listens on your own machine (localhost).
- **Secrets stay out of git.** `.env` files (the main one and each room's) are gitignored. Never
  commit a key.
