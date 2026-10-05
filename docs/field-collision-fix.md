# Protagonist DLC free-roam collision repair

With DLC Outfits Apply Everywhere v0.9.3 enabled, the reporter could not use
the planter inside the Gauntlet Runner and had trouble reaching other interaction
points. Disabling this mod restored interaction. After applying the repair below
with the mod enabled, the reporter confirmed that all tested interactions worked
again. This is gameplay validation reported by the user on Steam/Windows, not a
claim that every outfit, scene, or console platform has been tested.

## Resource change

The `0001` outfits `201` through `208` have field DCLs that are byte-identical
to their original battle DCLs. Their primary geometry differs from the native
default field geometry. The corresponding `0020` field outfits also use the
different primary geometry.

The DCL reader handles primary geometry separately from the outfit's bone
colliders. The reviewed DLC files have a version-210 prefix, a type-1 primary
block, and 13 bone records of 204 bytes each. The default field DCL has no version
prefix, so replacing the entire file would also replace its bone-record layout.

This repair instead copies only the native 52-byte primary block into bytes
`0x04` through `0x37` of each DLC field DCL. The version prefix, file length,
bone count, and all subsequent outfit bone records stay byte-identical. Each
file changes by 19 bytes; the total is 608 bytes across 32 files:

- Characters `0001` and `0020`.
- Outfits `201` through `208`.
- Both `FIELD.CPK/COMMON` and `FIELD.CPK/XBOX` resource directories.

No BCP, GFS, textures, DLLs, battle resources, or event resources change. The
protagonist's `500` home outfit already has native field primary geometry and
is excluded. Other companion home-outfit differences are outside this repair.

## Generate the repaired resources

The distributed `MFEssentials` assets are not tracked in this source repository.
The manifest therefore contains only primary geometry parameters and reviewed
SHA-256 hashes, with no complete game resources. The dependency-free Python tool
reproduces the exact repaired files from the existing v0.9.3 package assets.

Use Python 3.10 or later. First check the resource/package directory without
writing any files:

```shell
python tools/patch_field_collisions.py --mod-root /path/to/v0.9.3-mod
```

Export all 32 repaired DCLs to a separate directory:

```shell
python tools/patch_field_collisions.py --mod-root /path/to/v0.9.3-mod --output /path/to/repaired-overlay
```

Merge the exported `MFEssentials` directory into the staged mod package before
distribution. Do not delete collision directories. For a local installation,
exit the game and back up the affected files before merging the overlay.

The input directory is always read-only. Every input must match a reviewed
original or repaired hash before any export starts. Repeated exports are
idempotent; different existing output content is refused. Unknown versions or
modified resources need a new review and manifest, rather than an old full-file
overlay that could discard newer outfit records.

## Validation

```shell
python -m unittest discover -s tests -v
```

The tests use synthetic bone records and cover record preservation, incompatible
layouts, complete target scope, read-only checks, exact exports, idempotence,
unreviewed inputs, and output/path protection. Separately, exporting from the
actual v0.9.3 assets reproduced all 32 previously prepared and gameplay-tested
files byte-for-byte. The local installed-resource check confirmed that the other
1363 mod files were unchanged.

For gameplay regression checks, keep `FieldOutfits` and `EventOutfits` enabled
and `RandomOutfits` disabled, equip a DLC costume, revisit the originally failing
interaction points, and check movement through narrow passages. Outfit physics,
additional costumes, cutscenes, and battles still need their own coverage; the
reported interaction result does not establish those checks.
