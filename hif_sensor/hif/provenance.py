"""Cryptographic SHA-256 provenance manifest recorder and verifier for hif-sensor."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "results" / "provenance" / "manifest.json"

TRACKED_FILES = [
    ("circuit/ltspice_results.json", "LTspice 26.1.1 AC/transient front-end verification"),
    ("results/metrics.json", "Phase 0 simulated training/test/LOSO metrics (Kaggle christoopherchau/ch-y-n)"),
    ("results/model_int8.npz", "Phase 0 frozen 504 B int8 Tiny MLP weights + baseline pickups"),
    ("results/test_vectors.json", "Phase 0 Python reference test vectors for C firmware parity"),
    ("results/real_vehif.json", "Phase 1 zero-shot VeHIF 22 kV evaluation (Kaggle christoopherchau/ch-y-n)"),
    ("results/real_vehif_tests.csv", "Phase 1 per-recording VeHIF 22 kV results (250 recordings)"),
    ("firmware/hif_model.h", "Phase 0 auto-generated C int8 model header"),
    ("results/c_firmware_verify.json", "Phase 1.5 GCC -O2 -Wall -Werror C firmware parity & latency check"),
    ("results/phase15_vehif.json", "Phase 1.5 VeHIF adaptation, feature ablation & 50/60 Hz study"),
    ("results/model_phase15_int8.npz", "Phase 1.5 few-shot adapted 504 B int8 Tiny MLP"),
    ("firmware/hif_model_phase15.h", "Phase 1.5 adapted C int8 model header"),
]


TEXT_EXTS = {".json", ".csv", ".h", ".c", ".md", ".txt"}


def sha256_file(path: Path) -> str:
    """SHA-256 of file content; normalizes CRLF -> LF on text files so Windows & Linux CI match."""
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_EXTS:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip() or None
    except Exception:
        return None


def record_manifest(root: Path = ROOT, out_path: Path | None = None) -> dict:
    out_path = out_path or (root / "results" / "provenance" / "manifest.json")
    entries = []
    seen = set()
    for rel, desc in TRACKED_FILES:
        p = root / rel
        if p.exists():
            entries.append({
                "path": rel,
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size,
                "description": desc,
            })
            seen.add(rel)
    fig_dir = root / "results" / "figures"
    if fig_dir.exists():
        for p in sorted(fig_dir.glob("*.png")):
            rel = p.relative_to(root).as_posix()
            if rel not in seen:
                entries.append({
                    "path": rel,
                    "sha256": sha256_file(p),
                    "bytes": p.stat().st_size,
                    "description": f"Generated result figure ({p.name})",
                })
    manifest = {
        "project": "hif-sensor",
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git_head(),
        "file_count": len(entries),
        "files": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_manifest(root: Path = ROOT, manifest_path: Path | None = None) -> dict:
    manifest_path = manifest_path or (root / "results" / "provenance" / "manifest.json")
    if not manifest_path.exists():
        return {"ok": False, "error": f"Manifest missing: {manifest_path}", "checked": 0,
                "changed": [], "missing": [str(manifest_path)]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed, missing = [], []
    for item in manifest.get("files", []):
        p = root / item["path"]
        if not p.exists():
            missing.append(item["path"])
            continue
        actual = sha256_file(p)
        if actual != item["sha256"]:
            changed.append({"path": item["path"], "expected": item["sha256"], "actual": actual})
    return {
        "ok": not changed and not missing,
        "checked": len(manifest.get("files", [])),
        "changed": changed,
        "missing": missing,
        "generated_utc": manifest.get("generated_utc"),
    }


def main():
    ap = argparse.ArgumentParser(description="Record or verify SHA-256 provenance for hif-sensor results.")
    ap.add_argument("--record", action="store_true", help="Write results/provenance/manifest.json")
    ap.add_argument("--verify", action="store_true", help="Verify all files against manifest.json")
    args = ap.parse_args()
    if args.record:
        m = record_manifest()
        print(f"Recorded {m['file_count']} files -> {MANIFEST_PATH}")
        return 0
    res = verify_manifest()
    print(f"Verified {res['checked']} files: {len(res['changed'])} changed, {len(res['missing'])} missing")
    if not res["ok"]:
        if res.get("error"):
            print("ERROR:", res["error"])
        for c in res["changed"]:
            print("  CHANGED:", c["path"])
        for m in res["missing"]:
            print("  MISSING:", m)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
