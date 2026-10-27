# Wolfram|Alpha for the math room (not installed yet)

Lets Jamie ask Wolfram|Alpha: `python3 wolfram.py 'integrate x e^x from 0 to 1'`. Plain Python,
nothing to install, and Claude, Codex and Gemini can all run it.

## To add it

1. Get a free AppID: https://developer.wolframalpha.com, sign in, **Get an AppID**, choose **LLM API**.
2. `cp addons/wolfram/wolfram.py environments/math/`
3. `cp addons/wolfram/.env.example environments/math/.env`, then fill in `WOLFRAM_APP_ID`
   (the room's `.env` is gitignored, so the key stays on your machine).
4. Add this to the "How to work" list in `environments/math/ROOM.md`:

- Wolfram|Alpha is your second opinion and your source for facts and data (constants, unit
  conversions, step-by-step forms, special functions): `python3 wolfram.py '<query>'`. Use it to
  cross-check sympy on anything non-trivial. If it says the AppID isn't set, carry on with sympy.

5. Send a new math Jamie (running ones don't pick up the change) and ask it something like
   "check with Wolfram Alpha: the integral of x e^x from 0 to 1".

## Status

Tested without a real AppID: a missing AppID gives a clear message, and a fake one reaches
Wolfram's server and gets "Invalid appid". A real answer hasn't been seen yet.
