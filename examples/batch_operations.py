"""Example: Batch operations — execute multiple commands in one tick.

    python examples/batch_operations.py
"""

from bridge.client import UEFNBridge

ue = UEFNBridge()


# ── Spawn a grid of objects in a single tick ──────────────────────────────

commands = []
spacing = 200
for row in range(5):
    for col in range(5):
        commands.append({
            "command": "actors.spawn",
            "params": {
                "asset_path": "/Engine/BasicShapes/Cube",
                "location": [col * spacing, row * spacing, 0],
                "label": f"Grid_{row}_{col}",
            },
        })

results = ue.batch(commands)
spawned = sum(1 for r in results["results"] if r["success"])
print(f"Spawned {spawned}/{len(commands)} cubes in a single tick")


# ── Move them all up by 100 units ─────────────────────────────────────────

move_commands = []
for row in range(5):
    for col in range(5):
        move_commands.append({
            "command": "actors.transform",
            "params": {
                "target": f"Grid_{row}_{col}",
                "location": [col * spacing, row * spacing, 100],
            },
        })

ue.batch(move_commands)
print("Moved all cubes up")


# ── Delete them all ───────────────────────────────────────────────────────

labels = [f"Grid_{r}_{c}" for r in range(5) for c in range(5)]
deleted = ue.run("actors.delete", targets=labels)
print(f"Cleaned up {deleted['count']} cubes")
