"""How well the judge (Haiku) reads the room: ./jamie.sh judge

Runs real calls to the model (about a second each), so it's separate from the free self-checks.
Every case is something a person actually said, or a trap that once fooled it.
"""
import asyncio
import sys
import time

import bot
import hearing

NOTHING = "Nothing is being shared."
YOUTUBE = bot.describe({
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "heading": "Rick Astley - Never Gonna Give You Up",
    "items": ["Rick Astley - Never Gonna Give You Up (Official Video)", "Guardians of the Galaxy Vol. 3 | New Trailer",
              "Mr. Blue Sky - Electric Light Orchestra (Guardians of the Galaxy 2)", "Shorts", "Subscribe", "Share"]})
WIKI = bot.describe({"url": "https://en.wikipedia.org/wiki/Octopus", "heading": "Octopus",
                     "items": ["Anatomy", "Intelligence", "Evolution", "Main page", "Random article"]})

CARDS = "Shared tab: Solar System (file:///workspace/cards.html)\nVisible: (nothing clickable)"
TRIVIA = "Shared tab: SPACE TRIVIA (file:///workspace/game.html)\nVisible: (nothing clickable)"
ROOM_CONTROLS = {"show-answer": "show the answer, flip the card, what's the answer",
                 "next-card": "next card, next question, go on to the next flashcard",
                 "reveal-answer": "reveal the answer, what was the answer, show the answer"}

# (what was said, speakers in the call, what's on screen, expected action[:control])
CASES = [
    # Questions and requests that need the agent
    ("Hey Jamie, what is the capital of Australia?", ["Gabe"], NOTHING, "request"),
    ("Jamie, can you explain recursion like I'm five?", ["Gabe"], NOTHING, "request"),
    ("Hey Jamie, can we start vibe coding? Let's make a to-do app.", ["Gabe"], NOTHING, "request"),
    ("Jamie, what is this article about?", ["Gabe"], WIKI, "request"),
    ("Jamie, summarize what we've decided so far", ["Gabe", "Sam"], NOTHING, "request"),
    ("Jamie, pause it and then find the lyrics", ["Gabe"], YOUTUBE, "request"),
    # Instant controls
    ("Hey Jamie, can you pause?", ["Gabe"], YOUTUBE, "control:pause"),
    ("Jamie, stop the video", ["Gabe"], YOUTUBE, "control:pause"),
    ("Jamie play.", ["Gabe"], YOUTUBE, "control:play"),
    ("Jay Mickey, scroll down a little bit.", ["Gabe"], WIKI, "control:scroll-down"),
    ("Jamie, can you play that Guardians of the Galaxy video?", ["Gabe"], YOUTUBE, "control:open"),
    ("Jamie play the Mr Blue Sky one", ["Gabe"], YOUTUBE, "control:open"),
    ("Hey Jamie, pull up a YouTube video about funny cats", ["Gabe"], NOTHING, "control:play-video"),
    ("Jamie, pull up the Wikipedia page for octopuses", ["Gabe"], NOTHING, "control:show"),
    ("Jamie, open the code editor", ["Gabe"], NOTHING, "control:ide"),
    ("Jamie, go back", ["Gabe"], WIKI, "control:back"),
    ("Jamie skip this ad", ["Gabe"], YOUTUBE, "control:skip-ad"),
    ("Jamie, stop talking", ["Gabe"], NOTHING, "control:quiet"),
    # Sharing, leaving
    ("Jamie key stops sharing your screen.", ["Gabe"], YOUTUBE, "stop_sharing"),
    ("Hey, hey Jamie, uh, I think you can leave. I think you're done here.", ["Gabe"], NOTHING, "leave"),
    ("Thanks Jamie, you can leave now.", ["Gabe"], "Shared tab: Meeting notes (file:///workspace/notes.html)", "leave"),
    ("Okay team, we decided the demo will use the fun room. Sam will record a backup video by Friday.", ["Gabe", "Sam"], NOTHING, "none"),
    # Sound-alikes (captions mishear "Jamie")
    ("Amy, can you pull up a YouTube video of a cat playing piano?", ["Gabe"], NOTHING, "control:play-video"),
    ("Amy, can you send me the slides after this?", ["Gabe", "Amy Chen"], NOTHING, "none"),
    ("Hey Janie, what's two plus two?", ["Gabe"], NOTHING, "request"),
    # Not for Jamie
    ("Jamie is a really fun little tool that we built.", ["Gabe"], NOTHING, "none"),
    ("Yeah, I really like sleeping in my jammies.", ["Gabe"], NOTHING, "none"),
    ("I think the API should return JSON", ["Gabe", "Sam"], NOTHING, "none"),
    ("What is the capital of Australia? I always forget", ["Gabe"], NOTHING, "none"),
    ("I paused my video earlier", ["Gabe"], YOUTUBE, "none"),
    # Captions turn commands into the past tense; room controls (study and fun rooms)
    ("Jamie showed the answer.", ["Gabe"], CARDS, "control:show-answer"),
    ("Jamie revealed the answer.", ["Gabe"], TRIVIA, "control:reveal-answer"),
    ("Jamie next card.", ["Gabe"], CARDS, "control:next-card"),
    ("I showed the answer to my sister yesterday", ["Gabe"], CARDS, "none"),
    # While Jamie is busy: "never mind" stops the task; other controls still mean themselves
    ("Jamie, never mind, cancel that.", ["Gabe"], NOTHING, "control:cancel", "Build a tip calculator web page"),
    ("Jamie stop, that's the wrong app", ["Gabe"], NOTHING, "control:cancel", "Build a tip calculator web page"),
    ("Jamie, stop talking", ["Gabe"], NOTHING, "control:quiet", "Build a tip calculator web page"),
    ("Jamie, pause the video", ["Gabe"], YOUTUBE, "control:pause", "Find the lyrics for this song"),
    # Unfinished
    ("Hey Jamie, can we build out?", ["Gabe"], NOTHING, "wait"),
]

# Just one person in the call with Jamie: what they ask is for Jamie, name or not (said, speakers, people besides Jamie, expected)
SOLO = [
    ("What's the capital of Australia?", ["Gabe"], 1, "request"),
    ("Can you pull up a video about funny cats?", ["Gabe"], 1, "control:play-video"),
    ("Mom, can you grab me a water? I'm on a call", ["Gabe"], 1, "none"),
    ("Hey!", ["Gabe"], 1, "none"),
    ("Hey Gabeet, for a YouTube video about kauchi sequence.", ["Gabe Yocum"], 1, "request"),  # real, once ignored
    ("Hey Jay, can you look up the weather in Denver?", ["Gabe"], 1, "request"),
    ("Sam, what did you think of the demo?", ["Gabe", "Sam"], 2, "none"),  # several people: still needs the name
]


async def main():
    judge = hearing.Judge("Jamie", {**bot.BUILTIN_CONTROLS, **ROOM_CONTROLS})
    passed, times = 0, []
    for said, people, screen, want, *busy in CASES:
        start = time.monotonic()
        v = await judge([], [(people[0], said)], people=people, screen=screen, busy=busy[0] if busy else "")
        times.append(time.monotonic() - start)
        got = v["action"] + (f":{v['control']}" if v["action"] == "control" else "")
        if v.get("answer"):
            print(f"      quick answer: {v['answer']!r}")
        ok = got == want
        passed += ok
        print(f"{'ok ' if ok else 'NO '} {times[-1]:.1f}s  {got:22} {said!r}" + ("" if ok else f"  (wanted {want})"))
    for said, people, others, want in SOLO:
        start = time.monotonic()
        v = await judge([], [(people[0], said)], people=people, screen=NOTHING, others=others)
        times.append(time.monotonic() - start)
        got = v["action"] + (f":{v['control']}" if v["action"] == "control" else "")
        ok = got == want
        passed += ok
        print(f"{'ok ' if ok else 'NO '} {times[-1]:.1f}s  {got:22} {said!r} ({others} other)" + ("" if ok else f"  (wanted {want})"))
    await judge.close()

    # Notes: a short real exchange should come out as a decision and an owned action item
    import tempfile
    import notes
    n = notes.Notes(tempfile.mkdtemp())
    for speaker, said in [("Gabe", "Okay so for the demo I think we should use the fun room, it's the most visual."),
                          ("Sam", "Yeah agreed, fun room it is."), ("Gabe", "Hey Jamie, pause the video."),
                          ("Sam", "I can record a backup video in case the wifi dies. I'll have it by Friday."),
                          ("Gabe", "Cool. Do we know if the judges can hear the audio?")]:
        n.add(speaker, said)
    start = time.monotonic()
    md = await n.update()
    good = "fun room" in md.lower() and "sam" in md.lower() and "friday" in md.lower() and "pause" not in md.lower()
    print(f"{'ok ' if good else 'NO '} {time.monotonic() - start:.1f}s  notes: decision + Sam's action item, no assistant chatter")
    if not good:
        print(md)
    passed += good
    print(f"judge: {passed}/{len(CASES) + len(SOLO) + 1} right, {sum(times) / len(times):.1f}s average per judgment")
    sys.exit(0 if passed == len(CASES) + 1 else 1)


if __name__ == "__main__":
    asyncio.run(main())
