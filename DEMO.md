# Demo script

A tight 6-minute demo of Jamie for judges. Every line below comes from a scenario that passes in a
real Meet call (`./jamie.sh e2e`, `e2e vibe`, `e2e learn`, `e2e open`, `e2e --env fun|study|work|code`).

## Before you start (5 minutes, once)

1. `./jamie.sh controller` is running, the extension is connected, and Jamie's Google account is
   signed in (`./jamie.sh google-login`).
2. Run `./jamie.sh e2e` once that morning. If it says `e2e OK`, everything below works on this
   machine today.
3. Open the Meet, share your own screen **off**, and turn **captions on** for yourself, so the
   judges can see what Jamie hears.
4. In the extension pick:
   - Environment: **default**
   - Personality: **default** or **hype**
   - Agent: **claude**
   - Look: something fun (heart eyes and a crown always gets a laugh)
5. Send Jamie and admit it. The tile shows the animated orb. Say nothing else yet.

Talk clearly and pause after each request. Jamie acts when you stop talking.

## The demo

| # | Say | What the judges see | Why it matters |
|---|---|---|---|
| 1 | "Hey Jamie, can you pull up a YouTube video about funny cats?" | Jamie says "Playing …"; the video is shared fullscreen, and an ad gets skipped if one appears. About 8 seconds. | It hears the call, with no typing. Simple requests skip the LLM. |
| 2 | "Jamie, pause." then "Play." | Instant, both times. | Instant controls: about half a second. |
| 3 | "Hey Jamie, pull up the Wikipedia page for octopus." then "Jamie, open the evolution section." | The page appears, then it jumps to that section by clicking it on screen, about a second each. On YouTube, "play **that** Mr Blue Sky one" works the same way. | It knows what's on the shared screen. |
| 4 | "Hey Jamie, what's the capital of Australia?" then "Hey Jamie, what's the weather in Denver right now?" | Jamie *says* "Canberra" about a second later. The weather takes a few seconds, because it really looks it up. | It talks back, and knows when it needs to look something up. |
| 5 | "Hey Jamie, let's vibe code. Build a tip calculator web page and show it to us." | VS Code appears. Jamie narrates ("Writing index.html… putting it on screen"), and about 35 seconds later the working app is shared. | A real agent, building live. |
| 6 | "Okay team, we decided the demo will use the fun room. Sam will record a backup video by Friday." then "Jamie, show the meeting notes." | Live notes on screen: the decision, and Sam's action item with its date. | Meetings: it keeps notes as people talk. |
| 7 | "Hey Jamie, learn a new shortcut called coin flip. When I say coin flip, flip a coin and tell us heads or tails." then "Jamie, coin flip." | The second time, "Heads!" comes back in about a second, with no agent. | It **learns**: the LLM teaches the fast path. |
| 8 | "Thanks Jamie, you can leave now." | It posts the decisions and action items to chat, says bye and leaves. Notes and transcript are saved for the room. | Nothing is lost when the meeting ends. |

**Bonus rounds** (send a second Jamie in a room, or start one with that room):

| Room | Say | Then |
|---|---|---|
| fun | "Hey Jamie, let's play a trivia game about space. Make it three questions." | "Jamie, next question" · "Jamie, reveal the answer" |
| study | "Hey Jamie, make me three flashcards about the solar system and put them on screen." | "Jamie, show the answer" · "Jamie, next card" |
| work | "Hey Jamie, set up our meeting agenda on screen: intro, demo, and wrap up, five minutes each." | "Jamie, start the timer" · "Jamie, next agenda item" |
| code | "Hey Jamie, build a blackjack game we can play together." | Playable in about 30 seconds, with the code typing out beside it. Pick one of the two options it offers: "Let's do betting chips." |

## If something goes sideways

- **Jamie didn't react:** say it again, starting with "Hey Jamie". Captions sometimes miss the first
  word. Typing works as a backup: `/jamie <request>` in the chat, using your `JAMIE_TRIGGER`.
- **It went off on the wrong thing:** "Jamie, never mind" stops it mid-task. Then ask again more
  precisely.
- **It's talking too long:** "Jamie, stop talking."
- **To see what it's thinking:** open **watch** in the extension, or `docker logs -f <id>`. The
  `judge:` lines show how it read each sentence.

## Numbers worth quoting

These come from the real-call and judge test runs on 2026-10-27:
- **Speech to judgment:** about 1 second (1.1s average over 40 phrases).
- **Instant controls:** about 0.5 seconds after the judgment.
- **"Play a video about…":** about 8 seconds to fullscreen, with no LLM.
- **A question answered out loud:** about 1 second after the judgment for quick facts; a few seconds when it has
  to look something up.
- **A working app built live:** about 35 seconds.
- **Joining:** about 1 second from opening the meeting to clicking Join.
- **The judge:** 37 to 40 of 40 across runs on the real-phrase suite (`./jamie.sh judge`), with
  misheard names, past-tense captions, talking *about* Jamie, and a real person named Amy.
