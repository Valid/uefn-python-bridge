"""Compile the raw API introspection dump into usable reference files.

Takes the 355MB raw dump and produces:

1. api_summary.json     (~1 MB)  — Every type with member counts, bases, no hints
2. api_reference.json   (~15 MB) — Full detail for editor-relevant types only
3. api_index.md         (~200 KB) — Human/LLM-readable index of all types by domain
4. api_cheatsheet.md    (~50 KB)  — Top 50 most useful classes with key methods

Usage:
    python tools/compile_reference.py <path_to_uefn_api_introspection.json> [output_dir]

Output defaults to ./reference/
"""

import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Set

# ── Domain classification ──────────────────────────────────────────────────

DOMAIN_PATTERNS = {
    "Editor Core": [
        r"^Editor", r"^UnrealEd", r"^LevelEditor", r"^AssetEditor",
    ],
    "Actors & Levels": [
        r"^Actor", r"Level(?!Sequence)", r"^World", r"^Layer",
    ],
    "Assets & Registry": [
        r"^Asset", r"Registry", r"^Package", r"^Factory",
    ],
    "Materials": [
        r"^Material", r"^Shader",
    ],
    "Static Meshes": [
        r"^StaticMesh", r"^Mesh(?!Component)", r"^ProMesh",
    ],
    "Geometry Scripting": [
        r"^GeometryScript", r"^DynamicMesh",
    ],
    "PCG": [
        r"^PCG",
    ],
    "Skeletal & Animation": [
        r"^Anim", r"^Skeleton", r"^SkeletalMesh", r"^Bone",
        r"^BlendSpace", r"^Montage",
    ],
    "Niagara VFX": [
        r"^Niagara",
    ],
    "Sequencer & Cinematics": [
        r"^MovieScene", r"^LevelSequence", r"^Sequencer", r"^TakeRecorder",
    ],
    "Audio": [
        r"^Audio", r"^Sound", r"^Metasound", r"^Quartz", r"^Synesthesia",
    ],
    "Rendering & Post-Process": [
        r"^MovieGraph", r"^MoviePipeline", r"^MovieRender",
        r"^PostProcess", r"^Render",
    ],
    "UI / UMG": [
        r"^Widget", r"^UMG", r"^Slate", r"^Canvas",
    ],
    "Input": [
        r"^Input", r"^EnhancedInput", r"^PlayerInput",
    ],
    "Physics & Chaos": [
        r"^Chaos", r"^Physics", r"^Collision", r"^Geometry(?!Script)",
    ],
    "Landscape & Foliage": [
        r"^Landscape", r"^Foliage", r"^Grass",
    ],
    "Interchange (Import/Export)": [
        r"^Interchange",
    ],
    "Fortnite Core": [
        r"^Fort", r"^AFort", r"^UFort",
    ],
    "Fortnite Creative": [
        r"^Creative", r"^FortCreative", r"^Island",
    ],
    "Fortnite Modes": [
        r"^DelMar", r"^Sparks", r"^Juno", r"^Lego",
    ],
    "AI": [
        r"^AI", r"^BehaviorTree", r"^Blackboard", r"^NavMesh",
        r"^Navigation", r"^Crowd",
    ],
    "Networking": [
        r"^Net", r"^Replication", r"^Online",
    ],
    "Blueprints": [
        r"^Blueprint", r"^K2Node", r"^EdGraph",
    ],
}

# Classes that are particularly useful for editor scripting
PRIORITY_CLASSES = {
    "EditorActorSubsystem", "EditorAssetSubsystem", "EditorAssetLibrary",
    "EditorLevelLibrary", "EditorLevelUtils", "EditorUtilityLibrary",
    "EditorFilterLibrary", "LevelEditorSubsystem", "UnrealEditorSubsystem",
    "StaticMeshEditorSubsystem", "EditorValidatorSubsystem",
    "MaterialEditingLibrary", "AssetToolsHelpers", "AssetRegistryHelpers",
    "AssetImportTask", "AutomationLibrary", "EditorSkeletalMeshLibrary",
    "KismetMathLibrary", "KismetSystemLibrary", "KismetStringLibrary",
    "GameplayStatics", "SystemLibrary", "EditorLevelLibrary",
    "NiagaraFunctionLibrary", "GeometryScriptLibrary",
    # Core types
    "Actor", "StaticMeshActor", "PointLight", "SpotLight", "DirectionalLight",
    "CameraActor", "PlayerStart", "DecalActor",
    "StaticMesh", "SkeletalMesh", "Material", "MaterialInstanceConstant",
    "MaterialInstanceDynamic", "Texture2D", "TextureCube",
    "SoundWave", "SoundCue",
    "AnimSequence", "AnimMontage", "AnimBlueprint",
    "LevelSequence", "LevelSequenceActor",
    "NiagaraSystem", "NiagaraComponent",
    # Geometry types
    "Vector", "Rotator", "Transform", "LinearColor", "Color",
    "Vector2D", "Vector4", "Quat", "Box", "Sphere",
    # Asset data
    "AssetData", "ARFilter",
    # Factories
    "MaterialFactoryNew", "MaterialInstanceConstantFactoryNew",
    # Import/Export
    "InterchangeManager",
    # PCG
    "PCGComponent", "PCGGraph",
    # Subsystems
    "ImportSubsystem", "LayersSubsystem", "AssetEditorSubsystem",
}


def classify_type(name: str) -> str:
    """Assign a domain to a type name."""
    for domain, patterns in DOMAIN_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, name, re.IGNORECASE):
                return domain
    return "Other"


EDITOR_RELEVANT_DOMAINS = {
    "Editor Core", "Assets & Registry", "Materials", "Static Meshes",
    "Geometry Scripting", "Landscape & Foliage", "Blueprints",
}

# Domains where only small/utility types matter (skip giant inherited classes)
SELECTIVE_DOMAINS = {
    "Actors & Levels", "Sequencer & Cinematics", "Rendering & Post-Process",
    "PCG", "Niagara VFX", "Audio", "Skeletal & Animation", "Input",
    "UI / UMG", "Interchange (Import/Export)", "AI",
}

# Skip these entirely — read-only / not useful for scripting
SKIP_DOMAINS = {
    "Fortnite Core", "Fortnite Creative", "Fortnite Modes", "Networking",
}


def is_editor_relevant(name: str, info: dict) -> bool:
    """Determine if a type is useful for editor scripting."""
    if name in PRIORITY_CLASSES:
        return True
    domain = classify_type(name)

    if domain in SKIP_DOMAINS:
        return False

    if domain in EDITOR_RELEVANT_DOMAINS:
        return True

    if domain in SELECTIVE_DOMAINS:
        # Only include types that have their OWN methods (not just inherited),
        # or are subsystems/libraries
        members = info.get("members", {})
        own_methods = sum(1 for m in members.values() if m.get("kind") == "method")
        bases = info.get("bases", [])
        # Subsystems and Libraries are always useful
        if any(b in ("EditorSubsystem", "BlueprintFunctionLibrary") for b in bases):
            return True
        # Types with names ending in Subsystem/Library
        if name.endswith("Subsystem") or name.endswith("Library"):
            return True
        # Skip huge inherited-only classes (component/actor trees)
        if own_methods > 20 and len(bases) <= 2:
            return True
        return False

    # "Other" domain — only include if it looks like a utility/library
    if name.endswith(("Subsystem", "Library", "Helpers", "Utils")):
        return True
    return False


def compile_summary(data: dict) -> dict:
    """Create a lightweight summary: every type with member counts, no hints."""
    summary = {
        "meta": {
            "generated_from": data.get("generated_at", ""),
            "engine": data.get("engine_version", ""),
            "python": data.get("python_version", ""),
        },
        "stats": {},
        "functions": list(data.get("functions", {}).keys()),
        "types": {},
    }

    for section in ("classes", "enums", "structs"):
        items = data.get(section, {})
        summary["stats"][section] = len(items)
        for name, info in items.items():
            members = info.get("members", {})
            method_count = sum(1 for m in members.values() if m.get("kind") == "method")
            attr_count = sum(1 for m in members.values() if m.get("kind") in ("attribute", "property"))
            summary["types"][name] = {
                "kind": section.rstrip("es").rstrip("s"),  # class/enum/struct
                "domain": classify_type(name),
                "bases": info.get("bases", [])[:3],
                "methods": method_count,
                "attributes": attr_count,
            }

    return summary


def compile_reference(data: dict) -> dict:
    """Full detail for editor-relevant types only."""
    ref = {
        "meta": {
            "generated_from": data.get("generated_at", ""),
            "engine": data.get("engine_version", ""),
            "note": "Editor-relevant types with full method signatures",
        },
        "functions": data.get("functions", {}),
        "types": {},
    }

    for section in ("classes", "enums", "structs"):
        for name, info in data.get(section, {}).items():
            if not is_editor_relevant(name, info):
                continue
            # Include full detail but strip empty hints
            members = {}
            for mname, minfo in info.get("members", {}).items():
                entry = {"kind": minfo.get("kind", "unknown")}
                hint = minfo.get("hint", "").strip()
                if hint:
                    entry["sig"] = hint
                members[mname] = entry
            ref["types"][name] = {
                "kind": section.rstrip("es").rstrip("s"),
                "domain": classify_type(name),
                "bases": info.get("bases", []),
                "members": members,
            }

    return ref


def compile_index(summary: dict) -> str:
    """Human-readable markdown index grouped by domain."""
    lines = [
        "# UEFN Python API Index",
        "",
        f"Engine: {summary['meta']['engine']}",
        f"Generated: {summary['meta']['generated_from']}",
        "",
    ]

    # Stats
    stats = summary["stats"]
    total = sum(stats.values())
    lines.append(f"**{total:,} types** — {stats.get('classes', 0):,} classes, "
                 f"{stats.get('enums', 0):,} enums, {stats.get('structs', 0):,} structs, "
                 f"{len(summary.get('functions', []))} top-level functions")
    lines.append("")

    # Group by domain
    by_domain: Dict[str, List[dict]] = defaultdict(list)
    for name, info in summary["types"].items():
        by_domain[info["domain"]].append({"name": name, **info})

    for domain in sorted(by_domain.keys()):
        types = sorted(by_domain[domain], key=lambda t: t["methods"], reverse=True)
        lines.append(f"## {domain} ({len(types)} types)")
        lines.append("")

        # Show top types with most methods
        lines.append("| Type | Kind | Methods | Attrs | Bases |")
        lines.append("|------|------|---------|-------|-------|")
        for t in types[:30]:
            bases = ", ".join(t.get("bases", [])[:2]) or "—"
            lines.append(f"| {t['name']} | {t['kind']} | {t['methods']} | {t['attributes']} | {bases} |")
        if len(types) > 30:
            lines.append(f"| ... | | | | *+{len(types) - 30} more* |")
        lines.append("")

    return "\n".join(lines)


def compile_cheatsheet(data: dict) -> str:
    """Concise cheatsheet of the most useful classes with their key methods."""
    lines = [
        "# UEFN Python API Cheatsheet",
        "",
        "The most useful classes for editor scripting, with key methods.",
        "",
    ]

    for section in ("classes", "structs"):
        for name in sorted(PRIORITY_CLASSES):
            info = data.get(section, {}).get(name)
            if info is None:
                continue
            members = info.get("members", {})
            methods = {k: v for k, v in members.items() if v.get("kind") == "method"}
            if not methods:
                continue

            lines.append(f"## {name}")
            bases = info.get("bases", [])
            if bases:
                lines.append(f"*Inherits: {', '.join(bases[:3])}*")
            lines.append("")

            # Sort methods alphabetically, show signature
            for mname in sorted(methods.keys()):
                hint = methods[mname].get("hint", "").strip()
                if hint:
                    lines.append(f"- `{hint}`")
                else:
                    lines.append(f"- `{mname}()`")
            lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python compile_reference.py <uefn_api_introspection.json> [output_dir]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "reference"
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading {input_file}...")
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Compiling summary...")
    summary = compile_summary(data)
    out = os.path.join(output_dir, "api_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"  -> {out} ({os.path.getsize(out) / (1024*1024):.1f} MB)")

    print("Compiling editor reference...")
    ref = compile_reference(data)
    out = os.path.join(output_dir, "api_reference.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(ref, f, indent=1)
    print(f"  -> {out} ({os.path.getsize(out) / (1024*1024):.1f} MB) -- {len(ref['types']):,} types")

    print("Compiling markdown index...")
    index = compile_index(summary)
    out = os.path.join(output_dir, "api_index.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(index)
    print(f"  -> {out} ({os.path.getsize(out) / 1024:.0f} KB)")

    print("Compiling cheatsheet...")
    cheat = compile_cheatsheet(data)
    out = os.path.join(output_dir, "api_cheatsheet.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(cheat)
    print(f"  -> {out} ({os.path.getsize(out) / 1024:.0f} KB)")

    print("\nDone!")


if __name__ == "__main__":
    main()
