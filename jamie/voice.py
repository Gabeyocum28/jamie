"""Jamie's voice: text -> audio bytes. ElevenLabs when ELEVENLABS_API_KEY is set, else Piper (offline).

The bot plays the audio into the call through the microphone channel avatar.js gives Meet.
"""
import asyncio
import io
import json
import os
import re
import urllib.request
import wave

PIPER_MODEL = os.environ.get("JAMIE_PIPER_MODEL", "/opt/piper/en_US-amy-medium.onnx")
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # "Rachel", a stock voice
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")      # their lowest-latency model


def spoken(text, limit=240):
    """What to say out loud: chat keeps the full reply, speech gets its first sentence or two."""
    text = re.sub(r"https?://\S*[^\s.,!?)]", "", text or "")   # links are for reading, not hearing
    text = re.sub(r"[*_`#>|]+", "", text)                      # stray markdown
    text = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s+", " ", text)).strip()
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out) + len(sentence) > limit:
            break
        out = f"{out} {sentence}".strip()
    return out[:limit]


class Voice:
    def __init__(self):
        self.piper = None
        self.eleven_key = os.environ.get("ELEVENLABS_API_KEY")

    def available(self):
        return bool(self.eleven_key) or os.path.exists(PIPER_MODEL)

    async def warm_up(self):
        if not self.eleven_key and os.path.exists(PIPER_MODEL):
            await asyncio.to_thread(self._load)

    def _load(self):
        if self.piper is None:
            from piper import PiperVoice  # heavy import: only when Jamie talks
            self.piper = PiperVoice.load(PIPER_MODEL)

    def _piper(self, text):
        self._load()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.piper.synthesize_wav(text, w)
        return buf.getvalue()

    def _eleven(self, text):
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}?output_format=mp3_44100_128",
            data=json.dumps({"text": text, "model_id": ELEVEN_MODEL}).encode(),
            headers={"xi-api-key": self.eleven_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()

    async def synth(self, text):
        """Audio bytes (mp3 or wav) for text; falls back to Piper if ElevenLabs fails."""
        if self.eleven_key:
            try:
                return await asyncio.to_thread(self._eleven, text)
            except Exception as e:
                print("ElevenLabs failed, using the offline voice:", e, flush=True)
        return await asyncio.to_thread(self._piper, text)
