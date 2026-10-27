"""Hearing: Meet's live captions -> transcript.md, and a fast model that decides when Jamie is
being talked to.

Meet shows one caption block per speaker turn. Its text keeps growing, gets revised as the speech
recognizer changes its mind, and is trimmed from the front in long turns. Captions turns that into
finished lines: whatever was added since the last pause.
"""
import asyncio
import json
import os
import re
import time
from difflib import SequenceMatcher

PAUSE = 1.0  # seconds a caption block must stay unchanged before its new words count as said

# Each block: avatar + speaker name, then the text. Class names are obfuscated, so go by structure.
CAPTIONS_JS = """() => {
  const r = document.querySelector('[role=region][aria-label=Captions]');
  if (!r) return null;
  return [...r.children].filter(b => b.querySelector('img')).map(b => {
    if (!b.dataset.jamie) b.dataset.jamie = String(window.__jamieCaps = (window.__jamieCaps || 0) + 1);
    const text = b.lastElementChild;
    return { id: b.dataset.jamie, name: b.querySelector('img').parentElement.innerText.trim(),
             text: text.querySelector('img') ? '' : text.innerText.trim() };
  });
}"""


def _norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def fresh(said, text):
    """The words of `text` that come after `said` (the words already taken from this block)."""
    words = text.split()
    tail = [_norm(w) for w in said[-15:]]
    if not tail:
        return words
    m = SequenceMatcher(None, tail, [_norm(w) for w in words], autojunk=False)
    blocks = [b for b in m.get_matching_blocks() if b.size]
    # Prefer a match reaching the end of what was said. If the recognizer revised the last word or
    # two ("five" -> "fives"), skip as many words past the match.
    ends = [b.b + len(tail) - b.a for b in blocks if b.a + b.size >= len(tail) - 2]
    if not ends:
        ends = [b.b + b.size for b in blocks if b.size >= 3]
    return words[max(ends):] if ends else words  # no overlap: the old text scrolled away entirely


# Short spoken commands done the moment the captions show them: no waiting for a pause, no judge.
# Only things that are harmless if a caption was wrong (pausing a video, muting it).
QUICK = {
    "pause": r"pause|pause (it|this|that|the video|the song|the music)|stop the video|hold on,? pause( it)?",
    "play": r"resume|unpause|play it|keep playing|play the video|press play",
    "mute": r"mute|mute (it|the video|the sound)",
    "unmute": r"unmute|unmute (it|the video|the sound)",
    "skip-ad": r"skip( the)? ads?",
    "fullscreen": r"(go |make it )?full ?screen",
    "exit-fullscreen": r"(exit|leave) full ?screen",
}
FILLER = r"(?:(?:hey|hi|ok|okay|um|uh|yeah|yes|so|and|alright|now|oh)\s+)*"
POLITE = r"(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
QUICK_TAIL = re.compile(r"^\W*(it|this|that|the video|the song|the music|the sound|please|now)?\W*$", re.I)


def quick(words, names, solo=False):
    """The instant control a short spoken command asks for, or None: "Jamie, pause", "hey Jamie can you
    mute it". Without the name only when Jamie is alone with one person (solo)."""
    text = " ".join(re.sub(r"[^\w' ]", " ", " ".join(words).lower()).split())
    if not text or len(text.split()) > 10:
        return None
    m = re.fullmatch(rf"{FILLER}(?P<name>(?:{names})\s+)?{POLITE}(?P<cmd>.+?)(?:\s+please)?", text)
    if not m or not (m.group("name") or solo):
        return None
    return next((c for c, pat in QUICK.items() if re.fullmatch(pat, m.group("cmd"))), None)


class Captions:
    def __init__(self, hear_self=False):
        self.blocks = {}  # id -> {"text", "changed", "said"}
        self.hear_self = hear_self  # the end-to-end test talks through Jamie's own microphone

    def unsaid(self, block):
        """The words in a caption block (still being spoken, maybe) that haven't been taken yet."""
        st = self.blocks.get(block["id"])
        return fresh(st["said"], block["text"]) if st else block["text"].split()

    def take(self, block, now=None):
        """These words were handled already (an instant command): don't hand them out again."""
        now = time.monotonic() if now is None else now
        st = self.blocks.setdefault(block["id"], {"text": "", "changed": now, "said": [], "name": block["name"]})
        st["said"] += fresh(st["said"], block["text"])
        st["text"], st["changed"] = block["text"], now

    def feed(self, blocks, now=None):
        """Take a CAPTIONS_JS snapshot; return [(speaker, text)] for words finished by a pause."""
        now = time.monotonic() if now is None else now
        lines = []
        if blocks is not None:  # a block gone from the page (scrolled away) still said its last words
            here = {b["id"] for b in blocks}
            for gone in [i for i in self.blocks if i not in here]:
                st = self.blocks.pop(gone)
                new = fresh(st["said"], st["text"])
                if new and (st["name"] != "You" or self.hear_self) and not st["name"].endswith("Presentation"):
                    lines.append((st["name"], " ".join(new)))
        for b in blocks or []:
            st = self.blocks.setdefault(b["id"], {"text": "", "changed": now, "said": [], "name": b["name"]})
            if b["text"] != st["text"]:
                st["text"], st["changed"] = b["text"], now
            elif now - st["changed"] >= PAUSE:
                new = fresh(st["said"], st["text"])
                if new:
                    st["said"] += new
                    # "You" is Jamie's own voice; "... Presentation" is the sound of a shared tab
                    if (b["name"] != "You" or self.hear_self) and not b["name"].endswith("Presentation"):
                        lines.append((b["name"], " ".join(new)))
        return lines


JUDGE_PROMPT = """You listen to a Google Meet call for {name}, an AI assistant in the call. Speech
comes from live captions, so expect recognition errors: "{name}" often comes through as a
similar-sounding word or name ("Amy", "Jaime", "Jamey", "Jay me", "Jammy"). If that name isn't one
of the people in the call, it's {name}. Captions also turn commands into the past tense: "{name}
showed the answer", "{name} paused it", "{name} revealed it" right after the name are almost always
the commands "show the answer", "pause it", "reveal it". Decide whether the NEW lines ask {name} to do
something.

- "request": someone asks {name} a question ("Jamie, what's the capital of Peru?", "Jamie, how
  does this work?") or asks it to do, find, show, explain, build, check or change something.
  This includes a follow-up to what {name} just said or did, even without its name. Write
  "request" as one self-contained instruction: resolve "it", "that", "this" from the context, keep
  the details, and drop filler words.
- "wait": they started asking {name} something but it isn't complete yet: the sentence is cut off,
  or the request is too vague to act on without more words (for example "can we build out?" with
  nothing it refers to in the context). Captions arrive in pieces, so the rest is usually coming.
- "control": the request matches one of the instant controls below. Put its name in "control", any
  argument in "arg", and leave "ack" empty. "That"/"this" usually means something on the shared
  screen: "play that Guardians of the Galaxy video" is "open" with arg the matching title from Visible,
  not a new search. Always prefer it over "request" when it fits, however it's phrased: "can you
  pause?", "stop the video", "hold on, pause it" are all the control "pause"; "scroll down so I can
  see" is "scroll-down". Captions often hear a command as past tense: "Jamie showed the answer" is
  the control for showing the answer, "Jamie paused it" is "pause", "Jamie revealed it" is the reveal
  control. Use "request" when it needs more than that one control ("pause it and then find the
  lyrics" is a request).
- "stop_sharing": they want {name} to stop sharing its screen. "reset": start over with a fresh
  memory. "leave": they want {name} to leave the call.
- "none": everything else, including talking ABOUT {name} rather than to it, small talk, and
  questions people ask each other or themselves without addressing {name}, even ones you could
  answer ("What's the capital of Australia? I always forget" is "none").
  When unsure, choose "none".

"ack" is a very short, natural reply {name} says right away for request/stop_sharing/reset/leave
(for example "Sure, pulling up the video."). It's said before the work starts, so never claim it's
done ("Done", "It's fullscreen now"). Leave it empty otherwise. Each message is a new
moment in the same call; judge only its NEW lines. {busy}

For a "request" that is a quick question with a short, stable answer you are certain of (a capital
city, simple arithmetic, a definition), also put the answer in "answer" as a full sentence that restates the question ("The capital of
Australia is Canberra.", not just "Canberra."), and {name}
says it right away instead of starting its slower assistant. Leave "answer" empty for everything
else: anything current (news, weather, prices, "latest"), about the screen or the meeting, needing
a tool, or anything you aren't sure of.

Instant controls (name: what it does):
{controls}

Reply with only one line of JSON: {{"action": "...", "request": "...", "control": "...", "arg": "...", "answer": "...", "ack": "..."}}"""


def verdict(text):
    """The judge's JSON reply, even wrapped in a code fence or a sentence."""
    v = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return {"action": v.get("action", "none"), "request": v.get("request") or "", "ack": v.get("ack") or "",
            "control": v.get("control") or "", "arg": v.get("arg") or "", "answer": v.get("answer") or ""}


VALID = ("none", "wait", "request", "control", "stop_sharing", "reset", "leave")


class Judge:
    """Asks a fast model whether the new lines are for Jamie. Falls back to the wake word.

    Every judgment gets a fresh Claude process: one that has seen its own earlier answers starts
    copying them (one early miss turned a whole run of controls into requests). The next process is
    started as soon as one is used, so a judgment never waits for Claude to start. No extended
    thinking and plain JSON text (not --json-schema, which adds a round trip): ~1s instead of 3-5s."""

    def __init__(self, name, controls=None, model="haiku", timeout=30):
        self.name, self.model, self.timeout = name, model, timeout
        self.controls = controls or {}
        self.wake = re.compile(rf"\b({re.escape(name)}|jaime|jamey|amy)\b", re.I)  # captions mishear it
        self.proc, self.lock = None, asyncio.Lock()  # proc: the started, unused process for the next judgment

    def command(self):
        system = JUDGE_PROMPT.format(name=self.name, busy="",
                                     controls="\n".join(f"{k}: {v}" for k, v in self.controls.items()) or "(none)")
        return ["claude", "-p", "--model", self.model, "--tools", "", "--no-session-persistence",
                "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--system-prompt", system]

    async def spawn(self):
        return await asyncio.create_subprocess_exec(
            *self.command(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=2**22, env={**os.environ, "MAX_THINKING_TOKENS": "0"})

    async def ask(self, prompt):
        if not self.proc or self.proc.returncode is not None:
            self.proc = await self.spawn()
        proc, self.proc = self.proc, await self.spawn()  # this one answers; the next is already starting
        try:
            msg = {"type": "user", "message": {"role": "user", "content": prompt}}
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            while line := await proc.stdout.readline():
                event = json.loads(line)
                if event.get("type") == "result":
                    try:
                        return verdict(event.get("result") or "")
                    except ValueError as e:
                        raise ValueError(f"not JSON: {(event.get('result') or '')[:200]!r}") from e
            raise RuntimeError("judge process ended")
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def warm_up(self):
        """Start the process and make one call, while Jamie joins, so the first real one is fast."""
        await self([], [("System", "(warm-up, nobody has spoken yet)")])

    async def __call__(self, context, new, last_reply="", busy="", people=(), screen="", others=None):
        fmt = lambda ls: "\n".join(f"{s}: {t}" for s, t in ls)  # noqa: E731
        solo = (f"Only one person is in this call with {self.name}, so there's nobody else for them to talk to: "
                f"a question or ask from them is a \"request\" to {self.name} even without its name, unless it's "
                f"clearly for someone else (a phone call, someone in their room) or they're thinking out loud. "
                f"A garbled or unfamiliar name at the start (\"Hey Gabeet, a video about ...\") is {self.name} "
                f"misheard, and half-sentences like \"for a video about X\" are still a request. "
                f"Greetings and chatter are still \"none\".\n\n") if others == 1 else ""
        prompt = (f"{solo}People in the call (heard so far): {', '.join(people) or 'unknown'}\n\n"
                  f"{screen or 'Nothing is being shared.'}\n\n"
                  f"Earlier conversation:\n{fmt(context) or '(none)'}\n\n"
                  f"{self.name}'s last reply: {last_reply or '(none)'}\n"
                  f"{self.name} is busy with: {busy or '(nothing)'}\n\nNEW lines:\n{fmt(new)}")
        try:
            async with self.lock:
                verdict = await asyncio.wait_for(self.ask(prompt), self.timeout)
            action = verdict["action"].removeprefix("control:")
            if action in self.controls:  # it sometimes answers with the control's name as the action
                verdict["action"], verdict["control"] = "control", action
            elif action not in VALID and verdict["control"] in self.controls:  # ...or names the control, no action
                verdict["action"] = "control"
            if verdict["control"] in ("leave", "stop_sharing", "reset"):  # ...or these in the wrong field
                verdict["action"], verdict["control"] = verdict["control"], ""
            if verdict["answer"] and verdict["action"] in ("none", "", "answer"):  # it answered: so it was for Jamie
                verdict["action"] = "request"
            if verdict["action"] not in VALID:
                raise ValueError(f"unexpected verdict {verdict}")
            if verdict["action"] == "control" and verdict["control"] not in self.controls:
                verdict["action"] = "request"  # not a control we have: let the agent figure it out
            return verdict
        except Exception as e:  # no Claude login, timeout, bad output: fall back to the wake word
            print(time.strftime("%H:%M:%S"), "judge failed, using the wake word:", repr(e)[:300], flush=True)
            await self.close()  # out of sync now; the next call starts a fresh one
            text = " ".join(t for _, t in new)
            if self.wake.search(text):
                return {"action": "request", "request": text, "ack": "On it.", "control": "", "arg": ""}
            return {"action": "none", "request": "", "ack": "", "control": "", "arg": ""}
