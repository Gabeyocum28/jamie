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
print("hearing OK")
