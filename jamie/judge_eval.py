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
    # Unfinished
    ("Hey Jamie, can we build out?", ["Gabe"], NOTHING, "wait"),
]


async def main():
    judge = hearing.Judge("Jamie", bot.BUILTIN_CONTROLS)
    passed, times = 0, []
    for said, people, screen, want in CASES:
        start = time.monotonic()
        v = await judge([], [(people[0], said)], people=people, screen=screen)
        times.append(time.monotonic() - start)
        got = v["action"] + (f":{v['control']}" if v["action"] == "control" else "")
        ok = got == want
        passed += ok
        print(f"{'ok ' if ok else 'NO '} {times[-1]:.1f}s  {got:22} {said!r}" + ("" if ok else f"  (wanted {want})"))
    await judge.close()
    print(f"judge: {passed}/{len(CASES)} right, {sum(times) / len(times):.1f}s average")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    asyncio.run(main())
