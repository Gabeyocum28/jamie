"""Meeting board on the shared screen: agenda, a countdown for the current item, decisions, action items.

  python3 agenda.py meeting.json [--go N]
  writes meeting.html (+ meeting.data.js) next to it and prints its file:// URL

meeting.json:
  {"title": "Weekly sync",
   "items": [{"title": "Launch status", "minutes": 10, "owner": "Ana"}, ...],
   "decisions": ["Ship on Friday"],
   "actions": [{"task": "Send the release notes", "owner": "Ben", "due": "Thu"}]}

Show it once: python3 /app/bot.py --show "$(python3 agenda.py meeting.json)"
After editing meeting.json, run agenda.py again: the page on screen picks it up within 2 seconds.
--go N also jumps the board to item N and restarts its timer. Without it the board stays where it is.
Keys on the page: ArrowRight next item, ArrowLeft previous item, Space start/pause timer (s start, p pause),
a add 5 minutes.
"""
import argparse
import json
import os
import sys
import time

PAGE = """<!doctype html><meta charset="utf-8"><title>Meeting</title>
<style>
body { margin: 0; height: 100vh; display: grid; grid-template-columns: 58% 42%; background: #0f1115; color: #f5f5f5;
       font: 26px/1.3 system-ui, sans-serif; overflow: hidden }
section { padding: 28px 36px; overflow: hidden }
#side { background: #171a21; border-left: 3px solid #2a2f3a }
.label { color: #9aa3b2; font-size: 20px; text-transform: uppercase; letter-spacing: .12em; margin: 0 0 8px }
h1 { font-size: 52px; line-height: 1.15; margin: 0 }
#owner { color: #9aa3b2; margin-top: 6px }
#timer { font: 700 150px/1 ui-monospace, Menlo, monospace; margin: 16px 0 6px; color: #3ddc84 }
#timer.low { color: #ffd23f } #timer.over { color: #ff5c5c }
#state { color: #9aa3b2; font-size: 22px }
ol, ul { margin: 0 0 24px; padding-left: 1.3em }
#items li { padding: 6px 12px; border-left: 8px solid transparent; color: #9aa3b2 }
#items li.done { text-decoration: line-through; color: #5c6370 }
#items li.cur { color: #fff; background: #2a2f3a; border-left-color: #ffd23f; font-weight: 700 }
#items li span { float: right; font-weight: 400 }
#side li { margin-bottom: 10px }
#side li small { display: block; color: #ffd23f; font-size: 20px }
.empty { color: #5c6370 }
</style>
<section>
  <p class="label" id="mt">Now</p><h1 id="now"></h1><div id="owner"></div>
  <div id="timer">0:00</div><div id="state"></div>
  <p class="label" style="margin-top:28px">Agenda</p><ol id="items"></ol>
</section>
<section id="side">
  <p class="label">Decisions</p><ul id="decisions"></ul>
  <p class="label">Action items</p><ul id="actions"></ul>
</section>
<script>
const SRC = __SRC__;
let D = null, cur = 0, seen, left = 0, running = false, tick = Date.now();
const $ = id => document.getElementById(id);
function list(el, rows, html) {
  el.innerHTML = rows.length ? "" : '<li class="empty">None yet</li>';
  for (const r of rows) { const li = document.createElement("li"); html(li, r); el.append(li); }
}
function text(tag, s) { const e = document.createElement(tag); e.textContent = s; return e; }
function draw() {
  if (!D) return;
  const it = D.items[cur] || { title: "No agenda yet" };
  $("mt").textContent = (D.title || "Meeting") + " \u00b7 now";
  $("now").textContent = it.title;
  $("owner").textContent = it.owner ? "Led by " + it.owner : "";
  list($("items"), D.items, (li, r) => {
    const n = D.items.indexOf(r);
    li.className = n === cur ? "cur" : n < cur ? "done" : "";
    li.append(r.title, text("span", (r.minutes || 5) + " min"));
  });
  list($("decisions"), D.decisions || [], (li, r) => li.textContent = r);
  list($("actions"), D.actions || [], (li, r) => {
    li.append(r.task || "");
    li.append(text("small", [r.owner || "no owner", r.due ? "due " + r.due : "no date"].join(" · ")));
  });
  drawTimer();
}
function drawTimer() {
  const s = Math.ceil(Math.abs(left)), t = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  $("timer").textContent = left < 0 ? "+" + t : t;
  $("timer").className = left < 0 ? "over" : left <= 60 ? "low" : "";
  $("state").textContent = left < 0 ? "Over time" : running ? "Running" : "Paused · Space to start";
}
function go(n) {
  if (!D || !D.items.length) return;
  cur = Math.max(0, Math.min(n, D.items.length - 1));
  left = (D.items[cur].minutes || 5) * 60;
  draw();
}
function jamieData(d) {
  const first = !D, g = d.go || [0, 0];
  D = d; D.items = D.items || [];
  // Only --go moves the board, so plain updates don't undo key presses
  if (first || g[1] !== seen) { seen = g[1]; go(g[0]); }
  draw();
}
function poll() {
  const s = document.createElement("script");
  s.src = SRC + "?" + Date.now();  // a script tag, because file:// pages can't fetch() files
  s.onload = s.onerror = () => s.remove();
  document.head.append(s);
}
setInterval(() => { const n = Date.now(); if (running) left -= (n - tick) / 1000; tick = n; if (D) drawTimer(); }, 250);
setInterval(poll, 2000);
poll();
document.addEventListener("keydown", e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "ArrowRight": go(cur + 1); break;
    case "ArrowLeft": go(cur - 1); break;
    case " ": running = !running; break;
    case "s": running = true; break;
    case "p": running = false; break;
    case "a": left += 300; break;
    default: return;
  }
  e.preventDefault();
  drawTimer();
});
</script>"""


def render(path, go=None):
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
        sys.exit('meeting.json needs {"items": [{"title": ..., "minutes": ...}], ...}')
    if go is not None:
        data["go"] = [go - 1, time.time()]  # a fresh stamp, so the page jumps even to the item it was on
    base = os.path.splitext(os.path.abspath(path))[0]
    js = base + ".data.js"
    # Write then rename, so the page never loads a half-written file
    with open(js + ".tmp", "w") as f:
        f.write("jamieData(" + json.dumps(data) + ");\n")
    os.replace(js + ".tmp", js)
    with open(base + ".html", "w") as f:
        f.write(PAGE.replace("__SRC__", json.dumps(os.path.basename(js)).replace("</", "<\\/")))
    return base + ".html"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", help="meeting.json")
    ap.add_argument("--go", type=int, metavar="N", help="jump the page on screen to number N (1 = first)")
    args = ap.parse_args()
    print("file://" + render(args.json, args.go))
