# Jamie

An AI teammate that joins your Google Meet calls, for work, school and fun. You talk to it like a
person ("Hey Jamie, pull up that video", "Jamie, what did we decide?"), and it listens, talks back,
shares its screen, takes notes, builds things live, runs games, and learns shortcuts as it goes.

From a Chrome extension you pick:
- an **environment**: a "room" with its own focus, tools and on-screen apps (`study`, `work`, `fun`,
  `math`, `default`)
- a **personality**: how it talks
- an **agent**: the AI that does the real work, on your own subscription (Claude Code, Codex or Gemini)
- a **look**: its animated avatar

**What it can do**
- **Hears the call.** It reads Meet's live captions, with speaker names, and knows when it's being
  talked to. That covers misheard names ("Amy" for "Jamie"), follow-ups without its name, and
  people talking *about* it rather than to it. When you're the only person in the call with it,
  you don't need its name: anything you ask is for Jamie, unless you're clearly talking to someone else.
- **Talks back.** Its voice goes into the call: offline by default, or ElevenLabs if you add a key.
  The avatar's mouth moves with the audio, and "Jamie, stop talking" cuts it off.
- **Acts instantly.** Simple requests skip the AI agent entirely:
  - pause, play, fullscreen, skip ad, scroll, go back
  - "play that video" (clicks what's on screen), "play a video about…", "show the Wikipedia page…"
  - open the code editor, show the notes
  - anything a room adds

  Each takes about a second after you finish speaking.
- **Does real work.** The agent researches, answers questions, writes and runs code live in VS
  Code on the shared screen, and builds on-screen apps (flashcards, agendas, trivia).
- **Takes meeting notes.** Live notes (summary, decisions, action items, open questions) build up
  as people talk. They can be put on screen, they're posted to chat when Jamie leaves, and they're
  saved with the transcript.
- **Learns.** When it works out something repeatable, it saves it as a new instant control for
  that room. Next time it happens in a second.

```
Chrome extension ──► controller (one container on your machine)
                        └─► builds the room's image, starts a Jamie container per meeting
                               └─► Chromium on a virtual screen joins Meet
                                     captions ─► judge (Haiku, ~1s) ─┬─► instant control (no LLM)
                                                                     └─► agent (Claude Code, kept running)
                                     voice ◄── replies               screen share ◄── stage tab
```

Every Jamie is a fresh container, deleted when it leaves. What's worth keeping (notes, transcripts,
things it built, shortcuts it learned) is kept per room in Docker volumes. Logins live in Docker
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
   **Personality** and **Agent**. Optionally open **Look** to design its avatar: eyes, mouth,
   color, motion and an accessory, with a live preview. Turn **Voice** off to keep Jamie silent (it still answers in chat). Then click **Send Jamie**. The first start of a room builds its
   image and can take a few minutes; after that it takes seconds.
3. **Admit Jamie** when Meet asks. It turns on captions and posts "Jamie here. I'm listening and
   keeping a transcript." in chat. The avatar turns purple, with orbiting sparks, while Jamie works,
   and its mouth moves when it talks.
4. **Talk to it out loud**, the way you'd talk to a teammate:

   | You say | What happens |
   |---|---|
   | "Hey Jamie, play a video about funny cats" | Searches YouTube, shares it fullscreen, skips ads (~8s, no agent) |
   | "Jamie, pause" / "play" / "scroll down" / "go back" | Instant |
   | "Jamie, play **that** Guardians of the Galaxy video" | Clicks it on the shared screen |
   | "Jamie, what's the capital of Australia?" | Answered out loud in about a second (the judge knows it, so no agent needed) |
   | "Jamie, what's the weather in Denver right now?" | The agent looks it up, then answers out loud and in chat |
   | "Hey Jamie, can we start vibe coding? Let's make a to-do app" | Opens VS Code on screen and builds it live. In the **code** room: the Studio, playable in about 30 seconds |
   | "Jamie, show the meeting notes" | Live notes, updating on screen as people talk |
   | "Jamie, let's play space trivia" (fun room) | Builds a game show; "next question", "reveal the answer" are instant |
   | "Jamie, learn a shortcut: when I say coin flip, flip a coin" | Saves it; "Jamie, coin flip" is now instant |
   | "Jamie, never mind" (while it's working) | Stops the task right away; it still remembers the conversation |
   | "Jamie, stop talking" / "stop sharing" / "you can leave" | Leaving posts the decisions and action items to chat |

   - **Follow-ups** right after Jamie answers don't need its name ("make it red instead").
   - **Talking *about* Jamie** ("Jamie is a fun tool we built") is ignored.
   - **Interrupting:** say "Jamie…" while it's talking and it stops to listen.
   - **The orb reacts:** it brightens while people are talking, turns purple with sparks while
     working, and its mouth moves when it speaks.
5. Or type in the Meet chat: the trigger, then your request:

```
/jamie pull up a video of a cat playing piano
/jamie stop                          (stop screen sharing)
/jamie reset                         (forget the conversation so far)
/jamie leave                         (leave the call)
```

Use your own `JAMIE_TRIGGER` in place of `/jamie`.

From the extension's **Running** list you can:
- **watch** Jamie's screen live
- open apps it serves with the **:3000 / :5173 / :8000** links
- **Stop** it

The meeting you're in is marked **This meeting**.

**How hearing works.** Jamie reads Meet's live captions and adds each finished line to the
transcript. Whenever someone pauses, a fast model (Claude Haiku, kept running, ~1 second) reads the
new lines. It also sees who's in the call, what's on the shared screen and what Jamie just said,
and picks one of these:
- **an instant control:** done by the bot directly, in about half a second
- **a request:** rewritten as one clear instruction for the agent. If it's a quick, stable fact
  ("capital of Australia?", "two plus two?"), the judge answers it itself, in about a second.
- **still talking:** wait for the rest
- **stop sharing / reset / leave**
- **nothing for Jamie**

The judge uses the Claude login even if the agent is Codex or Gemini. Without a Claude login it
falls back to reacting to the name. Code: `jamie/hearing.py`. `./jamie.sh judge` scores it on 36
real phrases.

**Voice.** Connect your ElevenLabs subscription from the repo folder:

```bash
npx -y @elevenlabs/cli@latest onboard connect --env-path .env
```

Sign in to your existing account and authorize the setup. The official CLI saves
`ELEVENLABS_API_KEY` in your local, gitignored `.env`. Alternatively, create a key with
**Text to Speech** access in [ElevenLabs Developers](https://elevenlabs.io/app/developers/api-keys)
and set it in `.env`. The key stays in the bot container; it is never sent to the extension or Meet.
See [ElevenLabs authentication](https://elevenlabs.io/docs/api-reference/authentication).

`ELEVENLABS_VOICE_ID` selects the voice (Rachel by default). Copy a different voice's ID from your
ElevenLabs voice library. `ELEVENLABS_MODEL_ID` defaults to `eleven_flash_v2_5` for quick replies;
the older `ELEVENLABS_MODEL` setting still works. Leave **Voice** enabled in the extension.

Verify your key, voice and model before joining a call (this generates one short paid speech sample):

```bash
./jamie.sh voice-check
./jamie.sh files                     # copies the sample to files/default/jamie-voice-check.mp3
```

Without Docker, Python 3.10+ can run the same check directly:

```bash
python jamie/voice.py --check --env-file .env --output workspace/jamie-voice-check.mp3
```

The check fails visibly for missing credentials, invalid keys, unavailable voices or exhausted
quota; it never reports an offline fallback as an ElevenLabs success. Listen to the saved MP3,
then start a new Jamie. Existing containers keep the settings they started with.

During a call, Jamie uses Piper if no key is configured or ElevenLabs fails, and logs the reason
for a fallback. `JAMIE_VOICE=off` keeps command-line runs silent; the extension's **Voice** toggle
controls extension launches. Chat gets the full text; speech gets a short reply. Audio plays in
reply order through Meet's microphone and drives the avatar's mouth. Saying "Jamie, stop talking"
cancels playback and queued replies, including audio that was still being generated or decoded.
Code: `jamie/voice.py`, `jamie/bot.py`, `extension/avatar.js`.

**What's kept.** A Jamie's working folder goes when it leaves. The meeting's notes, its part of the
transcript, and anything the agent saves to `/files` are kept per room. Copy them to your Mac with
`./jamie.sh files --env <room>`. Shortcuts Jamie taught itself are listed with `./jamie.sh learned
--env <room>`, and `--keep` writes them into the room's `controls.json` so they can be committed.

### Give Jamie your project

Jamie can work in one of your own folders, like a dashboard repo or a folder of CSVs, the same way
Claude Code does on your machine. It can read the data, run code, and fix or add charts on screen.

1. Add the project from the extension: open **Add a project** under the Project dropdown, and either:
   - paste a folder's path (`C:\Users\you\Documents\sales`; in File Explorer, right-click it and pick
     **Copy as path**) and click **Link**. Jamie works on that original folder, where it is. Only
     folders inside your user folder can be linked.
   - paste a GitHub repo (`github.com/owner/repo`) and click **Clone**. For a private repo, first add
     a GitHub token under **Settings**. The token is only used for that clone; Jamie never sees it.
   - or put any folder in the projects folder (`~/jamie-projects`; the popup shows its path, with a
     Windows Explorer path on WSL), then reopen the popup.
2. Pick it as the **Project**. The **data** room has pandas, matplotlib, seaborn and plotly ready.
   Without the extension: `./jamie.sh join <url> --env data --project ~/sales-dashboard`.
3. In the call: "Jamie, we wish we had revenue by region for last quarter as a chart", or "Jamie,
   the churn chart looks wrong: the line drops to zero in March."

The folder is mounted live at `/workspace/project`, so **Jamie's changes are real changes to your
files**. It's told to write new files instead of overwriting yours and never to touch the data
files. Still, use git, or keep a copy. Everyone in the call can direct it, so only pick a project
for calls with people you trust. Jamie runs as a different user, so starting it with a project
makes the folder group-writable (for your own group). That way Jamie can edit it, and you can edit
what Jamie writes.

A folder that has to stay where it is, like one in OneDrive, can be linked instead: add
`JAMIE_PROJECTS=name=/path,name2=/path2` to `.env` and restart the controller.
`JAMIE_PROJECTS_HOME` moves the projects folder.

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
  - `study/`, `work/` and `fun/` add flashcards, a meeting board and a trivia game show.
  - `code/` is for live coding: the Studio shows the code typing itself out next to the running app.
- **Personalities** (`personalities/<name>.md`): a few lines on how Jamie talks. See `hype.md`.
- **Addons** (`addons/<name>/`): ready-made tools a room can choose to add, such as Wolfram|Alpha.
  Read **[addons/README.md](addons/README.md)**.

Try a room without a call: `./jamie.sh shell --env <name>` opens a shell inside its image.

Only change the shared core (`jamie/`, the root `Dockerfile`, `controller/`, `extension/`) when the
team agrees. Every room depends on it.

## 5. What's in the repo

```
README.md               this file
DEMO.md                 a tested 6-minute demo script, with what to say and what happens
.env.example            template for your .env (settings and secrets, gitignored)
jamie.sh                the command for everything: setup, logins, controller, join, test, shell
Dockerfile              jamie-base: Chromium, virtual screen, the bot, and the three agent CLIs.
                        Every room builds FROM it
start.sh                starts the virtual screen and the web viewer (noVNC) in each container
jamie/
  bot.py                the bot: joins Meet, reads chat, sets up the room, runs the agent,
                        replies, screen-shares (--show)
  hearing.py            captions -> transcript, and the Haiku judge that decides when Jamie
                        is being talked to
  voice.py              text -> speech (ElevenLabs or offline Piper)
  notes.py              live meeting notes (notes.md) and the page that shows them
  cdp_filter.py         hides the Meet tab from the agent's browser tools (touching it ends the call)
  judge_eval.py         scores the judge on real phrases (./jamie.sh judge)
  e2e.py                end-to-end checks in a real Meet (./jamie.sh e2e [learn] [--env room])
  test-*.wav            recorded speech the e2e checks play through Jamie's microphone
  test_hearing.py       self-check: caption handling and the judge's fallback
  test_voice.py         self-check: what gets spoken, offline speech
  test_notes.py         self-check: the notes page and the end-of-meeting recap
  test_avatar.py        self-check: the avatar animates, also behind a screen share
  test_env.py           self-check: rooms, personalities, agent setup
  test_show.py          self-check: screen sharing against a fake Meet page
controller/
  server.py             the API the extension calls: builds images, starts and stops Jamies,
                        hands out Google accounts
  test_server.py        self-check: request validation
  Dockerfile            the controller's image (Python and the Docker CLI)
extension/              the Chrome extension (manifest, popup.html, popup.js)
  test_popup.py         checks the popup against a fake controller (python3 extension/test_popup.py)
  avatar.js             Jamie's camera: a glowing orb with a face. The popup uses it for the live
                        preview, and the image copies it in so the bot can show it in Meet
environments/           rooms; each folder is one. README.md explains everything about them
  default/              general-purpose room
  math/                 math: sympy, plots, LaTeX on screen
  study/                school: tutoring, flashcards on screen
  work/                 meetings: agenda board with timer, decisions, action items
  fun/                  hangouts: trivia game show, would-you-rather, music
  code/                 live coding: the Studio (code typing out + the live app), playable in ~30s
  test_rooms.py         checks the rooms' on-screen tools (python3 environments/test_rooms.py)
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
| volumes `jamie-learned-<room>` | instant controls Jamie taught itself in that room |
| volumes `jamie-files-<room>` | meeting notes, transcripts and things Jamie built in that room |

## 6. Command reference

```
./jamie.sh controller                 start the API the extension talks to (localhost:7070)
./jamie.sh google-login [NAME]        sign a Google account in for Jamie (screen at localhost:6080)
./jamie.sh agent-login claude|codex|gemini
./jamie.sh join <meet-url> [--env NAME] [--personality NAME] [--agent NAME]
./jamie.sh debug <meet-url> [...]     join and dump Meet's page to workspace/<env>/meet-dump.html
./jamie.sh shell [--env NAME]         a shell inside a room's image
./jamie.sh test                       run all self-checks (fast, no real call)
./jamie.sh voice-check [--env NAME]    verify ElevenLabs; save a short MP3 in the room's files
./jamie.sh judge                      score the judge on 47 real phrases (~1 min of model calls)
./jamie.sh e2e                        end-to-end check in a real Meet (~5 min, see below)
./jamie.sh e2e all                    every real-call scenario below, one after another (~35 min)
./jamie.sh e2e learn                  ...Jamie teaches itself a shortcut, then uses it
./jamie.sh e2e vibe|open|cancel       ...builds an app live / clicks what's on screen / "never mind"
./jamie.sh e2e --env fun|study|work   ...a room's on-screen app, driven by its own controls
./jamie.sh e2e --env code             ...builds a game in the Studio, plays it, changes it on request
./jamie.sh learned [--env N] [--keep] shortcuts Jamie taught itself (--keep: into controls.json)
./jamie.sh files [--env N]            copy kept notes/transcripts/work to ./files/<room>/
```

## 7. When something goes wrong

- **Extension dropdowns say "Connect first" (and the pill says Not connected or Offline)**: the controller isn't running, or the
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
- **Make sure the core still works**: `./jamie.sh test`. For the real thing, `./jamie.sh e2e`. Jamie
  starts its own Meet and joins it alone, and its microphone plays recorded speech: a video
  request, "pause the video", "open the code editor", a trivia question, a team decision, "show the
  meeting notes" and "you can leave now". It checks each one happened in the real call, from Meet
  showing Jamie presenting to Meet captioning Jamie's own voice. It needs `google-login` and an
  agent login, and the account can't be running another Jamie.
- **Jamie heard but did the wrong thing**: look for the `judge:` lines in `docker logs <id>`. Add the
  phrase to `jamie/judge_eval.py`, fix the prompt in `jamie/hearing.py`, and run `./jamie.sh judge`.

## Security

- **Anyone in the call can ask Jamie to do things, out loud or with the chat trigger.** With
  `JAMIE_PERMISSIONS=full`, that means anything inside its container. That includes reading the agent login and using its Google
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
