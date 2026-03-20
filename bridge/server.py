"""UEFN Python Bridge — HTTP server that runs inside the UEFN editor.

Provides a local REST API so external tools (AI agents, scripts, CI pipelines)
can execute Python inside the editor.  All `unreal.*` calls are routed to the
main editor thread via Slate tick callbacks, keeping things thread-safe.

Start manually:
    Tools > Execute Python Script > select this file

Or auto-start:
    Copy bridge/ folder + startup.py to <Project>/Content/Python/

Docs & source: https://github.com/Valid/uefn-python-bridge
"""

from __future__ import annotations

import io
import json
import os
import queue
import socket
import sys
import threading
import time
import traceback
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, List, Optional

import unreal

# ── Configuration ──────────────────────────────────────────────────────────

PORT_RANGE_START = 9210
PORT_RANGE_END = 9220
WORKER_BATCH_SIZE = 8          # max commands per tick
REQUEST_TIMEOUT_S = 30.0
POLL_SLEEP_S = 0.015           # ~66 Hz polling
HISTORY_CAP = 500              # max entries in command history
LOG_CAP = 300                  # max log ring entries
VERSION = "0.1.0"

# ── Runtime state ──────────────────────────────────────────────────────────

_http: Optional[HTTPServer] = None
_http_thread: Optional[threading.Thread] = None
_tick_handle: Optional[object] = None
_active_port: int = 0

_work_queue: queue.Queue = queue.Queue()
_results: Dict[str, dict] = {}
_results_lock = threading.Lock()

_log_lines: List[str] = []
_history: List[dict] = []

# ── Logging ────────────────────────────────────────────────────────────────


def _log(msg: str, level: str = "info") -> None:
    ts = time.strftime("%H:%M:%S")
    entry = f"[Bridge {ts}] {msg}"
    _log_lines.append(entry)
    while len(_log_lines) > LOG_CAP:
        _log_lines.pop(0)
    {"error": unreal.log_error, "warn": unreal.log_warning}.get(
        level, unreal.log
    )(entry)


# ── Serialisation helpers ──────────────────────────────────────────────────


def to_json_safe(obj: Any) -> Any:
    """Recursively convert Unreal objects into JSON-friendly Python types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    # Geometry
    if isinstance(obj, unreal.Vector):
        return {"x": obj.x, "y": obj.y, "z": obj.z}
    if isinstance(obj, unreal.Rotator):
        return {"pitch": obj.pitch, "yaw": obj.yaw, "roll": obj.roll}
    if isinstance(obj, unreal.Vector2D):
        return {"x": obj.x, "y": obj.y}
    if isinstance(obj, unreal.Transform):
        return {
            "translation": to_json_safe(obj.translation),
            "rotation": to_json_safe(obj.rotation.rotator()),
            "scale": to_json_safe(obj.scale3d),
        }
    # Colour
    if isinstance(obj, (unreal.LinearColor, unreal.Color)):
        return {"r": obj.r, "g": obj.g, "b": obj.b, "a": obj.a}
    # Assets
    if isinstance(obj, unreal.AssetData):
        info: Dict[str, str] = {
            "asset_name": str(obj.asset_name),
            "package_name": str(obj.package_name),
            "package_path": str(obj.package_path),
        }
        if hasattr(obj, "asset_class_path"):
            info["asset_class"] = str(obj.asset_class_path.asset_name)
        elif hasattr(obj, "asset_class"):
            info["asset_class"] = str(obj.asset_class)
        return info
    # Generic unreal objects
    for attr in ("get_path_name", "get_name"):
        fn = getattr(obj, attr, None)
        if fn:
            return str(fn())
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def actor_summary(actor: unreal.Actor) -> dict:
    """Return a lightweight dict describing an actor."""
    return {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "path": actor.get_path_name(),
        "location": to_json_safe(actor.get_actor_location()),
        "rotation": to_json_safe(actor.get_actor_rotation()),
        "scale": to_json_safe(actor.get_actor_scale3d()),
    }


# ── Command registry ──────────────────────────────────────────────────────

_commands: Dict[str, Callable] = {}


def command(name: str):
    """Register a callable as a bridge command."""
    def _wrap(fn: Callable):
        _commands[name] = fn
        return fn
    return _wrap


def run_command(name: str, params: dict) -> dict:
    """Look up and execute a registered command (must be called on main thread)."""
    fn = _commands.get(name)
    if fn is None:
        raise KeyError(f"Unknown command '{name}'. Available: {sorted(_commands)}")
    return fn(**params)


# ── Built-in commands ──────────────────────────────────────────────────────
# Each command returns a plain dict; the bridge JSON-encodes it for the caller.


@command("status")
def _cmd_status() -> dict:
    return {
        "bridge_version": VERSION,
        "python": sys.version.split()[0],
        "port": _active_port,
        "uptime_s": round(time.monotonic() - _start_mono, 1) if _start_mono else 0,
        "commands": sorted(_commands),
    }


@command("exec")
def _cmd_exec(code: str, transaction: str = "") -> dict:
    """Run arbitrary Python inside the editor.  Assign to `result` to return
    a value; use print() for stdout.

    If ``transaction`` is provided, the code runs inside an
    ``unreal.ScopedEditorTransaction`` so the entire operation is a single
    undo entry in the editor.
    """
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    ns: Dict[str, Any] = {"__builtins__": __builtins__, "unreal": unreal, "result": None}
    # convenience subsystem refs
    for alias, cls_name in [
        ("actors", "EditorActorSubsystem"),
        ("assets", "EditorAssetSubsystem"),
        ("levels", "LevelEditorSubsystem"),
    ]:
        try:
            ns[alias] = unreal.get_editor_subsystem(getattr(unreal, cls_name))
        except Exception:
            pass
    try:
        sys.stdout, sys.stderr = out, err
        if transaction:
            with unreal.ScopedEditorTransaction(transaction):
                exec(code, ns)
        else:
            exec(code, ns)
    except Exception:
        traceback.print_exc(file=err)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return {
        "result": to_json_safe(ns.get("result")),
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
    }


@command("log")
def _cmd_log(tail: int = 80) -> dict:
    return {"lines": _log_lines[-tail:]}


@command("history")
def _cmd_history(tail: int = 30) -> dict:
    return {"entries": _history[-tail:]}


@command("shutdown")
def _cmd_shutdown() -> dict:
    """Stop the bridge server.  Re-run the py command to start again."""
    import threading
    def _do_stop():
        time.sleep(0.2)  # let the response flush
        stop()
    threading.Thread(target=_do_stop, daemon=True).start()
    return {"message": "Shutting down..."}


@command("reload")
def _cmd_reload() -> dict:
    """Stop the server, re-read the script from disk, and restart."""
    import threading
    script_path = os.path.join(os.path.dirname(__file__), "server.py")
    def _do_reload():
        time.sleep(0.2)  # let the response flush
        stop()
        time.sleep(0.3)
        _log("Reloading from disk...")
        with open(script_path, "r") as f:
            code = f.read()
        exec(code, {"__file__": script_path, "__name__": "__reloaded__", "__builtins__": __builtins__})
    threading.Thread(target=_do_reload, daemon=True).start()
    return {"message": f"Reloading from {script_path}..."}


# ── Actor commands ─────────────────────────────────────────────────────────


def _get_actor_sub():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _find_actor(identifier: str) -> unreal.Actor:
    """Resolve an actor by path OR label."""
    for a in _get_actor_sub().get_all_level_actors():
        if a.get_path_name() == identifier or a.get_actor_label() == identifier:
            return a
    raise ValueError(f"Actor not found: {identifier}")


@command("actors.list")
def _cmd_actors_list(class_filter: str = "") -> dict:
    actors = _get_actor_sub().get_all_level_actors()
    if class_filter:
        actors = [a for a in actors if a.get_class().get_name() == class_filter]
    return {"actors": [actor_summary(a) for a in actors], "count": len(actors)}


@command("actors.selected")
def _cmd_actors_selected() -> dict:
    actors = _get_actor_sub().get_selected_level_actors()
    return {"actors": [actor_summary(a) for a in actors], "count": len(actors)}


@command("actors.spawn")
def _cmd_actors_spawn(
    asset_path: str = "",
    actor_class: str = "",
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    label: str = "",
    transaction: str = "",
) -> dict:
    def _do():
        loc = unreal.Vector(*(location or [0, 0, 0]))
        rot = unreal.Rotator(*(rotation or [0, 0, 0]))
        actor = None
        if asset_path:
            asset = unreal.EditorAssetLibrary.load_asset(asset_path)
            if not asset:
                raise ValueError(f"Asset not found: {asset_path}")
            actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, loc, rot)
        elif actor_class:
            cls = getattr(unreal, actor_class, None)
            if cls is None:
                raise ValueError(f"Class not found: {actor_class}")
            actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, rot)
        else:
            raise ValueError("Provide asset_path or actor_class")
        if actor is None:
            raise RuntimeError("Spawn failed")
        if label:
            actor.set_actor_label(label)
        return {"actor": actor_summary(actor)}
    txn = transaction or f"Spawn {actor_class or asset_path}"
    with unreal.ScopedEditorTransaction(txn):
        return _do()


@command("actors.delete")
def _cmd_actors_delete(targets: List[str], transaction: str = "") -> dict:
    txn = transaction or f"Delete {len(targets)} actor(s)"
    with unreal.ScopedEditorTransaction(txn):
        sub = _get_actor_sub()
        all_actors = sub.get_all_level_actors()
        removed = []
        for t in targets:
            for a in all_actors:
                if a.get_path_name() == t or a.get_actor_label() == t:
                    sub.destroy_actor(a)
                    removed.append(t)
                    break
    return {"deleted": removed, "count": len(removed)}


@command("actors.transform")
def _cmd_actors_transform(
    target: str,
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    transaction: str = "",
) -> dict:
    txn = transaction or f"Transform {target}"
    with unreal.ScopedEditorTransaction(txn):
        actor = _find_actor(target)
        if location is not None:
            actor.set_actor_location(unreal.Vector(*location), False, False)
        if rotation is not None:
            actor.set_actor_rotation(unreal.Rotator(*rotation), False)
        if scale is not None:
            actor.set_actor_scale3d(unreal.Vector(*scale))
    return {"actor": actor_summary(actor)}


@command("actors.properties")
def _cmd_actors_properties(target: str, properties: List[str]) -> dict:
    actor = _find_actor(target)
    vals = {}
    for p in properties:
        try:
            vals[p] = to_json_safe(actor.get_editor_property(p))
        except Exception as exc:
            vals[p] = f"<error: {exc}>"
    return {"target": target, "properties": vals}


@command("actors.set_property")
def _cmd_actors_set_property(target: str, property_name: str, value: Any, transaction: str = "") -> dict:
    txn = transaction or f"Set {property_name} on {target}"
    with unreal.ScopedEditorTransaction(txn):
        actor = _find_actor(target)
        actor.set_editor_property(property_name, value)
    return {"target": target, "property": property_name, "value": to_json_safe(value)}


# ── Asset commands ─────────────────────────────────────────────────────────


@command("assets.list")
def _cmd_assets_list(
    directory: str = "/Game/",
    recursive: bool = True,
    class_filter: str = "",
) -> dict:
    paths = unreal.EditorAssetLibrary.list_assets(directory, recursive=recursive)
    if class_filter:
        filtered = []
        for p in paths:
            data = unreal.EditorAssetLibrary.find_asset_data(p)
            if data:
                cls = str(data.asset_class_path.asset_name) if hasattr(data, "asset_class_path") else str(getattr(data, "asset_class", ""))
                if cls == class_filter:
                    filtered.append(str(p))
        paths = filtered
    else:
        paths = [str(p) for p in paths]
    return {"assets": paths, "count": len(paths)}


@command("assets.info")
def _cmd_assets_info(path: str) -> dict:
    data = unreal.EditorAssetLibrary.find_asset_data(path)
    if data is None:
        raise ValueError(f"Asset not found: {path}")
    return {"asset": to_json_safe(data)}


@command("assets.exists")
def _cmd_assets_exists(path: str) -> dict:
    return {"exists": unreal.EditorAssetLibrary.does_asset_exist(path), "path": path}


@command("assets.rename")
def _cmd_assets_rename(old_path: str, new_path: str) -> dict:
    ok = unreal.EditorAssetLibrary.rename_asset(old_path, new_path)
    return {"success": ok, "old_path": old_path, "new_path": new_path}


@command("assets.duplicate")
def _cmd_assets_duplicate(source: str, destination: str) -> dict:
    result = unreal.EditorAssetLibrary.duplicate_asset(source, destination)
    return {"success": result is not None, "source": source, "destination": destination}


@command("assets.delete")
def _cmd_assets_delete(path: str) -> dict:
    ok = unreal.EditorAssetLibrary.delete_asset(path)
    return {"success": ok, "path": path}


@command("assets.save")
def _cmd_assets_save(path: str) -> dict:
    ok = unreal.EditorAssetLibrary.save_asset(path)
    return {"success": ok, "path": path}


@command("assets.search")
def _cmd_assets_search(
    class_name: str = "",
    directory: str = "/Game/",
    recursive: bool = True,
) -> dict:
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    filt = unreal.ARFilter()
    if directory:
        filt.package_paths = [directory]
    filt.recursive_paths = recursive
    if class_name:
        try:
            filt.class_names = [class_name]
        except Exception:
            pass
    results = reg.get_assets(filt)
    return {"assets": [to_json_safe(a) for a in results], "count": len(results)}


@command("assets.selected")
def _cmd_assets_selected() -> dict:
    sel = unreal.EditorUtilityLibrary.get_selected_assets()
    return {"assets": [to_json_safe(a) for a in sel], "count": len(sel)}


@command("assets.import_task")
def _cmd_assets_import(
    source_file: str,
    destination_path: str,
    replace_existing: bool = True,
    automated: bool = True,
    save: bool = True,
) -> dict:
    task = unreal.AssetImportTask()
    task.filename = source_file
    task.destination_path = destination_path
    task.replace_existing = replace_existing
    task.automated = automated
    task.save = save
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = [str(p) for p in task.imported_object_paths] if hasattr(task, "imported_object_paths") else []
    return {"imported": imported, "source": source_file}


# ── Level commands ─────────────────────────────────────────────────────────


@command("level.info")
def _cmd_level_info() -> dict:
    world = unreal.EditorLevelLibrary.get_editor_world()
    actors = _get_actor_sub().get_all_level_actors()
    return {
        "world_name": world.get_name() if world else "None",
        "actor_count": len(actors),
    }


@command("level.save")
def _cmd_level_save() -> dict:
    ok = unreal.EditorLevelLibrary.save_current_level()
    return {"success": ok}


# ── Viewport commands ──────────────────────────────────────────────────────


@command("viewport.camera")
def _cmd_viewport_camera() -> dict:
    loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
    return {"location": to_json_safe(loc), "rotation": to_json_safe(rot)}


@command("viewport.set_camera")
def _cmd_viewport_set_camera(
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
) -> dict:
    cur_loc, cur_rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
    loc = unreal.Vector(*location) if location else cur_loc
    rot = unreal.Rotator(*rotation) if rotation else cur_rot
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, rot)
    return {"location": to_json_safe(loc), "rotation": to_json_safe(rot)}


# ── Material commands ──────────────────────────────────────────────────────


@command("materials.create_instance")
def _cmd_materials_create_instance(
    parent_path: str,
    instance_name: str,
    destination: str = "/Game/Materials",
    scalar_params: Optional[Dict[str, float]] = None,
    vector_params: Optional[Dict[str, List[float]]] = None,
    texture_params: Optional[Dict[str, str]] = None,
) -> dict:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()
    mi = tools.create_asset(instance_name, destination, unreal.MaterialInstanceConstant, factory)
    if not mi:
        raise RuntimeError(f"Failed to create material instance '{instance_name}'")
    parent = unreal.EditorAssetLibrary.load_asset(parent_path)
    if parent:
        mi.set_editor_property("parent", parent)
    if scalar_params:
        for k, v in scalar_params.items():
            unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(mi, k, v)
    if vector_params:
        for k, v in vector_params.items():
            col = unreal.LinearColor(*v) if len(v) == 4 else unreal.LinearColor(v[0], v[1], v[2], 1.0)
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mi, k, col)
    if texture_params:
        for k, v in texture_params.items():
            tex = unreal.EditorAssetLibrary.load_asset(v)
            if tex:
                unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(mi, k, tex)
    return {"path": str(mi.get_path_name())}


# ── Batch / utility commands ──────────────────────────────────────────────


@command("batch.exec")
def _cmd_batch_exec(commands: List[dict], transaction: str = "") -> dict:
    """Execute multiple commands in sequence within a single undo transaction."""
    txn = transaction or f"Batch: {len(commands)} commands"
    results = []
    with unreal.ScopedEditorTransaction(txn):
        for i, item in enumerate(commands):
            name = item.get("command", "")
            params = item.get("params", {})
            params.pop("transaction", None)  # avoid nested transactions
            try:
                r = run_command(name, params)
                results.append({"index": i, "success": True, "result": r})
            except Exception as exc:
                results.append({"index": i, "success": False, "error": str(exc)})
    return {"results": results, "count": len(results)}


@command("undo")
def _cmd_undo() -> dict:
    ok = unreal.EditorLoadingAndSavingUtils.unload_unused_assets if hasattr(unreal, "GEditor") else False
    # GEditor access varies; use the transaction system
    try:
        unreal.SystemLibrary.execute_console_command(None, "TRANSACTION UNDO")
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@command("redo")
def _cmd_redo() -> dict:
    try:
        unreal.SystemLibrary.execute_console_command(None, "TRANSACTION REDO")
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@command("fix_throttle")
def _cmd_fix_throttle() -> dict:
    """Disable 'Use Less CPU when in Background' — callable at any time."""
    _disable_background_throttle()
    return {"success": True}


# ── HTTP layer ─────────────────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    """Minimal REST handler.  GET / for health; POST / to run commands."""

    def do_GET(self) -> None:
        body = json.dumps({
            "bridge": "uefn-python-bridge",
            "version": VERSION,
            "port": _active_port,
            "commands": sorted(_commands),
        }).encode()
        self._respond(200, body)

    def do_POST(self) -> None:
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            self._respond(400, json.dumps({"ok": False, "error": f"Bad JSON: {exc}"}).encode())
            return

        cmd = payload.get("command", "")
        params = payload.get("params", {})
        if not cmd:
            self._respond(400, json.dumps({"ok": False, "error": "Missing 'command'"}).encode())
            return

        rid = uuid.uuid4().hex

        # Thread-safe commands can always run directly on the HTTP thread
        if cmd in _THREAD_SAFE_COMMANDS:
            resp = _execute_and_respond(rid, cmd, params)
            self._respond(200, json.dumps(resp).encode())
            return

        # Unreal-API commands must run on the main (game) thread via tick queue
        _work_queue.put((rid, cmd, params))

        # If tick callback isn't processing, nudge with a one-shot callback
        if _dispatch_mode == "direct":
            try:
                def _oneshot(dt):
                    _tick(dt)
                    try:
                        unreal.unregister_slate_post_tick_callback(_oneshot)
                    except Exception:
                        pass
                unreal.register_slate_post_tick_callback(_oneshot)
            except Exception:
                pass  # fall through to poll loop either way

        deadline = time.monotonic() + REQUEST_TIMEOUT_S
        throttle_retry = False
        while time.monotonic() < deadline:
            with _results_lock:
                if rid in _results:
                    resp = _results.pop(rid)
                    self._respond(200, json.dumps(resp).encode())
                    return
            # If we've waited more than half the timeout, try re-disabling
            # background throttle in case user re-enabled it
            if not throttle_retry and (time.monotonic() - deadline + REQUEST_TIMEOUT_S) > REQUEST_TIMEOUT_S * 0.5:
                throttle_retry = True
                _disable_background_throttle()
            time.sleep(POLL_SLEEP_S)
        self._respond(504, json.dumps({"ok": False, "error": f"'{cmd}' timed out ({REQUEST_TIMEOUT_S}s). Unreal API calls require the editor main thread — ensure UEFN is focused."}).encode())

    # Allow cross-origin for web-based tools
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *_: Any) -> None:
        pass  # silence default stderr spam


# ── Command execution ──────────────────────────────────────────────────────

_start_mono: float = 0
_dispatch_mode: str = "direct"  # "tick" or "direct"
_tick_health: int = 0           # incremented by tick callback

# Commands that are safe to run from any thread (no Unreal subsystem calls)
_THREAD_SAFE_COMMANDS = frozenset({"status", "log", "history", "shutdown", "reload", "fix_throttle"})


def _execute_and_respond(rid: str, cmd: str, params: dict) -> dict:
    """Execute a command and return the response dict.  Thread-safe logging."""
    t0 = time.monotonic()
    try:
        data = run_command(cmd, params)
        resp = {"ok": True, "result": data}
    except Exception as exc:
        _log(f"Command '{cmd}' failed: {exc}", "error")
        resp = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    _history.append({"command": cmd, "elapsed_ms": elapsed_ms, "ok": resp.get("ok", False)})
    while len(_history) > HISTORY_CAP:
        _history.pop(0)
    return resp


def _tick(dt: float) -> None:
    """Drain the work queue on the editor's main thread (if tick dispatch is active)."""
    global _tick_health
    _tick_health += 1
    done = 0
    while not _work_queue.empty() and done < WORKER_BATCH_SIZE:
        try:
            rid, cmd, params = _work_queue.get_nowait()
        except queue.Empty:
            break
        resp = _execute_and_respond(rid, cmd, params)
        with _results_lock:
            _results[rid] = resp
        done += 1


# ── Start / Stop ───────────────────────────────────────────────────────────


def _pick_port() -> int:
    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        # First check if something is already listening
        test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test.settimeout(0.5)
        try:
            test.connect(("127.0.0.1", port))
            test.close()
            continue  # Port in use by a live server
        except (ConnectionRefusedError, OSError, TimeoutError):
            test.close()

        # Try to bind WITHOUT SO_REUSEADDR to avoid ghost binds
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"No free port in {PORT_RANGE_START}–{PORT_RANGE_END}")


def _disable_background_throttle() -> None:
    """Disable 'Use Less CPU when in Background' so tick callbacks fire
    even when UEFN is not the focused window."""
    success = False

    # Method 1: EditorPerformanceSettings CDO
    try:
        settings = unreal.get_default_object(unreal.EditorPerformanceSettings)
        if settings.get_editor_property("use_less_cpu_when_in_background"):
            settings.set_editor_property("use_less_cpu_when_in_background", False)
            _log("Disabled 'Use Less CPU when in Background' via EditorPerformanceSettings")
            success = True
    except Exception as e:
        _log(f"EditorPerformanceSettings method failed: {e}")

    # Method 2: Direct CVar access
    if not success:
        try:
            cvar = unreal.ConsoleVariable.find("t.IdleWhenNotForeground")
            if cvar:
                cvar.set_int(0)
                _log("Disabled background throttle via CVar")
                success = True
        except Exception:
            pass

    # Method 3: Console command — try various world context approaches
    if not success:
        for world_ctx in [None]:
            try:
                unreal.SystemLibrary.execute_console_command(
                    world_ctx, "t.IdleWhenNotForeground 0"
                )
                _log("Disabled background throttle via console command")
                success = True
                break
            except Exception:
                pass

    # Method 4: Keep-alive ticker — if we can't disable throttle,
    # ensure ticks fire by periodically requesting focus
    if not success:
        _log("WARNING: Could not disable background CPU throttle. "
             "Manually uncheck: Edit → Editor Preferences → General → "
             "Performance → 'Use Less CPU when in Background'")


def start(port: int = 0, mode: str = "auto") -> int:
    """Start the bridge.  Returns the bound port.

    Args:
        port: Port to bind (0 = auto-detect).
        mode: Dispatch mode — "auto" (detect best), "direct", or "tick".
    """
    global _http, _http_thread, _tick_handle, _active_port, _start_mono, _dispatch_mode

    if _http is not None:
        # Check if previous server is actually alive
        if _http_thread and _http_thread.is_alive():
            _log(f"Already running on :{_active_port}", "warn")
            return _active_port
        else:
            _log("Previous server died — cleaning up and restarting")
            try:
                _http.server_close()
            except Exception:
                pass
            _http = None

    _disable_background_throttle()

    port = port or _pick_port()
    # Override allow_reuse_address to prevent ghost binds
    HTTPServer.allow_reuse_address = False
    _http = HTTPServer(("127.0.0.1", port), _Handler)
    _active_port = port
    _start_mono = time.monotonic()

    def _serve():
        try:
            _log("HTTP server thread started")
            _http.serve_forever()
            _log("HTTP server thread exited normally")
        except Exception as exc:
            _log(f"HTTP server crashed: {exc}", "error")
            import traceback
            _log(traceback.format_exc(), "error")

    _http_thread = threading.Thread(target=_serve, daemon=True)
    _http_thread.start()

    # Register tick callback (useful even in direct mode for background tasks)
    try:
        _tick_handle = unreal.register_slate_post_tick_callback(_tick)
    except Exception as exc:
        _log(f"Tick callback registration failed: {exc}", "warn")
        _tick_handle = None

    # Auto-detect dispatch mode
    if mode == "auto":
        # Start in direct mode, but keep checking for ticks in background.
        # During editor startup, ticks often don't fire yet.
        _dispatch_mode = "direct"
        _log("Dispatch: starting in direct mode, will upgrade to tick mode when available")

        def _tick_upgrader():
            """Background thread that upgrades to tick dispatch once Slate ticks are detected."""
            global _dispatch_mode
            for attempt in range(30):  # Check for up to ~30 seconds
                time.sleep(1.0)
                if _tick_health > 0:
                    _dispatch_mode = "tick"
                    _log("Dispatch: upgraded to tick mode (Slate ticks detected)")
                    return
            _log("Dispatch: staying in direct mode (no Slate ticks after 30s)")

        threading.Thread(target=_tick_upgrader, daemon=True).start()
    else:
        _dispatch_mode = mode
        _log(f"Dispatch: {mode} (manual)")

    _log(f"Bridge v{VERSION} listening on http://127.0.0.1:{port}")
    _log(f"{len(_commands)} commands registered")
    return port


def stop() -> None:
    """Shut the bridge down cleanly."""
    global _http, _http_thread, _tick_handle, _active_port

    if _http is None:
        _log("Not running", "warn")
        return

    if _tick_handle:
        unreal.unregister_slate_post_tick_callback(_tick_handle)
        _tick_handle = None

    _http.shutdown()
    if _http_thread:
        _http_thread.join(timeout=3)

    _log(f"Stopped (was :{_active_port})")
    _http = None
    _http_thread = None
    _active_port = 0


def restart(port: int = 0) -> int:
    stop()
    time.sleep(0.3)
    return start(port)


# ── Auto-start when executed directly ──────────────────────────────────────

if __name__ != "__reloaded__":
    start()
else:
    # Reload path — re-register commands already defined above, then start
    start()
