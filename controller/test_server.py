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
              "personality": "hype", "agent": "claude", "look": {}, "voice": True, "project": ""}, ok
rejects({"meet_url": "https://meet.google.com/abc-defg-hij", "project": "../../etc"}, "unknown project")
for repo in ("github.com/acme/sales-dash", "https://github.com/acme/sales-dash.git", "acme/sales-dash",
             "https://github.com/acme/sales-dash/?tab=readme"):
    assert server.repo_url(repo) == ("https://github.com/acme/sales-dash", "sales-dash"), repo
assert server.repo_url("https://gitlab.com/team/sub/My Repo.git")[1] == "My-Repo"
for bad in ("http://github.com/acme/x", "https://user:pw@github.com/acme/x", "github.com", "file:///etc/x", "../.."):
    try:
        server.repo_url(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass

def folders(os_, homes, ok, bad, drives="/mnt"):
    """Linking a folder on one kind of computer: what people paste -> the path Docker gets, and what's refused."""
    server.HOST_OS, server.HOMES, server.WSL_DRIVES = os_, homes, drives
    for pasted, host in ok:
        assert server.host_folder(pasted) == host, (os_, pasted, server.host_folder(pasted))
    for b in bad:
        try:
            server.host_folder(b)
            raise AssertionError(f"{os_}: accepted {b}")
        except ValueError:
            pass


folders("wsl", ["/home/sam", "/mnt/c/Users/Sam Lee"],
        ok=[(r"C:\Users\Sam Lee\OneDrive\Desktop\sales", "/mnt/c/Users/Sam Lee/OneDrive/Desktop/sales"),
            (r'"C:\Users\Sam Lee\Q3 data\"', "/mnt/c/Users/Sam Lee/Q3 data"),  # Explorer's "Copy as path"
            (r"\\wsl.localhost\Ubuntu\home\sam\survey", "/home/sam/survey"),
            ("~/survey", "/home/sam/survey")],
        bad=["C:\\", r"C:\Users\Sam Lee", r"C:\Users\other\x", r"C:\Windows\System32", r"D:\data", "/home/sam",
             "/etc", "/home/sam/../../etc", "sales", r"\\server\share\x"])
folders("wsl", ["/home/sam", "/c/Users/sam"], drives="/",  # WSL set to mount drives at /c instead of /mnt/c
        ok=[(r"C:\Users\sam\x", "/c/Users/sam/x")], bad=[])
folders("mac", ["/Users/ana"],
        ok=[("/Users/ana/Documents/dash/", "/Users/ana/Documents/dash"), ("~/Desktop/q3", "/Users/ana/Desktop/q3")],
        bad=["/Users/ana", "/Users/bob/x", "/Volumes/USB/x", "/etc", r"C:\Users\ana\x"])
folders("linux", ["/var/home/kim"],  # e.g. Fedora Silverblue, where /home links to /var/home
        ok=[("/var/home/kim/work/dash", "/var/home/kim/work/dash")],
        bad=["/var/home/kim", "/home/other/x", "/srv/x", r"C:\Users\kim\x"])
server.HOST_OS, server.HOMES = "linux", []
try:
    server.add_repo({"repo": "acme/x", "token": 5})
    raise AssertionError("accepted a non-text token")
except ValueError:
    pass
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
assert server.last(["10:00 heard Gabe: hi", "10:01 heard Ana: Jamie, pause", "claude -> Done."], " heard ") == "Ana: Jamie, pause"
assert server.last([], " -> ") == ""
print("controller OK")
