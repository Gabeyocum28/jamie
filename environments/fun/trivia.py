"""Game-show trivia on the shared screen: question, choices, countdown, answer reveal, scoreboard.

  python3 trivia.py game.json [--go N]
  writes game.html (+ game.data.js) next to it and prints its file:// URL

game.json:
  {"title": "Movie Night Trivia",
   "questions": [{"q": "Who directed Jaws?", "choices": ["Spielberg", "Lucas", "Scott"], "a": "Spielberg",
                  "seconds": 20}, ...],
   "players": {"Ana": 0, "Ben": 0}}

"choices", "a" and "seconds" (default 20) are optional: leave out "a" for would-you-rather or polls.
Show it once: python3 /app/bot.py --show "$(python3 trivia.py game.json)"
After editing game.json (scores, new questions), run trivia.py again: the page updates within 2 seconds.
--go N also jumps to question N. Without it the page stays on the question it's showing.
Keys on the page: ArrowRight next question, ArrowLeft previous, Enter reveal answer (Space toggles), c start countdown.
"""
import argparse
import json
import os
import sys
import time

PAGE = """<!doctype html><meta charset="utf-8"><title>Trivia</title>
<style>
body { margin: 0; height: 100vh; display: grid; grid-template: auto 1fr / 1fr 300px; background: radial-gradient(
       circle at 30% 20%, #2a1b5e, #0b0a1a 70%); color: #fff; font: 28px/1.25 system-ui, sans-serif; overflow: hidden }
header { grid-column: 1 / 3; display: flex; justify-content: space-between; align-items: center; padding: 16px 32px;
         background: #00000055; font-weight: 800 }
header b { color: #ffd23f; font-size: 34px; text-transform: uppercase; letter-spacing: .06em }
main { padding: 24px 32px; display: flex; flex-direction: column; justify-content: center }
h1 { font-size: 58px; line-height: 1.15; margin: 0 0 28px }
#choices { display: grid; grid-template-columns: 1fr 1fr; gap: 16px }
#choices div { background: #ffffff18; border: 4px solid #ffffff30; border-radius: 18px; padding: 16px 20px;
               font-size: 34px; font-weight: 700 }
#choices div b { color: #ffd23f; margin-right: 12px }
#choices div.right { background: #1f7a45; border-color: #3ddc84 }
#choices div.wrong { opacity: .35 }
#answer { margin-top: 24px; font-size: 48px; font-weight: 800; color: #3ddc84 }
#clock { font: 800 64px/1 ui-monospace, Menlo, monospace; min-width: 110px; text-align: center; padding: 6px 18px;
         border-radius: 16px; background: #00000066 }
#clock.low { color: #ff5c5c } #clock.up { background: #ff5c5c; color: #fff; font-size: 40px }
aside { background: #00000055; padding: 20px; border-left: 3px solid #ffffff22 }
aside h2 { margin: 0 0 12px; font-size: 24px; color: #ffd23f; text-transform: uppercase; letter-spacing: .1em }
#board div { display: flex; justify-content: space-between; padding: 10px 14px; margin-bottom: 8px; border-radius: 12px;
            background: #ffffff12; font-size: 30px; font-weight: 700; transition: background .4s }
#board div.lead { background: #ffd23f; color: #1a1300 }
#board div.bump { background: #3ddc84; color: #002a12 }
</style>
<header><b id="title"></b><span id="clock"></span><span id="pos"></span></header>
<main><h1 id="q"></h1><div id="choices"></div><div id="answer"></div></main>
<aside><h2>Scores</h2><div id="board"></div></aside>
<script>
const SRC = __SRC__;
let D = null, i = 0, seen, shown = false, end = 0, prev = {};
const $ = id => document.getElementById(id);
function draw() {
  const qs = D.questions, q = qs[i] || { q: "Get ready!" };
  $("title").textContent = D.title || "Trivia";
  $("pos").textContent = qs.length ? `Question ${i + 1} / ${qs.length}` : "";
  $("q").textContent = q.q;
  $("choices").innerHTML = "";
  (q.choices || []).forEach((c, n) => {
    const d = document.createElement("div"), b = document.createElement("b");
    b.textContent = "ABCDEFGH"[n];
    d.append(b, c);
    if (shown && q.a !== undefined) d.className = String(c) === String(q.a) ? "right" : "wrong";
    $("choices").append(d);
  });
  $("answer").textContent = shown && q.a !== undefined ? "Answer: " + q.a : "";
  const players = Object.entries(D.players || {}).sort((x, y) => y[1] - x[1]);
  $("board").innerHTML = "";
  players.forEach(([name, score], n) => {
    const d = document.createElement("div"), s = document.createElement("span");
    s.textContent = score;
    d.append(name, s);
    d.className = score > (prev[name] ?? score) ? "bump" : n === 0 && score > 0 ? "lead" : "";
    $("board").append(d);
  });
  drawClock();
}
function drawClock() {
  const left = Math.ceil((end - Date.now()) / 1000), c = $("clock");
  c.textContent = !end ? "" : left > 0 ? left : "TIME'S UP";
  c.className = !end ? "" : left > 0 ? (left <= 5 ? "low" : "") : "up";
}
function go(n) { i = Math.max(0, Math.min(n, D.questions.length - 1)) || 0; shown = false; end = 0; draw(); }
function jamieData(d) {
  const first = !D, g = d.go || [0, 0];
  D = d; D.questions = D.questions || [];
  // Only --go moves the game, so plain updates don't undo key presses
  if (first || g[1] !== seen) { seen = g[1]; go(g[0]); }
  draw();
  // A raised score flashes for a moment, then the board settles
  setTimeout(() => { prev = Object.assign({}, D.players); draw(); }, 1500);
}
function poll() {
  const s = document.createElement("script");
  s.src = SRC + "?" + Date.now();  // a script tag, because file:// pages can't fetch() files
  s.onload = s.onerror = () => s.remove();
  document.head.append(s);
}
setInterval(() => D && drawClock(), 250);
setInterval(poll, 2000);
poll();
document.addEventListener("keydown", e => {
  if (!D || e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "ArrowRight": go(i + 1); break;
    case "ArrowLeft": go(i - 1); break;
    case " ": shown = !shown; draw(); break;
    case "Enter": shown = true; draw(); break;
    case "c": end = Date.now() + ((D.questions[i] || {}).seconds || 20) * 1000; drawClock(); break;
    default: return;
  }
  e.preventDefault();
});
</script>"""


def render(path, go=None):
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("questions", []), list) \
            or not isinstance(data.get("players", {}), dict):
        sys.exit('game.json needs {"questions": [{"q": ..., "a": ...}], "players": {"name": 0}}')
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
    ap.add_argument("json", help="game.json")
    ap.add_argument("--go", type=int, metavar="N", help="jump the page on screen to number N (1 = first)")
    args = ap.parse_args()
    print("file://" + render(args.json, args.go))
