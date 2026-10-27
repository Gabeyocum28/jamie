"""Self-check for hearing (captions -> lines, judge fallback): ./jamie.sh test"""
import asyncio

import hearing


def run(snapshots):
    """snapshots: [(seconds, [(id, name, text), ...])] -> finished lines"""
    c, out = hearing.Captions(), []
    for t, blocks in snapshots:
        out += c.feed(blocks and [{"id": i, "name": n, "text": x} for i, n, x in blocks], t)
    return out


# Words count once the block pauses; growth after that yields only the new words
assert run([(0, [("1", "Ana", "Hey")]), (1, [("1", "Ana", "Hey Jamie can you")]), (3, [("1", "Ana", "Hey Jamie can you")]),
            (4, [("1", "Ana", "Hey Jamie can you play it")]), (6, [("1", "Ana", "Hey Jamie can you play it")])]) == \
    [("Ana", "Hey Jamie can you"), ("Ana", "play it")]
# The recognizer revises the last words and trims the front of long turns: nothing repeats or gets lost
assert run([(0, [("1", "Ana", "one two three four five")]), (2, [("1", "Ana", "one two three four five")]),
            (3, [("1", "Ana", "three four fives. Six seven")]), (5, [("1", "Ana", "three four fives. Six seven")])]) == \
    [("Ana", "one two three four five"), ("Ana", "Six seven")]
# Speakers stay apart; Jamie's own voice ("You") isn't a line
assert run([(0, [("1", "Ana", "hi"), ("2", "Bo", "yo"), ("3", "You", "hello")]),
            (2, [("1", "Ana", "hi"), ("2", "Bo", "yo"), ("3", "You", "hello")])]) == [("Ana", "hi"), ("Bo", "yo")]
assert run([(0, None), (2, None)]) == []  # captions off
# A block that scrolls away before its pause still counts
assert run([(0, [("1", "Ana", "Jamie pause the video")]), (0.5, [("2", "Bo", "hi")]), (3, [("2", "Bo", "hi")])]) == \
    [("Ana", "Jamie pause the video"), ("Bo", "hi")]
# A shared video's sound gets captioned too; it isn't anyone talking
assert run([(0, [("1", "Your Presentation", "save 30 percent")]), (2, [("1", "Your Presentation", "save 30 percent")]),
            (0, [("2", "Ana's Presentation", "intro music")]), (2, [("2", "Ana's Presentation", "intro music")])]) == []

# Without a working model the judge falls back to the wake word
j = hearing.Judge("Jamie")
j.command = lambda: ["false"]
assert asyncio.run(j([], [("Ana", "Jaime, pull up the video")]))["action"] == "request"
assert asyncio.run(j([], [("Ana", "the API returns JSON")]))["action"] == "none"
assert hearing.verdict('```json\n{"action": "leave", "ack": "Bye!"}\n```') == {"action": "leave", "request": "", "ack": "Bye!", "control": "", "arg": "", "answer": ""}
# The model sometimes names the control as the action: read it as that control
j2 = hearing.Judge("Jamie", {"show-answer": "show the answer"})
async def says(text):
    j2.ask = lambda prompt: asyncio.sleep(0, result=hearing.verdict(text))
    return await j2([], [("Ana", "Jamie show the answer")])
for odd in ('{"action": "show-answer"}', '{"action": "control:show-answer"}', '{"action": "", "control": "show-answer"}'):
    v = asyncio.run(says(odd))
    assert (v["action"], v["control"]) == ("control", "show-answer"), v
v = asyncio.run(says('{"action": "none", "answer": "The capital of Australia is Canberra."}'))
assert v["action"] == "request" and v["answer"], v  # an answer means it was a question for Jamie
# Instant commands straight from live captions: short, with the name (or alone with one person), nothing more
N = "jamie|jaime|jamey"
for words, solo, want in [("Jamie pause", False, "pause"), ("Hey Jamie, pause the video, please.", False, "pause"),
                          ("Okay, pause.", True, "pause"), ("Okay, pause.", False, None), ("Jaime mute it", False, "mute"),
                          ("Yeah, can you pause this?", True, "pause"), ("I paused my video earlier", True, None),
                          ("Jamie, pause the video and find the lyrics", False, None), ("Jamie, can you resume?", False, "play"),
                          ("Jamie, play a video about cats", False, None), ("Jamie skip the ad", False, "skip-ad"),
                          ("Amy, pause", False, None), ("Jamie, what's the capital of Australia?", False, None)]:
    assert hearing.quick(words.split(), N, solo) == want, (words, solo)
assert hearing.QUICK_TAIL.match("the video.") and hearing.QUICK_TAIL.match("please") and not hearing.QUICK_TAIL.match("and find lyrics")
# Words handled that way aren't handed out again; words after them still are
c = hearing.Captions()
b = {"id": "1", "name": "Ana", "text": "Jamie pause"}
c.feed([b], now=0)
assert c.unsaid(b) == ["Jamie", "pause"]
c.take(b, now=0.1)
assert c.unsaid(b) == [] and c.feed([b], now=2) == []
b2 = {"id": "1", "name": "Ana", "text": "Jamie pause and what's next"}
c.feed([b2], now=2.1)
assert c.feed([b2], now=4) == [("Ana", "and what's next")]
print("hearing OK")
