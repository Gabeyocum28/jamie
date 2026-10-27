"""Self-check for environments/personalities/agents: ./jamie.sh test"""
import asyncio
import json
import os
import sys
import tempfile

import bot


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


def exits(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    raise AssertionError("expected exit")


def main():
    root = tempfile.mkdtemp()
    bot.ENVIRONMENT, bot.PERSONALITIES, bot.WORKSPACE = (os.path.join(root, d) for d in ("env", "pers", "ws"))
    bot.CLAUDE_MCP = os.path.join(root, "claude-mcp.json")
    env, ws = bot.ENVIRONMENT, bot.WORKSPACE
    write(f"{env}/ROOM.md", "v2 rules")
    write(f"{env}/mcp.json", json.dumps({"mcpServers": {"notes": {"command": "notes-mcp", "env": {"K": "v"}}}}))
    write(f"{env}/setup.sh", "touch setup-ran")
    write(f"{env}/.env", "SECRET=1")
    write(f"{env}/Dockerfile", "FROM jamie-base")
    write(f"{bot.PERSONALITIES}/pirate.md", "Talk like a pirate.")
    write(f"{ws}/ROOM.md", "v1 rules")         # stale copy from a previous run
    write(f"{ws}/app.py", "built by Jamie")    # Jamie's own work

    assert "Available: pirate" in exits(lambda: bot.prepare("lab", "../../etc/passwd", "claude"))
    assert "Available: claude, codex, gemini" in exits(lambda: bot.prepare("lab", "pirate", "gpt"))

    for agent, file in bot.INSTRUCTIONS.items():
        a = bot.prepare("lab", "pirate", agent)
        text = read(f"{ws}/{file}")
        assert "Talk like a pirate." in text and "v2 rules" in text and "--show" in text, agent
        assert set(a.servers) == {"browser", "notes"}, a.servers
        cmd = a.command("-rf everything")
        assert cmd[0] == agent, cmd
        a.has_session = True
        assert {"claude": "--continue", "codex": "resume", "gemini": "--resume"}[agent] in a.command("x")

    assert read(f"{ws}/app.py") == "built by Jamie"    # Jamie's work kept
    assert os.path.exists(f"{ws}/setup-ran")
    assert not os.path.exists(f"{ws}/.env") and not os.path.exists(f"{ws}/Dockerfile")  # secrets stay out
    assert set(json.load(open(bot.CLAUDE_MCP))["mcpServers"]) == {"browser", "notes"}
    assert set(json.load(open(f"{ws}/.gemini/settings.json"))["mcpServers"]) == {"browser", "notes"}
    flags = bot.codex_mcp(a.servers)
    assert 'mcp_servers.notes.env={K = "v"}' in flags and 'mcp_servers.browser.command="playwright-mcp"' in flags
    assert bot.Agent("gemini", {}).command("-rf x")[-1] == "--prompt=-rf x"  # not parsed as a flag

    # Claude stays running: requests reuse one process; reset starts over
    echo = [sys.executable, "-c", "import sys, json\nfor l in sys.stdin:\n"
            "    print(json.dumps({'type': 'assistant', 'note': 'x' * 100000}))\n"  # long event lines are fine
            "    print(json.dumps({'type': 'result', 'result': 'echo ' + json.loads(l)['message']['content']}), flush=True)"]
    c = bot.Agent("claude", {})
    c.command = lambda prompt=None: echo

    async def twice():
        first = await c.run("one")
        pid = c.proc.pid
        second = await c.run("two")
        assert (first, second) == ("echo one", "echo two") and c.proc.pid == pid and c.has_session
        await c.reset()
        assert c.proc is None and not c.has_session
    asyncio.run(twice())
    print("env OK")


if __name__ == "__main__":
    main()
