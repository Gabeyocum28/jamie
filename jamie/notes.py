"""Live meeting notes: a fast model keeps notes.md current as people talk, and notes.html shows them.

notes.html is a page for the shared screen. It reloads notes.js (the notes as a JS string) every
few seconds, so it updates in place, even from file:// where fetch() isn't allowed.
"""
import asyncio
import html
import json
import os
import re
import time

PROMPT = """You keep live notes for a meeting, as it happens. You get the current notes and the newest
part of the transcript (from live captions, so expect misheard words). Return the complete updated
notes in this exact markdown shape, and nothing else:

## Summary
2-4 bullets: what the meeting is about and where it stands.

## Decisions
- What was decided (who decided, if clear)

## Action items
- [ ] Owner: what, by when (only if someone actually took it on or was asked)

## Open questions
- Things raised but not settled

Rules: keep it short and concrete, use people's names as they appear, never invent anything, drop
small talk and requests to the assistant, and write "- None yet" under an empty section."""

EMPTY = "## Summary\n- None yet\n\n## Decisions\n- None yet\n\n## Action items\n- None yet\n\n## Open questions\n- None yet\n"

PAGE = """<!doctype html><meta charset="utf-8"><title>Meeting notes</title>
<style>
  body { margin: 0; background: #0f1218; color: #e8ecf3; font: 26px/1.45 system-ui, sans-serif; }
  header { display: flex; justify-content: space-between; align-items: baseline; padding: 28px 48px 8px; }
  h1 { margin: 0; font-size: 40px; letter-spacing: .5px; }
  #when { color: #8a93a6; font-size: 20px; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 24px 40px; padding: 8px 48px 40px; }
  section { background: #171c26; border-radius: 16px; padding: 18px 26px; }
  h2 { margin: 0 0 8px; font-size: 22px; text-transform: uppercase; letter-spacing: 2px; color: #7dd3fc; }
  ul { margin: 0; padding-left: 26px; } li { margin: 6px 0; }
  li.todo { list-style: "☐  "; } li.done { list-style: "☑  "; color: #8a93a6; }
  .none { color: #5d6678; }
</style>
<header><h1>Meeting notes</h1><span id="when"></span></header>
<main id="notes"></main>
<script>
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  function render(md, when) {
    let out = "", open = false;
    for (const raw of md.split("\\n")) {
      const line = raw.trim();
      if (line.startsWith("## ")) { out += (open ? "</ul></section>" : "") + "<section><h2>" + esc(line.slice(3)) + "</h2><ul>"; open = true; }
      else if (/^- \\[[ xX]\\]/.test(line)) out += `<li class="${/\\[ \\]/.test(line) ? "todo" : "done"}">` + esc(line.replace(/^- \\[[ xX]\\]\\s*/, "")) + "</li>";
      else if (line.startsWith("- ")) out += `<li class="${/none yet/i.test(line) ? "none" : ""}">` + esc(line.slice(2)).replace(/\\*\\*(.+?)\\*\\*/g, "<b>$1</b>") + "</li>";
    }
    document.getElementById("notes").innerHTML = out + (open ? "</ul></section>" : "");
    document.getElementById("when").textContent = when ? "updated " + when : "";
  }
  function reload() {  // a <script> tag can load from file://, fetch() can't
    const s = document.createElement("script");
    s.src = "notes.js?" + Date.now();
    s.onload = s.onerror = () => s.remove();
    document.head.append(s);
  }
  window.notesLoaded = render;
  reload();
  setInterval(reload, 3000);
</script>"""


class Notes:
    """Keeps notes.md / notes.js / notes.html in `folder` up to date from transcript lines."""

    def __init__(self, folder, model="haiku", every=45, min_lines=4):
        self.folder, self.model, self.every, self.min_lines = folder, model, every, min_lines
        self.lines, self.new, self.last, self.running = [], 0, 0.0, None
        self.md = EMPTY
        self.write()

    def path(self, name):
        return os.path.join(self.folder, name)

    def write(self):
        with open(self.path("notes.md"), "w") as f:
            f.write(self.md)
        with open(self.path("notes.js"), "w") as f:
            f.write(f"window.notesLoaded({json.dumps(self.md)}, {json.dumps(time.strftime('%H:%M'))});\n")
        if not os.path.exists(self.path("notes.html")):
            with open(self.path("notes.html"), "w") as f:
                f.write(PAGE)

    def add(self, speaker, text):
        self.lines.append(f"{speaker}: {text}")
        self.new += 1

    def due(self):
        return (self.new >= self.min_lines and time.monotonic() - self.last > self.every
                and not (self.running and not self.running.done()))

    def update_soon(self):
        """Refresh the notes in the background when enough new talk has piled up."""
        if self.due():
            self.running = asyncio.create_task(self.update())

    async def update(self):
        self.last, self.new = time.monotonic(), 0
        prompt = (f"Current notes:\n{self.md}\n\nNewest transcript:\n" + "\n".join(self.lines[-120:]))
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--model", self.model, "--tools", "", "--no-session-persistence",
            "--system-prompt", PROMPT, prompt, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "MAX_THINKING_TOKENS": "0"})
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return self.md
        except asyncio.CancelledError:  # someone waiting on us gave up: don't leave it running
            proc.kill()
            raise
        md = out.decode(errors="replace").strip()
        md = re.sub(r"^```\w*\n|\n```$", "", md)  # sometimes fenced
        if "## Summary" in md and "## Action items" in md:  # keep the old notes over a bad answer
            self.md = md[md.index("## Summary"):] + "\n"
            self.write()
        return self.md

    def recap(self, limit=1100):
        """Decisions and action items as chat text, for the end of the meeting."""
        keep, part = [], None
        for line in self.md.splitlines():
            if line.startswith("## "):
                part = line[3:].strip()
                if part in ("Decisions", "Action items"):
                    keep.append(part + ":")
            elif part in ("Decisions", "Action items") and line.strip().startswith("-") and "none yet" not in line.lower():
                keep.append("  " + re.sub(r"^- \[[ xX]\]\s*", "- ", line.strip()))
        text = "\n".join(k for i, k in enumerate(keep) if not (k.endswith(":") and (i + 1 == len(keep) or keep[i + 1].endswith(":"))))
        return html.unescape(text)[:limit]
