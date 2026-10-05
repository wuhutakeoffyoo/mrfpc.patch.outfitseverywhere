"""Export the reviewed v0.9.3 protagonist field DCL repair for packaging.

The input resource directory is always read-only. Only the independently read
primary geometry is replaced; the v210 prefix and outfit bone records survive.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

MANIFEST_PATH = Path(__file__).with_name("field_collision_patch.json")
CHARACTERS = ("0001", "0020")
PLATFORMS = ("COMMON", "XBOX")
PRIMARY_OFFSET = 4
PRIMARY_LENGTH = 52
TAIL_OFFSET = PRIMARY_OFFSET + PRIMARY_LENGTH


def digest(data):
    return hashlib.sha256(data).hexdigest()


def target_paths():
    return {
        f"MFEssentials/CPK/FIELD.CPK/{platform}/model/character/{character}/"
        f"collision/c_{character}_{outfit}_F.DCL"
        for platform in PLATFORMS
        for character in CHARACTERS
        for outfit in range(201, 209)
    }


def validate_manifest(manifest):
    if manifest.get("format") != 1 or manifest.get("mod_version") != "0.9.3":
        raise ValueError("unsupported patch manifest")
    rows = manifest["files"]
    if len(rows) != 32 or {row["path"] for row in rows} != target_paths():
        raise ValueError("manifest must contain exactly the 32 reviewed field DCL paths")
    geometry = manifest["primary_geometry_hex"]
    if set(geometry) != set(CHARACTERS):
        raise ValueError("unexpected character geometry")
    for value in geometry.values():
        validate_primary(bytes.fromhex(value))
    for row in rows:
        for key in ("before_sha256", "after_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                raise ValueError("invalid resource hash")


def validate_primary(primary):
    if len(primary) != PRIMARY_LENGTH or struct.unpack_from("<I", primary)[0] != 1:
        raise ValueError("expected type-1 native field primary geometry")


def patch_bytes(data, primary):
    validate_primary(primary)
    if len(data) < TAIL_OFFSET + 4 or struct.unpack_from("<II", data) != (210, 1):
        raise ValueError("expected a v210, type-1 DCL")
    count = struct.unpack_from("<I", data, TAIL_OFFSET)[0]
    if count != 13 or len(data) != TAIL_OFFSET + 4 + count * 204:
        raise ValueError("unexpected outfit bone-record layout")
    return data[:PRIMARY_OFFSET] + primary + data[TAIL_OFFSET:]


def contained_path(root, relative):
    root = root.resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"path escapes the selected directory: {relative}")
    return path


@dataclass(frozen=True)
class PlannedFile:
    path: str
    data: bytes
    changed: bool


def plan_patch(mod_root, manifest):
    validate_manifest(manifest)
    plan = []
    for row in manifest["files"]:
        data = contained_path(mod_root, row["path"]).read_bytes()
        before_hash = digest(data)
        if before_hash not in (row["before_sha256"], row["after_sha256"]):
            raise ValueError(f"unreviewed resource; refusing to patch: {row['path']}")
        character = row["path"].split("/")[6]
        primary = bytes.fromhex(manifest["primary_geometry_hex"][character])
        patched = patch_bytes(data, primary)
        if digest(patched) != row["after_sha256"]:
            raise ValueError(f"patched hash does not match the reviewed repair: {row['path']}")
        plan.append(PlannedFile(row["path"], patched, before_hash != row["after_sha256"]))
    return plan


def export_patch(mod_root, output_root, plan):
    mod_root, output_root = mod_root.resolve(), output_root.resolve()
    if output_root.is_relative_to(mod_root) or mod_root.is_relative_to(output_root):
        raise ValueError("output must be separate from the input mod resource directory")
    destinations = [(item, contained_path(output_root, item.path)) for item in plan]
    # Validate every existing destination before exporting any file.
    for item, path in destinations:
        if path.exists() and path.read_bytes() != item.data:
            raise ValueError(f"output has different content; refusing to overwrite: {item.path}")
    for item, path in destinations:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(item.data)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def run(mod_root, output_root, manifest):
    plan = plan_patch(mod_root, manifest)
    if output_root is not None:
        export_patch(mod_root, output_root, plan)
    return {
        "status": "PASS",
        "checked_files": len(plan),
        "files_needing_repair": sum(item.changed for item in plan),
        "already_patched_files": sum(not item.changed for item in plan),
        "exported_files": len(plan) if output_root is not None else 0,
        "input_modified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mod-root", required=True, type=Path, help="v0.9.3 mod resource/package directory")
    parser.add_argument("--output", type=Path, help="separate directory for the repaired MFEssentials overlay")
    args = parser.parse_args()
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        result = run(args.mod_root, args.output, manifest)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"error: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
