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

## Quick Start

### 1. Enable Python in UEFN

1. Open your project in UEFN
2. **Edit → Project Settings** → search "Python"
3. Enable **Python Editor Script Plugin** and **Editor Scripting Utilities**
4. Restart UEFN
5. **Edit → Editor Preferences** → search "Python" → enable **Developer Mode**
6. Restart UEFN

### 2. Start the bridge

**Option A — Manual start:**

In UEFN: **Tools → Execute Python Script** → select `bridge/server.py`

You should see in the Output Log:
```
[Bridge 14:30:00] Bridge v0.1.0 listening on http://127.0.0.1:9210
[Bridge 14:30:00] 30 commands registered
```

**Option B — Auto-start on project open:**

Copy the `bridge/` folder to your project's `Content/Python/` directory, then
copy `bridge/startup.py` as `Content/Python/init_unreal.py`:

```
YourProject/Content/Python/
├── bridge/
│   ├── __init__.py
│   ├── server.py
│   └── ...
└── init_unreal.py    ← copy of bridge/startup.py
```

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
    params: { asset_path: "/Engine/BasicShapes/Sphere", location: [0, 0, 200] }
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
| **System** | `status`, `exec`, `log`, `history`, `undo`, `redo` |
| **Actors** | `actors.list`, `actors.selected`, `actors.spawn`, `actors.delete`, `actors.transform`, `actors.properties`, `actors.set_property` |
| **Assets** | `assets.list`, `assets.info`, `assets.exists`, `assets.rename`, `assets.duplicate`, `assets.delete`, `assets.save`, `assets.search`, `assets.selected`, `assets.import_task` |
| **Level** | `level.info`, `level.save` |
| **Viewport** | `viewport.camera`, `viewport.set_camera` |
| **Materials** | `materials.create_instance` |
| **Batch** | `batch.exec` |

The `exec` command runs arbitrary Python inside the editor — if a structured command doesn't exist for what you need, `exec` can do it.

## Project Structure

```
uefn-python-bridge/
├── bridge/
│   ├── server.py       ← HTTP server (runs inside UEFN)
│   ├── client.py       ← Python client (runs outside UEFN)
│   └── startup.py      ← Auto-start script (copy as init_unreal.py)
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
2. Incoming commands are queued
3. A Slate tick callback drains the queue on the **main editor thread**
4. Results are returned via the HTTP response

This is necessary because all `unreal.*` API calls must happen on the main
thread.  The tick callback fires every editor frame (30–120 fps), so commands
execute with sub-frame latency.

## Tools

### API Introspection

Run inside UEFN to dump all available Python types:

```
Tools → Execute Python Script → tools/introspect_api.py
```

Output: `<Project>/Saved/uefn_api_introspection.json`

### Type Stub Generation

Generate `.pyi` stubs for IDE autocomplete:

```
Tools → Execute Python Script → tools/generate_stubs.py
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

## Requirements

- UEFN with Python scripting enabled (see Quick Start step 1)
- Python 3.10+ on host for the client library (optional — curl works too)

## Contributing

PRs welcome.  If you add new commands to `bridge/server.py`, please:
1. Use the `@command("category.name")` decorator
2. Add type hints and a docstring
3. Add an example in `examples/`
4. Update `RULES.md` with the new command

## License

MIT
