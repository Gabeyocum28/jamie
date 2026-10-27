"""Self-check for request validation: JAMIE_ROOT=.. python3 test_server.py (or ./jamie.sh test)"""
import json

import server


def rejects(body, why):
    try:
        server.parse(json.dumps(body))
    except ValueError as e:
        assert why in str(e), e
        return
    raise AssertionError(f"accepted {body}")


ok = server.parse(json.dumps({"meet_url": "https://meet.google.com/abc-defg-hij?authuser=1", "personality": "hype"}))
assert ok == {"meet_url": "https://meet.google.com/abc-defg-hij", "env": "default",
              "personality": "hype", "agent": "claude", "look": {}, "voice": True}, ok
assert server.parse(json.dumps({"meet_url": "https://meet.google.com/abc-defg-hij", "voice": False}))["voice"] is False
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "voice": "loud"}, "voice")
look = {"eyes": "x", "mouth": "cat", "color": "gold", "motion": "bounce", "accessory": "party-hat"}
assert server.parse(json.dumps({"meet_url": "https://meet.google.com/abc-defg-hij", "look": look}))["look"] == look
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "look": {"eyes": "<script>"}}, "look")
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "look": {"hat": "crown"}}, "look")
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "look": "crown"}, "look")
assert server.parse(json.dumps({"meet_url": "https://meet.google.com/meet/siy-jvzm-ryq"}))["meet_url"] == \
    "https://meet.google.com/siy-jvzm-ryq"
rejects({"meet_url": "https://evil.com/abc-defg-hij"}, "meet_url")
rejects({"meet_url": "https://meet.google.com/abc-defg-hij/../x"}, "meet_url")
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "env": "../../etc"}, "unknown env")
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "agent": "gpt"}, "unknown agent")
rejects({"env": "default"}, "expected JSON")
assert server.status([]) == "starting"
assert server.status(["10:00 Opening https://meet.google.com/abc", "10:00 Clicked 'ask to join'. Waiting to be admitted (up to 10 min)..."]) == "waiting to be admitted"
assert server.status(["Listening for '/jz7' in chat", "claude <- Gabe asked out loud: build it"]) == "working on a request"
assert server.status(["claude <- Gabe asked out loud: build it", "claude -> Done."]) == "listening"
assert server.status(["Listening", "Call ended or Jamie was removed."]) == "left the call"
print("controller OK")
