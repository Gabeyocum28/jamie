"""Self-check for requests running side by side: ./jamie.sh test"""
import asyncio
import os
import subprocess
import sys

import bot


async def main():
    started = asyncio.Event()
    finish = asyncio.Event()

    async def fake_worker(page, agent, state, prompt):  # a request that runs until the test says so
        started.set()
        await finish.wait()

    async def fake_avatar(page, look):
        pass

    bot.worker, bot.avatar = fake_worker, fake_avatar
    state = {"busy": {}, "last_reply": "", "replies": []}
    workers = bot.Workers(None, bot.Agent("claude", {}), state)
    assert len(workers.agents) == bot.WORKERS and len({a.session for a in workers.agents}) == bot.WORKERS

    workers.put("show a video about black holes")
    workers.put("find a pizza place nearby")
    await started.wait()
    assert len(state["busy"]) == 2 and not workers.full(), state  # the second didn't wait for the first
    assert list(state["busy"])[0] is workers.agents[0]  # the first agent is used first
    assert workers.pick("cancel the pizza one") is workers.agents[1]
    assert workers.pick("") is workers.agents[1]  # "never mind": the newest
    assert "pizza" in bot.busy(state) and "black holes" in bot.busy(state)

    for _ in range(bot.WORKERS - 1):
        workers.put("one more")
    assert workers.full() and workers.waiting == ["one more"]  # every agent busy: the last one waits
    finish.set()
    for _ in range(50):
        if not state["busy"] and not workers.waiting:
            break
        await asyncio.sleep(0.05)
    assert not state["busy"] and not workers.waiting, state

    # The screen: another request that's still running has it, so --show refuses; free, it's taken
    with open(bot.SCREEN, "w") as f:
        f.write("1")
    env = {**os.environ, "JAMIE_WORKER": "2"}
    run = subprocess.run([sys.executable, "bot.py", "--show", "https://example.com"], env=env,
                         capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    assert run.returncode != 0 and "has the screen" in run.stderr, run
    note = bot.alongside(workers.agents[1], {"busy": {workers.agents[0]: "a video", workers.agents[1]: "pizza"},
                                              "replies": []})
    assert "a video" in note and "don't put anything on it" in note, note
    os.remove(bot.SCREEN)
    bot.WORKER = "2"
    bot.take_screen()
    assert bot.screen_owner() == "2"
    os.remove(bot.SCREEN)
    print("workers ok")


asyncio.run(main())
