"""Self-check for Jamie's voice: ./jamie.sh test"""
import asyncio
import io
import os
import wave

import voice

# Speech gets the first sentence or two; links and markdown aren't read out
assert voice.spoken("Done! It's on screen at https://youtu.be/x. Want me to **skip** ahead?") == \
    "Done! It's on screen at. Want me to skip ahead?"
long = "First sentence here. " + "This one is very long " * 30 + "end."
assert voice.spoken(long) == "First sentence here."
assert voice.spoken("") == ""

v = voice.Voice()
v.eleven_key = None  # the offline voice, whatever .env says
if os.path.exists(voice.PIPER_MODEL):
    audio = asyncio.run(v.synth("Sure, pulling that up now."))
    with wave.open(io.BytesIO(audio)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 1 < seconds < 5, seconds
    print(f"voice OK ({seconds:.1f}s of speech)")
else:
    print("voice OK (no offline voice model here; skipped synthesis)")
