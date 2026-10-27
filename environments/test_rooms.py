"""Self-check for the study, work and fun rooms' on-screen tools. Run: python3 environments/test_rooms.py

Renders sample data, checks the HTML and that every controls.json key is one the page handles.
If Python Playwright and Google Chrome are installed, it also presses the keys in a headless
browser and checks the live update (skipped otherwise).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
SAMPLES = {
    "study": ("quiz.py", "cards.json", {"title": "Bio", "cards": [
        {"q": "What makes ATP? </script>", "a": "Mitochondria"}, {"q": "Cell wall?", "a": "Plants"}]}),
    "work": ("agenda.py", "meeting.json", {"title": "Sync", "items": [
        {"title": "Launch", "minutes": 10, "owner": "Ana"}, {"title": "Hiring", "minutes": 1}],
        "decisions": ["Ship Friday"], "actions": [{"task": "Notes", "owner": "Ben", "due": "Thu"}]}),
    "fun": ("trivia.py", "game.json", {"title": "Movies", "questions": [
        {"q": "Who directed Jaws?", "choices": ["Spielberg", "Lucas"], "a": "Spielberg", "seconds": 3},
        {"q": "Cats or dogs?", "choices": ["Cats", "Dogs"]}], "players": {"Ana": 0, "Ben": 2}}),
}
EXPECT = {"study": ['id="q"', 'id="a"', 'id="score"'], "work": ['id="timer"', 'id="items"', 'id="actions"',
          "meeting.data.js"], "fun": ['id="clock"', 'id="board"', 'id="choices"', "game.data.js"]}


def event_key(k):  # Playwright key name -> KeyboardEvent.key
    return " " if k == "Space" else k


def render(room):
    tool, name, data = SAMPLES[room]
    path = os.path.join(TMP, name)
    with open(path, "w") as f:
        json.dump(data, f)
    out = subprocess.run([sys.executable, os.path.join(HERE, room, tool), path], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out.startswith("file://") and out.endswith(".html") and os.path.isfile(out[7:]), out
    return out, path


def static_checks():
    for room, (tool, _, _) in SAMPLES.items():
        help_out = subprocess.run([sys.executable, os.path.join(HERE, room, tool), "--help"], capture_output=True,
                                  text=True)
        assert help_out.returncode == 0 and "python3 " + tool in help_out.stdout, room
        url, _ = render(room)
        page = open(url[7:]).read()
        for want in EXPECT[room]:
            assert want in page, (room, want)
        assert page.count("</script>") == 1, f"{room}: data broke out of the script tag"
        handled = set(re.findall(r'case "([^"]+)"', page))
        with open(os.path.join(HERE, room, "controls.json")) as f:
            controls = json.load(f)
        assert controls and os.path.isfile(os.path.join(HERE, room, "ROOM.md")), room
        for name, c in controls.items():
            assert c["description"] and c["keys"], (room, name)
            for k in c["keys"]:
                assert event_key(k) in handled, f"{room}/{name}: page doesn't handle {k}"
        print(f"ok {room}: {tool} renders, {len(controls)} controls all handled ({', '.join(sorted(handled))})")
    bad = subprocess.run([sys.executable, os.path.join(HERE, "study", "quiz.py"), "-"], input="[]",
                         capture_output=True, text=True)
    assert bad.returncode != 0 and "Need" in bad.stderr, "empty deck should fail clearly"
    print("ok bad input fails with a message")


def browser_checks():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return print("skip browser checks: no Python Playwright")
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome")
        except Exception as e:
            return print("skip browser checks: no Chrome:", str(e).splitlines()[0])
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        text = lambda sel: pg.inner_text(sel)

        pg.goto(render("study")[0])
        assert "What makes ATP? </script>" in text("#q") and not pg.is_visible("#a")
        pg.keyboard.press("Enter")
        assert pg.evaluate("!document.getElementById('a').hidden")
        pg.keyboard.press("y"); pg.keyboard.press("ArrowRight")
        assert text("#q") == "Cell wall?" and "2 / 2" in text("#pos") and "✓ 1" in text("#score")
        pg.keyboard.press("ArrowLeft")
        assert "1 / 2" in text("#pos")
        assert pg.evaluate("parseFloat(getComputedStyle(document.getElementById('q')).fontSize)") >= 48
        print("ok study page: Enter shows answer, y scores, arrows move")

        url, path = render("work")
        pg.goto(url)
        pg.wait_for_function("document.getElementById('now').textContent === 'Launch'")
        assert text("#timer") == "10:00" and "Ship Friday" in text("#decisions") and "Ben" in text("#actions")
        pg.keyboard.press("s"); time.sleep(1.3)
        assert text("#timer") in ("9:59", "9:58"), text("#timer")
        pg.keyboard.press("p"); pg.keyboard.press("a")
        assert text("#timer").startswith("14:5"), text("#timer")
        pg.keyboard.press("ArrowRight")
        assert text("#now") == "Hiring" and text("#timer") == "1:00"
        data = SAMPLES["work"][2] | {"decisions": ["Ship Friday", "Hire two"]}
        json.dump(data, open(path, "w"))
        subprocess.run([sys.executable, os.path.join(HERE, "work", "agenda.py"), path], check=True, capture_output=True)
        pg.wait_for_function("document.getElementById('decisions').innerText.includes('Hire two')", timeout=5000)
        assert text("#now") == "Hiring", "a data update without --go must not move the board"
        subprocess.run([sys.executable, os.path.join(HERE, "work", "agenda.py"), path, "--go", "1"], check=True,
                       capture_output=True)
        pg.wait_for_function("document.getElementById('now').textContent === 'Launch'", timeout=5000)
        assert text("#timer") == "10:00" and "go" not in json.load(open(path)), "--go stays out of the user's JSON"
        print("ok work page: timer runs/pauses/+5, next item, live JSON update, --go jump")

        url, path = render("fun")
        pg.goto(url)
        pg.wait_for_function("document.getElementById('q').textContent === 'Who directed Jaws?'")
        assert text("#answer") == "" and text("#board").startswith("Ben")
        pg.keyboard.press("c")
        pg.wait_for_function("document.getElementById('clock').textContent === \"TIME'S UP\"", timeout=5000)
        pg.keyboard.press("Enter")
        assert "Spielberg" in text("#answer") and pg.locator("#choices .right").count() == 1
        data = SAMPLES["fun"][2] | {"players": {"Ana": 5, "Ben": 2}}
        json.dump(data, open(path, "w"))
        subprocess.run([sys.executable, os.path.join(HERE, "fun", "trivia.py"), path], check=True, capture_output=True)
        pg.wait_for_function("document.getElementById('board').innerText.startsWith('Ana')", timeout=5000)
        assert pg.locator("#board .bump").count() == 1
        pg.keyboard.press("ArrowRight")
        assert text("#q") == "Cats or dogs?" and text("#answer") == ""
        pg.keyboard.press("Enter")
        assert text("#answer") == "", "no answer key: nothing to reveal"
        subprocess.run([sys.executable, os.path.join(HERE, "fun", "trivia.py"), path, "--go", "1"], check=True,
                       capture_output=True)
        pg.wait_for_function("document.getElementById('q').textContent === 'Who directed Jaws?'", timeout=5000)
        print("ok fun page: countdown, reveal, live score update, next question")
        pg.screenshot(path=os.path.join(TMP, "fun.png"))
        assert not errors, errors
        b.close()


if __name__ == "__main__":
    static_checks()
    browser_checks()
    print("all room checks passed; files in", TMP)
