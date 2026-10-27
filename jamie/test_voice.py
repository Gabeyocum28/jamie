"""Voice regression checks: python3 test_voice.py (no ElevenLabs credits used)."""
import asyncio
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave

import voice


MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00mock-mp3-data"


class AudioResponse(io.BytesIO):
    def __init__(self, data=MP3, content_type="audio/mpeg"):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


def http_error(code, status):
    body = json.dumps({"detail": {"status": status, "message": "private request info secret-test-key"}}).encode()
    return urllib.error.HTTPError("https://api.elevenlabs.io", code, "Failure", {}, io.BytesIO(body))


class VoiceTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def configured(self):
        os.environ["ELEVENLABS_API_KEY"] = "secret-test-key"
        return voice.Voice()

    def test_spoken_text(self):
        self.assertEqual(voice.spoken("Done! It's on screen at https://youtu.be/x. Want me to **skip** ahead?"),
                         "Done! It's on screen at. Want me to skip ahead?")
        self.assertEqual(voice.spoken("First sentence here. " + "This one is very long " * 30 + "end."), "First sentence here.")
        self.assertEqual(voice.spoken(""), "")

    def test_blank_environment_uses_defaults(self):
        os.environ.update({key: "  " for key in voice.VOICE_ENV_KEYS})
        engine = voice.Voice()
        self.assertFalse(engine.eleven_key)
        self.assertEqual(engine.eleven_voice, voice.ELEVEN_VOICE)
        self.assertEqual(engine.eleven_model, voice.ELEVEN_MODEL)
        self.assertEqual(engine.piper_model, voice.PIPER_MODEL)

    def test_environment_is_read_per_instance_and_supports_legacy_model(self):
        first = voice.Voice()
        os.environ.update(ELEVENLABS_API_KEY=" key ", ELEVENLABS_VOICE_ID="customVoice", ELEVENLABS_MODEL="legacy_model", JAMIE_PIPER_MODEL="custom.onnx")
        second = voice.Voice()
        self.assertFalse(first.eleven_key)
        self.assertEqual(second.eleven_key, "key")
        self.assertEqual(second.eleven_voice, "customVoice")
        self.assertEqual(second.eleven_model, "legacy_model")
        self.assertEqual(second.piper_model, "custom.onnx")
        os.environ["ELEVENLABS_MODEL_ID"] = "current_model"
        self.assertEqual(voice.Voice().eleven_model, "current_model")

    def test_elevenlabs_request_and_audio(self):
        engine = self.configured()
        with patch("voice.urllib.request.urlopen", return_value=AudioResponse()) as request, patch.object(engine, "_piper") as offline:
            self.assertEqual(asyncio.run(engine.synth("Hello Jamie.")), MP3)
        req = request.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(f"/{engine.eleven_voice}?output_format=mp3_44100_128", req.full_url)
        self.assertEqual(req.get_header("Xi-api-key"), "secret-test-key")
        self.assertEqual(req.get_header("Accept"), "audio/mpeg")
        self.assertEqual(json.loads(req.data), {"text": "Hello Jamie.", "model_id": voice.ELEVEN_MODEL})
        offline.assert_not_called()

    def test_mpeg_frame_without_id3_is_accepted(self):
        with patch("voice.urllib.request.urlopen", return_value=AudioResponse(b"\xff\xfb\x90\x64audio")):
            self.assertTrue(self.configured()._eleven("Hello").startswith(b"\xff\xfb"))

    def test_invalid_audio_is_rejected(self):
        for data, mime in ((b"", "audio/mpeg"), (b'{"error":"bad"}', "application/json"), (b"not audio", "audio/mpeg"), (MP3, "text/html")):
            with self.subTest(data=data, mime=mime), patch("voice.urllib.request.urlopen", return_value=AudioResponse(data, mime)):
                with self.assertRaisesRegex(voice.VoiceError, "invalid MP3"):
                    self.configured()._eleven("Hello")

    def test_safe_actionable_api_errors(self):
        for code, status, expected in ((401, "invalid_api_key", "API key"), (403, "missing_permissions", "permissions"), (401, "quota_exceeded", "credits"), (404, "voice_not_found", "VOICE_ID"), (400, "model_not_found", "MODEL_ID"), (429, "too_many_concurrent_requests", "concurrency"), (500, "unknown", "HTTP 500")):
            with self.subTest(status=status), patch("voice.urllib.request.urlopen", side_effect=http_error(code, status)):
                with self.assertRaisesRegex(voice.VoiceError, expected) as raised:
                    self.configured()._eleven("Hello")
                self.assertNotIn("secret-test-key", str(raised.exception))
                self.assertNotIn("private request", str(raised.exception))

    def test_network_failure_has_safe_message(self):
        for error in (urllib.error.URLError("private request info secret-test-key"), TimeoutError(), http.client.IncompleteRead(b"partial")):
            with self.subTest(error=type(error)), patch("voice.urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(voice.VoiceError, "Could not reach ElevenLabs") as raised:
                    self.configured()._eleven("Hello")
                self.assertNotIn("secret-test-key", str(raised.exception))

    def test_malformed_key_never_reaches_http_headers_or_errors(self):
        engine = self.configured()
        engine.eleven_key = "secret-test-key\ninvalid-header"
        with patch("voice.urllib.request.urlopen") as request:
            with self.assertRaisesRegex(voice.VoiceError, "invalid characters") as raised:
                engine._eleven("Hello")
            self.assertNotIn("secret-test-key", str(raised.exception))
            request.assert_not_called()

    def test_elevenlabs_failure_falls_back_to_installed_piper(self):
        engine = self.configured()
        output = io.StringIO()
        with patch("voice.urllib.request.urlopen", side_effect=http_error(401, "invalid_api_key")), patch("voice.os.path.isfile", return_value=True), patch.object(engine, "_piper", return_value=b"offline WAV") as offline, contextlib.redirect_stdout(output):
            self.assertEqual(asyncio.run(engine.synth("Hello")), b"offline WAV")
            offline.assert_called_once_with("Hello")
        self.assertIn("Using the offline Piper voice", output.getvalue())
        self.assertNotIn("secret-test-key", output.getvalue())

    def test_failure_without_piper_preserves_elevenlabs_reason(self):
        engine = self.configured()
        with patch("voice.urllib.request.urlopen", side_effect=http_error(401, "quota_exceeded")), patch("voice.os.path.isfile", return_value=False):
            with self.assertRaisesRegex(voice.VoiceError, "credits.*Piper voice is unavailable"):
                asyncio.run(engine.synth("Hello"))

    def test_no_configuration_or_empty_text_does_not_send_requests(self):
        with patch("voice.os.path.isfile", return_value=False), patch("voice.urllib.request.urlopen") as request:
            engine = voice.Voice()
            self.assertFalse(engine.available())
            with self.assertRaisesRegex(voice.VoiceError, "No voice configured"):
                asyncio.run(engine.synth("Hello"))
            with self.assertRaisesRegex(voice.VoiceError, "no text"):
                asyncio.run(engine.synth("  "))
            request.assert_not_called()

    def test_invalid_voice_configuration_does_not_send_request(self):
        os.environ["ELEVENLABS_VOICE_ID"] = "https://example.com/voice"
        with patch("voice.urllib.request.urlopen") as request:
            with self.assertRaisesRegex(voice.VoiceError, "voice ID"):
                self.configured()._eleven("Hello")
            request.assert_not_called()

    def test_cli_requires_elevenlabs_and_never_silently_falls_back(self):
        output = io.StringIO()
        with patch("voice.Voice._piper") as offline, contextlib.redirect_stderr(output):
            self.assertEqual(voice.main(["--check"]), 1)
            self.configured()
            with patch("voice.urllib.request.urlopen", side_effect=http_error(401, "invalid_api_key")):
                self.assertEqual(voice.main(["--check"]), 1)
            offline.assert_not_called()
        self.assertIn("ELEVENLABS_API_KEY is missing", output.getvalue())
        self.assertIn("rejected the API key", output.getvalue())
        self.assertNotIn("secret-test-key", output.getvalue())

    def test_cli_saves_response_and_reads_only_voice_env_keys(self):
        with tempfile.TemporaryDirectory() as folder, patch("voice.urllib.request.urlopen", return_value=AudioResponse()) as request, contextlib.redirect_stdout(io.StringIO()) as output:
            env = Path(folder) / ".env"
            env.write_text("# comment\nELEVENLABS_API_KEY=\nELEVENLABS_API_KEY='secret-test-key'\nexport ELEVENLABS_MODEL_ID=\"my_model\" # comment\nELEVENLABS_VOICE_ID=fileVoice # comment\nUNRELATED_VAR=ignored\n", encoding="utf-8")
            os.environ["ELEVENLABS_VOICE_ID"] = "processVoice"
            path = Path(folder) / "check.mp3"
            self.assertEqual(voice.main(["--check", "--env-file", str(env), "--output", str(path)]), 0)
            self.assertEqual(path.read_bytes(), MP3)
            self.assertEqual(request.call_args.args[0].get_header("Xi-api-key"), "secret-test-key")
            self.assertEqual(json.loads(request.call_args.args[0].data)["model_id"], "my_model")
            self.assertIn("/processVoice?", request.call_args.args[0].full_url)
            self.assertNotIn("UNRELATED_VAR", os.environ)
            self.assertIn("ElevenLabs voice check passed", output.getvalue())
            self.assertNotIn("secret-test-key", output.getvalue())

    def test_cli_invalid_env_file_reports_safe_error(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stderr(io.StringIO()) as output, patch("voice.urllib.request.urlopen") as request:
            path = Path(folder) / ".env"
            self.assertEqual(voice.main(["--check", "--env-file", str(path)]), 1)
            path.write_text("ELEVENLABS_API_KEY='secret-test-key", encoding="utf-8")
            self.assertEqual(voice.main(["--check", "--env-file", str(path)]), 1)
            self.assertNotIn("secret-test-key", output.getvalue())
            request.assert_not_called()


class OfflineVoiceSmokeTest(unittest.TestCase):
    def test_installed_piper_voice(self):
        engine = voice.Voice()
        engine.eleven_key = ""
        if not os.path.isfile(engine.piper_model):
            self.skipTest("No offline Piper model installed here")
        audio = asyncio.run(engine.synth("Sure, pulling that up now."))
        with wave.open(io.BytesIO(audio)) as wav:
            seconds = wav.getnframes() / wav.getframerate()
        self.assertGreater(seconds, 1)
        self.assertLess(seconds, 5)


if __name__ == "__main__":
    unittest.main()
