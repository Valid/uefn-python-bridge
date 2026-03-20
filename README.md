# UEFN Python Bridge

Control [UEFN](https://dev.epicgames.com/documentation/en-us/fortnite/unreal-editor-for-fortnite) from any AI agent, script, or automation tool via a local HTTP bridge.

```
Your Tool  ──HTTP POST──►  Bridge (inside UEFN)  ──main thread──►  unreal.* API
  (AI agent, Python                                     │
   script, CI, etc.)        127.0.0.1:9210              ▼
                                                   Editor actions
```

**Works with any LLM** — Claude, GPT, Gemini, Cursor, or plain Python scripts.
No vendor lock-in, no MCP, no SDK dependencies inside the editor.

## Features

- **30+ commands** — actors, assets, materials, viewport, levels, batch operations
- **`exec` command** — run arbitrary Python inside the editor for anything not covered
- **Batch execution** — send multiple commands in a single editor tick
- **Python client** — optional convenience library for external scripts
- **LLM rules file** — drop [`RULES.md`](RULES.md) into your AI tool for instant UEFN knowledge
- **API introspection tools** — dump the full UEFN API and generate `.pyi` stubs
- **Zero C++ compilation** — pure Python, stdlib only inside the editor

## Super-Quick Start (AI Agent)

Paste this into your AI agent of choice (Claude Code, Cursor, ChatGPT, etc.):

> Clone https://github.com/Valid/uefn-python-bridge and walk me through setting it up with my UEFN project.

The agent will clone the repo, read `RULES.md`, and guide you through enabling Python scripting and starting the bridge. That's it.

## Quick Start

### 1. Enable Python in UEFN

1. Open your project in UEFN
2. **Project dropdown → Project Settings → Enable Python Editor Scripting**

### 2. Start the bridge

In UEFN's Output Log command bar (bottom of the Output Log panel), type:

```
py "path/to/uefn-python-bridge/bridge/server.py"
```

You should see:
```
[Bridge] Bridge v0.1.0 listening on http://127.0.0.1:9210
[Bridge] 30 commands registered
```

> **Tip:** Use backslashes in the path for UEFN's file picker, e.g. `py "C:\Users\you\uefn-python-bridge\bridge\server.py"`

### 3. Send commands

**From Python:**

```python
from bridge.client import UEFNBridge

ue = UEFNBridge()
print(ue.status())
print(ue.actors())
ue.spawn(asset_path="/Engine/BasicShapes/Cube", location=[500, 0, 100])
```

**From curl:**

```bash
curl -X POST http://127.0.0.1:9210 \
  -H "Content-Type: application/json" \
  -d '{"command": "actors.list"}'
```

**From any HTTP client (JS, Go, Rust, etc.):**

```javascript
const resp = await fetch("http://127.0.0.1:9210", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    command: "actors.spawn",
    params: { actor_class: "PointLight", location: [0, 0, 200], label: "MyLight" }
  })
});
const data = await resp.json();
console.log(data.result.actor.label);
```

### 4. Use with AI agents

Drop [`RULES.md`](RULES.md) into your AI tool's context:

| Tool | How |
|------|-----|
| **Cursor** | Copy `RULES.md` → `.cursorrules` in project root |
| **Claude Code** | Copy `RULES.md` → `CLAUDE.md` in project root |
| **OpenClaw** | Copy `RULES.md` → skill's `SKILL.md` |
| **ChatGPT / Gemini / etc.** | Paste `RULES.md` into system prompt or context |

The rules file teaches the LLM everything it needs to generate working UEFN Python scripts.

## Commands

| Category | Commands |
|----------|----------|
| **System** | `status`, `exec`, `log`, `history`, `undo`, `redo`, `reload`, `shutdown`, `fix_throttle` |
| **Actors** | `actors.list`, `actors.selected`, `actors.spawn`, `actors.duplicate`, `actors.delete`, `actors.transform`, `actors.properties`, `actors.set_property`, `actors.set_color` |
| **Assets** | `assets.list`, `assets.info`, `assets.exists`, `assets.rename`, `assets.duplicate`, `assets.delete`, `assets.save`, `assets.search`, `assets.selected`, `assets.import_task` |
| **Level** | `level.info`, `level.save` |
| **Viewport** | `viewport.camera`, `viewport.set_camera` |
| **Batch** | `batch.exec` |

The `exec` command runs arbitrary Python inside the editor — if a structured command doesn't exist for what you need, `exec` can do it.

### Notable Commands

- **`actors.set_color`** — creates a persistent `MaterialInstanceConstant` and applies it. Pass `color: [r, g, b, a]` (0.0–1.0).
- **`actors.duplicate`** — clones an existing actor with all its meshes, materials, and properties intact. Great for creating copies of creative props.
- **`batch.exec`** — runs multiple commands in a single undo transaction.
- **`fix_throttle`** — disables UEFN's "Use Less CPU when in Background" so commands work when UEFN isn't focused.

## Project Structure

```
uefn-python-bridge/
├── bridge/
│   ├── server.py       ← HTTP server (runs inside UEFN)
│   ├── client.py       ← Python client (runs outside UEFN)
│   └── startup.py      ← Auto-start script (for standard UE5 projects)
├── tools/
│   ├── introspect_api.py   ← Dump full UEFN API to JSON
│   └── generate_stubs.py   ← Generate .pyi for IDE autocomplete
├── examples/
│   ├── actors.py
│   ├── assets.py
│   ├── materials.py
│   └── batch_operations.py
├── RULES.md            ← LLM context file (the main reference)
└── README.md
```

## How It Works

The bridge server runs inside the UEFN editor process:

1. A background thread runs an HTTP server on `127.0.0.1:9210`
2. Incoming commands are queued to the main editor thread
3. A Slate tick callback drains the queue every editor frame
4. Results are returned via the HTTP response

All `unreal.*` API calls must happen on the main thread — the tick callback ensures this. Thread-safe commands (`status`, `log`, `history`, etc.) bypass the queue and respond instantly.

The bridge starts in direct mode and automatically upgrades to tick mode once Slate ticks are detected (usually within 1–2 seconds of editor startup).

## Tools

### API Introspection

Run inside UEFN to dump all available Python types:

```
py "path/to/tools/introspect_api.py"
```

Output: `<Project>/Saved/uefn_api_introspection.json`

### Type Stub Generation

Generate `.pyi` stubs for IDE autocomplete:

```
py "path/to/tools/generate_stubs.py"
```

Output: `<Project>/Saved/unreal.pyi`

Then in VS Code / Cursor settings:
```json
{
  "python.analysis.extraPaths": ["path/to/Saved"]
}
```

## Configuration

### Custom Port

Edit `PORT_RANGE_START` in `bridge/server.py`, or the bridge will auto-detect
a free port in the range `9210–9220`.

### Custom Client Port

```python
from bridge.client import UEFNBridge
ue = UEFNBridge(port=9215)
```

## Important Notes

- **UEFN ≠ Unreal Engine.** Many standard UE5 Python APIs are missing or different. The `RULES.md` file documents what works and what doesn't.
- **Background throttle.** UEFN throttles tick callbacks when not focused. The bridge auto-disables this on start, but if commands time out, run `fix_throttle` or click the UEFN window.
- **Port reuse.** If UEFN crashes with the bridge running, the port may stay bound until you restart UEFN. The bridge detects and handles zombie ports on next startup.
- **`init_unreal.py` auto-start** does not work in UEFN (only standard Unreal Engine). Use the manual `py "..."` command in the Output Log.

## Requirements

- UEFN with Python Editor Scripting enabled
- Python 3.10+ on host for the client library (optional — curl works too)

## Contributing

PRs welcome. If you add new commands to `bridge/server.py`, please:
1. Use the `@command("category.name")` decorator
2. Add type hints and a docstring
3. Add an example in `examples/`
4. Update `RULES.md` with the new command

## Support

- Issues: [GitHub Issues](https://github.com/Valid/uefn-python-bridge/issues)
- Contact: jon@fchq.io
- Discord: [discord.gg/fchq](https://discord.gg/fchq)

## License

MIT
