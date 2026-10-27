"""Put math on the shared screen.

  python3 board.py 'text with $inline$ and $$display$$ LaTeX' [image.png ...]
  echo '...' | python3 board.py - [image.png ...]
"""
import html
import os
import subprocess
import sys

KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.22/dist"
PAGE = """<!doctype html><meta charset="utf-8"><title>Board</title>
<link rel="stylesheet" href="{k}/katex.min.css">
<script defer src="{k}/katex.min.js"></script>
<script defer src="{k}/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters: [{{left: '$$', right: '$$', display: true}},
  {{left: '$', right: '$', display: false}}], throwOnError: false}})"></script>
<style>body {{ font: 32px/1.5 system-ui, sans-serif; margin: 48px; background: #fff; color: #111 }}
#t {{ white-space: pre-wrap }} img {{ max-width: 100%; max-height: 70vh; display: block; margin-top: 24px }}</style>
<div id="t">{text}</div>{imgs}"""


def write(text, images, out):
    imgs = "".join(f'<img src="{html.escape(os.path.abspath(i))}">' for i in images)
    with open(out, "w") as f:
        f.write(PAGE.format(k=KATEX, text=html.escape(text), imgs=imgs))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    text = sys.stdin.read() if sys.argv[1] == "-" else sys.argv[1]
    missing = [i for i in sys.argv[2:] if not os.path.isfile(i)]
    if missing:
        sys.exit(f"No such image: {', '.join(missing)}")
    path = write(text, sys.argv[2:], os.path.abspath("board.html"))
    sys.exit(subprocess.call(["python3", "/app/bot.py", "--show", f"file://{path}"]))
