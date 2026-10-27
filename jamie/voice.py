"""Jamie's voice: text -> audio bytes. ElevenLabs when ELEVENLABS_API_KEY is set, else Piper (offline).

The bot plays the audio into the call through the microphone channel avatar.js gives Meet.
"""
import argparse
import asyncio
import http.client
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import wave

PIPER_MODEL = "/opt/piper/en_US-amy-medium.onnx"
ELEVEN_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel; override with a voice from your account
ELEVEN_MODEL = "eleven_flash_v2_5"
VOICE_ENV_KEYS = {"ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "ELEVENLABS_MODEL", "JAMIE_PIPER_MODEL"}


def _env(name, default=""):
    return os.environ.get(name, "").strip() or default


class VoiceError(RuntimeError):
    """A speech failure safe to show in logs (never includes credentials or API response bodies)."""


def _load_env_file(path):
    """Read only voice settings for the diagnostic; never execute or expand dotenv values."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise VoiceError("Could not read --env-file; check its path and permissions.") from None
    values = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in VOICE_ENV_KEYS:
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith("#")):
                raise VoiceError(f"Invalid quoted voice setting on env-file line {number}.")
            value = value[1:end]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value  # Match Docker --env-file: the last duplicate wins.
    for key, value in values.items():
        os.environ.setdefault(key, value)  # Explicit process settings take precedence.


def _api_error(error):
    # Only use known status codes. An upstream message can contain request details,
    # so neither the raw body nor exception text belongs in the bot's logs.
    status = ""
    try:
        detail = json.loads(error.read(4096)).get("detail", {})
        if isinstance(detail, dict):
            status = detail.get("status", "")
    except (ValueError, OSError, AttributeError):
        pass
    if status == "quota_exceeded":
        return VoiceError("ElevenLabs credits are exhausted; check the subscription or API key credit limit.")
    if status in ("voice_not_found", "voice_does_not_exist"):
        return VoiceError("ElevenLabs voice was not found; check ELEVENLABS_VOICE_ID and account access.")
    if status == "model_not_found":
        return VoiceError("ElevenLabs model was not found; check ELEVENLABS_MODEL_ID.")
    if error.code in (401, 403):
        return VoiceError("ElevenLabs rejected the API key or permissions; check that the key allows Text to Speech and this voice.")
    if error.code == 429:
        return VoiceError("ElevenLabs rate or concurrency limit reached; try again after current speech finishes.")
    if error.code == 404:
        return VoiceError("ElevenLabs voice or model was not found; check ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL_ID.")
    return VoiceError(f"ElevenLabs speech request failed (HTTP {error.code}).")


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
        # Read configuration per instance, including env files containing blank values.
        self.eleven_key = _env("ELEVENLABS_API_KEY")
        self.eleven_voice = _env("ELEVENLABS_VOICE_ID", ELEVEN_VOICE)
        self.eleven_model = _env("ELEVENLABS_MODEL_ID", _env("ELEVENLABS_MODEL", ELEVEN_MODEL))
        self.piper_model = _env("JAMIE_PIPER_MODEL", PIPER_MODEL)

    def available(self):
        return bool(self.eleven_key) or os.path.isfile(self.piper_model)

    async def warm_up(self):
        if not self.eleven_key and os.path.isfile(self.piper_model):
            await asyncio.to_thread(self._load)

    def _load(self):
        if self.piper is None:
            from piper import PiperVoice  # heavy import: only when Jamie talks
            self.piper = PiperVoice.load(self.piper_model)

    def _piper(self, text):
        self._load()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            self.piper.synthesize_wav(text, w)
        return buf.getvalue()

    def _eleven(self, text):
        if not self.eleven_key:
            raise VoiceError("ELEVENLABS_API_KEY is missing; set it in the server's .env file.")
        if not self.eleven_key.isascii() or re.search(r"[\x00-\x20\x7f]", self.eleven_key):
            raise VoiceError("ELEVENLABS_API_KEY contains invalid characters; check the server's env file.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.eleven_voice):
            raise VoiceError("ELEVENLABS_VOICE_ID must be a voice ID, not a name or URL.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.eleven_model):
            raise VoiceError("ELEVENLABS_MODEL_ID must be a model ID.")
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.eleven_voice}?output_format=mp3_44100_128",
            data=json.dumps({"text": text, "model_id": self.eleven_model}).encode(),
            headers={"xi-api-key": self.eleven_key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                audio = response.read()
        except urllib.error.HTTPError as error:
            raise _api_error(error) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise VoiceError("Could not reach ElevenLabs; check the connection and try again.") from None
        # decodeAudioData in avatar.js needs the complete MP3, not individual stream chunks.
        mp3_header = audio.startswith(b"ID3") or (len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)
        if content_type not in ("audio/mpeg", "audio/mp3") or len(audio) < 4 or not mp3_header:
            raise VoiceError("ElevenLabs returned empty or invalid MP3 audio.")
        return audio

    async def synth(self, text):
        """Audio bytes (mp3 or wav) for text; falls back to Piper if ElevenLabs fails."""
        if not text or not text.strip():
            raise VoiceError("There is no text to speak.")
        failure = None
        if self.eleven_key:
            try:
                return await asyncio.to_thread(self._eleven, text)
            except VoiceError as error:
                failure = error
        if not os.path.isfile(self.piper_model):
            if failure:
                raise VoiceError(f"{failure} The offline Piper voice is unavailable.") from None
            raise VoiceError("No voice configured; set ELEVENLABS_API_KEY or install the Piper voice model.")
        if failure:
            print(f"{failure} Using the offline Piper voice.", flush=True)
        return await asyncio.to_thread(self._piper, text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check Jamie's ElevenLabs account with one short speech request.")
    parser.add_argument("--check", action="store_true", required=True, help="Generate a short MP3 using ElevenLabs, without offline fallback")
    parser.add_argument("--env-file", type=Path, help="Read voice settings from an env file; existing process values take precedence")
    parser.add_argument("--output", type=Path, default=Path("/files/jamie-voice-check.mp3"), help="Where to save the MP3 (default: /files/jamie-voice-check.mp3)")
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            _load_env_file(args.env_file)
        engine = Voice()
        audio = engine._eleven("Hi, I'm Jamie. My voice is ready for the meeting.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(audio)
    except VoiceError as error:
        print(f"Voice check failed: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Voice check failed: could not write the MP3; check --output and directory permissions.", file=sys.stderr)
        return 1
    print(f"ElevenLabs voice check passed: voice={engine.eleven_voice}, model={engine.eleven_model}, {len(audio)} bytes.")
    print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
