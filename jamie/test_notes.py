"""Self-check for live meeting notes (no model calls): ./jamie.sh test"""
import asyncio
import tempfile

from playwright.async_api import async_playwright

import notes

MD = """## Summary
- Planning the hackathon demo

## Decisions
- Demo uses the fun room (Gabe)

## Action items
- [ ] Sam: record the backup video by Friday
- [x] Gabe: book the room

## Open questions
- None yet
"""


async def main():
    folder = tempfile.mkdtemp()
    n = notes.Notes(folder, every=0, min_lines=2)
    assert not n.due()
    n.add("Gabe", "let's use the fun room")
    n.add("Sam", "I'll record the backup video by Friday")
    assert n.due()

    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.goto(f"file://{folder}/notes.html")
        await page.wait_for_selector("section")
        assert await page.locator("h2").all_inner_texts() == ["SUMMARY", "DECISIONS", "ACTION ITEMS", "OPEN QUESTIONS"]
        n.md = MD  # what an update produces: the open page picks it up without a reload
        n.write()
        await page.wait_for_selector("text=record the backup video", timeout=6000)
        assert await page.locator("li.todo").count() == 1 and await page.locator("li.done").count() == 1
        await b.close()

    recap = n.recap()
    assert recap == ("Decisions:\n  - Demo uses the fun room (Gabe)\nAction items:\n"
                     "  - Sam: record the backup video by Friday\n  - Gabe: book the room"), recap
    n.md = notes.EMPTY
    assert n.recap() == ""  # nothing decided: say nothing
    print("notes OK")


asyncio.run(main())
