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


class Captions:
    def __init__(self, hear_self=False):
        self.blocks = {}  # id -> {"text", "changed", "said"}
        self.hear_self = hear_self  # the end-to-end test talks through Jamie's own microphone

    def feed(self, blocks, now=None):
        """Take a CAPTIONS_JS snapshot; return [(speaker, text)] for words finished by a pause."""
        now = time.monotonic() if now is None else now
        lines = []
        for b in blocks or []:
            st = self.blocks.setdefault(b["id"], {"text": "", "changed": now, "said": []})
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
of the people in the call, it's {name}. Decide whether the NEW lines ask {name} to do something.

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
  see" is "scroll-down". Use "request" only when it needs more than that one control.
- "stop_sharing": they want {name} to stop sharing its screen. "reset": start over with a fresh
  memory. "leave": they want {name} to leave the call.
- "none": everything else, including talking ABOUT {name} rather than to it, and small talk.
  When unsure, choose "none".

"ack" is a very short, natural reply {name} says right away for request/stop_sharing/reset/leave
(for example "Sure, pulling up the video."). It's said before the work starts, so never claim it's
done ("Done", "It's fullscreen now"). Leave it empty otherwise. Each message is a new
moment in the same call; judge only its NEW lines. {busy}

Instant controls (name: what it does):
{controls}

Reply with only one line of JSON: {{"action": "...", "request": "...", "control": "...", "arg": "...", "ack": "..."}}"""


def verdict(text):
    """The judge's JSON reply, even wrapped in a code fence or a sentence."""
    v = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return {"action": v.get("action", "none"), "request": v.get("request") or "", "ack": v.get("ack") or "",
            "control": v.get("control") or "", "arg": v.get("arg") or ""}


class Judge:
    """Asks a fast model whether the new lines are for Jamie. Falls back to the wake word.

    One Claude process stays open for the whole call (stream-json in and out), so a judgment
    doesn't pay for starting Claude, and the first one doesn't land on a cold start. No extended
    thinking and plain JSON text (not --json-schema, which adds a round trip): ~1s instead of 3-5s."""

    RESTART_AFTER = 40  # judgments; each one adds to the process's conversation

    def __init__(self, name, controls=None, model="haiku", timeout=30):
        self.name, self.model, self.timeout = name, model, timeout
        self.controls = controls or {}
        self.wake = re.compile(rf"\b({re.escape(name)}|jaime|jamey|amy)\b", re.I)  # captions mishear it
        self.proc, self.calls, self.lock = None, 0, asyncio.Lock()  # one message at a time per process

    def command(self):
        system = JUDGE_PROMPT.format(name=self.name, busy="",
                                     controls="\n".join(f"{k}: {v}" for k, v in self.controls.items()) or "(none)")
        return ["claude", "-p", "--model", self.model, "--tools", "", "--no-session-persistence",
                "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--system-prompt", system]

    async def ask(self, prompt):
        if not self.proc or self.proc.returncode is not None or self.calls >= self.RESTART_AFTER:
            if self.proc and self.proc.returncode is None:
                self.proc.kill()
            self.proc = await asyncio.create_subprocess_exec(
                *self.command(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=2**22, env={**os.environ, "MAX_THINKING_TOKENS": "0"})
            self.calls = 0
        self.calls += 1
        msg = {"type": "user", "message": {"role": "user", "content": prompt}}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()
        while line := await self.proc.stdout.readline():
            event = json.loads(line)
            if event.get("type") == "result":
                return verdict(event.get("result") or "")
        raise RuntimeError("judge process ended")

    async def close(self):
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def warm_up(self):
        """Start the process and make one call, while Jamie joins, so the first real one is fast."""
        await self([], [("System", "(warm-up, nobody has spoken yet)")])

    async def __call__(self, context, new, last_reply="", busy="", people=(), screen=""):
        fmt = lambda ls: "\n".join(f"{s}: {t}" for s, t in ls)  # noqa: E731
        prompt = (f"People in the call (heard so far): {', '.join(people) or 'unknown'}\n\n"
                  f"{screen or 'Nothing is being shared.'}\n\n"
                  f"Earlier conversation:\n{fmt(context) or '(none)'}\n\n"
                  f"{self.name}'s last reply: {last_reply or '(none)'}\n"
                  f"{self.name} is busy with: {busy or '(nothing)'}\n\nNEW lines:\n{fmt(new)}")
        try:
            async with self.lock:
                verdict = await asyncio.wait_for(self.ask(prompt), self.timeout)
            assert verdict["action"] in ("none", "wait", "request", "control", "stop_sharing", "reset", "leave")
            if verdict["action"] == "control" and verdict["control"] not in self.controls:
                verdict["action"] = "request"  # not a control we have: let the agent figure it out
            return verdict
        except Exception:  # no Claude login, timeout, bad output: fall back to the wake word
            if self.proc and self.proc.returncode is None:
                self.proc.kill()  # out of sync now; the next call starts a fresh one
            self.proc = None
            text = " ".join(t for _, t in new)
            if self.wake.search(text):
                return {"action": "request", "request": text, "ack": "On it.", "control": "", "arg": ""}
            return {"action": "none", "request": "", "ack": "", "control": "", "arg": ""}
