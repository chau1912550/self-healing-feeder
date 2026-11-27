"""IEEE C37.111-1999 & 2013 COMTRADE reader/writer and model feature adapter.

Reads relay/recloser disturbance records (.cfg/.dat in ASCII, BINARY, BINARY32,
FLOAT32, plus single-file .cff), converts raw samples through `a * x + b` and
primary/secondary CT/PT ratios, extracts pre- and post-fault fundamental-frequency
phasors via full-cycle DFT (50/60 Hz), and maps them onto the three feature schemas
used across `self-healing-feeder`:

  1. Tier-2 `shf.model`: 15 features/device (missing devices filled with NaN,
     matching `shf.model.sensor_dropout`).
  2. Graph models: 21 node features/device (`shf.transfer`) and 26 node
     features/device (`shf.active_grid`).
  3. Optional Tier-1 `shf.hif_edge` bridge: 16 window features over residual
     current when the sampling rate and duration are sufficient.

Pure Python (stdlib + numpy/scipy). Synthetic roundtrip helper is simulation only.
"""
from __future__ import annotations

import cmath
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import CubicSpline

from . import config, hif_edge

# ---------------------------------------------------------------------------
# Feature schemas (exact parity with shf/model.py, shf/transfer.py, shf/active_grid.py)
# ---------------------------------------------------------------------------
A_OP = cmath.rect(1.0, 2.0 * math.pi / 3.0)  # 120-degree sequence operator (shf/feeder.py)

DEFAULT_DEVICES: tuple[str, ...] = tuple(config.SECTIONALIZERS)

TIER2_DEVICE_KEYS_FULL: tuple[str, ...] = (
    "Ia", "Ib", "Ic", "dIa", "dIb", "dIc", "I0", "dI0", "dI2",
    "Va", "Vb", "Vc", "dVa", "dVb", "dVc",
)
TIER2_DEVICE_KEYS_MAG: tuple[str, ...] = (
    "Ia", "Ib", "Ic", "I0", "Va", "Vb", "Vc",
)

TRANSFER_FEATURES: tuple[str, ...] = (
    "dIa", "dIb", "dIc", "Ia", "Ib", "Ic", "dI0", "dI2",
    "Va", "Vb", "Vc", "dVa", "dVb", "dVc", "has_a", "has_b", "has_c",
    "depth", "n_children", "share_down", "share_own",
)
N_TRANSFER_ELEC = 17  # indices 0..16 are live measurements; 17..20 are tree structure

ACTIVE_FEATURES: tuple[str, ...] = (
    "dIa", "dIb", "dIc", "Ia", "Ib", "Ic", "dI0", "dI2",
    "Va", "Vb", "Vc", "dVa", "dVb", "dVc", "has_a", "has_b", "has_c",
    "cos_vi_post", "cos_vi_pre", "cos_di_vpre", "power_rev",
    "is_closed", "active_deg", "share_own", "der_ratio", "is_source_adj",
)
N_ACTIVE_ELEC = 21  # indices 0..20 are live measurements; 21..25 are grid state

CANONICAL_CHANNELS: tuple[str, ...] = ("Ia", "Ib", "Ic", "Va", "Vb", "Vc", "In")

# Minimum sampling rate for Tier-1 HIF features: >= 16 samples/cycle (Nyquist >= 8*f0)
# so harmonics up to the 6th (used in even_ratio) are below Nyquist.
MIN_HIF_SAMPLES_PER_CYCLE = 16
# Full passband coverage matching Tier-1 2,045 Hz Butterworth cutoff.
RECOMMENDED_HIF_FS_HZ = 4096.0

_SUPPORTED_FORMATS = ("ASCII", "BINARY", "BINARY32", "FLOAT32")
_MISSING_INT16 = -32768
_MISSING_INT32 = -2147483648
_MISSING_TIMESTAMP = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class AnalogChannel:
    """IEEE C37.111 analog channel header."""

    index: int
    name: str
    phase: str = ""
    ccbm: str = ""
    unit: str = ""
    a: float = 1.0
    b: float = 0.0
    skew: float = 0.0
    min_val: float = -32767.0
    max_val: float = 32767.0
    primary: float = 1.0
    secondary: float = 1.0
    ps: str = "P"

    def ratio_factor(self, side: str = "primary") -> float:
        """Scale factor converting recorded side (`ps`) to requested `side`."""
        side_l = side.lower()
        ps_u = (self.ps or "P").strip().upper()
        if side_l == "raw":
            return 1.0
        p = float(self.primary) if self.primary else 1.0
        s = float(self.secondary) if self.secondary else 1.0
        if side_l == "primary":
            return (p / s) if (ps_u == "S" and s != 0.0) else 1.0
        if side_l == "secondary":
            return (s / p) if (ps_u == "P" and p != 0.0) else 1.0
        raise ValueError(f"side must be 'primary', 'secondary', or 'raw', got {side!r}")

    def unit_scale_si(self) -> tuple[str, float]:
        """Return `(base_unit, multiplier)` normalizing kA/mA -> A, kV/mV -> V, pu -> pu."""
        u = self.unit.strip()
        ul = u.lower().replace(".", "")
        if ul in ("a", "amp", "amps", "ampere", "amperes"):
            return "A", 1.0
        if ul in ("ka", "kamp", "kamps"):
            return "A", 1e3
        if ul in ("ma", "mamp", "mamps") and not u.startswith("M"):
            return "A", 1e-3
        if ul in ("v", "volt", "volts"):
            return "V", 1.0
        if ul in ("kv", "kvolt", "kvolts"):
            return "V", 1e3
        if ul in ("mv", "mvolt", "mvolts") and not u.startswith("M"):
            return "V", 1e-3
        if ul == "pu":
            return "pu", 1.0
        return u, 1.0


@dataclass
class DigitalChannel:
    """IEEE C37.111 status/digital channel header."""

    index: int
    name: str
    phase: str = ""
    ccbm: str = ""
    normal_state: int = 0


@dataclass
class ComtradeRecord:
    """Parsed IEEE C37.111-1991/1999/2013 COMTRADE record."""

    station: str
    rec_dev_id: str
    rev_year: int
    analog_channels: list[AnalogChannel]
    digital_channels: list[DigitalChannel]
    frequency: float
    rates: list[tuple[float, int]]
    start_time: str
    trigger_time: str
    trigger_offset_s: float | None
    data_format: str
    timemult: float
    time: np.ndarray                         # (n_samples,) seconds from sample 0
    raw_timestamps: np.ndarray               # (n_samples,) raw timestamp field
    analog: np.ndarray                       # (n_analog, n_samples) float64 in requested `side`
    digital: np.ndarray                      # (n_digital, n_samples) uint8
    side: str = "primary"
    time_code: str = ""
    local_code: str = ""
    tmq_code: str = ""
    leapsec: str = ""
    source_path: Path | None = None
    extra_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return int(self.time.shape[0])

    @property
    def n_analog(self) -> int:
        return len(self.analog_channels)

    @property
    def n_digital(self) -> int:
        return len(self.digital_channels)

    @property
    def duration_s(self) -> float:
        return float(self.time[-1] - self.time[0]) if self.n_samples >= 2 else 0.0

    @property
    def analog_names(self) -> list[str]:
        return [c.name for c in self.analog_channels]

    @property
    def digital_names(self) -> list[str]:
        return [c.name for c in self.digital_channels]

    def sample_rate_hz(self, t_s: float | None = None) -> float:
        """Active sampling rate (Hz) at `t_s`, or nominal/median rate across the record."""
        if self.n_samples < 2:
            if self.rates and self.rates[0][0] > 0:
                return float(self.rates[0][0])
            return 0.0
        if t_s is not None:
            idx = int(np.searchsorted(self.time, t_s, side="left"))
            idx = min(max(idx, 1), self.n_samples - 1)
            dt = float(self.time[idx] - self.time[idx - 1])
            if dt > 0:
                return 1.0 / dt
        if self.rates and all(r > 0 for r, _ in self.rates):
            if len(self.rates) == 1:
                return float(self.rates[0][0])
            # Prefer the highest active rate when multi-rate records step down post-fault.
            return float(max(r for r, _ in self.rates))
        dts = np.diff(self.time)
        pos = dts[dts > 0]
        return float(1.0 / np.median(pos)) if len(pos) else 0.0

    def get_analog(self, key: str | int, *, si: bool = False) -> np.ndarray:
        """Fetch an analog waveform by 0-based index or channel name (case-insensitive)."""
        idx = _resolve_channel_index(self, key)
        arr = self.analog[idx]
        if si:
            _, scale = self.analog_channels[idx].unit_scale_si()
            return arr * scale
        return arr


# ---------------------------------------------------------------------------
# Timestamp and CFG parsing helpers
# ---------------------------------------------------------------------------
def _parse_float(tok: str, default: float = 0.0) -> float:
    s = tok.strip()
    return float(s) if s else default


def _parse_int(tok: str, default: int = 0) -> int:
    s = tok.strip()
    return int(float(s)) if s else default


def _parse_timestamp(raw: str, rev_year: int) -> tuple[datetime | None, float, int]:
    """Parse COMTRADE timestamp `dd/mm/yyyy,hh:mm:ss.ssssss[sss]`.

    Returns `(base_datetime_without_frac, frac_seconds, frac_digits)`.
    """
    s = raw.strip()
    if not s or "," not in s:
        return None, 0.0, 6
    date_part, time_part = [p.strip() for p in s.split(",", 1)]
    date_toks = date_part.split("/")
    time_toks = time_part.split(":")
    if len(date_toks) != 3 or len(time_toks) != 3:
        return None, 0.0, 6
    try:
        p1, p2, yr = int(date_toks[0]), int(date_toks[1]), int(date_toks[2])
        if yr == 0 or p1 == 0 or p2 == 0:
            return None, 0.0, 6
        if yr < 100:
            yr += 2000 if yr < 70 else 1900
        # 1991 used mm/dd/yyyy; 1999 & 2013 use dd/mm/yyyy. Disambiguate when unambiguous.
        if p1 > 12:
            day, month = p1, p2
        elif p2 > 12:
            month, day = p1, p2
        elif rev_year <= 1991:
            month, day = p1, p2
        else:
            day, month = p1, p2
        hh, mm = int(time_toks[0]), int(time_toks[1])
        sec_str = time_toks[2]
        if "." in sec_str:
            ss_s, frac_s = sec_str.split(".", 1)
            frac_digits = len(frac_s)
            ss = int(ss_s)
            frac = float("0." + frac_s) if frac_s else 0.0
        else:
            ss = int(sec_str)
            frac = 0.0
            frac_digits = 6
        base = datetime(yr, month, day, hh, mm, ss)
        return base, frac, frac_digits
    except ValueError:
        return None, 0.0, 6


def _format_timestamp(base_str: str, offset_s: float, rev_year: int) -> str:
    """Shift a COMTRADE timestamp string by `offset_s` seconds."""
    dt, frac, digits = _parse_timestamp(base_str, rev_year)
    digits = 9 if rev_year >= 2013 and digits > 6 else 6
    if dt is None:
        dt = datetime(2026, 1, 1, 0, 0, 0)
        frac = 0.0
    total = frac + float(offset_s)
    whole_s = math.floor(total)
    rem = total - whole_s
    dt2 = dt + timedelta(seconds=whole_s)
    scale = 10 ** digits
    frac_int = int(round(rem * scale))
    if frac_int >= scale:
        dt2 += timedelta(seconds=1)
        frac_int -= scale
    return f"{dt2.day:02d}/{dt2.month:02d}/{dt2.year:04d},{dt2.hour:02d}:{dt2.minute:02d}:{dt2.second:02d}.{frac_int:0{digits}d}"


def _parse_cfg_text(text: str) -> dict[str, Any]:
    """Parse IEEE C37.111-1991/1999/2013 `.cfg` text into structured header fields."""
    lines = [ln.rstrip("\r\n") for ln in text.lstrip("\ufeff").splitlines() if ln.strip()]
    if len(lines) < 7:
        raise ValueError(f"COMTRADE .cfg too short ({len(lines)} non-empty lines)")

    # Line 1: station_name, rec_dev_id [, rev_year]
    hdr = [p.strip() for p in lines[0].split(",")]
    rev_year = 1991
    if len(hdr) >= 3 and hdr[-1].isdigit():
        rev_year = int(hdr[-1])
        rec_dev_id = hdr[-2]
        station = ",".join(hdr[:-2]).strip()
    elif len(hdr) >= 2:
        station, rec_dev_id = hdr[0], hdr[1]
    else:
        station, rec_dev_id = hdr[0], ""

    # Line 2: TT, ##A, ##D
    cnt = [p.strip() for p in lines[1].split(",")]
    if len(cnt) < 3:
        raise ValueError(f"Invalid COMTRADE channel count line: {lines[1]!r}")
    total_ch = int(cnt[0])
    n_analog = int(re.sub(r"[aA]$", "", cnt[1]))
    n_digital = int(re.sub(r"[dD]$", "", cnt[2]))
    if total_ch != n_analog + n_digital:
        raise ValueError(
            f"COMTRADE channel count mismatch: total={total_ch} != {n_analog}A + {n_digital}D"
        )

    pos = 2
    analog_channels: list[AnalogChannel] = []
    for _ in range(n_analog):
        parts = [p.strip() for p in lines[pos].split(",")]
        pos += 1
        if len(parts) < 10:
            raise ValueError(f"Analog channel line has {len(parts)} fields (<10): {parts!r}")
        analog_channels.append(
            AnalogChannel(
                index=_parse_int(parts[0]),
                name=parts[1],
                phase=parts[2],
                ccbm=parts[3],
                unit=parts[4],
                a=_parse_float(parts[5], 1.0),
                b=_parse_float(parts[6], 0.0),
                skew=_parse_float(parts[7], 0.0),
                min_val=_parse_float(parts[8], -32767.0),
                max_val=_parse_float(parts[9], 32767.0),
                primary=_parse_float(parts[10], 1.0) if len(parts) > 10 else 1.0,
                secondary=_parse_float(parts[11], 1.0) if len(parts) > 11 else 1.0,
                ps=(parts[12].upper() if len(parts) > 12 and parts[12] else "P"),
            )
        )

    digital_channels: list[DigitalChannel] = []
    for _ in range(n_digital):
        parts = [p.strip() for p in lines[pos].split(",")]
        pos += 1
        if len(parts) >= 5:
            digital_channels.append(
                DigitalChannel(
                    index=_parse_int(parts[0]),
                    name=parts[1],
                    phase=parts[2],
                    ccbm=parts[3],
                    normal_state=_parse_int(parts[4], 0),
                )
            )
        elif len(parts) >= 3:
            digital_channels.append(
                DigitalChannel(
                    index=_parse_int(parts[0]),
                    name=parts[1],
                    normal_state=_parse_int(parts[2], 0),
                )
            )
        else:
            raise ValueError(f"Digital channel line invalid: {parts!r}")

    frequency = _parse_float(lines[pos], 60.0)
    pos += 1

    nrates = _parse_int(lines[pos], 0)
    pos += 1
    rate_lines = max(nrates, 1)  # nrates==0 still has 1 line `0,endsamp`
    rates: list[tuple[float, int]] = []
    for _ in range(rate_lines):
        r_parts = [p.strip() for p in lines[pos].split(",")]
        pos += 1
        rates.append((_parse_float(r_parts[0], 0.0), _parse_int(r_parts[1], 0)))

    start_time = lines[pos].strip()
    pos += 1
    trigger_time = lines[pos].strip()
    pos += 1

    data_format = lines[pos].strip().upper()
    pos += 1
    if data_format not in _SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported COMTRADE data format: {data_format!r}")

    timemult = _parse_float(lines[pos], 1.0) if pos < len(lines) else 1.0
    pos += 1

    time_code = ""
    local_code = ""
    if pos < len(lines):
        tc = [p.strip() for p in lines[pos].split(",")]
        time_code = tc[0] if len(tc) > 0 else ""
        local_code = tc[1] if len(tc) > 1 else ""
        pos += 1

    tmq_code = ""
    leapsec = ""
    if pos < len(lines):
        tq = [p.strip() for p in lines[pos].split(",")]
        tmq_code = tq[0] if len(tq) > 0 else ""
        leapsec = tq[1] if len(tq) > 1 else ""

    dt_start, frac_start, d_start = _parse_timestamp(start_time, rev_year)
    dt_trig, frac_trig, d_trig = _parse_timestamp(trigger_time, rev_year)
    trigger_offset_s: float | None = None
    if dt_start is not None and dt_trig is not None:
        trigger_offset_s = float((dt_trig - dt_start).total_seconds() + (frac_trig - frac_start))
    ts_unit_s = 1e-9 if (rev_year >= 2013 and max(d_start, d_trig) > 6) else 1e-6

    return {
        "station": station,
        "rec_dev_id": rec_dev_id,
        "rev_year": rev_year,
        "analog_channels": analog_channels,
        "digital_channels": digital_channels,
        "frequency": frequency,
        "nrates": nrates,
        "rates": rates,
        "start_time": start_time,
        "trigger_time": trigger_time,
        "trigger_offset_s": trigger_offset_s,
        "ts_unit_s": ts_unit_s,
        "data_format": data_format,
        "timemult": timemult,
        "time_code": time_code,
        "local_code": local_code,
        "tmq_code": tmq_code,
        "leapsec": leapsec,
    }


def _find_dat_path(cfg_path: Path) -> Path:
    """Locate the matching `.dat` file case-insensitively beside `cfg_path`."""
    for ext in (".dat", ".DAT", ".Dat"):
        cand = cfg_path.with_suffix(ext)
        if cand.is_file():
            return cand
    stem_l = cfg_path.stem.lower()
    for p in cfg_path.parent.iterdir():
        if p.is_file() and p.stem.lower() == stem_l and p.suffix.lower() == ".dat":
            return p
    raise FileNotFoundError(f"Matching .dat file not found for {cfg_path}")


def _split_cff(raw_bytes: bytes) -> tuple[str, bytes]:
    """Extract CFG text and DAT payload from an IEEE C37.111-2013 `.cff` file."""
    marker_re = re.compile(rb"^--- file type:\s*([A-Za-z0-9_ :]+?)\s*---\r?\n", re.MULTILINE)
    matches = list(marker_re.finditer(raw_bytes))
    if not matches:
        raise ValueError("Invalid .cff file: no `--- file type: ... ---` section headers found")
    cfg_bytes: bytes | None = None
    dat_bytes: bytes | None = None
    for i, m in enumerate(matches):
        header = m.group(1).decode("ascii", errors="ignore").strip().upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_bytes)
        body = raw_bytes[start:end]
        if header.startswith("CFG"):
            cfg_bytes = body
        elif header.startswith("DAT"):
            dat_bytes = body
    if cfg_bytes is None or dat_bytes is None:
        raise ValueError("Invalid .cff file: missing CFG or DAT section")
    return cfg_bytes.decode("utf-8-sig", errors="replace"), dat_bytes


def _parse_dat_ascii(
    raw_bytes: bytes,
    n_analog: int,
    n_digital: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse ASCII `.dat` payload into `(raw_timestamps, analog_raw, digital)`."""
    text = raw_bytes.decode("utf-8-sig", errors="replace").replace("\x1a", "")
    ts_list: list[float] = []
    a_rows: list[list[float]] = []
    d_rows: list[list[int]] = []
    expected = 2 + n_analog + n_digital

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split(",")
        if len(parts) < expected:
            parts = parts + [""] * (expected - len(parts))
        ts_tok = parts[1].strip()
        ts_list.append(float(ts_tok) if ts_tok else np.nan)
        a_rows.append([float(p) if p.strip() else np.nan for p in parts[2 : 2 + n_analog]])
        d_rows.append([int(float(p)) & 1 if p.strip() else 0 for p in parts[2 + n_analog : expected]])

    n = len(ts_list)
    raw_ts = np.asarray(ts_list, dtype=np.float64)
    analog_raw = (
        np.asarray(a_rows, dtype=np.float64).T
        if (n and n_analog)
        else np.empty((n_analog, n), dtype=np.float64)
    )
    digital = (
        np.asarray(d_rows, dtype=np.uint8).T
        if (n and n_digital)
        else np.empty((n_digital, n), dtype=np.uint8)
    )
    return raw_ts, analog_raw, digital


def _parse_dat_binary(
    raw_bytes: bytes,
    data_format: str,
    analog_channels: list[AnalogChannel],
    n_digital: int,
    expected_samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse BINARY / BINARY32 / FLOAT32 `.dat` payload via structured numpy dtype."""
    n_analog = len(analog_channels)
    n_dwords = (n_digital + 15) // 16
    analog_dtype = {"BINARY": "<i2", "BINARY32": "<i4", "FLOAT32": "<f4"}[data_format]

    fields: list[tuple[str, Any]] = [("n", "<u4"), ("ts", "<u4")]
    if n_analog > 0:
        fields.append(("a", analog_dtype, (n_analog,)))
    if n_dwords > 0:
        fields.append(("d", "<u2", (n_dwords,)))
    rec_dtype = np.dtype(fields, align=False)
    rec_size = rec_dtype.itemsize

    n_avail = len(raw_bytes) // rec_size
    n_read = min(n_avail, expected_samples) if expected_samples > 0 else n_avail
    arr = np.frombuffer(raw_bytes, dtype=rec_dtype, count=n_read)

    raw_ts = arr["ts"].astype(np.float64)
    raw_ts[arr["ts"] == _MISSING_TIMESTAMP] = np.nan

    if n_analog > 0:
        a_mat = arr["a"]
        if a_mat.ndim == 1:
            a_mat = a_mat[:, None]
        analog_raw = a_mat.astype(np.float64).T
        if data_format == "BINARY":
            for k, ch in enumerate(analog_channels):
                if ch.min_val > _MISSING_INT16:
                    analog_raw[k, a_mat[:, k] == _MISSING_INT16] = np.nan
        elif data_format == "BINARY32":
            for k, ch in enumerate(analog_channels):
                if ch.min_val > _MISSING_INT32:
                    analog_raw[k, a_mat[:, k] == _MISSING_INT32] = np.nan
    else:
        analog_raw = np.empty((0, n_read), dtype=np.float64)

    if n_digital > 0:
        d_words = arr["d"]
        if d_words.ndim == 1:
            d_words = d_words[:, None]
        digital = np.empty((n_digital, n_read), dtype=np.uint8)
        for j in range(n_digital):
            digital[j] = ((d_words[:, j // 16] >> (j % 16)) & 1).astype(np.uint8)
    else:
        digital = np.empty((0, n_read), dtype=np.uint8)

    return raw_ts, analog_raw, digital


def _build_time_axis(
    n_samples: int,
    nrates: int,
    rates: list[tuple[float, int]],
    raw_timestamps: np.ndarray,
    timemult: float,
    ts_unit_s: float,
) -> np.ndarray:
    """Construct exact sample time vector (seconds) per IEEE C37.111."""
    if n_samples == 0:
        return np.empty((0,), dtype=np.float64)

    use_rates = nrates > 0 and len(rates) > 0 and all(r > 0.0 for r, _ in rates)
    if use_rates:
        t = np.zeros(n_samples, dtype=np.float64)
        idx = 0
        for seg_i, (fs_seg, end_samp) in enumerate(rates):
            dt = 1.0 / float(fs_seg)
            stop = min(int(end_samp), n_samples) if seg_i < len(rates) - 1 else n_samples
            if seg_i == 0:
                if stop > 1:
                    t[1:stop] = np.arange(1, stop, dtype=np.float64) * dt
                idx = max(stop, 1)
            else:
                if stop > idx:
                    t0 = t[idx - 1]
                    t[idx:stop] = t0 + np.arange(1, stop - idx + 1, dtype=np.float64) * dt
                    idx = stop
        return t

    # Variable sampling rate (nrates == 0): timestamps from .dat are authoritative.
    valid = np.isfinite(raw_timestamps)
    if np.all(valid):
        t = raw_timestamps * float(timemult) * float(ts_unit_s)
        return t - t[0]
    raise ValueError("COMTRADE nrates=0 requires valid timestamps in .dat")


# ---------------------------------------------------------------------------
# Public reader & writer
# ---------------------------------------------------------------------------
def read_comtrade(
    path: Path | str,
    *,
    dat_path: Path | str | None = None,
    side: str = "primary",
) -> ComtradeRecord:
    """Read an IEEE C37.111-1991/1999/2013 COMTRADE file (`.cfg` + `.dat` or `.cff`).

    Parameters
    ----------
    path : Path | str
        Path to the `.cfg` file (sibling `.dat` located automatically) or `.cff` file.
    dat_path : Path | str | None
        Optional explicit path to the `.dat` file.
    side : {'primary', 'secondary', 'raw'}
        Convert analog channels to `'primary'` (default, applies CT/PT ratio when
        `PS='S'`), `'secondary'`, or `'raw'` (keep `a*x + b` as recorded).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"COMTRADE file not found: {p}")

    if p.suffix.lower() == ".cff":
        cfg_text, dat_bytes = _split_cff(p.read_bytes())
    else:
        cfg_text = p.read_text(encoding="utf-8-sig", errors="replace")
        dp = Path(dat_path) if dat_path is not None else _find_dat_path(p)
        dat_bytes = dp.read_bytes()

    hdr = _parse_cfg_text(cfg_text)
    analog_channels: list[AnalogChannel] = hdr["analog_channels"]
    digital_channels: list[DigitalChannel] = hdr["digital_channels"]
    expected_samples = hdr["rates"][-1][1] if hdr["rates"] else 0

    if hdr["data_format"] == "ASCII":
        raw_ts, analog_raw, digital = _parse_dat_ascii(
            dat_bytes, len(analog_channels), len(digital_channels)
        )
    else:
        raw_ts, analog_raw, digital = _parse_dat_binary(
            dat_bytes, hdr["data_format"], analog_channels, len(digital_channels), expected_samples
        )

    # Apply IEEE C37.111 scaling: y = (a * x + b) * primary_or_secondary_factor
    n_samples = int(raw_ts.shape[0])
    analog = np.empty_like(analog_raw, dtype=np.float64)
    for k, ch in enumerate(analog_channels):
        factor = ch.ratio_factor(side)
        analog[k] = (ch.a * analog_raw[k] + ch.b) * factor

    time_s = _build_time_axis(
        n_samples, hdr["nrates"], hdr["rates"], raw_ts, hdr["timemult"], hdr["ts_unit_s"]
    )

    return ComtradeRecord(
        station=hdr["station"],
        rec_dev_id=hdr["rec_dev_id"],
        rev_year=hdr["rev_year"],
        analog_channels=analog_channels,
        digital_channels=digital_channels,
        frequency=hdr["frequency"],
        rates=hdr["rates"],
        start_time=hdr["start_time"],
        trigger_time=hdr["trigger_time"],
        trigger_offset_s=hdr["trigger_offset_s"],
        data_format=hdr["data_format"],
        timemult=hdr["timemult"],
        time=time_s,
        raw_timestamps=raw_ts,
        analog=analog,
        digital=digital,
        side=side,
        time_code=hdr["time_code"],
        local_code=hdr["local_code"],
        tmq_code=hdr["tmq_code"],
        leapsec=hdr["leapsec"],
        source_path=p,
    )


def _infer_default_unit_phase(name: str) -> tuple[str, str]:
    """Infer default `(unit, phase)` for `write_comtrade` when not explicitly supplied."""
    nl = name.strip().upper()
    unit = "A" if nl.startswith("I") else ("V" if nl.startswith(("V", "U")) else "")
    phase = ""
    if re.search(r"(?:^|[_\-\s])?[IVU](?:[_\-\s]?)(A|1|L1|AN)$", nl):
        phase = "A"
    elif re.search(r"(?:^|[_\-\s])?[IVU](?:[_\-\s]?)(B|2|L2|BN)$", nl):
        phase = "B"
    elif re.search(r"(?:^|[_\-\s])?[IVU](?:[_\-\s]?)(C|3|L3|CN)$", nl):
        phase = "C"
    elif re.search(r"(?:^|[_\-\s])?[IVU](?:[_\-\s]?)(N|0|G|RES)$", nl):
        phase = "N"
    return unit, phase


def write_comtrade(
    path: Path | str,
    *,
    analog: dict[str, np.ndarray] | np.ndarray | None = None,
    fs: float | None = None,
    rates: list[tuple[float, int]] | None = None,
    time: np.ndarray | None = None,
    freq: float = 60.0,
    fmt: str = "ASCII",
    rev_year: int | None = None,
    station: str = "SHF_SIM",
    rec_dev_id: str = "DEV1",
    start_time: str = "01/01/2026,00:00:00.000000",
    trigger_time: str | None = None,
    trigger_offset_s: float = 0.0,
    digital: dict[str, np.ndarray] | np.ndarray | None = None,
    channels: list[AnalogChannel] | None = None,
    digital_channels: list[DigitalChannel] | None = None,
    units: dict[str, str] | None = None,
    phases: dict[str, str] | None = None,
    ct_ratio: float | tuple[float, float] = (1.0, 1.0),
    pt_ratio: float | tuple[float, float] = (1.0, 1.0),
    ps: str = "P",
    timemult: float = 1.0,
    record: ComtradeRecord | None = None,
) -> tuple[Path, Path]:
    """Write IEEE C37.111-1999/2013 `.cfg` and `.dat` files (ASCII/BINARY/BINARY32/FLOAT32).

    When `ps='S'`, input waveforms are assumed to be primary values and are divided
    by `primary / secondary` before encoding so `read_comtrade(..., side='primary')`
    recovers the original primary signal.
    """
    fmt_u = fmt.strip().upper()
    if fmt_u not in _SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format {fmt!r}; expected one of {_SUPPORTED_FORMATS}")

    if record is not None:
        analog_mat = np.asarray(record.analog, dtype=np.float64)
        ch_list = [
            AnalogChannel(
                index=i + 1,
                name=c.name,
                phase=c.phase,
                ccbm=c.ccbm,
                unit=c.unit,
                a=1.0,
                b=0.0,
                skew=c.skew,
                primary=c.primary,
                secondary=c.secondary,
                ps=c.ps if record.side == "raw" else ps.upper(),
            )
            for i, c in enumerate(record.analog_channels)
        ]
        digital_mat = np.asarray(record.digital, dtype=np.uint8)
        d_list = list(record.digital_channels)
        freq = record.frequency
        station = record.station
        rec_dev_id = record.rec_dev_id
        start_time = record.start_time
        trigger_time = record.trigger_time
        rates = list(record.rates) if record.rates else rates
        time_arr = np.asarray(record.time, dtype=np.float64)
        rev_year = rev_year or (2013 if fmt_u in ("BINARY32", "FLOAT32") else record.rev_year)
        timemult = record.timemult or 1.0
    else:
        if analog is None:
            raise ValueError("Provide either `record` or `analog` waveforms")
        if isinstance(analog, dict):
            names = list(analog.keys())
            analog_mat = np.vstack([np.asarray(analog[k], dtype=np.float64) for k in names])
        else:
            analog_mat = np.asarray(analog, dtype=np.float64)
            if analog_mat.ndim == 1:
                analog_mat = analog_mat[None, :]
            names = [c.name for c in channels] if channels else [f"CH{i + 1}" for i in range(analog_mat.shape[0])]

        ct_p, ct_s = (float(ct_ratio), 1.0) if isinstance(ct_ratio, (int, float)) else (float(ct_ratio[0]), float(ct_ratio[1]))
        pt_p, pt_s = (float(pt_ratio), 1.0) if isinstance(pt_ratio, (int, float)) else (float(pt_ratio[0]), float(pt_ratio[1]))
        ps_u = ps.strip().upper()
        if channels is not None:
            ch_list = [
                AnalogChannel(
                    index=i + 1, name=c.name, phase=c.phase, ccbm=c.ccbm, unit=c.unit,
                    a=c.a, b=c.b, skew=c.skew, min_val=c.min_val, max_val=c.max_val,
                    primary=c.primary, secondary=c.secondary, ps=c.ps,
                )
                for i, c in enumerate(channels)
            ]
        else:
            ch_list = []
            for i, name in enumerate(names):
                u_def, ph_def = _infer_default_unit_phase(name)
                unit = (units or {}).get(name, u_def)
                phase = (phases or {}).get(name, ph_def)
                is_v = unit.lower().endswith("v") or name.upper().startswith(("V", "U"))
                prim, sec = (pt_p, pt_s) if is_v else (ct_p, ct_s)
                ch_list.append(
                    AnalogChannel(
                        index=i + 1, name=name, phase=phase, unit=unit,
                        primary=prim, secondary=sec, ps=ps_u,
                    )
                )

        n_samples = int(analog_mat.shape[1])
        if digital is None:
            digital_mat = np.empty((0, n_samples), dtype=np.uint8)
            d_list = []
        elif isinstance(digital, dict):
            d_names = list(digital.keys())
            digital_mat = np.vstack([np.asarray(digital[k], dtype=np.uint8) & 1 for k in d_names])
            d_list = digital_channels or [DigitalChannel(i + 1, nm) for i, nm in enumerate(d_names)]
        else:
            digital_mat = np.asarray(digital, dtype=np.uint8) & 1
            if digital_mat.ndim == 1:
                digital_mat = digital_mat[None, :]
            d_list = digital_channels or [DigitalChannel(i + 1, f"D{i + 1}") for i in range(digital_mat.shape[0])]

        if time is not None:
            time_arr = np.asarray(time, dtype=np.float64)
        elif rates:
            time_arr = _build_time_axis(n_samples, len(rates), rates, np.zeros(n_samples), timemult, 1e-6)
        elif fs is not None and fs > 0:
            time_arr = np.arange(n_samples, dtype=np.float64) / float(fs)
            rates = [(float(fs), n_samples)]
        else:
            raise ValueError("Provide `fs`, `rates`, or `time`")

        if rates is None:
            dts = np.diff(time_arr)
            if len(dts) > 0 and np.allclose(dts, dts[0], rtol=1e-4, atol=1e-9):
                rates = [(float(1.0 / dts[0]), n_samples)]
            else:
                rates = [(0.0, n_samples)]

        rev_year = rev_year or (2013 if fmt_u in ("BINARY32", "FLOAT32") else 1999)

    n_analog, n_samples = analog_mat.shape
    n_digital = digital_mat.shape[0]
    if trigger_time is None:
        trigger_time = _format_timestamp(start_time, trigger_offset_s, rev_year)

    # Convert primary input to recorded side (`P` or `S`) before quantizing into .dat.
    rec_vals = np.empty_like(analog_mat, dtype=np.float64)
    for k, ch in enumerate(ch_list):
        if (record is None or record.side == "primary") and ch.ps.upper() == "S" and ch.primary != 0:
            rec_vals[k] = analog_mat[k] * (ch.secondary / ch.primary)
        else:
            rec_vals[k] = analog_mat[k]

    # Compute per-channel (a, b, min_val, max_val) and raw encoded matrix.
    raw_enc = np.empty((n_analog, n_samples), dtype=np.float64)
    for k, ch in enumerate(ch_list):
        y = rec_vals[k]
        finite = y[np.isfinite(y)]
        if fmt_u == "FLOAT32":
            ch.a = 1.0
            ch.b = 0.0
            ch.min_val = float(np.min(finite)) if len(finite) else -1.0
            ch.max_val = float(np.max(finite)) if len(finite) else 1.0
            raw_enc[k] = y
        else:
            lim = {"ASCII": 999_999, "BINARY": 32_767, "BINARY32": 2_147_483_647}[fmt_u]
            if len(finite) == 0:
                ch.a, ch.b, ch.min_val, ch.max_val = 1.0, 0.0, -lim, lim
                raw_enc[k] = np.nan
            else:
                ymin, ymax = float(np.min(finite)), float(np.max(finite))
                if abs(ymax - ymin) < 1e-15:
                    ch.a, ch.b = 1.0, ymin
                    raw_enc[k] = np.where(np.isfinite(y), 0.0, np.nan)
                else:
                    ch.b = 0.5 * (ymax + ymin)
                    ch.a = 0.5 * (ymax - ymin) / float(lim)
                    q = np.round((y - ch.b) / ch.a)
                    raw_enc[k] = np.where(np.isfinite(y), np.clip(q, -lim, lim), np.nan)
                ch.min_val, ch.max_val = -lim, lim

    cfg_path = Path(path)
    if cfg_path.suffix.lower() != ".cfg":
        cfg_path = cfg_path.with_suffix(".cfg")
    dat_path = cfg_path.with_suffix(".dat")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    # Write .cfg
    nrates_hdr = 0 if (len(rates) == 1 and rates[0][0] == 0.0) else len(rates)
    cfg_lines = [
        f"{station},{rec_dev_id},{rev_year}",
        f"{n_analog + n_digital},{n_analog}A,{n_digital}D",
    ]
    for ch in ch_list:
        min_s = f"{ch.min_val:.6g}" if fmt_u == "FLOAT32" else str(int(round(ch.min_val)))
        max_s = f"{ch.max_val:.6g}" if fmt_u == "FLOAT32" else str(int(round(ch.max_val)))
        cfg_lines.append(
            f"{ch.index},{ch.name},{ch.phase},{ch.ccbm},{ch.unit},"
            f"{ch.a:.12g},{ch.b:.12g},{ch.skew:.6g},{min_s},{max_s},"
            f"{ch.primary:.12g},{ch.secondary:.12g},{ch.ps.upper()}"
        )
    for dc in d_list:
        cfg_lines.append(f"{dc.index},{dc.name},{dc.phase},{dc.ccbm},{int(dc.normal_state)}")
    cfg_lines.append(f"{freq:.6g}")
    cfg_lines.append(str(nrates_hdr))
    for samp_hz, end_s in rates:
        cfg_lines.append(f"{samp_hz:.12g},{int(end_s)}")
    cfg_lines.append(start_time)
    cfg_lines.append(trigger_time)
    cfg_lines.append(fmt_u)
    cfg_lines.append(f"{timemult:.12g}")
    if rev_year >= 2013:
        cfg_lines.append("0,0")
        cfg_lines.append("0,0")
    cfg_path.write_text("\r\n".join(cfg_lines) + "\r\n", encoding="utf-8")

    # Write .dat
    ts_us = np.round((time_arr - time_arr[0]) / (1e-6 * float(timemult))).astype(np.int64)
    if fmt_u == "ASCII":
        out_lines: list[str] = []
        for i in range(n_samples):
            row = [str(i + 1), str(int(ts_us[i]))]
            for k in range(n_analog):
                v = raw_enc[k, i]
                row.append(str(int(round(v))) if np.isfinite(v) else "")
            for j in range(n_digital):
                row.append(str(int(digital_mat[j, i])))
            out_lines.append(",".join(row))
        dat_path.write_text("\r\n".join(out_lines) + "\r\n", encoding="utf-8")
    else:
        n_dwords = (n_digital + 15) // 16
        analog_dt = {"BINARY": "<i2", "BINARY32": "<i4", "FLOAT32": "<f4"}[fmt_u]
        fields: list[tuple[str, Any]] = [("n", "<u4"), ("ts", "<u4")]
        if n_analog > 0:
            fields.append(("a", analog_dt, (n_analog,)))
        if n_dwords > 0:
            fields.append(("d", "<u2", (n_dwords,)))
        buf = np.zeros(n_samples, dtype=np.dtype(fields, align=False))
        buf["n"] = np.arange(1, n_samples + 1, dtype=np.uint32)
        buf["ts"] = np.clip(ts_us, 0, 0xFFFFFFFE).astype(np.uint32)
        if n_analog > 0:
            if fmt_u == "FLOAT32":
                vals_t = raw_enc.T.astype(np.float32)
            elif fmt_u == "BINARY":
                vals_t = np.where(np.isfinite(raw_enc.T), np.round(raw_enc.T), _MISSING_INT16).astype(np.int16)
            else:
                vals_t = np.where(np.isfinite(raw_enc.T), np.round(raw_enc.T), _MISSING_INT32).astype(np.int32)
            buf["a"] = vals_t
        if n_dwords > 0:
            words = np.zeros((n_samples, n_dwords), dtype=np.uint16)
            for j in range(n_digital):
                words[:, j // 16] |= (digital_mat[j].astype(np.uint16) & 1) << (j % 16)
            buf["d"] = words
        dat_path.write_bytes(buf.tobytes())

    return cfg_path, dat_path


# ---------------------------------------------------------------------------
# Automatic & custom 3-phase channel mapping
# ---------------------------------------------------------------------------
def _resolve_channel_index(record: ComtradeRecord, key: str | int) -> int:
    """Resolve a 0-based index, `'#An'` 1-based string, or channel name (case-insensitive)."""
    if isinstance(key, (int, np.integer)):
        idx = int(key)
        if not (0 <= idx < record.n_analog):
            raise IndexError(f"Analog channel index {idx} out of range (0..{record.n_analog - 1})")
        return idx
    s = str(key).strip()
    if s.startswith("#") and s[1:].isdigit():
        an = int(s[1:])
        for i, ch in enumerate(record.analog_channels):
            if ch.index == an:
                return i
        raise KeyError(f"Analog channel number {s!r} not found")
    sl = s.lower()
    for i, ch in enumerate(record.analog_channels):
        if ch.name.strip().lower() == sl:
            return i
    raise KeyError(f"Analog channel {key!r} not found in {record.analog_names}")


def _classify_quantity(ch: AnalogChannel) -> str:
    """Return `'I'` (current), `'V'` (voltage), or `''`."""
    base_u, _ = ch.unit_scale_si()
    if base_u == "A":
        return "I"
    if base_u == "V":
        return "V"
    nm = ch.name.strip().upper()
    if re.search(r"(^|[\s_\-])(I[ABCNG0-3RSLT]|CURR|AMP)", nm):
        return "I"
    if re.search(r"(^|[\s_\-])([VU][ABCN0-3RSLT]|VOLT)", nm):
        return "V"
    return ""


def _is_line_to_line(ch: AnalogChannel) -> bool:
    """True for phase-to-phase voltage channels like VAB, VBC, VCA, U12."""
    ph = ch.phase.strip().upper()
    if ph in ("AB", "BC", "CA", "BA", "CB", "AC", "12", "23", "31", "RS", "ST", "TR"):
        return True
    nm = ch.name.strip().upper()
    return bool(re.search(r"(^|[\s_\-])([VU][_\-]?(AB|BC|CA|12|23|31|RS|ST|TR))($|[\s_\-])", nm))


def _phase_candidates(ch: AnalogChannel, qty: str) -> list[tuple[str, int]]:
    """Return scored `(phase_tag, score)` pairs where `phase_tag` in `{'a','b','c','n'}`."""
    ph = ch.phase.strip().upper()
    nm = ch.name.strip().upper()
    out: list[tuple[str, int]] = []

    if qty == "V" and _is_line_to_line(ch):
        return out

    # 1) Explicit neutral/ground/residual indicators
    if ph in ("N", "G", "0", "NG", "RES"):
        out.append(("n", 95))
    if re.search(r"(^|[\s_\-])(3?I[_\-]?(N|G|0|O|RES|GND)|IN|IG|I0|IRES|NEUT|RESID)($|[\s_\-])", nm):
        out.append(("n", 90))

    # 2) Explicit A/B/C, R/S/T, L1/L2/L3 from `phase` header
    ph_map = {
        "A": "a", "AN": "a", "R": "a", "L1": "a", "PH A": "a",
        "B": "b", "BN": "b", "S": "b", "L2": "b", "PH B": "b",
        "C": "c", "CN": "c", "T": "c", "L3": "c", "PH C": "c",
    }
    if ph in ph_map:
        out.append((ph_map[ph], 100))
    elif ph in ("1", "2", "3"):
        out.append(({"1": "a", "2": "b", "3": "c"}[ph], 60))

    # 3) Explicit tokens in channel name
    prefix = r"I" if qty == "I" else (r"[VU]" if qty == "V" else r"[IVU]")
    for tag, pat in (
        ("a", rf"(^|[\s_\-]){prefix}[_\-]?(A|AN|R|L1)($|[\s_\-0-9])"),
        ("b", rf"(^|[\s_\-]){prefix}[_\-]?(B|BN|S|L2)($|[\s_\-0-9])"),
        ("c", rf"(^|[\s_\-]){prefix}[_\-]?(C|CN|T|L3)($|[\s_\-0-9])"),
    ):
        if re.search(pat, nm):
            out.append((tag, 85))
    for tag, word in (("a", "A|AN|L1"), ("b", "B|BN|L2"), ("c", "C|CN|L3")):
        if re.search(rf"(PH(?:ASE)?[\s_\-]*({word})|[\s_\-]({word}))($|[\s_\-])", nm):
            out.append((tag, 70))

    # Numeric 1/2/3 suffix (lower score so A/B/C wins over sequence I1/I2)
    for tag, num in (("a", "1"), ("b", "2"), ("c", "3")):
        if re.search(rf"(^|[\s_\-]){prefix}[_\-]?{num}($|[\s_\-])", nm):
            out.append((tag, 45))

    return out


def map_channels(
    record: ComtradeRecord,
    channel_map: dict[str, str | int] | None = None,
) -> dict[str, int]:
    """Map canonical keys (`Ia/Ib/Ic`, `Va/Vb/Vc`, optional `In`) to 0-based analog indices.

    Auto-detects standard relay/recloser naming conventions, then applies any explicit
    overrides from `channel_map` (channel name, 0-based int, or `'#An'` 1-based string).
    """
    best: dict[str, tuple[int, int]] = {}  # canonical -> (score, idx)
    qty_by_idx = [_classify_quantity(ch) for ch in record.analog_channels]

    # Check if numeric 1/2/3 forms a complete 3-phase triplet per quantity (vs sequence I1/I2 only).
    num_phases: dict[str, set[str]] = {"I": set(), "V": set()}
    for ch, qty in zip(record.analog_channels, qty_by_idx):
        if not qty:
            continue
        for tag, score in _phase_candidates(ch, qty):
            if score in (45, 60):
                num_phases[qty].add(tag)

    for idx, (ch, qty) in enumerate(zip(record.analog_channels, qty_by_idx)):
        if qty not in ("I", "V"):
            continue
        for tag, score in _phase_candidates(ch, qty):
            if tag == "n":
                if qty != "I":
                    continue
                canon = "In"
            else:
                if score in (45, 60) and num_phases[qty] != {"a", "b", "c"}:
                    continue
                canon = f"{qty}{tag}"
            prev = best.get(canon)
            if prev is None or score > prev[0]:
                best[canon] = (score, idx)

    resolved: dict[str, int] = {k: idx for k, (_, idx) in best.items()}

    if channel_map:
        for canon, ref in channel_map.items():
            if ref is None:
                resolved.pop(canon, None)
                continue
            resolved[canon] = _resolve_channel_index(record, ref)

    return resolved


def load_channel_map(path: Path | str) -> dict[str, Any]:
    """Load a JSON channel map (flat `{Ia: ...}` or per-device `{Sw1: {Ia: ...}}`)."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Channel map JSON must be an object, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Fundamental-frequency phasor extraction (full-cycle DFT)
# ---------------------------------------------------------------------------
def extract_cycle_phasor(
    samples: np.ndarray,
    time: np.ndarray,
    freq: float,
    t_start: float,
    *,
    skew_us: float = 0.0,
    n_cycles: int = 1,
) -> complex:
    """Full-cycle DFT RMS phasor over `[t_start, t_start + n_cycles / freq)`.

    Uses global record time `t_eff = time + skew_us * 1e-6` so pre-fault and
    post-fault phasors share an exact phase reference across arbitrary window
    offsets and multi-rate segments:
        x(t) = Re{ sqrt(2) * X * exp(j * 2*pi*freq * t) }.
    """
    y = np.asarray(samples, dtype=np.float64)
    t = np.asarray(time, dtype=np.float64) + float(skew_us) * 1e-6
    period = 1.0 / float(freq)
    dur = float(n_cycles) * period
    t_end = float(t_start) + dur

    # Select window samples (inclusive left, half-open right with small tolerance).
    eps = 1e-9
    mask = (t >= t_start - eps) & (t < t_end - eps)
    tw, yw = t[mask], y[mask]
    finite = np.isfinite(yw)
    tw, yw = tw[finite], yw[finite]
    if len(tw) < 3:
        raise ValueError(f"Not enough valid samples in [{t_start:.6f}, {t_end:.6f}] s (got {len(tw)})")

    dts = np.diff(tw)
    dt0 = float(dts[0])
    is_uniform = len(dts) > 0 and np.allclose(dts, dt0, rtol=1e-4, atol=1e-9)
    n_exact = dur / dt0 if dt0 > 0 else 0.0
    is_int_cycle = is_uniform and abs(n_exact - round(n_exact)) < 1e-3 and len(tw) == int(round(n_exact))

    if is_int_cycle:
        basis = np.exp(-1j * 2.0 * math.pi * float(freq) * tw)
        return complex((math.sqrt(2.0) / len(tw)) * np.dot(yw, basis))

    # Non-integer samples/cycle or multi-rate window: cubic resample onto exact uniform cycle grid.
    pad_mask = (t >= t_start - 2.0 * dt0) & (t <= t_end + 2.0 * dt0) & np.isfinite(y)
    tp, yp = t[pad_mask], y[pad_mask]
    # Remove duplicate timestamps if any exist at rate boundaries.
    _, uniq = np.unique(tp, return_index=True)
    tp, yp = tp[uniq], yp[uniq]
    n_grid = max(32, int(round(max(n_exact, 32.0))))
    t_u = t_start + np.arange(n_grid, dtype=np.float64) * (dur / n_grid)
    if len(tp) >= 4 and tp[0] <= t_u[0] + eps and tp[-1] >= t_u[-1] - eps:
        y_u = CubicSpline(tp, yp)(t_u)
    else:
        y_u = np.interp(t_u, tp, yp)
    basis = np.exp(-1j * 2.0 * math.pi * float(freq) * t_u)
    return complex((math.sqrt(2.0) / n_grid) * np.dot(y_u, basis))


def detect_event_time(
    record: ComtradeRecord,
    ch_map: dict[str, int],
) -> tuple[float, str]:
    """Locate event onset time (seconds from `record.time[0]`).

    Uses the COMTRADE trigger timestamp when it lies cleanly inside the record
    (at least one cycle from both ends); otherwise detects the largest cycle-to-cycle
    RMS step across mapped current (or voltage) channels.
    """
    period = 1.0 / float(record.frequency)
    t0, t1 = float(record.time[0]), float(record.time[-1])
    trig = record.trigger_offset_s
    if trig is not None and (t0 + period - 1e-9) <= trig <= (t1 - period + 1e-9):
        return float(trig), "trigger"

    keys = [k for k in ("Ia", "Ib", "Ic") if k in ch_map] or [k for k in ("Va", "Vb", "Vc") if k in ch_map]
    if keys and (t1 - t0) >= 2.5 * period:
        step = 0.25 * period
        centers = np.arange(t0 + 0.5 * period, t1 - 0.5 * period, step)
        if len(centers) >= 4:
            rms_sq = np.zeros(len(centers), dtype=np.float64)
            for k in keys:
                sig = record.get_analog(ch_map[k], si=True)
                for ci, tc in enumerate(centers):
                    m = (record.time >= tc - 0.5 * period) & (record.time < tc + 0.5 * period)
                    seg = sig[m]
                    seg = seg[np.isfinite(seg)]
                    if len(seg):
                        rms_sq[ci] += float(np.mean(seg * seg))
            rms = np.sqrt(rms_sq)
            diff = np.abs(np.diff(rms))
            if float(np.max(diff)) > 1e-6 * max(float(np.max(rms)), 1.0):
                best_i = int(np.argmax(diff))
                t_ev = float(np.clip(centers[best_i], t0 + period, t1 - period))
                return t_ev, "auto_step"

    return 0.5 * (t0 + t1), "midpoint"


def _choose_windows(
    t0: float,
    t1: float,
    t_ev: float,
    period: float,
    *,
    pre_window: tuple[float, float] | None = None,
    post_window: tuple[float, float] | None = None,
    pre_margin_cycles: float = 0.5,
    post_delay_cycles: float = 1.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Select 1-cycle pre-fault and post-fault DFT windows inside `[t0, t1]`."""
    if pre_window is not None:
        pre_w = (float(pre_window[0]), float(pre_window[1]))
    else:
        avail_pre = t_ev - t0
        if avail_pre >= (1.0 + pre_margin_cycles) * period:
            pre_end = t_ev - pre_margin_cycles * period
        else:
            pre_end = max(t0 + period, min(t_ev, t1))
        pre_start = max(t0, pre_end - period)
        pre_w = (pre_start, pre_start + period)

    if post_window is not None:
        post_w = (float(post_window[0]), float(post_window[1]))
    else:
        avail_post = t1 - t_ev
        if avail_post >= (1.0 + post_delay_cycles) * period:
            post_start = t_ev + post_delay_cycles * period
        else:
            post_start = max(t0, min(t_ev, t1 - period))
        post_w = (post_start, post_start + period)

    return pre_w, post_w


def extract_device_phasors(
    record: ComtradeRecord,
    *,
    channel_map: dict[str, str | int] | None = None,
    v_base_ln: float | None = None,
    v_base_kv: float | None = None,
    event_time_s: float | None = None,
    pre_window: tuple[float, float] | None = None,
    post_window: tuple[float, float] | None = None,
    pre_margin_cycles: float = 0.5,
    post_delay_cycles: float = 1.0,
) -> dict[str, Any]:
    """Extract pre-fault and post-fault 3-phase RMS phasors matching `shf.feeder.device_measurement`.

    Currents are returned in primary Amperes RMS; voltages are returned in per-unit
    (using `v_base_ln` in V, `v_base_kv * 1000 / sqrt(3)`, `'pu'` units, or
    auto-estimated from pre-fault energized phase voltages when unspecified).
    """
    ch_map = map_channels(record, channel_map)
    period = 1.0 / float(record.frequency)
    t0, t1 = float(record.time[0]), float(record.time[-1])
    if event_time_s is not None:
        t_ev, onset_source = float(event_time_s), "explicit"
    else:
        t_ev, onset_source = detect_event_time(record, ch_map)

    pre_w, post_w = _choose_windows(
        t0, t1, t_ev, period,
        pre_window=pre_window,
        post_window=post_window,
        pre_margin_cycles=pre_margin_cycles,
        post_delay_cycles=post_delay_cycles,
    )
    pre_ncycles = max(1, int(round((pre_w[1] - pre_w[0]) / period)))
    post_ncycles = max(1, int(round((post_w[1] - post_w[0]) / period)))

    def _phasors_for(t_start: float, n_cyc: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
        i_vec = np.zeros(3, dtype=np.complex128)
        v_vec = np.zeros(3, dtype=np.complex128)
        pres_i = np.zeros(3, dtype=bool)
        pres_v = np.zeros(3, dtype=bool)
        v_units: list[str] = []
        for k, ph in enumerate("abc"):
            ik = f"I{ph}"
            if ik in ch_map:
                ci = ch_map[ik]
                ch = record.analog_channels[ci]
                sig = record.get_analog(ci, si=True)
                i_vec[k] = extract_cycle_phasor(
                    sig, record.time, record.frequency, t_start, skew_us=ch.skew, n_cycles=n_cyc
                )
                pres_i[k] = True
            vk = f"V{ph}"
            if vk in ch_map:
                ci = ch_map[vk]
                ch = record.analog_channels[ci]
                base_u, _ = ch.unit_scale_si()
                v_units.append(base_u)
                sig = record.get_analog(ci, si=True)
                v_vec[k] = extract_cycle_phasor(
                    sig, record.time, record.frequency, t_start, skew_us=ch.skew, n_cycles=n_cyc
                )
                pres_v[k] = True
        return i_vec, v_vec, pres_i, pres_v, v_units

    i_pre, v_pre_raw, pres_i, pres_v, v_units = _phasors_for(pre_w[0], pre_ncycles)
    i_post, v_post_raw, _, _, _ = _phasors_for(post_w[0], post_ncycles)

    # Convert voltage phasors to per-unit (matching OpenDSS `PuVoltage()`).
    v_base_source = "missing"
    v_base_used: float | None = None
    if np.any(pres_v):
        if v_base_ln is not None:
            v_base_used = float(v_base_ln)
            v_base_source = "explicit_v_base_ln"
        elif v_base_kv is not None:
            v_base_used = float(v_base_kv) * 1000.0 / math.sqrt(3.0)
            v_base_source = "explicit_v_base_kv"
        elif v_units and all(u == "pu" for u in v_units):
            v_base_used = 1.0
            v_base_source = "channel_unit_pu"
        else:
            mags = np.abs(v_pre_raw[pres_v])
            nz = mags[mags > 1e-6]
            if len(nz):
                v_base_used = float(np.median(nz))
                v_base_source = "auto_prefault_median"
            else:
                v_base_used = 1.0
                v_base_source = "fallback_unity"
        v_pre = v_pre_raw / v_base_used
        v_post = v_post_raw / v_base_used
    else:
        v_pre = np.zeros(3, dtype=np.complex128)
        v_post = np.zeros(3, dtype=np.complex128)

    def _pack(i_arr: np.ndarray, v_arr: np.ndarray) -> dict[str, Any]:
        ia, ib, ic = i_arr[0], i_arr[1], i_arr[2]
        return {
            "i": i_arr,
            "v": v_arr,
            "i0": (ia + ib + ic) / 3.0,
            "i2": (ia + A_OP * A_OP * ib + A_OP * ic) / 3.0,
        }

    return {
        "pre": _pack(i_pre, v_pre),
        "post": _pack(i_post, v_post),
        "present_i": pres_i,
        "present_v": pres_v,
        "v_base_ln_v": v_base_used,
        "v_base_source": v_base_source,
        "event_time_s": t_ev,
        "onset_source": onset_source,
        "pre_window_s": pre_w,
        "post_window_s": post_w,
        "channel_map": ch_map,
        "frequency_hz": float(record.frequency),
        "sample_rate_hz": float(record.sample_rate_hz(t_ev)),
    }


# ---------------------------------------------------------------------------
# Feature converters: (1) Tier-2 shf.model, (2) shf.transfer / shf.active_grid, (3) Tier-1 HIF
# ---------------------------------------------------------------------------
def to_tier2_features(
    pre_by_device: dict[str, dict[str, Any]],
    post_by_device: dict[str, dict[str, Any]],
    *,
    devices: list[str] | tuple[str, ...] | None = None,
    kind: str = "full",
    present_by_device: dict[str, dict[str, np.ndarray]] | None = None,
) -> tuple[dict[str, float], np.ndarray, list[str]]:
    """Build Tier-2 `shf.model` features (15/device for `full`, 7/device for `magnitude`).

    Exact formula parity with `shf/faults.py:features` and exact column order of
    `shf/model.py:feature_columns`. Missing devices (or unmapped voltage/current
    channels) are filled with `np.nan`, matching `shf/model.py:sensor_dropout`.
    """
    dev_list = list(devices) if devices is not None else list(DEFAULT_DEVICES)
    if kind == "full":
        keys = TIER2_DEVICE_KEYS_FULL
    elif kind == "magnitude":
        keys = TIER2_DEVICE_KEYS_MAG
    else:
        raise ValueError(f"kind must be 'full' or 'magnitude', got {kind!r}")

    row: dict[str, float] = {}
    cols: list[str] = []
    for d in dev_list:
        dev_cols = [f"{d}_{k}" for k in keys]
        cols.extend(dev_cols)
        if d not in post_by_device or d not in pre_by_device:
            for c in dev_cols:
                row[c] = float("nan")
            continue

        m, p = post_by_device[d], pre_by_device[d]
        pres = (present_by_device or {}).get(d, {})
        has_i = pres.get("present_i", np.ones(3, dtype=bool))
        has_v = pres.get("present_v", np.ones(3, dtype=bool))
        any_i = bool(np.any(has_i))

        vals: dict[str, float] = {}
        for k, ph in enumerate("abc"):
            vals[f"I{ph}"] = float(abs(m["i"][k])) if has_i[k] else float("nan")
            vals[f"dI{ph}"] = float(abs(m["i"][k] - p["i"][k])) if has_i[k] else float("nan")
            vals[f"V{ph}"] = float(abs(m["v"][k])) if has_v[k] else float("nan")
            vals[f"dV{ph}"] = float(abs(m["v"][k]) - abs(p["v"][k])) if has_v[k] else float("nan")
        vals["I0"] = float(abs(m["i0"])) if any_i else float("nan")
        vals["dI0"] = float(abs(m["i0"] - p["i0"])) if any_i else float("nan")
        vals["dI2"] = float(abs(m["i2"] - p["i2"])) if any_i else float("nan")

        for k in keys:
            row[f"{d}_{k}"] = vals[k]

    vec = np.array([row[c] for c in cols], dtype=np.float64)
    return row, vec, cols


def _default_grid_spec(devices: list[str]) -> tuple[list[str], dict[str, str | None], dict[str, float]]:
    """Fallback radial chain spec when no OpenDSS `Grid` is provided (standalone COMTRADE)."""
    devs = list(devices)
    parent: dict[str, str | None] = {devs[0]: None}
    for i in range(1, len(devs)):
        parent[devs[i]] = devs[0]
    kw = {d: 100.0 for d in devs}
    return devs, parent, kw


def _grid_structure(devices: list[str], parent: dict[str, str | None], kw: dict[str, float]) -> np.ndarray:
    """Exact parity with `shf/transfer.py:structure`."""
    total = sum(kw.values()) or 1.0

    def _depth(d: str) -> int:
        n, cur = 0, d
        while parent.get(cur) is not None:
            cur = parent[cur]  # type: ignore[assignment]
            n += 1
        return n

    def _subtree(d: str) -> list[str]:
        out, stack = [], [d]
        while stack:
            z = stack.pop()
            out.append(z)
            stack.extend(c for c in devices if parent.get(c) == z)
        return out

    rows = []
    for d in devices:
        kids = [c for c in devices if parent.get(c) == d]
        rows.append([
            _depth(d),
            len(kids),
            sum(kw.get(z, 0.0) for z in _subtree(d)) / total,
            kw.get(d, 0.0) / total,
        ])
    return np.array(rows, dtype=float)


def to_transfer_features(
    pre_by_device: dict[str, dict[str, Any]],
    post_by_device: dict[str, dict[str, Any]],
    *,
    grid: Any | None = None,
    struct: np.ndarray | None = None,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Build `(N, 21)` float32 node features matching `shf/transfer.py:node_features`.

    Missing devices have live electrical columns `0..16` set to `NaN` (matching
    `shf/transfer_models.py:blank_sensor`) while keeping tree structure `17..20`.
    Returns `(X_nodes, devices, parent_idx)`.
    """
    if grid is not None:
        devs = list(grid.devices)
        parent = dict(grid.parent)
        kw = dict(grid.kw)
    else:
        devs, parent, kw = _default_grid_spec(list(post_by_device.keys()))

    if struct is None:
        struct = _grid_structure(devs, parent, kw)

    idx_map = {d: i for i, d in enumerate(devs)}
    parent_idx = np.array([idx_map[parent[d]] if parent.get(d) else -1 for d in devs], dtype=np.int64)

    head = devs[0]
    if head in pre_by_device:
        head_max = float(np.abs(pre_by_device[head]["i"]).max())
    else:
        head_max = max((float(np.abs(pre_by_device[d]["i"]).max()) for d in devs if d in pre_by_device), default=1e-6)
    floor = 0.05 * max(head_max, 1e-6)

    out = np.full((len(devs), len(TRANSFER_FEATURES)), np.nan, dtype=np.float32)
    for k, d in enumerate(devs):
        out[k, N_TRANSFER_ELEC:] = struct[k]
        if d not in pre_by_device or d not in post_by_device:
            continue
        m, p = post_by_device[d], pre_by_device[d]
        base = max(float(np.abs(p["i"]).max()), floor)
        has = np.abs(p["v"]) > 0.1
        row = list(np.log1p(np.abs(m["i"] - p["i"]) / base)) + list(np.log1p(np.abs(m["i"]) / base))
        row += [float(np.log1p(abs(m["i0"] - p["i0"]) / base)), float(np.log1p(abs(m["i2"] - p["i2"]) / base))]
        row += list(np.abs(m["v"]) * has) + list((np.abs(m["v"]) - np.abs(p["v"])) * has) + list(has.astype(float))
        out[k, :N_TRANSFER_ELEC] = row

    return out, devs, parent_idx


def _phase_cos(v: np.ndarray, i: np.ndarray, has: np.ndarray) -> float:
    """Exact parity with `shf/active_grid.py:_phase_cos`."""
    vals = []
    for k in range(3):
        if has[k] and abs(v[k]) > 1e-6 and abs(i[k]) > 1e-4:
            vals.append(float(np.real(v[k] * np.conj(i[k])) / (abs(v[k]) * abs(i[k]))))
    return float(np.mean(vals)) if vals else 0.0


def to_active_grid_features(
    pre_by_device: dict[str, dict[str, Any]],
    post_by_device: dict[str, dict[str, Any]],
    *,
    grid: Any | None = None,
    topo: Any | None = None,
    adj: np.ndarray | None = None,
    der_kw_by_zone: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Build `(N, 26)` float32 node features matching `shf/active_grid.py:active_node_features`.

    Missing devices have live electrical columns `0..20` set to `NaN` (matching
    `shf/active_models.py:blank_active_sensor`) while keeping grid state `21..25`.
    Returns `(X_nodes, devices, adj_matrix)`.
    """
    if grid is not None:
        devs = list(grid.devices)
        parent = dict(grid.parent)
        kw = dict(grid.kw)
    else:
        devs, parent, kw = _default_grid_spec(list(post_by_device.keys()))

    open_devices = tuple(getattr(topo, "open_devices", ())) if topo is not None else ()
    extra_sources = tuple(getattr(topo, "extra_source_zones", ())) if topo is not None else ()
    tie_links = tuple(getattr(topo, "tie_zone_links", ())) if topo is not None else ()
    der_map = dict(der_kw_by_zone or {})

    n = len(devs)
    idx_map = {d: i for i, d in enumerate(devs)}
    if adj is None:
        adj_mat = np.zeros((n, n), dtype=np.float32)
        for d in devs:
            p_dev = parent.get(d)
            if p_dev is not None and d not in open_devices and p_dev in idx_map:
                u, v = idx_map[p_dev], idx_map[d]
                adj_mat[u, v] = adj_mat[v, u] = 1.0
        for a, b in tie_links:
            if a in idx_map and b in idx_map:
                u, v = idx_map[a], idx_map[b]
                adj_mat[u, v] = adj_mat[v, u] = 1.0
    else:
        adj_mat = np.asarray(adj, dtype=np.float32)

    source_devs = [devs[0], *extra_sources]
    head_max = max((float(np.abs(pre_by_device[d]["i"]).max()) for d in source_devs if d in pre_by_device), default=0.0)
    if head_max <= 0.0:
        head_max = max((float(np.abs(pre_by_device[d]["i"]).max()) for d in devs if d in pre_by_device), default=1e-6)
    floor = 0.05 * max(head_max, 1e-6)
    total_kw = sum(kw.values()) or 1.0
    deg = adj_mat.sum(axis=1)

    out = np.full((n, len(ACTIVE_FEATURES)), np.nan, dtype=np.float32)
    for k, d in enumerate(devs):
        is_closed = 0.0 if d in open_devices else 1.0
        share_own = kw.get(d, 0.0) / total_kw
        der_ratio = min(der_map.get(d, 0.0) / max(kw.get(d, 0.0), 20.0), 3.0)
        is_src = 1.0 if (k == 0 or d in extra_sources) else 0.0
        out[k, N_ACTIVE_ELEC:] = [is_closed, float(deg[k]), float(share_own), float(der_ratio), is_src]

        if d not in pre_by_device or d not in post_by_device:
            continue
        m, p = post_by_device[d], pre_by_device[d]
        base = max(float(np.abs(p["i"]).max()), floor)
        has = np.abs(p["v"]) > 0.1
        di_vec = m["i"] - p["i"]

        cos_post = _phase_cos(m["v"], m["i"], has)
        cos_pre = _phase_cos(p["v"], p["i"], has)
        dom = int(np.argmax(np.abs(di_vec)))
        if has[dom] and abs(p["v"][dom]) > 1e-6 and abs(di_vec[dom]) > 1e-4:
            cos_di = float(np.real(p["v"][dom] * np.conj(di_vec[dom])) / (abs(p["v"][dom]) * abs(di_vec[dom])))
        else:
            cos_di = 0.0
        power_rev = 1.0 if (cos_pre * cos_post < -0.05) else 0.0

        row = list(np.log1p(np.abs(di_vec) / base)) + list(np.log1p(np.abs(m["i"]) / base))
        row += [float(np.log1p(abs(m["i0"] - p["i0"]) / base)), float(np.log1p(abs(m["i2"] - p["i2"]) / base))]
        row += list(np.abs(m["v"]) * has) + list((np.abs(m["v"]) - np.abs(p["v"])) * has) + list(has.astype(float))
        row += [cos_post, cos_pre, cos_di, power_rev]
        out[k, :N_ACTIVE_ELEC] = row

    return out, devs, adj_mat


def to_hif_edge_features(
    record: ComtradeRecord,
    *,
    channel_map: dict[str, str | int] | None = None,
    residual_channel: str | int | None = None,
    model: hif_edge.EdgeModel | None = None,
    start_cycle: int | None = None,
    min_samples_per_cycle: int = MIN_HIF_SAMPLES_PER_CYCLE,
) -> dict[str, Any]:
    """Optional bridge from high-rate COMTRADE residual current to Tier-1 `shf.hif_edge` 16 features.

    Clearly reports `ok=False` and `reason` whenever `fs` is too low to resolve
    harmonics up to the 6th (`fs < min_samples_per_cycle * freq`), when no residual/
    3-phase current channels exist, or when the record has fewer than `K = 8` cycles.
    """
    fs_hz = float(record.sample_rate_hz())
    min_fs_hz = float(min_samples_per_cycle) * float(record.frequency)
    warnings: list[str] = []

    def _fail(reason: str) -> dict[str, Any]:
        return {
            "ok": False,
            "reason": reason,
            "fs_hz": fs_hz,
            "min_fs_hz": min_fs_hz,
            "recommended_fs_hz": RECOMMENDED_HIF_FS_HZ,
            "frequency_hz": float(record.frequency),
            "residual_source": None,
            "n_cycles": 0,
            "features": np.empty((0, len(hif_edge.FEATURES)), dtype=np.float32),
            "feature_names": list(hif_edge.FEATURES),
            "end_cycles": np.empty((0,), dtype=np.int16),
            "p_hif": None,
            "hif_alarm": None,
            "warnings": warnings,
        }

    if fs_hz < min_fs_hz - 1e-6:
        return _fail(
            f"Sampling rate too low for Tier-1 HIF features: fs={fs_hz:.1f} Hz < "
            f"minimum {min_fs_hz:.1f} Hz ({min_samples_per_cycle} samples/cycle at {record.frequency:g} Hz)."
        )

    ch_map = map_channels(record, channel_map)
    if residual_channel is not None:
        i_res = record.get_analog(residual_channel, si=True)
        res_source = f"explicit:{residual_channel}"
    elif "In" in ch_map:
        i_res = record.get_analog(ch_map["In"], si=True)
        res_source = f"In:{record.analog_channels[ch_map['In']].name}"
    elif all(k in ch_map for k in ("Ia", "Ib", "Ic")):
        i_res = (
            record.get_analog(ch_map["Ia"], si=True)
            + record.get_analog(ch_map["Ib"], si=True)
            + record.get_analog(ch_map["Ic"], si=True)
        )
        res_source = "sum_abc"
    else:
        return _fail("No residual channel (In) and incomplete 3-phase currents (Ia/Ib/Ic) to form I_res.")

    finite = np.isfinite(i_res) & np.isfinite(record.time)
    if int(np.sum(finite)) < 4:
        return _fail("Residual current channel contains insufficient finite samples.")

    t_valid, y_valid = record.time[finite], i_res[finite]
    _, uniq = np.unique(t_valid, return_index=True)
    t_valid, y_valid = t_valid[uniq], y_valid[uniq]

    period = 1.0 / float(record.frequency)
    dts = np.diff(t_valid)
    dt_med = float(np.median(dts[dts > 0])) if np.any(dts > 0) else (1.0 / fs_hz)
    # N uniform samples at step dt cover a duration of N * dt = (t[-1] - t[0]) + dt.
    n_cycles = int(math.floor((float(t_valid[-1]) - float(t_valid[0]) + dt_med) / period + 1e-9))
    if n_cycles < hif_edge.K:
        return _fail(
            f"Record duration too short for Tier-1 HIF window: {n_cycles} whole cycles < K={hif_edge.K} cycles."
        )

    if fs_hz < RECOMMENDED_HIF_FS_HZ - 1e-6:
        warnings.append(
            f"fs={fs_hz:.1f} Hz is below Tier-1 front-end Nyquist ({RECOMMENDED_HIF_FS_HZ:.0f} Hz); "
            "high-frequency interharmonic energy above fs/2 is absent."
        )
    if abs(float(record.frequency) - hif_edge.F_LINE) > 0.5:
        warnings.append(
            f"Record frequency is {record.frequency:g} Hz while frozen Tier-1 model_int8.npz was trained at 60 Hz "
            "(resampled to 256 samples/cycle for harmonic ratio alignment)."
        )

    # Use samples directly when already uniform at exact 256 samples/cycle; else cubic resample.
    n_target = n_cycles * hif_edge.N_CYCLE
    dt_target = period / hif_edge.N_CYCLE
    is_exact_grid = (
        len(t_valid) >= n_target
        and len(dts) > 0
        and np.allclose(dts[: n_target - 1], dt_target, rtol=1e-4, atol=1e-9)
    )
    if is_exact_grid:
        amps_256 = y_valid[:n_target]
    else:
        t_grid = float(t_valid[0]) + np.arange(n_target, dtype=np.float64) * dt_target
        t_grid = np.clip(t_grid, float(t_valid[0]), float(t_valid[-1]))
        amps_256 = CubicSpline(t_valid, y_valid)(t_grid)
    X_win, ends = hif_edge.window_features(amps_256)

    p_hif: float | None = None
    hif_alarm: float | None = None
    if model is not None and len(X_win) > 0:
        probs = hif_edge.predict_q(model.layers, X_win)
        p_hif = hif_edge.persisted_score(probs, ends=ends, start_cycle=start_cycle)
        hif_alarm = 1.0 if p_hif > model.threshold else 0.0

    return {
        "ok": True,
        "reason": "",
        "fs_hz": fs_hz,
        "min_fs_hz": min_fs_hz,
        "recommended_fs_hz": RECOMMENDED_HIF_FS_HZ,
        "frequency_hz": float(record.frequency),
        "residual_source": res_source,
        "n_cycles": n_cycles,
        "features": X_win,
        "feature_names": list(hif_edge.FEATURES),
        "end_cycles": ends,
        "p_hif": p_hif,
        "hif_alarm": hif_alarm,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# End-to-end bundle helper & synthetic roundtrip generator
# ---------------------------------------------------------------------------
def synthesize_phasor_waveforms(
    pre: dict[str, Any],
    post: dict[str, Any],
    *,
    fs: float = 3840.0,
    freq: float = 60.0,
    v_base_ln: float = 4160.0 / math.sqrt(3.0),
    pre_cycles: int = 4,
    post_cycles: int = 6,
) -> tuple[dict[str, np.ndarray], float]:
    """Generate clean sinusoidal 3-phase waveforms from OpenDSS `pre`/`post` phasors (simulation only).

    Returns `(waveforms_dict, trigger_offset_s)` with primary Amperes for `Ia/Ib/Ic`
    and primary Volts for `Va/Vb/Vc`.
    """
    n_pre = int(round(pre_cycles * fs / freq))
    n_post = int(round(post_cycles * fs / freq))
    t = np.arange(n_pre + n_post, dtype=np.float64) / float(fs)
    trigger_s = n_pre / float(fs)
    w = 2.0 * math.pi * float(freq)
    exp_jwt = np.exp(1j * w * t)

    waves: dict[str, np.ndarray] = {}
    for k, ph in enumerate("abc"):
        i_pre_w = np.real(math.sqrt(2.0) * complex(pre["i"][k]) * exp_jwt[:n_pre])
        i_post_w = np.real(math.sqrt(2.0) * complex(post["i"][k]) * exp_jwt[n_pre:])
        waves[f"I{ph}"] = np.concatenate([i_pre_w, i_post_w])

        v_pre_w = np.real(math.sqrt(2.0) * complex(pre["v"][k]) * float(v_base_ln) * exp_jwt[:n_pre])
        v_post_w = np.real(math.sqrt(2.0) * complex(post["v"][k]) * float(v_base_ln) * exp_jwt[n_pre:])
        waves[f"V{ph}"] = np.concatenate([v_pre_w, v_post_w])
    return waves, trigger_s


def comtrade_to_model_inputs(
    records: ComtradeRecord | Path | str | dict[str, ComtradeRecord | Path | str],
    *,
    device_name: str = "Sw1",
    channel_maps: dict[str, Any] | None = None,
    v_base_ln: float | None = None,
    v_base_kv: float | None = None,
    grid: Any | None = None,
    topo: Any | None = None,
    adj: np.ndarray | None = None,
    der_kw_by_zone: dict[str, float] | None = None,
    devices: list[str] | tuple[str, ...] | None = None,
    tier2_kind: str = "full",
    hif_model: hif_edge.EdgeModel | None = None,
    include_hif: bool = True,
    **phasor_kwargs: Any,
) -> dict[str, Any]:
    """Convert one COMTRADE record or a `{device: record/path}` dict into all 3 model feature frames."""
    if isinstance(records, dict):
        rec_map = {
            dev: (r if isinstance(r, ComtradeRecord) else read_comtrade(r))
            for dev, r in records.items()
        }
    else:
        rec = records if isinstance(records, ComtradeRecord) else read_comtrade(records)
        rec_map = {device_name: rec}

    # Support either flat channel_map `{Ia: ...}` or per-device `{Sw1: {Ia: ...}}`.
    def _cmap_for(dev: str) -> dict[str, str | int] | None:
        if not channel_maps:
            return None
        if dev in channel_maps and isinstance(channel_maps[dev], dict):
            return channel_maps[dev]
        if any(k in CANONICAL_CHANNELS for k in channel_maps):
            return channel_maps
        return None

    pre_by_dev: dict[str, dict[str, Any]] = {}
    post_by_dev: dict[str, dict[str, Any]] = {}
    pres_by_dev: dict[str, dict[str, np.ndarray]] = {}
    phasor_info: dict[str, dict[str, Any]] = {}
    hif_by_dev: dict[str, dict[str, Any]] = {}

    for dev, rec in rec_map.items():
        cm = _cmap_for(dev)
        info = extract_device_phasors(
            rec, channel_map=cm, v_base_ln=v_base_ln, v_base_kv=v_base_kv, **phasor_kwargs
        )
        pre_by_dev[dev] = info["pre"]
        post_by_dev[dev] = info["post"]
        pres_by_dev[dev] = {"present_i": info["present_i"], "present_v": info["present_v"]}
        phasor_info[dev] = info
        if include_hif:
            hif_by_dev[dev] = to_hif_edge_features(rec, channel_map=cm, model=hif_model)

    target_devs = list(devices) if devices is not None else list(DEFAULT_DEVICES)
    t2_dict, t2_vec, t2_cols = to_tier2_features(
        pre_by_dev, post_by_dev, devices=target_devs, kind=tier2_kind, present_by_device=pres_by_dev
    )
    X_tr, tr_devs, tr_parent = to_transfer_features(pre_by_dev, post_by_dev, grid=grid)
    X_ag, ag_devs, ag_adj = to_active_grid_features(
        pre_by_dev, post_by_dev, grid=grid, topo=topo, adj=adj, der_kw_by_zone=der_kw_by_zone
    )

    present_list = [d for d in target_devs if d in post_by_dev]
    missing_list = [d for d in target_devs if d not in post_by_dev]
    return {
        "devices_present": list(rec_map.keys()),
        "tier2_devices_present": present_list,
        "tier2_devices_missing": missing_list,
        "phasors": phasor_info,
        "tier2": {"features": t2_dict, "vector": t2_vec, "columns": t2_cols},
        "transfer": {
            "X": X_tr,
            "devices": tr_devs,
            "parent": tr_parent,
            "features": list(TRANSFER_FEATURES),
        },
        "active_grid": {
            "X": X_ag,
            "devices": ag_devs,
            "adj": ag_adj,
            "features": list(ACTIVE_FEATURES),
        },
        "hif_edge": hif_by_dev if include_hif else {},
    }
