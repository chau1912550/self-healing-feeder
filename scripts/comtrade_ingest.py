"""One-command CLI to ingest IEEE C37.111 COMTRADE recordings into self-healing-feeder models.

Supports two workflows:
  1. Ingest a single `.cfg`/`.cff` file or a multi-device folder (+ optional JSON channel map),
     convert waveforms to the exact Tier-2 (`shf.model`), Transfer (`shf.transfer`),
     Active-Grid (`shf.active_grid`), and optional Tier-1 (`shf.hif_edge`) feature schemas,
     and run trial inference if trained models are available (always reporting scope limits).
  2. Verify the bundled public COMTRADE samples (`data/comtrade_samples/public/`) and
     OpenDSS/LTspice simulation round-trip suite (`data/comtrade_samples/synthetic_roundtrip/`),
     writing `results/comtrade/summary.json` and locking its SHA-256 provenance record.

All trained models in this project are simulation-only (IEEE 123-bus OpenDSS / LTspice /
synthetic HIF waveforms); no utility field validation is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shf import active_grid, comtrade, config, faults, feeder, hif_edge, model, provenance, topology, transfer
from shf import transfer_models

SAMPLES_DIR = config.ROOT / "data" / "comtrade_samples"
PUBLIC_DIR = SAMPLES_DIR / "public"
SYNTH_DIR = SAMPLES_DIR / "synthetic_roundtrip"
OUT_DIR = config.RESULTS / "comtrade"
SUMMARY_PATH = OUT_DIR / "summary.json"

# Provenance metadata for the downloaded open-source IEEE C37.111 samples in data/comtrade_samples/public/
PUBLIC_METADATA: dict[str, dict[str, str]] = {
    "sample_ascii.cfg": {
        "source_repo": "dparrini/python-comtrade",
        "commit": "1714f3a7fad071b149012e1de474a1bcddee6c59",
        "license": "MIT",
        "url": "https://raw.githubusercontent.com/dparrini/python-comtrade/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_ascii.cfg",
        "note": "IEEE C37.111-2013 ASCII current-only record (IA/IB/IC/3I0, secondary CT 933:1, 60 Hz, 1200 Hz, 40 samples).",
    },
    "sample_bin.cfg": {
        "source_repo": "dparrini/python-comtrade",
        "commit": "1714f3a7fad071b149012e1de474a1bcddee6c59",
        "license": "MIT",
        "url": "https://raw.githubusercontent.com/dparrini/python-comtrade/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_bin.cfg",
        "note": "IEEE C37.111-1999 BINARY short voltage-only smoke sample (VA/VB/VC/VN, primary, 60 Hz, 15360 Hz, 5 samples < 1 cycle).",
    },
    "sample_iso8859-1_bin.cfg": {
        "source_repo": "dparrini/python-comtrade",
        "commit": "1714f3a7fad071b149012e1de474a1bcddee6c59",
        "license": "MIT",
        "url": "https://raw.githubusercontent.com/dparrini/python-comtrade/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_iso8859-1_bin.cfg",
        "note": "IEEE C37.111-2013 BINARY current-only record with ISO-8859-1 station text and non-unit timemult (60 Hz, 1200 Hz, 40 samples).",
    },
    "fdr2214_ag_fault.cfg": {
        "source_repo": "sagswell/comtrade-sample-files",
        "commit": "3333a8cf6b523c07f28d1b9a4e88a4cc19b8e9eb",
        "license": "CC0-1.0",
        "url": "https://raw.githubusercontent.com/sagswell/comtrade-sample-files/3333a8cf6b523c07f28d1b9a4e88a4cc19b8e9eb/FDR-2214_AG-FAULT/FDR-2214_AG-FAULT.cfg",
        "note": "IEEE C37.111-2013 ASCII synthetic 132 kV A-G fault (VA/VB/VC + IA/IB/IC, 50 Hz, 4800 Hz, 2400 samples = 25 cycles, trigger at 148 ms).",
    },
    "wisp_relay_bin.cfg": {
        "source_repo": "Esticonv/Wisp.Comtrade",
        "commit": "004f3f8ac35cbaea0a7be808f511d5f1ca93fe19",
        "license": "MIT",
        "url": "https://raw.githubusercontent.com/Esticonv/Wisp.Comtrade/004f3f8ac35cbaea0a7be808f511d5f1ca93fe19/ComtradeTests/ExampleSet2/3.cfg",
        "note": "IEEE C37.111-1999 BINARY relay record (nrates=0 timestamped, 24A/64D, secondary CT 1000:1 & PT 190740:57.8, 50 Hz, ~800 Hz, 1360 samples).",
    },
}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(config.ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _round_list(arr: Any, digits: int = 4) -> list[float]:
    return [round(float(x), digits) if np.isfinite(x) else float("nan") for x in arr]


def _json_safe(obj: Any) -> Any:
    """Convert numpy scalars/arrays and NaN/Inf cleanly for JSON serialization."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, Path):
        return _rel(obj)
    return obj


# ---------------------------------------------------------------------------
# Model loading & trial inference (with explicit limitation checks)
# ---------------------------------------------------------------------------
class LoadedModels:
    """Lazy container for optional trained simulation models."""

    def __init__(self) -> None:
        self.tier2_clf: Any = None
        self.tier2_cols: list[str] = []
        self.transfer_gbdt: Any = None
        self.transfer_gnn: Any = None
        self.hif_model: hif_edge.EdgeModel | None = None
        self.hif_model_rel: str | None = None
        self._load()

    def _load(self) -> None:
        t2_path = config.MODELS / "model.pkl"
        if t2_path.is_file():
            with open(t2_path, "rb") as f:
                pkg = pickle.load(f)
            self.tier2_clf = pkg.get("model")
            self.tier2_cols = list(pkg.get("columns", []))

        tr_dir = config.MODELS / "transfer"
        if (tr_dir / "per_node_gbdt_ieee123.pkl").is_file() and (tr_dir / "gnn_ieee123.pt").is_file():
            self.transfer_gbdt, self.transfer_gnn, _ = transfer_models.load_frozen_models(tr_dir)

        hif_path = hif_edge.find_model_npz()
        if hif_path is not None and hif_path.is_file():
            self.hif_model = hif_edge.load_model_npz(hif_path, source=_rel(hif_path))
            self.hif_model_rel = _rel(hif_path)

    def availability(self) -> dict[str, bool]:
        return {
            "tier2_gbdt": self.tier2_clf is not None,
            "transfer_gbdt": self.transfer_gbdt is not None,
            "transfer_gnn": self.transfer_gnn is not None,
            "tier1_hif_int8": self.hif_model is not None,
        }


def _collect_limitations(
    bundle: dict[str, Any],
    records: dict[str, comtrade.ComtradeRecord],
    *,
    is_ieee123_match: bool,
) -> list[str]:
    """Build explicit, honest scope limitations for trial inference."""
    notes: list[str] = []
    n_present = len(bundle["tier2_devices_present"])
    n_total = len(comtrade.DEFAULT_DEVICES)
    if n_present < n_total:
        notes.append(
            f"Only {n_present}/{n_total} IEEE 123-bus devices provided; missing devices are filled with NaN. "
            "Single-device or partial-fleet records cannot localize across feeder zones reliably."
        )
    if not is_ieee123_match:
        notes.append(
            "Input recording is not from the simulated IEEE 123-bus (4.16 kV, 60 Hz) feeder; "
            "Tier-2/Transfer predictions are trial pipeline outputs only, not valid zone locations."
        )
    for dev, rec in records.items():
        if abs(rec.frequency - 60.0) > 0.5:
            notes.append(
                f"Device {dev} nominal frequency is {rec.frequency:g} Hz (models were trained on 60 Hz simulation)."
            )
        period = 1.0 / max(rec.frequency, 1e-6)
        if rec.duration_s < 1.0 * period - 1e-6:
            notes.append(
                f"Device {dev} duration is {rec.duration_s * 1e3:.2f} ms (< 1 cycle at {rec.frequency:g} Hz); "
                "full-cycle DFT phasors are under-determined."
            )
        ph = bundle["phasors"][dev]
        if not bool(np.any(ph["present_v"])):
            notes.append(f"Device {dev} has no mapped phase voltage channels (Va/Vb/Vc); voltage features are NaN.")
        if not bool(np.any(ph["present_i"])):
            notes.append(f"Device {dev} has no mapped phase current channels (Ia/Ib/Ic); current features are NaN.")
    notes.append("All bundled models are simulation-trained only; field utility data has not been evaluated.")
    return notes


def run_trial_inference(
    bundle: dict[str, Any],
    models_obj: LoadedModels,
    records: dict[str, comtrade.ComtradeRecord],
    *,
    is_ieee123_match: bool = False,
) -> dict[str, Any]:
    """Run optional trial inference across Tier-2 GBDT, Transfer PerNodeGBDT/GNN, and Tier-1 HIF."""
    out: dict[str, Any] = {
        "tier2_gbdt": None,
        "transfer_gbdt": None,
        "transfer_gnn": None,
        "tier1_hif": {},
        "limitations": _collect_limitations(bundle, records, is_ieee123_match=is_ieee123_match),
    }

    # 1) Tier-2 shf.model (IEEE 123-bus 150-feature HistGradientBoostingClassifier)
    if models_obj.tier2_clf is not None:
        t2_dict = bundle["tier2"]["features"]
        vec = np.array([t2_dict.get(c, float("nan")) for c in models_obj.tier2_cols], dtype=np.float64)[None, :]
        pred = str(models_obj.tier2_clf.predict(vec)[0])
        proba = models_obj.tier2_clf.predict_proba(vec)[0]
        classes = [str(c) for c in models_obj.tier2_clf.classes_]
        order = np.argsort(proba)[::-1]
        out["tier2_gbdt"] = {
            "predicted_zone": pred,
            "confidence": round(float(proba[order[0]]), 4),
            "top3": [
                {"zone": classes[int(i)], "prob": round(float(proba[int(i)]), 4)}
                for i in order[:3]
            ],
            "finite_features": int(np.isfinite(vec).sum()),
            "total_features": int(vec.size),
        }

    # 2) Feeder-independent Transfer models (PerNodeGBDT + ZoneTreeGNN)
    X_tr = bundle["transfer"]["X"][None, :, :]          # (1, N, 21)
    tr_devs = list(bundle["transfer"]["devices"])
    tr_parent = np.asarray(bundle["transfer"]["parent"], dtype=np.int64)
    has_observed_node = bool(np.isfinite(X_tr[:, :, :comtrade.N_TRANSFER_ELEC]).all(axis=-1).any())

    if models_obj.transfer_gbdt is not None and has_observed_node:
        scores = models_obj.transfer_gbdt.scores(X_tr, tr_parent)[0]
        idx = int(np.argmax(scores))
        out["transfer_gbdt"] = {
            "predicted_zone": tr_devs[idx],
            "node_count": len(tr_devs),
            "scores": {tr_devs[i]: round(float(scores[i]), 4) for i in range(len(tr_devs))},
        }

    if models_obj.transfer_gnn is not None and has_observed_node:
        import torch

        with torch.no_grad():
            logits = models_obj.transfer_gnn(
                torch.from_numpy(X_tr.astype(np.float32)),
                torch.from_numpy(tr_parent),
            )[0].numpy()
        ex = np.exp(logits - np.max(logits))
        probs = ex / np.sum(ex)
        idx = int(np.argmax(logits))
        out["transfer_gnn"] = {
            "predicted_zone": tr_devs[idx],
            "confidence": round(float(probs[idx]), 4),
            "node_count": len(tr_devs),
            "probs": {tr_devs[i]: round(float(probs[i]), 4) for i in range(len(tr_devs))},
        }

    # 3) Tier-1 Edge HIF Sensor (504 B int8 MLP) per device
    for dev, hres in bundle.get("hif_edge", {}).items():
        out["tier1_hif"][dev] = {
            "ok": bool(hres["ok"]),
            "reason": hres["reason"],
            "n_cycles": int(hres["n_cycles"]),
            "n_windows": int(len(hres["end_cycles"])),
            "residual_source": hres["residual_source"],
            "p_hif": None if hres["p_hif"] is None else round(float(hres["p_hif"]), 4),
            "hif_alarm": None if hres["hif_alarm"] is None else bool(hres["hif_alarm"] > 0.5),
            "threshold": None if models_obj.hif_model is None else round(float(models_obj.hif_model.threshold), 4),
            "warnings": list(hres.get("warnings", [])),
        }

    return out


# ---------------------------------------------------------------------------
# Input discovery (single file or multi-device folder)
# ---------------------------------------------------------------------------
def _canonical_device_from_stem(stem: str) -> str:
    """Match filename stem (e.g. 'Sw1', 'sw4_bus60', 'L13') to canonical IEEE 123-bus device if possible."""
    low = stem.lower()
    for d in comtrade.DEFAULT_DEVICES:
        if low == d.lower():
            return d
    for d in comtrade.DEFAULT_DEVICES:
        if low.startswith(d.lower() + "_") or low.endswith("_" + d.lower()):
            return d
    return stem


def _parse_channel_map_config(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, str], float | None]:
    """Support flat `{Ia:...}`, per-device `{Sw1:{Ia:...}}`, or `{devices:{...}, channels:{...}, v_base_kv:...}`."""
    if not raw:
        return None, {}, None
    if "channels" in raw or "devices" in raw or "v_base_kv" in raw:
        ch_map = raw.get("channels")
        dev_map = {str(k): str(v) for k, v in raw.get("devices", {}).items()}
        v_kv = float(raw["v_base_kv"]) if raw.get("v_base_kv") is not None else None
        return ch_map, dev_map, v_kv
    return raw, {}, None


def load_input_records(
    target: Path,
    *,
    device_name: str | None = None,
    channel_map_path: Path | None = None,
    side: str = "primary",
) -> tuple[dict[str, comtrade.ComtradeRecord], dict[str, Any] | None, float | None]:
    """Load one COMTRADE file or a folder of multi-device `.cfg`/`.cff` files."""
    if channel_map_path is None and target.is_dir():
        auto_map = target / "channel_map.json"
        if auto_map.is_file():
            channel_map_path = auto_map

    raw_map = comtrade.load_channel_map(channel_map_path) if channel_map_path is not None else None
    ch_map, dev_aliases, map_v_kv = _parse_channel_map_config(raw_map)

    if target.is_file():
        rec = comtrade.read_comtrade(target, side=side)
        stem = target.stem
        dev = device_name or dev_aliases.get(stem) or dev_aliases.get(target.name) or _canonical_device_from_stem(stem)
        # Single arbitrary file defaults to Sw1 if stem is not an IEEE 123-bus device and no explicit name was given
        if device_name is None and dev not in comtrade.DEFAULT_DEVICES:
            dev = "Sw1"
        return {dev: rec}, ch_map, map_v_kv

    if target.is_dir():
        files = sorted(
            [p for p in target.iterdir() if p.is_file() and p.suffix.lower() in (".cfg", ".cff")],
            key=lambda p: p.name.lower(),
        )
        if not files:
            raise FileNotFoundError(f"No .cfg or .cff COMTRADE files found in {target}")
        recs: dict[str, comtrade.ComtradeRecord] = {}
        for p in files:
            stem = p.stem
            dev = dev_aliases.get(stem) or dev_aliases.get(p.name) or _canonical_device_from_stem(stem)
            recs[dev] = comtrade.read_comtrade(p, side=side)
        return recs, ch_map, map_v_kv

    raise FileNotFoundError(f"Input path does not exist: {target}")


# ---------------------------------------------------------------------------
# Synthetic round-trip COMTRADE generator (simulation only!)
# ---------------------------------------------------------------------------
OPENDSS_ROUNDTRIP_SPECS: list[dict[str, Any]] = [
    {
        "id": "opendss_ieee123_bus60_slg1_ascii",
        "bus": "60",
        "zone": "Sw2",
        "ftype": "SLG",
        "phases": "1",
        "r_ohm": 1.0,
        "spec": "phases=1 bus1=60.1 bus2=60.0 r=1.0",
        "load_mult": 0.85,
        "fmt": "ASCII",
        "rev_year": 2013,
        "ps": "S",
        "ct_ratio": (1000.0, 1.0),
        "pt_ratio": (4160.0 / math.sqrt(3.0), 120.0),
        "fs": 3840.0,
        "write_channel_map": True,
    },
    {
        "id": "opendss_ieee123_bus18_slg25_bin",
        "bus": "18",
        "zone": "L13",
        "ftype": "SLG",
        "phases": "1",
        "r_ohm": 25.0,
        "spec": "phases=1 bus1=18.1 bus2=18.0 r=25.0",
        "load_mult": 0.70,
        "fmt": "BINARY",
        "rev_year": 1999,
        "ps": "P",
        "ct_ratio": (1.0, 1.0),
        "pt_ratio": (1.0, 1.0),
        "fs": 3840.0,
        "write_channel_map": False,
    },
    {
        "id": "opendss_ieee123_bus76_3ph_bin",
        "bus": "76",
        "zone": "Sw4",
        "ftype": "3PH",
        "phases": "123",
        "r_ohm": 0.01,
        "spec": "phases=3 bus1=76.1.2.3 bus2=76.0.0.0 r=0.01",
        "load_mult": 0.95,
        "fmt": "BINARY",
        "rev_year": 2013,
        "ps": "S",
        "ct_ratio": (1000.0, 1.0),
        "pt_ratio": (4160.0 / math.sqrt(3.0), 120.0),
        "fs": 3840.0,
        "write_channel_map": False,
    },
]


def _serialize_phasors(meas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d, m in meas.items():
        out[d] = {
            "i_real": [float(np.real(x)) for x in m["i"]],
            "i_imag": [float(np.imag(x)) for x in m["i"]],
            "v_real": [float(np.real(x)) for x in m["v"]],
            "v_imag": [float(np.imag(x)) for x in m["v"]],
        }
    return out


def _deserialize_phasors(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for d, m in raw.items():
        i_arr = np.array([complex(r, im) for r, im in zip(m["i_real"], m["i_imag"])], dtype=np.complex128)
        v_arr = np.array([complex(r, im) for r, im in zip(m["v_real"], m["v_imag"])], dtype=np.complex128)
        ia, ib, ic = i_arr[0], i_arr[1], i_arr[2]
        out[d] = {
            "i": i_arr,
            "v": v_arr,
            "i0": (ia + ib + ic) / 3.0,
            "i2": (ia + feeder.A * feeder.A * ib + feeder.A * ic) / 3.0,
        }
    return out


def generate_synthetic_roundtrip(*, force: bool = False) -> Path:
    """Generate deterministic OpenDSS + LTspice + Tier-1 HIF COMTRADE round-trip samples (simulation only)."""
    manifest_path = SYNTH_DIR / "manifest.json"
    if manifest_path.is_file() and not force:
        return manifest_path

    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    v_base_ln = 4160.0 / math.sqrt(3.0)

    # 1) Multi-device OpenDSS IEEE 123-bus events (10 devices each)
    feeder.load_feeder()
    zones = topology.find_zones()
    grid = transfer.study_grid()
    struct = transfer.structure(grid)
    topo_normal = active_grid.TOPOLOGIES["ieee123"][0]
    adj_normal = np.zeros((len(grid.devices), len(grid.devices)), dtype=np.float32)
    idx_map = {d: i for i, d in enumerate(grid.devices)}
    for d in grid.devices:
        p = grid.parent[d]
        if p is not None:
            adj_normal[idx_map[p], idx_map[d]] = adj_normal[idx_map[d], idx_map[p]] = 1.0

    exists = "fault.f" in (n.lower() for n in feeder.dss.Circuit.AllElementNames())
    feeder.cmd(f"{'Edit' if exists else 'New'} Fault.F phases=1 bus1=149.1 bus2=149.0 r=1 enabled=no")

    opendss_entries: list[dict[str, Any]] = []
    for sp in OPENDSS_ROUNDTRIP_SPECS:
        feeder.set_normal_configuration()
        feeder.set_load_level(sp["load_mult"])
        feeder.cmd("Edit Fault.F enabled=no")
        feeder.reset_regulators()
        ok_pre = feeder.solve(controls=True)
        pre = faults.snapshot(None)

        feeder.cmd(f"Edit Fault.F {sp['spec']} enabled=yes")
        ok_post = feeder.solve(controls=False)
        post = faults.snapshot(None)
        feeder.cmd("Edit Fault.F enabled=no")

        assert ok_pre and ok_post, f"OpenDSS did not converge for {sp['id']}"
        actual_zone = zones.bus_zone[sp["bus"]]
        assert actual_zone == sp["zone"], f"Bus {sp['bus']} zone mismatch: {actual_zone} != {sp['zone']}"

        ev_dir = SYNTH_DIR / sp["id"]
        ev_dir.mkdir(parents=True, exist_ok=True)
        dev_files: dict[str, dict[str, str]] = {}
        for dev in comtrade.DEFAULT_DEVICES:
            waves, trig_s = comtrade.synthesize_phasor_waveforms(
                pre[dev],
                post[dev],
                fs=sp["fs"],
                freq=60.0,
                v_base_ln=v_base_ln,
                pre_cycles=4,
                post_cycles=6,
            )
            cfg_p, dat_p = comtrade.write_comtrade(
                ev_dir / f"{dev}.cfg",
                analog=waves,
                fs=sp["fs"],
                freq=60.0,
                fmt=sp["fmt"],
                rev_year=sp["rev_year"],
                station="SHF_IEEE123_SIM",
                rec_dev_id=dev,
                trigger_offset_s=trig_s,
                ct_ratio=sp["ct_ratio"],
                pt_ratio=sp["pt_ratio"],
                ps=sp["ps"],
            )
            dev_files[dev] = {
                "cfg": _rel(cfg_p),
                "dat": _rel(dat_p),
                "cfg_sha256": _file_sha256(cfg_p),
                "dat_sha256": _file_sha256(dat_p),
            }

        cmap_rel = None
        if sp["write_channel_map"]:
            cmap_path = ev_dir / "channel_map.json"
            cmap_obj = {
                "v_base_kv": 4.16,
                "devices": {d: d for d in comtrade.DEFAULT_DEVICES},
                "channels": {"Ia": "Ia", "Ib": "Ib", "Ic": "Ic", "Va": "Va", "Vb": "Vb", "Vc": "Vc"},
            }
            cmap_path.write_text(json.dumps(cmap_obj, indent=2) + "\n", encoding="utf-8")
            cmap_rel = _rel(cmap_path)

        t2_gt = faults.features(post, pre)
        tr_gt = transfer.node_features(grid, pre, post, struct)
        ag_gt, _, _ = comtrade.to_active_grid_features(pre, post, grid=grid, topo=topo_normal, adj=adj_normal)

        opendss_entries.append({
            "id": sp["id"],
            "simulation": True,
            "dir": _rel(ev_dir),
            "channel_map": cmap_rel,
            "bus": sp["bus"],
            "true_zone": actual_zone,
            "ftype": sp["ftype"],
            "phases": sp["phases"],
            "r_ohm": sp["r_ohm"],
            "load_mult": sp["load_mult"],
            "fmt": sp["fmt"],
            "rev_year": sp["rev_year"],
            "ps": sp["ps"],
            "fs_hz": sp["fs"],
            "v_base_ln_v": v_base_ln,
            "devices": dev_files,
            "gt_pre": _serialize_phasors(pre),
            "gt_post": _serialize_phasors(post),
            "gt_tier2": {k: float(v) for k, v in t2_gt.items()},
            "gt_transfer": tr_gt.tolist(),
            "gt_active_grid": ag_gt.tolist(),
        })

    # Restore clean OpenDSS state
    feeder.set_normal_configuration()
    feeder.set_load_level(1.0)
    feeder.reset_regulators()
    feeder.solve(controls=True)

    # 2) LTspice time-domain exports -> COMTRADE (simulation only)
    spice_sum = json.loads((config.RESULTS / "spice" / "summary.json").read_text(encoding="utf-8"))
    ltspice_entries: list[dict[str, Any]] = []

    fc_csv = config.ROOT / "exports" / "spice_fault_current.csv"
    df_fc = pd.read_csv(fc_csv)
    t_fc = df_fc["time_ms"].to_numpy(dtype=np.float64) * 1e-3
    fs_fc = round(1.0 / float(t_fc[1] - t_fc[0]), 6)
    cfg_fc, dat_fc = comtrade.write_comtrade(
        SYNTH_DIR / "ltspice_bus60_bolted_ascii.cfg",
        analog={
            "IA": df_fc["i_no_offset_a"].to_numpy(dtype=np.float64),
            "IA_OFFSET": df_fc["i_max_offset_a"].to_numpy(dtype=np.float64),
            "VA": df_fc["v_f_no_offset_v"].to_numpy(dtype=np.float64),
            "VA_OFFSET": df_fc["v_f_max_offset_v"].to_numpy(dtype=np.float64),
        },
        fs=fs_fc,
        freq=60.0,
        fmt="ASCII",
        rev_year=2013,
        station="SHF_LTSPICE_SIM",
        rec_dev_id="BUS60_BOLTED",
        trigger_offset_s=0.0532,
        units={"IA": "A", "IA_OFFSET": "A", "VA": "V", "VA_OFFSET": "V"},
        phases={"IA": "A", "IA_OFFSET": "", "VA": "A", "VA_OFFSET": ""},
        ps="P",
    )
    ltspice_entries.append({
        "id": "ltspice_bus60_bolted_ascii",
        "simulation": True,
        "source_csv": _rel(fc_csv),
        "cfg": _rel(cfg_fc),
        "dat": _rel(dat_fc),
        "cfg_sha256": _file_sha256(cfg_fc),
        "dat_sha256": _file_sha256(dat_fc),
        "fmt": "ASCII",
        "rev_year": 2013,
        "fs_hz": fs_fc,
        "trigger_offset_s": 0.0532,
        "reference_metric": "ltspice_steady_fault_rms_a",
        "reference_value": float(spice_sum["fault_rms_a"]["ltspice_steady"]),
        "channel_map": {"Ia": "IA", "Va": "VA"},
        "v_base_ln_v": float(spice_sum["model"]["vph"]),
    })

    hif_csv = config.ROOT / "exports" / "spice_hif.csv"
    df_hif = pd.read_csv(hif_csv)
    t_hif = df_hif["time_ms"].to_numpy(dtype=np.float64) * 1e-3
    fs_hif = round(1.0 / float(t_hif[1] - t_hif[0]), 6)
    cfg_hif, dat_hif = comtrade.write_comtrade(
        SYNTH_DIR / "ltspice_bus60_hif_arc_bin.cfg",
        analog={
            "IN": df_hif["i_arc_100ohm_a"].to_numpy(dtype=np.float64),
            "IN_FIX100": df_hif["i_fixed_100ohm_a"].to_numpy(dtype=np.float64),
            "IN_ARC400": df_hif["i_arc_400ohm_a"].to_numpy(dtype=np.float64),
            "IN_FIX400": df_hif["i_fixed_400ohm_a"].to_numpy(dtype=np.float64),
        },
        fs=fs_hif,
        freq=60.0,
        fmt="BINARY",
        rev_year=1999,
        station="SHF_LTSPICE_SIM",
        rec_dev_id="BUS60_HIF_ARC",
        trigger_offset_s=0.05,
        units={"IN": "A", "IN_FIX100": "A", "IN_ARC400": "A", "IN_FIX400": "A"},
        phases={"IN": "N", "IN_FIX100": "", "IN_ARC400": "", "IN_FIX400": ""},
        ps="P",
    )
    ltspice_entries.append({
        "id": "ltspice_bus60_hif_arc_bin",
        "simulation": True,
        "source_csv": _rel(hif_csv),
        "cfg": _rel(cfg_hif),
        "dat": _rel(dat_hif),
        "cfg_sha256": _file_sha256(cfg_hif),
        "dat_sha256": _file_sha256(dat_hif),
        "fmt": "BINARY",
        "rev_year": 1999,
        "fs_hz": fs_hif,
        "trigger_offset_s": 0.05,
        "reference_metric": "hif_100ohm_i1_arc_a",
        "reference_value": float(spice_sum["hif"]["cases"]["100"]["i1_arc"]),
        "channel_map": {"In": "IN", "Ia": "IN"},
        "v_base_ln_v": float(spice_sum["model"]["vph"]),
    })

    # 3) 15.36 kHz simulated Emanuel arcing HIF waveform -> COMTRADE BINARY (Tier-1 end-to-end check)
    rng_hif = np.random.default_rng(42)
    amps_sim, meta_sim = hif_edge.make_event(rng_hif, is_hif=True)
    X_hif_gt, ends_gt = hif_edge.window_features(amps_sim)
    trig_hif_s = float(meta_sim["start_cycle"]) / hif_edge.F_LINE
    cfg_t1, dat_t1 = comtrade.write_comtrade(
        SYNTH_DIR / "sim_hif_arc_15360hz_bin.cfg",
        analog={"IN": amps_sim},
        fs=hif_edge.FS_ADC,
        freq=hif_edge.F_LINE,
        fmt="BINARY",
        rev_year=2013,
        station="SHF_TIER1_HIF_SIM",
        rec_dev_id="EDGE_CT_15360HZ",
        trigger_offset_s=trig_hif_s,
        units={"IN": "A"},
        phases={"IN": "N"},
        ps="P",
    )
    hif_entry = {
        "id": "sim_hif_arc_15360hz_bin",
        "simulation": True,
        "cfg": _rel(cfg_t1),
        "dat": _rel(dat_t1),
        "cfg_sha256": _file_sha256(cfg_t1),
        "dat_sha256": _file_sha256(dat_t1),
        "fmt": "BINARY",
        "rev_year": 2013,
        "fs_hz": float(hif_edge.FS_ADC),
        "freq_hz": float(hif_edge.F_LINE),
        "start_cycle": int(meta_sim["start_cycle"]),
        "surface": str(meta_sim.get("surface", "")),
        "seed": 42,
        "gt_n_windows": int(len(ends_gt)),
        "gt_features": X_hif_gt.tolist(),
    }

    manifest = {
        "simulation_only": True,
        "note": "Synthetic COMTRADE round-trip verification suite generated from OpenDSS IEEE 123-bus, LTspice exports, and shf.hif_edge (simulation only).",
        "opendss_events": opendss_entries,
        "ltspice_records": ltspice_entries,
        "tier1_hif_record": hif_entry,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# Verification runner (--verify-samples)
# ---------------------------------------------------------------------------
def verify_all_samples(*, regen_synthetic: bool = False) -> dict[str, Any]:
    """Verify all public + synthetic round-trip COMTRADE samples, write summary.json and provenance."""
    t0 = time.time()
    manifest_path = generate_synthetic_roundtrip(force=regen_synthetic)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models_obj = LoadedModels()

    # Load IEEE 123-bus Grid once for OpenDSS Transfer / Active-Grid feature comparisons
    feeder.load_feeder()
    grid_123 = transfer.study_grid()
    topo_normal = active_grid.TOPOLOGIES["ieee123"][0]
    adj_normal = np.zeros((len(grid_123.devices), len(grid_123.devices)), dtype=np.float32)
    idx_map = {d: i for i, d in enumerate(grid_123.devices)}
    for d in grid_123.devices:
        p = grid_123.parent[d]
        if p is not None:
            adj_normal[idx_map[p], idx_map[d]] = adj_normal[idx_map[d], idx_map[p]] = 1.0

    # --- 1) Public open-source IEEE C37.111 samples ---
    public_results: list[dict[str, Any]] = []
    for cfg in sorted(PUBLIC_DIR.glob("*.cfg"), key=lambda p: p.name.lower()):
        dat = comtrade._find_dat_path(cfg)
        meta = PUBLIC_METADATA.get(cfg.name, {})
        rec = comtrade.read_comtrade(cfg, side="primary")
        bundle = comtrade.comtrade_to_model_inputs(
            rec,
            device_name="Sw1",
            hif_model=models_obj.hif_model,
            include_hif=True,
        )
        infer = run_trial_inference(bundle, models_obj, {"Sw1": rec}, is_ieee123_match=False)
        ph = bundle["phasors"]["Sw1"]
        t2_vec = bundle["tier2"]["vector"]
        n_fin = int(np.isfinite(t2_vec).sum())
        period = 1.0 / max(rec.frequency, 1e-6)
        dur_cycles = rec.duration_s / period
        ok = bool(rec.n_samples > 0 and n_fin > 0)

        public_results.append({
            "id": cfg.stem,
            "cfg": _rel(cfg),
            "dat": _rel(dat),
            "cfg_sha256": _file_sha256(cfg),
            "dat_sha256": _file_sha256(dat),
            "source_repo": meta.get("source_repo", "unknown"),
            "commit": meta.get("commit", ""),
            "license": meta.get("license", "unknown"),
            "url": meta.get("url", ""),
            "note": meta.get("note", ""),
            "rev_year": int(rec.rev_year),
            "data_format": rec.data_format,
            "frequency_hz": float(rec.frequency),
            "sample_rate_hz": round(float(rec.sample_rate_hz()), 2),
            "n_samples": int(rec.n_samples),
            "n_analog": int(rec.n_analog),
            "n_digital": int(rec.n_digital),
            "duration_ms": round(rec.duration_s * 1e3, 3),
            "duration_cycles": round(dur_cycles, 3),
            "mapped_channels": {
                k: rec.analog_channels[idx].name for k, idx in ph["channel_map"].items()
            },
            "onset_source": ph["onset_source"],
            "event_time_ms": round(ph["event_time_s"] * 1e3, 3),
            "i_pre_rms_a": _round_list(np.abs(ph["pre"]["i"]), 3),
            "i_post_rms_a": _round_list(np.abs(ph["post"]["i"]), 3),
            "v_post_pu": _round_list(np.abs(ph["post"]["v"]), 4),
            "tier2_finite_features": n_fin,
            "tier2_total_features": int(t2_vec.size),
            "transfer_shape": list(bundle["transfer"]["X"].shape),
            "active_grid_shape": list(bundle["active_grid"]["X"].shape),
            "hif_edge": infer["tier1_hif"].get("Sw1"),
            "trial_inference": {
                "tier2_gbdt": infer["tier2_gbdt"],
                "transfer_gbdt": infer["transfer_gbdt"],
                "transfer_gnn": infer["transfer_gnn"],
                "limitations": infer["limitations"],
            },
            "ok": ok,
        })

    # --- 2) Synthetic multi-device OpenDSS round-trip verification ---
    opendss_results: list[dict[str, Any]] = []
    max_t2_abs = 0.0
    max_t2_rel = 0.0
    max_tr_abs = 0.0
    max_ag_abs = 0.0
    t2_matches = 0
    tr_gbdt_matches = 0
    tr_gnn_matches = 0
    single_device_demo: dict[str, Any] = {}

    for ev in manifest["opendss_events"]:
        ev_dir = config.ROOT / ev["dir"]
        recs, ch_map, map_v_kv = load_input_records(ev_dir, side="primary")
        bundle = comtrade.comtrade_to_model_inputs(
            recs,
            channel_maps=ch_map,
            v_base_ln=ev["v_base_ln_v"] if map_v_kv is None else None,
            v_base_kv=map_v_kv,
            grid=grid_123,
            topo=topo_normal,
            adj=adj_normal,
            hif_model=models_obj.hif_model,
            include_hif=False,
        )
        infer = run_trial_inference(bundle, models_obj, recs, is_ieee123_match=True)

        # Direct OpenDSS ground-truth comparison (normalize current errors by each device's peak current,
        # and voltage errors by 1.0 pu, matching 16-bit BINARY COMTRADE full-scale quantization)
        t2_cols = bundle["tier2"]["columns"]
        gt_t2_vec = np.array([ev["gt_tier2"][c] for c in t2_cols], dtype=np.float64)
        ct_t2_vec = bundle["tier2"]["vector"]
        t2_abs_err = float(np.max(np.abs(ct_t2_vec - gt_t2_vec)))
        dev_i_scale: dict[str, float] = {}
        for d in comtrade.DEFAULT_DEVICES:
            dev_i_scale[d] = max(
                1.0,
                float(ev["gt_tier2"].get(f"{d}_Ia", 0.0)),
                float(ev["gt_tier2"].get(f"{d}_Ib", 0.0)),
                float(ev["gt_tier2"].get(f"{d}_Ic", 0.0)),
            )
        scales = np.array(
            [1.0 if ("_V" in c or "_dV" in c) else dev_i_scale[c.split("_", 1)[0]] for c in t2_cols],
            dtype=np.float64,
        )
        t2_rel_err = float(np.max(np.abs(ct_t2_vec - gt_t2_vec) / scales))

        gt_tr = np.asarray(ev["gt_transfer"], dtype=np.float32)
        ct_tr = bundle["transfer"]["X"]
        tr_abs_err = float(np.max(np.abs(ct_tr - gt_tr)))

        gt_ag = np.asarray(ev["gt_active_grid"], dtype=np.float32)
        ct_ag = bundle["active_grid"]["X"]
        ag_abs_err = float(np.max(np.abs(ct_ag - gt_ag)))

        # Ground-truth model predictions directly on OpenDSS features (for exact parity check)
        gt_pred_t2 = None
        if models_obj.tier2_clf is not None:
            gt_vec_ordered = np.array([ev["gt_tier2"][c] for c in models_obj.tier2_cols], dtype=np.float64)[None, :]
            gt_pred_t2 = str(models_obj.tier2_clf.predict(gt_vec_ordered)[0])
        gt_pred_tr_gbdt = None
        if models_obj.transfer_gbdt is not None:
            idx_g = int(models_obj.transfer_gbdt.predict(gt_tr[None, :, :], bundle["transfer"]["parent"])[0])
            gt_pred_tr_gbdt = bundle["transfer"]["devices"][idx_g]
        gt_pred_tr_gnn = None
        if models_obj.transfer_gnn is not None:
            idx_n = int(transfer_models.predict_gnn(models_obj.transfer_gnn, gt_tr[None, :, :], bundle["transfer"]["parent"])[0])
            gt_pred_tr_gnn = bundle["transfer"]["devices"][idx_n]

        ct_pred_t2 = infer["tier2_gbdt"]["predicted_zone"] if infer["tier2_gbdt"] else None
        ct_pred_tr_gbdt = infer["transfer_gbdt"]["predicted_zone"] if infer["transfer_gbdt"] else None
        ct_pred_tr_gnn = infer["transfer_gnn"]["predicted_zone"] if infer["transfer_gnn"] else None

        ok_t2_match = ct_pred_t2 == ev["true_zone"] == gt_pred_t2
        ok_gbdt_match = ct_pred_tr_gbdt == ev["true_zone"] == gt_pred_tr_gbdt
        ok_gnn_match = ct_pred_tr_gnn == ev["true_zone"] == gt_pred_tr_gnn
        if ok_t2_match:
            t2_matches += 1
        if ok_gbdt_match:
            tr_gbdt_matches += 1
        if ok_gnn_match:
            tr_gnn_matches += 1

        max_t2_abs = max(max_t2_abs, t2_abs_err)
        max_t2_rel = max(max_t2_rel, t2_rel_err)
        max_tr_abs = max(max_tr_abs, tr_abs_err)
        max_ag_abs = max(max_ag_abs, ag_abs_err)

        ok_ev = bool(t2_rel_err < 1e-3 and tr_abs_err < 1e-3 and ag_abs_err < 1e-3 and ok_t2_match)
        opendss_results.append({
            "id": ev["id"],
            "simulation": True,
            "dir": ev["dir"],
            "bus": ev["bus"],
            "true_zone": ev["true_zone"],
            "ftype": ev["ftype"],
            "r_ohm": ev["r_ohm"],
            "fmt": ev["fmt"],
            "rev_year": ev["rev_year"],
            "ps": ev["ps"],
            "n_devices": len(recs),
            "tier2_max_abs_err": round(t2_abs_err, 6),
            "tier2_max_rel_err": round(t2_rel_err, 7),
            "transfer_max_abs_err": round(tr_abs_err, 7),
            "active_grid_max_abs_err": round(ag_abs_err, 7),
            "predictions": {
                "tier2_gbdt": {"comtrade": ct_pred_t2, "opendss_direct": gt_pred_t2, "matches_true_zone": ok_t2_match},
                "transfer_gbdt": {"comtrade": ct_pred_tr_gbdt, "opendss_direct": gt_pred_tr_gbdt, "matches_true_zone": ok_gbdt_match},
                "transfer_gnn": {"comtrade": ct_pred_tr_gnn, "opendss_direct": gt_pred_tr_gnn, "matches_true_zone": ok_gnn_match},
            },
            "ok": ok_ev,
        })

        # Single-device vs 10-device limitation demo on the first OpenDSS event
        if not single_device_demo:
            rec_sw1 = comtrade.read_comtrade(ev_dir / "Sw1.cfg", side="primary")
            b1 = comtrade.comtrade_to_model_inputs(
                rec_sw1,
                device_name="Sw1",
                v_base_ln=ev["v_base_ln_v"],
                grid=grid_123,
                include_hif=False,
            )
            inf1 = run_trial_inference(b1, models_obj, {"Sw1": rec_sw1}, is_ieee123_match=True)
            single_device_demo = {
                "event_id": ev["id"],
                "simulation": True,
                "true_zone": ev["true_zone"],
                "single_device_file": _rel(ev_dir / "Sw1.cfg"),
                "single_device_finite_tier2": int(np.isfinite(b1["tier2"]["vector"]).sum()),
                "all_10_devices_finite_tier2": int(np.isfinite(ct_t2_vec).sum()),
                "single_device_tier2_pred": inf1["tier2_gbdt"]["predicted_zone"] if inf1["tier2_gbdt"] else None,
                "single_device_tier2_conf": inf1["tier2_gbdt"]["confidence"] if inf1["tier2_gbdt"] else None,
                "all_10_devices_tier2_pred": ct_pred_t2,
                "all_10_devices_tier2_conf": infer["tier2_gbdt"]["confidence"] if infer["tier2_gbdt"] else None,
                "note": "With 1 of 10 devices (15/150 features populated, 135 NaN), feeder-wide zone localization is under-determined; multi-device records recover exact parity with OpenDSS.",
            }

    # --- 3) Synthetic LTspice waveform round-trip verification ---
    ltspice_results: list[dict[str, Any]] = []
    ltspice_bolted_err_pct = None
    ltspice_hif100_err_pct = None

    for item in manifest["ltspice_records"]:
        cfg_p = config.ROOT / item["cfg"]
        rec = comtrade.read_comtrade(cfg_p, side="primary")
        cmap = item["channel_map"]
        # Choose a steady-state post-fault cycle (last full cycle before record end) to compare against summary.json
        period = 1.0 / rec.frequency
        steady_start = float(rec.time[-1]) - 1.5 * period
        if item["id"] == "ltspice_bus60_bolted_ascii":
            ph = comtrade.extract_device_phasors(
                rec,
                channel_map=cmap,
                v_base_ln=item["v_base_ln_v"],
                event_time_s=item["trigger_offset_s"],
                pre_window=(0.015, 0.015 + period),
                post_window=(steady_start, steady_start + period),
            )
            recovered = float(abs(ph["post"]["i"][0]))
            rel_err_pct = 100.0 * abs(recovered - item["reference_value"]) / item["reference_value"]
            ltspice_bolted_err_pct = round(rel_err_pct, 4)
            hif_res = comtrade.to_hif_edge_features(rec, channel_map=cmap, model=models_obj.hif_model)
            ok_lt = bool(rel_err_pct < 0.5)
        else:
            # LTspice HIF arc 100 ohm: extract steady-state fundamental I1 over last full cycle
            ph = comtrade.extract_device_phasors(
                rec,
                channel_map=cmap,
                v_base_ln=item["v_base_ln_v"],
                post_window=(steady_start, steady_start + period),
            )
            recovered = float(abs(ph["post"]["i"][0]))
            rel_err_pct = 100.0 * abs(recovered - item["reference_value"]) / item["reference_value"]
            ltspice_hif100_err_pct = round(rel_err_pct, 4)
            hif_res = comtrade.to_hif_edge_features(rec, channel_map={"In": "IN"}, model=models_obj.hif_model)
            # spice_hif.csv is 100 ms = 6 cycles < K=8 cycles, so Tier-1 must cleanly report ok=False
            ok_lt = bool(rel_err_pct < 0.5 and (not hif_res["ok"]))

        ltspice_results.append({
            "id": item["id"],
            "simulation": True,
            "source_csv": item["source_csv"],
            "cfg": item["cfg"],
            "dat": item["dat"],
            "cfg_sha256": item["cfg_sha256"],
            "dat_sha256": item["dat_sha256"],
            "fmt": item["fmt"],
            "rev_year": item["rev_year"],
            "fs_hz": item["fs_hz"],
            "n_samples": int(rec.n_samples),
            "duration_ms": round(rec.duration_s * 1e3, 2),
            "reference_metric": item["reference_metric"],
            "reference_value_a": round(float(item["reference_value"]), 4),
            "comtrade_dft_value_a": round(recovered, 4),
            "rel_err_pct": round(rel_err_pct, 4),
            "hif_edge_ok": bool(hif_res["ok"]),
            "hif_edge_reason": hif_res["reason"],
            "ok": ok_lt,
        })

    # --- 4) Synthetic 15.36 kHz Tier-1 HIF end-to-end round-trip ---
    t1_item = manifest["tier1_hif_record"]
    rec_t1 = comtrade.read_comtrade(config.ROOT / t1_item["cfg"], side="primary")
    hif_t1 = comtrade.to_hif_edge_features(
        rec_t1,
        channel_map={"In": "IN"},
        model=models_obj.hif_model,
        start_cycle=t1_item["start_cycle"],
    )
    gt_X_hif = np.asarray(t1_item["gt_features"], dtype=np.float32)
    ct_X_hif = hif_t1["features"]
    # Compare overlapping window count (COMTRADE 16-bit quantization adds tiny LSB error)
    n_cmp = min(len(gt_X_hif), len(ct_X_hif))
    hif_max_feat_err = float(np.max(np.abs(ct_X_hif[:n_cmp] - gt_X_hif[:n_cmp]))) if n_cmp > 0 else float("nan")

    gt_p_hif = None
    p_hif_abs_err = None
    if models_obj.hif_model is not None and n_cmp > 0:
        gt_probs = hif_edge.predict_q(models_obj.hif_model.layers, gt_X_hif)
        gt_ends = np.arange(hif_edge.K - 1, hif_edge.K - 1 + len(gt_X_hif), dtype=np.int16)
        gt_p_hif = float(hif_edge.persisted_score(gt_probs, ends=gt_ends, start_cycle=t1_item["start_cycle"]))
        p_hif_abs_err = abs(float(hif_t1["p_hif"]) - gt_p_hif) if hif_t1["p_hif"] is not None else None

    hif_roundtrip_result = {
        "id": t1_item["id"],
        "simulation": True,
        "cfg": t1_item["cfg"],
        "dat": t1_item["dat"],
        "cfg_sha256": t1_item["cfg_sha256"],
        "dat_sha256": t1_item["dat_sha256"],
        "fmt": t1_item["fmt"],
        "rev_year": t1_item["rev_year"],
        "fs_hz": t1_item["fs_hz"],
        "n_cycles": int(hif_t1["n_cycles"]),
        "n_windows": int(len(ct_X_hif)),
        "surface": t1_item["surface"],
        "max_feature_abs_err": round(hif_max_feat_err, 6),
        "p_hif_comtrade": None if hif_t1["p_hif"] is None else round(float(hif_t1["p_hif"]), 6),
        "p_hif_direct": None if gt_p_hif is None else round(gt_p_hif, 6),
        "p_hif_abs_err": None if p_hif_abs_err is None else round(p_hif_abs_err, 6),
        "hif_alarm": None if hif_t1["hif_alarm"] is None else bool(hif_t1["hif_alarm"] > 0.5),
        "ok": bool(hif_t1["ok"] and n_cmp > 0 and hif_max_feat_err < 1e-2 and (p_hif_abs_err is None or p_hif_abs_err < 1e-3)),
    }

    pub_pass = sum(1 for r in public_results if r["ok"])
    od_pass = sum(1 for r in opendss_results if r["ok"])
    lt_pass = sum(1 for r in ltspice_results if r["ok"])
    hif_pass = 1 if hif_roundtrip_result["ok"] else 0
    total_rec = len(public_results) + len(opendss_results) + len(ltspice_results) + 1
    total_pass = pub_pass + od_pass + lt_pass + hif_pass

    summary = {
        "status": "ok" if total_pass == total_rec else "partial",
        "simulation_notice": (
            "Public samples are open-source IEEE C37.111 test recordings (MIT / CC0-1.0) from external grids; "
            "round-trip samples are OpenDSS/LTspice/Emanuel simulations. No utility field fault dataset on IEEE 123-bus has been evaluated."
        ),
        "models_available": models_obj.availability(),
        "counts": {
            "public_samples": len(public_results),
            "public_passed": pub_pass,
            "synthetic_opendss_events": len(opendss_results),
            "synthetic_opendss_passed": od_pass,
            "synthetic_ltspice_records": len(ltspice_results),
            "synthetic_ltspice_passed": lt_pass,
            "synthetic_hif_records": 1,
            "synthetic_hif_passed": hif_pass,
            "total_verified": total_rec,
            "total_passed": total_pass,
        },
        "parity": {
            "opendss_max_tier2_abs_err": round(max_t2_abs, 6),
            "opendss_max_tier2_rel_err": round(max_t2_rel, 7),
            "opendss_max_transfer_abs_err": round(max_tr_abs, 7),
            "opendss_max_active_abs_err": round(max_ag_abs, 7),
            "opendss_tier2_model_matches": t2_matches,
            "opendss_transfer_gbdt_matches": tr_gbdt_matches,
            "opendss_transfer_gnn_matches": tr_gnn_matches,
            "opendss_total_events": len(opendss_results),
            "ltspice_bolted_rms_rel_err_pct": ltspice_bolted_err_pct,
            "ltspice_hif100_i1_rel_err_pct": ltspice_hif100_err_pct,
            "hif_roundtrip_max_feat_abs_err": round(hif_max_feat_err, 6),
            "hif_roundtrip_p_hif_abs_err": None if p_hif_abs_err is None else round(p_hif_abs_err, 6),
        },
        "public_samples": public_results,
        "synthetic_opendss": opendss_results,
        "synthetic_ltspice": ltspice_results,
        "synthetic_hif_edge": hif_roundtrip_result,
        "single_device_demo": single_device_demo,
        "cli_examples": {
            "single_file": ".venv\\Scripts\\python scripts/comtrade_ingest.py data/comtrade_samples/public/fdr2214_ag_fault.cfg",
            "multi_device_folder": ".venv\\Scripts\\python scripts/comtrade_ingest.py data/comtrade_samples/synthetic_roundtrip/opendss_ieee123_bus60_slg1_ascii --channel-map data/comtrade_samples/synthetic_roundtrip/opendss_ieee123_bus60_slg1_ascii/channel_map.json",
            "verify_samples": ".venv\\Scripts\\python scripts/comtrade_ingest.py --verify-samples",
        },
        "runtime_s": round(time.time() - t0, 2),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8")
    provenance.record("comtrade_verify", [SUMMARY_PATH])
    return summary


# ---------------------------------------------------------------------------
# Human-readable CLI printing
# ---------------------------------------------------------------------------
def _print_verify_summary(summary: dict[str, Any]) -> None:
    c = summary["counts"]
    p = summary["parity"]
    print(f"COMTRADE verification: {summary['status'].upper()} ({c['total_passed']}/{c['total_verified']} passed, {summary['runtime_s']} s)")
    print(f"  Public IEEE C37.111 samples : {c['public_passed']}/{c['public_samples']} passed")
    for r in summary["public_samples"]:
        ch = ",".join(r["mapped_channels"].keys()) or "none"
        print(
            f"    - {r['id']:<24s} {r['rev_year']} {r['data_format']:<6s} {r['frequency_hz']:g}Hz "
            f"fs={r['sample_rate_hz']:g}Hz n={r['n_samples']:<4d} ch=[{ch}] "
            f"tier2={r['tier2_finite_features']}/{r['tier2_total_features']}"
        )
    print(f"  OpenDSS round-trip (sim)    : {c['synthetic_opendss_passed']}/{c['synthetic_opendss_events']} passed")
    print(
        f"    max err -> Tier-2 rel={p['opendss_max_tier2_rel_err']:.2e}, "
        f"Transfer abs={p['opendss_max_transfer_abs_err']:.2e}, "
        f"Active abs={p['opendss_max_active_abs_err']:.2e}"
    )
    print(
        f"    model parity -> Tier-2 GBDT {p['opendss_tier2_model_matches']}/{p['opendss_total_events']}, "
        f"Transfer GBDT {p['opendss_transfer_gbdt_matches']}/{p['opendss_total_events']}, "
        f"Transfer GNN {p['opendss_transfer_gnn_matches']}/{p['opendss_total_events']}"
    )
    print(f"  LTspice round-trip (sim)    : {c['synthetic_ltspice_passed']}/{c['synthetic_ltspice_records']} passed")
    for r in summary["synthetic_ltspice"]:
        print(
            f"    - {r['id']:<28s} ref={r['reference_value_a']:.2f} A vs DFT={r['comtrade_dft_value_a']:.2f} A "
            f"(err={r['rel_err_pct']:.3f}%)"
        )
    h = summary["synthetic_hif_edge"]
    print(
        f"  Tier-1 HIF round-trip (sim) : {c['synthetic_hif_passed']}/{c['synthetic_hif_records']} passed "
        f"(feat_err={h['max_feature_abs_err']:.2e}, p_hif={h['p_hif_comtrade']} vs {h['p_hif_direct']}, alarm={h['hif_alarm']})"
    )
    print(f"  Wrote: {_rel(SUMMARY_PATH)} + results/provenance/comtrade_verify.json")


def _print_ingest_summary(payload: dict[str, Any]) -> None:
    print(f"COMTRADE Ingest Summary ({payload['input']})")
    print(f"  Devices loaded ({len(payload['devices'])}): {', '.join(payload['devices'])}")
    for dev, info in payload["records"].items():
        ch = ", ".join(f"{k}->{v}" for k, v in info["mapped_channels"].items()) or "none"
        print(
            f"  [{dev}] IEEE C37.111-{info['rev_year']} {info['data_format']} | "
            f"{info['frequency_hz']:g} Hz, fs={info['sample_rate_hz']:g} Hz, "
            f"{info['n_samples']} samples ({info['duration_ms']:.1f} ms)"
        )
        print(f"       channels : {ch}")
        print(
            f"       onset    : {info['event_time_ms']:.2f} ms ({info['onset_source']}) | "
            f"|I_pre|={info['i_pre_rms_a']} A -> |I_post|={info['i_post_rms_a']} A | "
            f"|V_post|={info['v_post_pu']} pu"
        )
    fsum = payload["feature_summary"]
    print(
        f"  Features: Tier-2 {fsum['tier2_finite']}/{fsum['tier2_total']} finite | "
        f"Transfer {tuple(fsum['transfer_shape'])} | Active-Grid {tuple(fsum['active_grid_shape'])}"
    )
    inf = payload.get("trial_inference")
    if inf:
        print("  Trial inference (simulation-trained models):")
        if inf.get("tier2_gbdt"):
            t2 = inf["tier2_gbdt"]
            print(f"    - Tier-2 GBDT   : zone={t2['predicted_zone']} (conf={t2['confidence']:.3f})")
        if inf.get("transfer_gbdt"):
            tg = inf["transfer_gbdt"]
            print(f"    - Transfer GBDT : zone={tg['predicted_zone']} ({tg['node_count']} nodes)")
        if inf.get("transfer_gnn"):
            tn = inf["transfer_gnn"]
            print(f"    - Transfer GNN  : zone={tn['predicted_zone']} (conf={tn['confidence']:.3f}, {tn['node_count']} nodes)")
        for dev, h in (inf.get("tier1_hif") or {}).items():
            if h["ok"]:
                print(
                    f"    - Tier-1 HIF [{dev}]: p_hif={h['p_hif']} alarm={h['hif_alarm']} "
                    f"(thr={h['threshold']}, {h['n_windows']} windows, src={h['residual_source']})"
                )
                for w in h.get("warnings") or []:
                    print(f"        note: {w}")
            else:
                print(f"    - Tier-1 HIF [{dev}]: skipped ({h['reason']})")
        if inf.get("limitations"):
            print("  Limitations / notes:")
            for note in inf["limitations"]:
                print(f"    * {note}")


# ---------------------------------------------------------------------------
# Main CLI entrypoint
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read IEEE C37.111 COMTRADE file(s), convert to SHF model features, and run trial inference."
    )
    ap.add_argument(
        "input_path",
        nargs="?",
        default=None,
        help="Path to one .cfg/.cff COMTRADE file or a folder of multi-device COMTRADE files.",
    )
    ap.add_argument(
        "--verify-samples",
        action="store_true",
        help="Verify all public & synthetic round-trip samples, write results/comtrade/summary.json and provenance.",
    )
    ap.add_argument(
        "--regen-synthetic",
        action="store_true",
        help="Force regeneration of data/comtrade_samples/synthetic_roundtrip/ before verifying.",
    )
    ap.add_argument("--channel-map", type=Path, default=None, help="Optional JSON channel/device mapping file.")
    ap.add_argument("--device-name", type=str, default=None, help="Device name when ingesting a single file (default Sw1).")
    ap.add_argument("--v-base-kv", type=float, default=None, help="Line-to-line base voltage in kV (e.g. 4.16).")
    ap.add_argument("--v-base-ln", type=float, default=None, help="Line-to-neutral base voltage in V (overrides --v-base-kv).")
    ap.add_argument("--event-time-s", type=float, default=None, help="Explicit fault onset offset in seconds from sample 0.")
    ap.add_argument("--side", choices=("primary", "secondary", "raw"), default="primary", help="Analog scaling side (default primary).")
    ap.add_argument("--out-features", type=Path, default=None, help="Optional JSON path to save extracted features and summary.")
    ap.add_argument("--no-infer", action="store_true", help="Extract features only; skip trial model inference.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = ap.parse_args(argv)

    if args.verify_samples:
        summary = verify_all_samples(regen_synthetic=args.regen_synthetic)
        if args.json:
            print(json.dumps(_json_safe(summary), indent=2))
        else:
            _print_verify_summary(summary)
        return 0 if summary["status"] == "ok" else 1

    if args.input_path is None:
        ap.error("Provide a COMTRADE .cfg/.cff file or directory, or pass --verify-samples.")

    target = Path(args.input_path)
    recs, ch_map, map_v_kv = load_input_records(
        target,
        device_name=args.device_name,
        channel_map_path=args.channel_map,
        side=args.side,
    )
    models_obj = LoadedModels() if not args.no_infer else None
    v_kv = args.v_base_kv if args.v_base_kv is not None else map_v_kv

    # Use IEEE 123-bus Grid when all loaded devices belong to IEEE 123-bus sectionalizers
    is_ieee123_devs = bool(recs) and all(d in comtrade.DEFAULT_DEVICES for d in recs)
    grid_obj = None
    if is_ieee123_devs and len(recs) > 1:
        feeder.load_feeder()
        grid_obj = transfer.study_grid()

    phasor_kw: dict[str, Any] = {}
    if args.event_time_s is not None:
        phasor_kw["event_time_s"] = args.event_time_s

    bundle = comtrade.comtrade_to_model_inputs(
        recs,
        channel_maps=ch_map,
        v_base_ln=args.v_base_ln,
        v_base_kv=v_kv if args.v_base_ln is None else None,
        grid=grid_obj,
        hif_model=models_obj.hif_model if models_obj is not None else None,
        include_hif=True,
        **phasor_kw,
    )

    is_full_ieee123 = is_ieee123_devs and len(recs) == len(comtrade.DEFAULT_DEVICES) and all(
        abs(r.frequency - 60.0) < 0.5 for r in recs.values()
    )
    infer = (
        run_trial_inference(bundle, models_obj, recs, is_ieee123_match=is_full_ieee123)
        if models_obj is not None
        else None
    )

    rec_summaries: dict[str, Any] = {}
    for dev, rec in recs.items():
        ph = bundle["phasors"][dev]
        rec_summaries[dev] = {
            "source": _rel(rec.source_path) if rec.source_path else "",
            "rev_year": int(rec.rev_year),
            "data_format": rec.data_format,
            "frequency_hz": float(rec.frequency),
            "sample_rate_hz": round(float(rec.sample_rate_hz()), 2),
            "n_samples": int(rec.n_samples),
            "duration_ms": round(rec.duration_s * 1e3, 3),
            "mapped_channels": {
                k: rec.analog_channels[idx].name for k, idx in ph["channel_map"].items()
            },
            "onset_source": ph["onset_source"],
            "event_time_ms": round(ph["event_time_s"] * 1e3, 3),
            "i_pre_rms_a": _round_list(np.abs(ph["pre"]["i"]), 3),
            "i_post_rms_a": _round_list(np.abs(ph["post"]["i"]), 3),
            "v_post_pu": _round_list(np.abs(ph["post"]["v"]), 4),
        }

    t2_vec = bundle["tier2"]["vector"]
    payload = {
        "input": _rel(target),
        "devices": list(recs.keys()),
        "records": rec_summaries,
        "feature_summary": {
            "tier2_finite": int(np.isfinite(t2_vec).sum()),
            "tier2_total": int(t2_vec.size),
            "transfer_shape": list(bundle["transfer"]["X"].shape),
            "active_grid_shape": list(bundle["active_grid"]["X"].shape),
        },
        "features": {
            "tier2": bundle["tier2"]["features"],
            "transfer": {
                "devices": bundle["transfer"]["devices"],
                "parent": bundle["transfer"]["parent"].tolist(),
                "columns": bundle["transfer"]["features"],
                "X": bundle["transfer"]["X"].tolist(),
            },
            "active_grid": {
                "devices": bundle["active_grid"]["devices"],
                "adj": bundle["active_grid"]["adj"].tolist(),
                "columns": bundle["active_grid"]["features"],
                "X": bundle["active_grid"]["X"].tolist(),
            },
        },
        "trial_inference": infer,
    }

    if args.out_features is not None:
        args.out_features.parent.mkdir(parents=True, exist_ok=True)
        args.out_features.write_text(json.dumps(_json_safe(payload), indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(_json_safe(payload), indent=2))
    else:
        _print_ingest_summary(payload)
        if args.out_features is not None:
            print(f"  Saved features JSON: {_rel(args.out_features)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
