"""A Chrome DevTools endpoint for the agent's browser tools that hides the Meet tab.

Meet leaves the call as soon as something starts navigating its tab, and the agent's browser tools
start out on that tab. So the agent connects here instead of to Chrome: everything passes through,
except that Meet's targets never show up in tab lists or events, and commands aimed at them fail.
"""
import asyncio
import json
from urllib.parse import urlsplit
from urllib.request import urlopen

import websockets


def hidden_url(url):
    return urlsplit(url or "").hostname == "meet.google.com"


async def serve(upstream="http://localhost:9222", port=9223):
    async def relay(client):
        version = json.load(urlopen(f"{upstream}/json/version"))
        hidden_targets, hidden_sessions, asked = set(), set(), {}  # asked: request id -> method

        shown = set()  # targets the agent has seen: hidden only on first sight, so its own tab never vanishes

        def hide(info):
            tid = info.get("targetId")
            if tid in hidden_targets:
                return True
            if tid not in shown and hidden_url(info.get("url")):
                hidden_targets.add(tid)
                return True
            shown.add(tid)
            return False

        async with websockets.connect(version["webSocketDebuggerUrl"], max_size=None) as browser:
            async def down():  # browser -> agent
                async for raw in browser:
                    msg = json.loads(raw)
                    if msg.get("sessionId") in hidden_sessions or msg.get("id") == -1:  # (-1: our own runIfWaitingForDebugger)
                        continue
                    params = msg.get("params", {})
                    if "targetInfo" in params and hide(params["targetInfo"]):
                        if "sessionId" in params:
                            hidden_sessions.add(params["sessionId"])
                            if params.get("waitingForDebugger"):  # auto-attach paused it for the agent: let it run
                                await browser.send(json.dumps({"id": -1, "method": "Runtime.runIfWaitingForDebugger",
                                                               "sessionId": params["sessionId"]}))
                        continue
                    if msg.get("method") in ("Target.targetDestroyed", "Target.detachedFromTarget") and (
                            params.get("targetId") in hidden_targets or params.get("sessionId") in hidden_sessions):
                        continue
                    if asked.pop(msg.get("id"), None) == "Target.getTargets" and "result" in msg:
                        msg["result"]["targetInfos"] = [t for t in msg["result"]["targetInfos"] if not hide(t)]
                        raw = json.dumps(msg)
                    await client.send(raw)

            async def up():  # agent -> browser
                async for raw in client:
                    msg = json.loads(raw)
                    params = msg.get("params", {})
                    if params.get("targetId") in hidden_targets or msg.get("sessionId") in hidden_sessions:
                        await client.send(json.dumps({"id": msg.get("id"), "error": {"code": -32000, "message": "No such target"}}))
                        continue
                    asked[msg.get("id")] = msg.get("method")
                    await browser.send(raw)

            tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()

    def http(connection, request):  # /json/version is how clients find the WebSocket URL
        if request.path.startswith("/json/version"):
            body = json.load(urlopen(f"{upstream}/json/version"))
            body["webSocketDebuggerUrl"] = f"ws://localhost:{port}/devtools/browser/filtered"
            return connection.respond(200, json.dumps(body))
        if request.path.startswith("/json"):
            return connection.respond(200, "[]")
        return None  # a WebSocket handshake: let it through

    return await websockets.serve(relay, "127.0.0.1", port, process_request=http, max_size=None)
