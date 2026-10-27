# Addons

Ready-made tools that aren't installed in any room yet. Each one waits here until a room's owner
decides to add it. Nothing in `addons/` reaches a Jamie by itself: it never shows up in the
extension and never gets copied into a Jamie's working folder.

| Addon | What it does | For |
|---|---|---|
| [wolfram](wolfram/) | Asks Wolfram\|Alpha: math, unit conversions, facts and data | math |

## Adding one to a room

Every addon's own README has the exact steps. They always follow the same pattern:

1. Copy its files into `environments/<room>/`.
2. Put any keys in that room's `.env`. It's gitignored, so keys stay on your machine.
3. Paste its snippet into the room's `ROOM.md`. Without that, Jamie may never use the tool.
4. Send a new Jamie into that room. Jamies already in a call don't pick up changes.

Read [environments/README.md](../environments/README.md) for how rooms use these files.

## Making an addon

Make a folder `addons/<name>/` with:

- **The tool.** Prefer a script Jamie can run (`python3 tool.py '<input>'`): every agent can use
  it, and it needs nothing installed. Use an MCP server (`mcp.json` snippet) only when the tool
  needs to keep state or the server already exists.
- **`README.md`**, which says:
  - what it does
  - how to add it: which files to copy, which keys to get and where
  - the `ROOM.md` snippet to paste
  - anything the room's `Dockerfile` needs
  - a test prompt to try it
  - what has and hasn't been tested
- **`.env.example`** if it needs keys. Never commit a real key.

Then add a row to the table above.

Good addon scripts:
- fail with a clear message when a key is missing, so Jamie can tell people and carry on
- print plain text, which the agent can read straight away
- keep output short, because Jamie's chat replies are limited to about 1200 characters
