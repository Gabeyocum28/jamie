"""Speech ordering, interruption, and the audio sent to Meet's microphone (no paid API calls)."""
import asyncio
import base64
import io
import math
import os
import struct
import unittest
import wave
from unittest.mock import patch

from playwright.async_api import async_playwright

import bot


class SpeechQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.synthesized = []
        self.played = []

        async def synth(text):
            self.synthesized.append(text)
            if text == "first":
                self.started.set()
                await self.release.wait()
            return text.encode()

        async def evaluate(script, audio=None):
            if audio:
                self.played.append(base64.b64decode(audio).decode())

        class Engine:
            available = staticmethod(lambda: True)

        self.engine = Engine()
        self.engine.synth = synth
        self.page = type("Page", (), {"evaluate": staticmethod(evaluate)})()
        self.patches = [patch.object(bot, "VOICE", True), patch.object(bot, "VOICE_ENGINE", self.engine),
                        patch.object(bot, "voice_lock", asyncio.Lock()),
                        patch.object(bot, "speaking", {"until": 0.0, "said": [], "hush": 0})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_acknowledgment_plays_before_faster_answer(self):
        first = asyncio.create_task(bot.speak(self.page, "first"))
        await asyncio.wait_for(self.started.wait(), 3)
        second = asyncio.create_task(bot.speak(self.page, "second"))
        await asyncio.sleep(0.01)
        self.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.played, ["first", "second"])

    async def test_interrupt_drops_inflight_and_queued_speech(self):
        first = asyncio.create_task(bot.speak(self.page, "first"))
        await asyncio.wait_for(self.started.wait(), 3)
        second = asyncio.create_task(bot.speak(self.page, "second"))
        await asyncio.sleep(0)
        await bot.stop_speaking(self.page)
        self.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.played, [])
        self.assertEqual(self.synthesized, ["first"])  # canceled queued replies cost no API credits
        await bot.speak(self.page, "new answer")
        self.assertEqual(self.played, ["new answer"])
        self.assertFalse(bot.said_by_me("first"))

    async def test_failed_synthesis_does_not_block_next_reply(self):
        original = self.engine.synth

        async def synth(text):
            if text == "bad":
                raise RuntimeError("speech unavailable")
            return await original(text)

        self.engine.synth = synth
        await bot.speak(self.page, "bad")
        await bot.speak(self.page, "next")
        self.assertEqual(self.played, ["next"])
        self.assertFalse(bot.voice_lock.locked())


def tone():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(i * 2 * math.pi * 440 / 16000)))
                              for i in range(16000)))
    return base64.b64encode(buf.getvalue()).decode()


async def browser_checks():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel=os.environ.get("JAMIE_TEST_BROWSER_CHANNEL"),
                                          args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await browser.new_context()
        await ctx.add_init_script(bot.avatar_script())
        page = await ctx.new_page()
        await page.route("https://meet.google.com/**", lambda r: r.fulfill(body="<html></html>", content_type="text/html"))
        await page.goto("https://meet.google.com/speech-test")
        # Speech before getUserMedia must initialize the mixer rather than silently disappear.
        await page.evaluate("b => window.__jamieVoice.say(b)", tone())
        assert await page.evaluate("window.__jamieVoice.ctx.state") == "running"
        await page.evaluate("""async () => {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
          window.receiver = new AudioContext();
          window.meter = receiver.createAnalyser();
          receiver.createMediaStreamSource(stream).connect(meter);
          await receiver.resume();
          window.level = () => { const a = new Float32Array(meter.fftSize); meter.getFloatTimeDomainData(a);
            return Math.sqrt(a.reduce((sum, x) => sum + x * x, 0) / a.length); };
        }""")
        assert await page.evaluate("level()") < 0.001, "fake microphone noise leaked into Meet"
        # A suspended context must resume, and decoded audio must reach the outbound microphone.
        await page.evaluate("window.__jamieVoice.ctx.suspend()")
        await page.evaluate("b => { window.playing = window.__jamieVoice.say(b); }", tone())
        await page.wait_for_function("level() > 0.05")
        assert await page.evaluate("window.__jamieAvatar.state") == "talking"
        await page.evaluate("window.__jamieVoice.stop(); window.playing")
        await page.wait_for_function("level() < 0.001")
        assert await page.evaluate("window.__jamieVoice.source === null && window.__jamieAvatar.state !== 'talking'")
        # Stop while decode is pending must invalidate the eventual audio.
        await page.evaluate("""() => {
          const v = window.__jamieVoice;
          window.decode = v.ctx.decodeAudioData.bind(v.ctx);
          v.ctx.decodeAudioData = async bytes => {
            const buffer = await decode(bytes);
            await new Promise(resolve => { window.finishDecode = resolve; });
            return buffer;
          };
        }""")
        await page.evaluate("b => { window.pending = window.__jamieVoice.say(b); }", tone())
        await page.wait_for_function("!!window.finishDecode")
        await page.evaluate("window.__jamieVoice.stop(); window.finishDecode(); window.pending")
        assert await page.evaluate("window.__jamieVoice.source === null")
        await page.evaluate("() => { window.__jamieVoice.ctx.decodeAudioData = window.decode; }")
        # A delayed ended event from the interrupted reply must leave the replacement intact.
        await page.evaluate("b => { window.oldPlayback = window.__jamieVoice.say(b); }", tone())
        await page.wait_for_function("window.__jamieVoice.source")
        await page.evaluate("window.oldSource = window.__jamieVoice.source")
        await page.evaluate("b => { window.newPlayback = window.__jamieVoice.say(b); }", tone())
        await page.wait_for_function("window.__jamieVoice.source && window.__jamieVoice.source !== window.oldSource")
        await page.evaluate("window.oldSource.onended()")
        assert await page.evaluate("window.__jamieVoice.source !== null && window.__jamieAvatar.state === 'talking'")
        await page.evaluate("window.__jamieVoice.stop(); Promise.all([window.oldPlayback, window.newPlayback])")
        sample = os.environ.get("JAMIE_SPEECH_SAMPLE")
        if sample:
            with open(sample, "rb") as f:
                audio = base64.b64encode(f.read()).decode()
            await page.evaluate("b => { window.samplePlayback = window.__jamieVoice.say(b); }", audio)
            await page.wait_for_function("level() > 0.01 && window.__jamieAvatar.mouth > 0.01")
            await page.evaluate("window.samplePlayback")
            print("ElevenLabs sample decoded and reached Meet microphone with mouth animation")
        await ctx.close()
        await browser.close()
    print("speech microphone playback OK (signal, resume, interruption, replacement)")


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    asyncio.run(browser_checks())
