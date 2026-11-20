"""Files made in other apps (AutoCAD, SolidWorks, LTspice, Factory IO) and the exports the report uses.

The study itself runs in Python/OpenDSS. Drawings, 3D parts, circuit simulations and the virtual
control panel are made by hand in their own apps, so nothing can re-run them automatically. To keep
them honest anyway, every such file is listed in workflow.toml as an [[asset]]: its source file
(kept in git), its export (what the report or another tool reads) and the claim it supports.

    python scripts/register_export.py <id>    # after you export: record both files' fingerprints

harness/check.py then fails if a source changed after its export was registered (re-export it),
or if an export was replaced without registering it.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import date
from pathlib import Path

from . import config

MANIFEST = config.ROOT / "workflow.toml"
REGISTER = config.ROOT / "exports" / "registered.json"
FOLDERS = {  # folder: what goes in it
    "cad": "AutoCAD drawings (.dwg sources)",
    "mech": "SolidWorks parts and assemblies (.sldprt / .sldasm sources)",
    "spice": "LTspice circuits (.asc sources)",
    "hmi": "Factory IO scenes (.factoryio) and the Modbus address map",
    "board": "ESP32 control panel: firmware and its Wokwi simulation",
    "exports": "Exports the report and other tools read (PDF, SVG, DXF, GLB, STEP, CSV)",
}
FIELDS = ("id", "tool", "source", "export", "supports")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(manifest: Path = MANIFEST) -> list[dict]:
    """The [[asset]] entries of workflow.toml; raises ValueError on a malformed entry."""
    if not manifest.exists():
        return []
    assets = tomllib.loads(manifest.read_text(encoding="utf-8")).get("asset", [])
    ids = [a.get("id") for a in assets]
    for a in assets:
        missing = [f for f in FIELDS if not a.get(f)]
        if missing:
            raise ValueError(f"asset {a.get('id', '?')} in {manifest.name} lacks {', '.join(missing)}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate asset id in {manifest.name}")
    return assets


def registered(path: Path = REGISTER) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def status(asset: dict, root: Path = config.ROOT, reg: dict | None = None) -> tuple[bool | None, str]:
    """(up to date?, what to do). None means planned: the app work has not been done yet.

    Optional fields: `from` is a generated file the source was made from (e.g. the DXF that
    Python writes for AutoCAD); `planned = true` turns a missing source into a reminder
    instead of a failure."""
    reg = registered() if reg is None else reg
    a, src, exp = asset["id"], root / asset["source"], root / asset["export"]
    redo = f"export it from {asset['tool']} to {asset['export']}, then python scripts/register_export.py {a}"
    if not src.exists():
        if asset.get("planned"):
            start = f" starting from {asset['from']}" if asset.get("from") else ""
            return None, f"{a}: planned: make {asset['source']} in {asset['tool']}{start}, then {redo}"
        return False, f"{a}: source {asset['source']} is missing"
    if not exp.exists():
        return False, f"{a}: no export yet: {redo}"
    r = reg.get(a)
    if not r:
        return False, f"{a}: export not registered: python scripts/register_export.py {a}"
    if r["source_sha256"] != sha256(src):
        return False, f"{a}: {asset['source']} changed after its export: {redo}"
    if r["export_sha256"] != sha256(exp):
        return False, f"{a}: {asset['export']} was replaced without registering: python scripts/register_export.py {a}"
    gen = root / asset["from"] if asset.get("from") else None
    if gen is not None and gen.exists() and r.get("from_sha256") != sha256(gen):
        return False, (f"{a}: {asset['from']} was regenerated after {asset['source']} was made from it "
                       f"(the study changed): update the drawing in {asset['tool']}, then {redo}")
    return True, f"{a}: {asset['export']} matches {asset['source']}"


def register(asset_id: str, root: Path = config.ROOT, manifest: Path = MANIFEST, reg_path: Path = REGISTER) -> dict:
    """Record the fingerprints of an asset's source and export after a fresh export."""
    asset = next((a for a in load(manifest) if a["id"] == asset_id), None)
    if asset is None:
        raise KeyError(f"no asset {asset_id!r} in {manifest.name}; add it there first")
    src, exp = root / asset["source"], root / asset["export"]
    for p in (src, exp):
        if not p.exists():
            raise FileNotFoundError(p)
    reg = registered(reg_path)
    reg[asset_id] = {"source_sha256": sha256(src), "export_sha256": sha256(exp), "registered": date.today().isoformat()}
    gen = root / asset["from"] if asset.get("from") else None
    if gen is not None and gen.exists():
        reg[asset_id]["from_sha256"] = sha256(gen)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(dict(sorted(reg.items())), indent=2) + "\n", encoding="utf-8")
    return reg[asset_id]
