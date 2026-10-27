"""Flashcards on the shared screen, one card at a time.

  python3 quiz.py cards.json        writes cards.html next to it and prints its file:// URL
  echo '[...]' | python3 quiz.py -  reads the cards from stdin, writes quiz.html here

Cards: [{"q": "question", "a": "answer"}, ...] or {"title": "Biology ch. 3", "cards": [...]}
Show it: python3 /app/bot.py --show "$(python3 quiz.py cards.json)"
Keys on the page: ArrowRight next, ArrowLeft back, Enter show answer, Space show/hide, y got it, n missed it.
"""
import json
import os
import sys

PAGE = """<!doctype html><meta charset="utf-8"><title>Flashcards</title>
<style>
body { margin: 0; height: 100vh; display: flex; flex-direction: column; background: #0f1115; color: #f5f5f5;
       font: 28px/1.35 system-ui, sans-serif }
header, footer { display: flex; justify-content: space-between; padding: 20px 40px; color: #9aa3b2 }
header b { color: #ffd23f } .ok { color: #3ddc84 } .no { color: #ff5c5c }
main { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 0 64px;
       border: 6px solid #2a2f3a; border-radius: 28px; margin: 0 40px; background: #171a21 }
main.ok { border-color: #3ddc84 } main.no { border-color: #ff5c5c }
h1 { font-size: 60px; line-height: 1.2; margin: 0 }
#a { font-size: 52px; color: #ffd23f; margin-top: 40px; padding-top: 32px; border-top: 3px dashed #3a4050 }
#a[hidden] { display: block; visibility: hidden }
footer { font-size: 22px }
</style>
<header><b id="title"></b><span id="score"></span><span id="pos"></span></header>
<main id="card"><h1 id="q"></h1><div id="a" hidden></div></main>
<footer><span>&rarr; next &nbsp; &larr; back &nbsp; Space answer</span><span>Y got it &nbsp; N missed it</span></footer>
<script>
const D = __DATA__, results = [];
let i = 0;
const $ = id => document.getElementById(id);
function draw() {
  const c = D.cards[i];
  $("title").textContent = D.title || "Flashcards";
  $("pos").textContent = `Card ${i + 1} / ${D.cards.length}`;
  $("q").textContent = c.q;
  $("a").textContent = c.a;
  const ok = results.filter(r => r === true).length, no = results.filter(r => r === false).length;
  $("score").innerHTML = `<span class="ok">&#10003; ${ok}</span> &nbsp; <span class="no">&#10007; ${no}</span>`;
  $("card").className = results[i] === true ? "ok" : results[i] === false ? "no" : "";
}
function go(n) { i = Math.max(0, Math.min(n, D.cards.length - 1)); $("a").hidden = true; draw(); }
function mark(r) { results[i] = r; $("a").hidden = false; draw(); }
document.addEventListener("keydown", e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "ArrowRight": go(i + 1); break;
    case "ArrowLeft": go(i - 1); break;
    case " ": $("a").hidden = !$("a").hidden; break;
    case "Enter": $("a").hidden = false; break;
    case "y": mark(true); break;
    case "n": mark(false); break;
    default: return;
  }
  e.preventDefault();
});
draw();
</script>"""


def load(f):
    data = json.load(f)
    if isinstance(data, list):
        data = {"cards": data}
    cards = data.get("cards")
    if not cards or not all(isinstance(c, dict) and c.get("q") and c.get("a") for c in cards):
        sys.exit('Need a non-empty list of cards like {"q": "question", "a": "answer"}')
    return data


def write(data, out):
    with open(out, "w") as f:
        f.write(PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))  # no early </script>
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(len(sys.argv) != 2)
    src = sys.argv[1]
    if src == "-":
        data, out = load(sys.stdin), "quiz.html"
    else:
        with open(src) as f:
            data = load(f)
        out = os.path.splitext(src)[0] + ".html"
    print("file://" + write(data, os.path.abspath(out)))
