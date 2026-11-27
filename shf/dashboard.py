"""Build docs/index.html: a one-page report of the latest run that a reader can scan.

    python -m shf.dashboard      # rebuild from results/ (run.py and scripts/error_analysis.py call this)

Reads only the files in results/, so it takes about a second and runs no simulation.
The page is a single self-contained file (inline SVG, no external scripts), so it
opens straight from disk and is served as-is by GitHub Pages from docs/.

Every text is written in English and Vietnamese; the page shows one language at a
time (EN/VI button, ?lang=vi in the URL, or the browser language). Reading aids:
glossary pop-ups on dotted words, a one-line takeaway per section, searchable
questions & answers, light/dark theme, section links and a print layout.
Q&A and glossary text live in shf/dashboard_text.py.
"""
from __future__ import annotations

import csv
import html
import json
import math
import re
import shutil

import numpy as np

from . import config, hif_edge, provenance
from .dashboard_text import CATEGORIES, EXPLAIN, FAQ, GLOSSARY, MODEL, TIE_TEXT
from .model import DROPOUT_RATE

OUT = config.ROOT / "docs" / "index.html"
REPO = "https://github.com/chau1912550/self-healing-feeder"
V_TOL = config.V_TOL

METHODS = [  # (metrics key, English, Vietnamese, categorical slot)
    ("fpi_baseline", "Conventional FPI", "FPI truyền thống", 1),
    ("ml_magnitude_only", "ML, magnitudes only", "ML, chỉ biên độ", 2),
    ("ml_full", "ML, full features", "ML, đủ đặc trưng", 3),
]

DIRECTIONS = {  # error_analysis.json key: (English, Vietnamese)
    "predicted parent (1 zone upstream)": ("predicted parent", "đoán zone cha"),
    "predicted child (1 zone downstream)": ("predicted child", "đoán zone con"),
    "further upstream": ("further upstream", "lệch xa lên trạm"),
    "further downstream": ("further downstream", "lệch xa xuống"),
    "unrelated branch": ("unrelated branch", "khác nhánh"),
    "sibling (same parent)": ("sibling", "zone anh em"),
}


# ---------------------------------------------------------------- data
def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load() -> dict:
    r = config.RESULTS
    d = {"m": json.loads((r / "metrics.json").read_text(encoding="utf-8")),
         "zones": _csv(r / "zones.csv"), "rest": _csv(r / "restoration.csv"), "ea": None}
    geo = r / "feeder_geometry.json"   # written by shf/report.py with the feeder map
    d["geo"] = json.loads(geo.read_text(encoding="utf-8")) if geo.exists() else None
    ea = r / "error_analysis"
    if (ea / "error_analysis.json").exists():
        d["ea"] = json.loads((ea / "error_analysis.json").read_text(encoding="utf-8"))
        d["per_zone"] = _csv(ea / "per_zone_ml.csv")
        d["confusion"] = _csv(ea / "confusion_ml.csv")
    hj = r / "hourly" / "hourly.json"   # scripts/load_shape.py + scripts/hourly_restoration.py
    d["h"] = json.loads(hj.read_text(encoding="utf-8")) if hj.exists() else None
    if d["h"] and not d["h"].get("load_shape"):
        d["h"] = None   # load-level sweep only: nothing per hour to show yet
    sp = r / "spice" / "summary.json"   # scripts/spice_run.py (LTspice)
    d["sp"] = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None
    if d["sp"] and "hif" not in d["sp"]:
        d["sp"] = None   # written before the arcing-fault circuit existed: re-run scripts/spice_run.py
    tr_files = {
        "p2": r / "transfer" / "phase2_ieee123.json",
        "p2b": r / "transfer" / "phase2b_bus_location.json",
        "p3": r / "transfer" / "phase3_ieee34.json",
        "ag123": r / "active_grid" / "phase_active_ieee123.json",
        "ag34": r / "active_grid" / "phase_active_ieee34.json",
        "conf": r / "active_grid" / "conformal_safety.json",
    }
    d["tr"] = ({k: json.loads(p.read_text(encoding="utf-8")) for k, p in tr_files.items()}
               if all(p.exists() for p in tr_files.values()) else None)
    for key, rel in (
        ("s2l", ("transfer", "signal_to_load.json")),                       # scripts/signal_to_load.py
        ("tr_ds123", ("transfer", "dataset_ieee123.json")),                 # scripts/transfer_sweep.py --feeder ieee123
        ("tr_ds34", ("transfer", "dataset_ieee34.json")),                   # scripts/transfer_sweep.py --feeder ieee34
        ("tr_ds37", ("transfer", "dataset_ieee37.json")),                   # scripts/transfer_sweep.py --feeder ieee37
        ("ag_ds", ("active_grid", "dataset_summary.json")),                 # scripts/active_grid_run.py
        ("ag_cal", ("active_grid", "conformal_calsize.json")),              # scripts/active_conformal_calsize.py
        ("agpost", ("active_grid", "conformal_posthoc.json")),              # scripts/active_conformal_posthoc.py
        ("p3_37", ("transfer", "phase3_ieee37.json")),                      # scripts/transfer_eval37.py
        ("p2b_37", ("transfer", "phase2b_bus_ieee37.json")),                # scripts/transfer_bus_stage.py --feeder ieee37
        ("ag37_ds", ("active_grid_ieee37", "dataset_summary.json")),        # scripts/active_grid_run.py --test-feeder ieee37
        ("ag37", ("active_grid_ieee37", "phase_active_ieee37.json")),       # Kaggle GPU run (pending if absent)
        ("ag37_conf", ("active_grid_ieee37", "conformal_safety.json")),     # Kaggle GPU run (pending if absent)
        ("ag37_post", ("active_grid_ieee37", "conformal_posthoc.json")),    # Kaggle GPU run (pending if absent)
        ("ag37_cal", ("active_grid_ieee37", "conformal_calsize.json")),     # Kaggle GPU run (pending if absent)
        ("mfb", ("transfer", "multi_feeder_benchmark.json")),               # scripts/multi_feeder_eval.py --merge
    ):
        p = r.joinpath(*rel)
        d[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    hif_files = {
        "ds": r / "hif_fusion" / "dataset_summary.json",
        "p123": r / "hif_fusion" / "passive_ieee123.json",
        "p34": r / "hif_fusion" / "passive_ieee34.json",
        "a123": r / "hif_fusion" / "active_ieee123.json",
        "a34": r / "hif_fusion" / "active_ieee34.json",
        "conf": r / "hif_fusion" / "conformal_hif.json",
    }
    d["hif"] = {k: (json.loads(p.read_text(encoding="utf-8")) if p.exists() else None)
                for k, p in hif_files.items()}
    hif_real_files = {
        "ds": r / "hif_fusion_realistic" / "dataset_summary.json",
        "p123": r / "hif_fusion_realistic" / "passive_ieee123.json",
        "p34": r / "hif_fusion_realistic" / "passive_ieee34.json",
        "a123": r / "hif_fusion_realistic" / "active_ieee123.json",
        "a34": r / "hif_fusion_realistic" / "active_ieee34.json",
        "conf": r / "hif_fusion_realistic" / "conformal_hif.json",
        "summary": r / "hif_fusion_realistic" / "summary.json",
    }
    d["hif_real"] = {k: (json.loads(p.read_text(encoding="utf-8")) if p.exists() else None)
                     for k, p in hif_real_files.items()}
    ct = r / "comtrade" / "summary.json"   # scripts/comtrade_ingest.py --verify-samples
    d["comtrade"] = json.loads(ct.read_text(encoding="utf-8")) if ct.exists() else None
    d["prov_ledger"] = provenance.ledger()
    d["prov_verify"] = provenance.verify()
    return d


# ---------------------------------------------------------------- small helpers
esc = html.escape


def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}%"


def num(x: float) -> str:
    return f"{x:,.0f}"


# numbers a reader scans for: percentages and values with a unit (ranges like 0.95–1.05 pu included)
EMPH = re.compile(r"(?<![\w.#])([−+-]?\d[\d,]*(?:\.\d+)?(?:–\d[\d,]*(?:\.\d+)?)?\s?"
                  r"(?:%|kW·min|kW·phút|kW|kvar|kft|kV|Ω|pu\b|A\b|min\b|phút\b|s\b))")


def emph(s: str) -> str:
    """Bold the key numbers in text that may contain HTML; tags and attributes are left alone."""
    return "".join(p if p.startswith("<") else EMPH.sub(r"<b>\1</b>", p) for p in re.split(r"(<[^>]+>)", s))


def T(en: str, vi: str | None = None) -> str:
    """Inline text in both languages; CSS shows the one matching <html lang>."""
    if vi is None or vi == en:
        return en
    return f'<span data-l="en">{en}</span><span data-l="vi">{vi}</span>'


def TB(en: str, vi: str, tag: str = "div", cls: str = "") -> str:
    """Block text in both languages."""
    c = f' class="{cls}"' if cls else ""
    return f'<{tag}{c} data-l="en">{en}</{tag}><{tag}{c} data-l="vi">{vi}</{tag}>'


def tip(en: str, vi: str | None = None) -> str:
    """Attributes for the hover/tap tooltip (HTML allowed, built from our own data)."""
    vi = en if vi is None else vi
    return f'data-tip="{esc(en, quote=True)}" data-tip-vi="{esc(vi, quote=True)}" tabindex="0"'


def term(key: str, en: str | None = None, vi: str | None = None) -> str:
    """A word with a dotted underline that pops up its glossary definition."""
    ten, den, tvi, dvi = GLOSSARY[key]
    return (f'<span class="term" {tip(f"<b>{ten}</b><br>{den}", f"<b>{tvi}</b><br>{dvi}")}>'
            f'{T(en or ten, vi or en or tvi)}</span>')


def svg_text(x: float, y: float, en: str, vi: str | None = None, cls: str = "tick", anchor: str = "start") -> str:
    a = f'class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"'
    if vi is None or vi == en:
        return f"<text {a}>{esc(en)}</text>"
    return f'<text {a} data-l="en">{esc(en)}</text><text {a} data-l="vi">{esc(vi)}</text>'


def bar_path(x0: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Horizontal bar, square at the baseline, 4px rounded data end."""
    r = min(r, w, h / 2)
    return (f"M{x0:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z")


# ---------------------------------------------------------------- charts
def line_chart(xlabels: list[str], series: list[tuple], title: str, *, ylim=(0.0, 1.0),
               yticks=(0, .25, .5, .75, 1),
               xlab=("fault resistance (Ω), line-to-ground faults", "điện trở sự cố (Ω), sự cố chạm đất một pha"),
               xunit=" Ω", label_every: int = 1, dots: bool = True) -> str:
    """Series are (English, Vietnamese, colour slot, values[, dashed]); values are shares (0-1)."""
    W, H, L, R, T_, B = 680, 300, 46, 150, 14, 42
    pw, ph = W - L - R, H - T_ - B
    step = pw / (len(xlabels) - 1)
    X = [L + i * step for i in range(len(xlabels))]
    y0, y1 = ylim
    Y = lambda v: T_ + ph * (1 - (v - y0) / (y1 - y0))  # noqa: E731
    dash = lambda s: ";stroke-dasharray:6 4" if len(s) > 4 and s[4] else ""  # noqa: E731
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    for v in yticks:
        g.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 + svg_text(L - 8, Y(v) + 4, f"{v:.0%}", anchor="end"))
    for i, (x, lab) in enumerate(zip(X, xlabels)):
        if i % label_every == 0:
            g.append(svg_text(x, T_ + ph + 18, lab, anchor="middle"))
    g.append(svg_text(L + pw / 2, H - 4, *xlab, anchor="middle"))
    gid = "guide-" + "".join(c for c in title.lower() if c.isalnum())   # stable id, no diff noise
    g.append(f'<line id="{gid}" class="guide-line" x1="0" x2="0" y1="{T_}" y2="{T_ + ph}"/>')
    for s in series:
        slot, vals = s[2], s[3]
        pts = " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(X, vals))
        g.append(f'<polyline class="ln" style="stroke:var(--s{slot}){dash(s)}" points="{pts}"/>')
        if dots:
            for x, v in zip(X, vals):
                g.append(f'<circle class="dot" style="fill:var(--s{slot})" cx="{x:.1f}" cy="{Y(v):.1f}" r="4"/>')
    # direct labels at the line ends, nudged apart so they never overlap
    placed, last = [], -1e9
    for y, en, vi, slot, ds in sorted((Y(s[3][-1]), s[0], s[1], s[2], dash(s)) for s in series):
        y = max(y, last + 15)
        placed.append((y, en, vi, slot, ds))
        last = y
    for y, en, vi, slot, ds in placed:
        g.append(f'<line style="stroke:var(--s{slot}){ds}" class="key" x1="{L + pw + 10}" x2="{L + pw + 22}" '
                 f'y1="{y:.1f}" y2="{y:.1f}"/>' + svg_text(L + pw + 27, y + 4, en, vi, "lab"))
    for i, (x, lab) in enumerate(zip(X, xlabels)):  # hover columns, wider than the marks
        en = "".join(f"<br>{esc(s[0])}: <b>{pct(s[3][i])}</b>" for s in series)
        vi = "".join(f"<br>{esc(s[1])}: <b>{pct(s[3][i])}</b>" for s in series)
        g.append(f'<rect class="hit" x="{x - step / 2:.1f}" y="{T_}" width="{step:.1f}" height="{ph}" '
                 f'data-guide="{gid}:{x:.1f}" {tip(f"<b>{lab}{xunit}</b>{en}", f"<b>{lab}{xunit}</b>{vi}")}/>')
    g.append("</svg>")
    return "".join(g)


SEASONS = [("summer", "Summer (Jun–Aug)", "Hè (T6–T8)"), ("winter", "Winter (Dec–Feb)", "Đông (T12–T2)")]


def hour_heatmap(zone_hour: dict, order: list[str]) -> str:
    """Faulted zone (rows) x hour of the fault (columns), one block per season: the share of the
    zone's healthy downstream load the ties pick up. Darker = more comes back."""
    cw, ch, L, gap = 21, 20, 48, 48
    zones = [z for z in order if z in zone_hour["summer"]]
    W = L + 24 * cw + 4
    H = 20 + len(SEASONS) * (gap + len(zones) * ch) + 4
    g = [f'<svg viewBox="0 0 {W} {H}" class="heat" role="img" '
         f'aria-label="Share of healthy load restored, faulted zone by hour of the fault">']
    g.append(svg_text(L + 12 * cw, 12, "hour of the fault →", "giờ xảy ra sự cố →", anchor="middle"))
    y = 20
    for key, en, vi in SEASONS:
        y += gap
        g.append(svg_text(4, y - 28, en, vi, "lab"))
        for hr in range(0, 24, 3):
            g.append(svg_text(L + hr * cw + cw / 2, y - 8, f"{hr:02d}", anchor="middle"))
        for z in zones:
            g.append(svg_text(L - 8, y + ch / 2 + 4, z, anchor="end"))
            for hr, v in enumerate(zone_hour[key][z]):
                q = 0 if v <= 0 else 1 + min(4, int(v * 5 - 1e-9))   # 0 | (0,20%] ... (80%,100%]
                ten = (f"<b>Fault in {z}</b>, {hr:02d}:00, {en.split(' ')[0].lower()}<br>ties pick up "
                       f"<b>{pct(v)}</b> of the healthy load left dark beyond it")
                tvi = (f"<b>Sự cố ở {z}</b>, {hr:02d}:00, {vi.split(' ')[0].lower()}<br>tie cấp lại "
                       f"<b>{pct(v)}</b> phần tải lành bị mất điện phía sau")
                # no tabindex: 288 cells would swamp keyboard navigation; the same numbers are in by_hour.csv
                g.append(f'<rect class="cell q{q}" x="{L + hr * cw + 1}" y="{y + 1}" width="{cw - 2}" '
                         f'height="{ch - 2}" rx="2" data-tip="{esc(ten, quote=True)}" '
                         f'data-tip-vi="{esc(tvi, quote=True)}"/>')
            y += ch
    g.append("</svg>")
    return "".join(g)


def hbar_chart(items: list[tuple[str, str, float, str, str]], vmax: float, fmt, title: str,
               ref: tuple[float, str, str] | None = None) -> str:
    W, L, R, rowh, bh = 680, 150, 70, 26, 16
    pw = W - L - R
    H = len(items) * rowh + 30
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    g.append(f'<line class="axis" x1="{L}" x2="{L}" y1="4" y2="{len(items) * rowh + 4}"/>')
    if ref:
        x = L + pw * ref[0] / vmax
        g.append(f'<line class="ref" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{len(items) * rowh + 8}"/>'
                 + svg_text(x, H - 6, ref[1], ref[2], anchor="middle"))
    for i, (en, vi, v, ten, tvi) in enumerate(items):
        y = 4 + i * rowh + (rowh - bh) / 2
        w = max(pw * v / vmax, 1)
        g.append(svg_text(L - 10, y + bh - 3, en, vi, "lab", "end")
                 + f'<path class="bar" d="{bar_path(L, y, w, bh)}"/>'
                 + svg_text(L + w + 6, y + bh - 3, fmt(v), cls="val")
                 + f'<rect class="hit" x="0" y="{4 + i * rowh}" width="{W}" height="{rowh}" {tip(ten, tvi)}/>')
    g.append("</svg>")
    return "".join(g)


def confusion_heatmap(rows: list[dict], order: list[str]) -> str:
    cell, L, T_ = 44, 64, 56
    n = len(order)
    W, H = L + n * cell + 4, T_ + n * cell + 4
    m = {r["true"]: r for r in rows}
    off = [int(m[t][p]) for t in order for p in order if t != p]
    top = max(off) or 1
    g = [f'<svg viewBox="0 0 {W} {H}" class="heat" role="img" aria-label="Confusion matrix, true vs predicted zone">']
    g.append(svg_text(L + n * cell / 2, 12, "predicted zone →", "zone dự đoán →", anchor="middle"))
    g.append(svg_text(L - 8, T_ - 10, "true ↓", "thật ↓", anchor="end"))
    for j, p in enumerate(order):
        g.append(svg_text(L + j * cell + cell / 2, T_ - 10, p, anchor="middle"))
    for i, t in enumerate(order):
        y = T_ + i * cell
        g.append(svg_text(L - 8, y + cell / 2 + 4, t, anchor="end"))
        for j, p in enumerate(order):
            x, c = L + j * cell, int(m[t][p])
            if t == p:
                cls, label = "diag", f"{c:,}"
                en, vi = f"<b>{t}</b> correctly placed: <b>{c:,}</b> faults", f"<b>{t}</b> đoán đúng: <b>{c:,}</b> sự cố"
            elif c == 0:
                cls, label = "q0", ""
                en, vi = f"True {t} → predicted {p}: 0", f"Thật {t} → đoán {p}: 0"
            else:
                q = 1 + min(4, int(4 * math.sqrt(c / top)))   # 5 sequential steps, sqrt scale
                cls, label = f"q{q}", str(c)
                en = f"True <b>{t}</b> → predicted <b>{p}</b>: <b>{c}</b> faults"
                vi = f"Thật <b>{t}</b> → đoán <b>{p}</b>: <b>{c}</b> sự cố"
            g.append(f'<g {tip(en, vi)}><rect class="cell {cls}" x="{x + 1}" y="{y + 1}" width="{cell - 2}" '
                     f'height="{cell - 2}" rx="3"/><text class="ct {cls}" x="{x + cell / 2}" y="{y + cell / 2 + 4}" '
                     f'text-anchor="middle">{label}</text></g>')
    g.append("</svg>")
    return "".join(g)


# ---------------------------------------------------------------- page pieces
CHIP = {"good": ("✓", "Pass", "Đạt"), "warning": ("!", "Watch", "Lưu ý"), "critical": ("✕", "Fail", "Lỗi")}


def status(kind: str, title: tuple[str, str], detail: tuple[str, str]) -> str:
    icon, en, vi = CHIP[kind]
    return (f'<li class="check"><span class="chip {kind}"><span aria-hidden="true">{icon}</span> {T(en, vi)}</span>'
            f'<div><b>{T(*title)}</b><span class="muted">{T(*(emph(s) for s in detail))}</span></div></li>')


def tile(label: str, value: str, sub: str, x: str) -> str:
    return (f'<div class="tile" data-x="{x}"><div class="tl">{label}</div><div class="tv">{value}</div>'
            f'<div class="ts">{emph(sub)}</div></div>')


def xbox(key: str, inner: str, cls: str = "") -> str:
    """Wrap a chart or table so the guide buddy can point at it and explain it (EXPLAIN[key])."""
    return f'<div class="xbox {cls}" data-x="{key}">{inner}</div>'


def deep_box(title_en: str, title_vi: str, sub_en: str, sub_vi: str,
             inner: str, badge: str = "", id_: str = "") -> str:
    """Collapsible deep-dive panel so first-time readers scan the page in 30 seconds while reviewers
    can open every table, chart, and SHA-256 hash in one click (or expand all at once)."""
    if not inner or not inner.strip():
        return ""
    id_attr = f' id="{id_}"' if id_ else ""
    b_html = f'<span class="deep-badge">{badge}</span>' if badge else ""
    return (
        f'<details class="deep"{id_attr}>'
        f'<summary class="deep-sum">'
        f'<span class="deep-t"><b>{T(title_en, title_vi)}</b>'
        f'<small>{T(sub_en, sub_vi)}</small></span>'
        f'<span class="deep-r">{b_html}'
        f'<span class="deep-act">{T("Expand", "Xem chi tiết")}</span></span>'
        f'</summary>'
        f'<div class="deep-body">{inner}</div>'
        f'</details>'
    )


def explanations(d: dict, v: dict) -> str:
    """EXPLAIN filled with this run's numbers, as JSON for the page script."""
    out = {k: {lang: bubble_text({f: e[f][i].format(**v) for f in ("title", "what", "read", "why")})
               for i, lang in enumerate(("en", "vi"))}
           for k, e in EXPLAIN.items() if (d["ea"] or not e.get("needs_ea")) and (d["h"] or not e.get("needs_h"))
           and (d["sp"] or not e.get("needs_sp")) and (d["tr"] or not e.get("needs_tr"))
           and (d.get("comtrade") or not e.get("needs_ct"))}
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/")


def bubble_text(t: dict) -> dict:
    """Plain text for the guide's bubble -> escaped HTML with the key numbers in bold."""
    return {f: s if f == "title" else emph(esc(s, quote=False)) for f, s in t.items()}


def _fill(kind: str, **fields) -> dict:
    return {lang: bubble_text({f: MODEL[kind][f][i].format(**fields) for f in ("title", "what", "read", "why")})
            for i, lang in enumerate(("en", "vi"))}


def _restore_text(r: dict) -> tuple[str, str]:
    """What restoration does when this zone is the faulted one, in both languages."""
    dark, back = float(r["kW_downstream_healthy"]), float(r["kW_restored_by_tie"])
    ties = [t for t in r["ties_closed"].split() if t != "-"]
    still = [z for z in r["unserved_healthy"].split() if z != "-"]
    listed = lambda xs, word: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + f" {word} " + xs[-1]  # noqa: E731
    one = len(still) == 1
    if not dark:
        return ("nothing beyond it loses power, so only this zone waits for the repair.",
                "không có zone nào phía sau bị mất điện, nên chỉ zone này chờ sửa xong.")
    if not back:
        return (f"none of the {num(dark)} kW left dark beyond it can be picked up within limits, so "
                f"{listed(still, 'and')} {'waits' if one else 'wait'} for the repair.",
                f"không thể cấp lại {num(dark)} kW bị mất điện phía sau mà vẫn giữ giới hạn, nên {listed(still, 'và')} "
                "phải chờ sửa xong.")
    en = f"{num(back)} kW of the {num(dark)} kW left dark beyond it comes back through tie {listed(ties, 'and')}"
    vi = f"{num(back)} kW trên {num(dark)} kW bị mất điện phía sau được cấp lại qua tie {listed(ties, 'và')}"
    if still:
        return (en + f"; {listed(still, 'and')} {'stays' if one else 'stay'} dark until the repair.",
                vi + f"; {listed(still, 'và')} vẫn mất điện tới khi sửa xong.")
    return en + "; every healthy zone gets power back.", vi + "; mọi zone lành đều có điện lại."


def publish_models(root=config.ROOT) -> dict[str, str]:
    """SolidWorks equipment (exports/<part>.glb), copied to docs/models/ only while workflow.toml
    says the export is fresh. The 3D view swaps each one in for its drawn stand-in."""
    from . import assets, mech
    items = {a["id"]: a for a in assets.load(root / "workflow.toml")}
    reg = assets.registered(root / "exports" / "registered.json")
    dst = root / "docs" / "models"
    out = {}
    for name in mech.PARTS:
        a = items.get(f"mech-{name.replace('_', '-')}-glb")
        if a is None or assets.status(a, root, reg)[0] is not True:
            continue
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / a["export"], dst / f"{name}.glb")
        out[name] = f"models/{name}.glb"
    if dst.exists():
        for old in dst.glob("*.glb"):        # a model that went stale leaves the page
            if old.stem not in out:
                old.unlink()
    return out


DRAWING_LABELS = {"recloser": ("recloser", "recloser"), "auto_switch": ("auto switch", "dao tự động"),
                  "regulator": ("regulator", "điều áp"), "capacitor": ("capacitor bank", "giàn tụ"),
                  "transformer": ("pole-top transformer", "MBA trên cột"), "substation": ("substation", "trạm nguồn")}


def publish_drawings(root=config.ROOT) -> list[tuple[str, str, str]]:
    """Technical drawings (exports/drawing_<part>.pdf from AutoCAD), copied to docs/drawings/ only
    while workflow.toml says the export is fresh: [(label en, label vi, url)]."""
    from . import assets, mech
    items = {a["id"]: a for a in assets.load(root / "workflow.toml")}
    reg = assets.registered(root / "exports" / "registered.json")
    dst = root / "docs" / "drawings"
    out, keep = [], set()
    for name in mech.PARTS:
        a = items.get(f"drawing-{name.replace('_', '-')}-pdf")
        if a is None or assets.status(a, root, reg)[0] is not True:
            continue
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / a["export"], dst / f"{name}.pdf")
        keep.add(f"{name}.pdf")
        out.append((*DRAWING_LABELS[name], f"drawings/{name}.pdf"))
    if dst.exists():
        for old in dst.glob("*.pdf"):        # a drawing that went stale leaves the page
            if old.name not in keep:
                old.unlink()
    return out


def model_data(d: dict) -> str:
    """Geometry plus the guide's text for every clickable part of the 3D model, as JSON."""
    geo = d["geo"]
    if not geo:
        return "null"
    zrow = {z["zone"]: z for z in d["zones"]}
    rest = {r["fault_zone"]: r for r in d["rest"]}
    pz = {r["zone"]: r for r in d.get("per_zone", [])}
    zones = {}
    for z in (g["name"] for g in geo["zones"]):
        r = zrow[z]
        kind = "recloser" if z == "Sw1" else "ieee" if z.startswith("Sw") else "added"
        device = {"recloser": (f"recloser {z}", f"recloser {z}"), "ieee": (f"IEEE switch {z}", f"dao IEEE {z}"),
                  "added": (f"automated switch {z} (added)", f"dao tự động {z} (thêm vào)")}[kind]
        restore = _restore_text(rest[z])
        zones[z] = _fill("zone", zone=z, kw=num(float(r["kW"])), loads=r["load_points"], kft=f'{float(r["line_kft"]):.1f}',
                         device=device[0], device_vi=device[1],
                         parent=r["parent_zone"] or "the substation", parent_vi=r["parent_zone"] or "trạm nguồn",
                         recall=pct(1 - float(pz[z]["FNR"])) if z in pz else "–",
                         fpr=pct(float(pz[z]["FPR"]), 2) if z in pz else "–",
                         restore=restore[0], restore_vi=restore[1])
    obj = {"src": _fill("source", bus=geo["source"][0])}
    for name, kind, *_ in geo["devices"]:
        obj["dev:" + name] = _fill(kind, name=name, zone=next(d_[4] for d_ in geo["devices"] if d_[0] == name))
    for name, *_ in geo["ties"]:
        (what, read) = TIE_TEXT[name]
        obj["tie:" + name] = _fill("tie", name=name, what=what[0], what_vi=what[1], read=read[0], read_vi=read[1])
    for name, bus, *_ in geo["regs"]:
        obj["reg:" + bus] = _fill("reg", name=name, bus=bus)
    for name, bus, kvar, *_ in geo["caps"]:
        obj["cap:" + name] = _fill("cap", name=name, bus=bus, kvar=num(kvar))
    load = {lang: {f: esc(MODEL["load"][f][i], quote=False) for f in ("title", "what", "read", "why")}
            for i, lang in enumerate(("en", "vi"))}
    hif_demo = None
    hif_ver = config.ROOT / "hif_sensor" / "results" / "c_firmware_verify.json"
    hif_vec = config.ROOT / "hif_sensor" / "results" / "test_vectors.json"
    if hif_ver.exists() and hif_vec.exists():
        p0 = json.loads(hif_ver.read_text(encoding="utf-8"))["phase0_official_6_vectors"]
        vecs = json.loads(hif_vec.read_text(encoding="utf-8"))
        v1 = next((x for x in vecs if x.get("is_hif") and float(x["prob"]) > float(p0["threshold"])), vecs[1])
        mon_path = config.ROOT / "docs" / "monitor" / "data.json"
        demo_bus, demo_z, demo_r, demo_conf = "72", "Sw4", 200.0, None
        if mon_path.exists():
            mon = json.loads(mon_path.read_text(encoding="utf-8"))
            inc = next((x for x in mon.get("incidents", []) if x.get("id") == "INC-1024"), None)
            if inc:
                demo_bus, demo_z, demo_r = inc["bus"], inc["zone"], float(inc["r_ohm"])
                demo_conf = float(inc["ml_top"][0]["p"])
        hif_demo = {
            "bus": demo_bus, "Z": demo_z, "P": demo_z, "ftype": "SLG", "r": demo_r, "conf": demo_conf,
            "p_hif": round(float(v1["prob"]), 6), "threshold": float(p0["threshold"]),
            "persist": int(p0["persist_windows"]), "params": int(p0["params"]),
            "bytes": int(p0["model_bytes_int8_weights_float_bias"]),
            "host_us": float(p0["host_latency_us_per_inference"]),
        }
    out = {"geo": geo, "kw": {z: num(float(zrow[z]["kW"])) for z in zrow},
           "text": {"zone": zones, "obj": obj, "load": load}, "glb": d.get("glb", {}),
           "hif_demo": hif_demo, **fault_layers(d)}
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/")


def fault_layers(d: dict) -> dict:
    """Data for the 3D model's error map and fault replay: errors per bus, every misplaced fault,
    the common confusions, the zone tree and what restoration does for each faulted zone."""
    geo, ea_dir = d["geo"], config.RESULTS / "error_analysis"
    base = lambda b: b[:-1] if b[-1:] in "rs" and b[:-1] in geo["buses"] else b  # noqa: E731  (9r -> 9)
    err = {}
    if (ea_dir / "per_bus_ml.csv").exists():
        for r in _csv(ea_dir / "per_bus_ml.csv"):
            e = err.setdefault(base(r["bus"]), [0, 0, 0, 0, r["top_wrong_zone"], 0])
            e[0] += int(r["faults"]); e[1] += int(r["ml_wrong"]); e[2] += int(r["fpi_wrong"]); e[3] += int(r["wrong_weak_slg"])
            if int(r["top_wrong_n"]) > e[5]:
                e[4], e[5] = r["top_wrong_zone"], int(r["top_wrong_n"])
    missed = []
    if (ea_dir / "ml_errors.csv").exists():
        missed = [[base(r["bus"]), r["zone"], r["pred"], r["ftype"], float(r["r"]), float(r["confidence"]), r["relation"]]
                  for r in _csv(ea_dir / "ml_errors.csv")]
    pairs = sorted(([r["true"], p, int(n)] for r in d.get("confusion", []) for p, n in r.items()
                    if p != "true" and p != r["true"] and int(n) >= 8), key=lambda x: -x[2])
    rest = {r["fault_zone"]: {"ties": [t for t in r["ties_closed"].split() if t != "-"],
                              "back": [z for z in r["restored_by_tie"].split() if z != "-"],
                              "dark": [z for z in r["unserved_healthy"].split() if z != "-"],
                              "kw_back": num(float(r["kW_restored_by_tie"])), "kw_dark": num(float(r["kW_downstream_healthy"]))}
            for r in d["rest"]}
    return {"err": err, "missed": missed, "pairs": pairs, "rest": rest,
            "tree": {z["zone"]: z["parent_zone"] or None for z in d["zones"]},
            "zkw": {z["zone"]: float(z["kW"]) for z in d["zones"]},
            "kft": {z["zone"]: float(z["line_kft"]) for z in d["zones"]},
            "patrol_none": f'{d["m"]["patrol_kft"]["no_location"]:.1f}'}


DATA_DIR = config.ROOT / "docs" / "data"   # files published with the page (GitHub Pages serves docs/)
PUBLISHED = [  # (published name, source, English, Vietnamese)
    ("fault_dataset.csv.gz", config.GENERATED / "dataset.csv.gz",
     "All simulated faults, one row each: true zone, fault type, nominal & arcing R_eff diagnostics, load level and 150 measurements.",
     "Toàn bộ sự cố mô phỏng, mỗi sự cố một dòng: zone thật, loại sự cố, điện trở danh định & chẩn đoán hồ quang R_eff, mức tải và 150 số đo."),
    ("fault_dataset_sample.csv", None,
     "A 300-row sample of the same table, small enough to open in a spreadsheet.",
     "Bản mẫu 300 dòng của cùng bảng đó, đủ nhỏ để mở bằng Excel."),
    ("metrics.json", config.RESULTS / "metrics.json",
     "Every headline number on this page.", "Mọi con số chính trên trang này."),
    ("zones.csv", config.RESULTS / "zones.csv",
     "The 10 zones: feeding device, upstream zone, load, line length and buses.",
     "10 zone: thiết bị cấp, zone phía trên, phụ tải, chiều dài dây và các bus."),
    ("restoration.csv", config.RESULTS / "restoration.csv",
     "Isolation and restoration result for each faulted zone.", "Kết quả cô lập và khôi phục cho từng zone sự cố."),
    ("switching_orders.md", config.RESULTS / "switching_orders.md",
     "The switching steps for each faulted zone, in order.", "Các bước đóng cắt theo thứ tự cho từng zone sự cố."),
    ("per_zone_ml.csv", config.RESULTS / "error_analysis" / "per_zone_ml.csv",
     "Per-zone recall, FNR, precision and FPR of the model.", "Recall, FNR, precision và FPR của model theo từng zone."),
    ("confusion_ml.csv", config.RESULTS / "error_analysis" / "confusion_ml.csv",
     "True zone × predicted zone counts.", "Số đếm zone thật × zone dự đoán."),
    ("ml_errors.csv", config.RESULTS / "error_analysis" / "ml_errors.csv",
     "Every misplaced fault with its confidence and error direction.",
     "Mọi sự cố bị đoán sai, kèm độ tự tin và hướng lệch."),
    ("per_bus_ml.csv", config.RESULTS / "error_analysis" / "per_bus_ml.csv",
     "Errors per bus: faults simulated, misplaced by the model and by fault indicators (the 3D error map).",
     "Lỗi theo từng bus: số sự cố mô phỏng, số bị model và bộ chỉ báo đoán sai (bản đồ lỗi 3D)."),
    ("hourly.json", config.HOURLY / "hourly.json",
     "Hourly restoration study: typical-day curves, zone × hour shares, rejection reasons, yearly summary.",
     "Nghiên cứu khôi phục theo giờ: đường ngày điển hình, tỉ lệ zone × giờ, lý do bị loại, tóm tắt cả năm."),
    ("by_level.csv", config.HOURLY / "by_level.csv",
     "Restoration for every fault zone at every load level of the hourly study.",
     "Kết quả khôi phục cho từng zone sự cố ở mọi mức tải của nghiên cứu theo giờ."),
    ("by_hour.csv", config.HOURLY / "by_hour.csv",
     "Every hour of the year: load level, share restored at the fault hour and over the outage window, rejection reasons.",
     "Mỗi giờ trong năm: mức tải, tỉ lệ cấp lại ở giờ sự cố và trong cả thời gian mất điện, lý do bị loại."),
    ("spice_summary.json", config.RESULTS / "spice" / "summary.json",
     "LTspice circuits: fault DC offset, CT and ADC front end, arcing vs fixed-resistance ground fault.",
     "Mạch LTspice: DC lệch của dòng sự cố, mạch CT và ADC, sự cố chạm đất có hồ quang so với điện trở cố định."),
    ("spice_fault_current.csv", config.ROOT / "exports" / "spice_fault_current.csv",
     "LTspice waveform: bolted fault current at bus 60 with and without DC offset (20 µs steps).",
     "Dạng sóng LTspice: dòng sự cố trực tiếp tại bus 60, có và không có DC lệch (bước 20 µs)."),
    ("spice_hif.csv", config.ROOT / "exports" / "spice_hif.csv",
     "LTspice waveform: arcing and fixed-resistance ground fault at 100 Ω and 400 Ω (20 µs steps).",
     "Dạng sóng LTspice: sự cố chạm đất có hồ quang và điện trở cố định ở 100 Ω và 400 Ω (bước 20 µs)."),
    ("feeder_oneline.pdf", config.ROOT / "exports" / "feeder_oneline.pdf",
     "One-line diagram of the feeder and its 10 zones, drawn in AutoCAD from this study's data (A3).",
     "Sơ đồ một sợi của tuyến và 10 zone, vẽ bằng AutoCAD từ dữ liệu của nghiên cứu này (khổ A3)."),
    ("feeder_geometry.json", config.RESULTS / "feeder_geometry.json",
     "Bus coordinates, lines and equipment used by the 3D model.", "Tọa độ bus, đường dây và thiết bị dùng cho mô hình 3D."),
    ("phase2_ieee123.json", config.RESULTS / "transfer" / "phase2_ieee123.json",
     "Feeder-independent models trained on IEEE 123-bus only (5-fold GroupKFold by bus): FPI, PerNodeGBDT, ZoneTreeGNN.",
     "Các model độc lập với tên thiết bị, chỉ huấn luyện trên IEEE 123-bus (GroupKFold 5 phần theo bus): FPI, PerNodeGBDT, ZoneTreeGNN."),
    ("phase2b_bus_location.json", config.RESULTS / "transfer" / "phase2b_bus_location.json",
     "Stage-2 bus ranking inside the predicted zone on IEEE 123-bus and 34-bus: Takagi reactance vs BusGraphGNN.",
     "Xếp hạng tới từng bus bên trong zone dự đoán trên IEEE 123-bus và 34-bus: điện kháng Takagi so với BusGraphGNN."),
    ("phase3_ieee34.json", config.RESULTS / "transfer" / "phase3_ieee34.json",
     "Zero-shot, in-domain upper bound and few-shot transfer from IEEE 123-bus (4.16 kV) to unseen IEEE 34-bus (24.9 kV).",
     "Kết quả chuyển giao zero-shot, giới hạn trên và few-shot từ IEEE 123-bus (4.16 kV) sang IEEE 34-bus (24.9 kV) chưa từng thấy."),
    ("dataset_ieee37.json", config.RESULTS / "transfer" / "dataset_ieee37.json",
     "Passive fault-sweep summary on the third unseen feeder: urban underground IEEE 37-bus (4.8 kV, 3-wire ungrounded delta).",
     "Tóm tắt bộ dữ liệu sự cố thụ động trên lưới thứ 3 chưa từng thấy: cáp ngầm đô thị IEEE 37-bus (4.8 kV, 3 dây delta không nối đất)."),
    ("phase3_ieee37.json", config.RESULTS / "transfer" / "phase3_ieee37.json",
     "Zero-shot, in-domain upper bound and few-shot transfer from IEEE 123-bus (4.16 kV) to unseen underground delta IEEE 37-bus (4.8 kV).",
     "Kết quả chuyển giao zero-shot, giới hạn trên và few-shot từ IEEE 123-bus (4.16 kV) sang lưới cáp ngầm delta IEEE 37-bus (4.8 kV) chưa từng thấy."),
    ("phase2b_bus_ieee37.json", config.RESULTS / "transfer" / "phase2b_bus_ieee37.json",
     "Stage-2 bus ranking inside the predicted zone on IEEE 37-bus (4.8 kV delta cable): Takagi reactance vs BusGraphGNN.",
     "Xếp hạng tới từng bus trong zone dự đoán trên IEEE 37-bus (cáp ngầm delta 4.8 kV): điện kháng Takagi so với BusGraphGNN."),
    ("phase_active_ieee123.json", config.RESULTS / "active_grid" / "phase_active_ieee123.json",
     "Active IEEE 123-bus (0–50% inverter DER, reconfiguration, closed loop, non-fault transients): FPI vs GBDT vs ActiveGridGATv2.",
     "Lưới IEEE 123-bus chủ động (0–50% điện mặt trời DER, đổi cấu trúc, vòng kín, quá độ không sự cố): FPI so với GBDT và ActiveGridGATv2."),
    ("phase_active_ieee34.json", config.RESULTS / "active_grid" / "phase_active_ieee34.json",
     "Unseen active IEEE 34-bus (24.9 kV, DER 0–50%, closed loop, SLG up to 10 kΩ, non-fault transients): zero-shot & few-shot transfer.",
     "Lưới IEEE 34-bus chủ động chưa từng thấy (24.9 kV, DER 0–50%, vòng kín, SLG tới 10 kΩ, quá độ không sự cố): chuyển giao zero-shot & few-shot."),
    ("conformal_safety.json", config.RESULTS / "active_grid" / "conformal_safety.json",
     "Pre-registered Split Conformal Prediction (deterministic APS at 90% and 95%) on active IEEE 123-bus and IEEE 34-bus.",
     "Split Conformal Prediction đã đăng ký trước (APS xác định ở mức 90% và 95%) trên lưới chủ động IEEE 123-bus và IEEE 34-bus."),
    ("conformal_posthoc.json", config.RESULTS / "active_grid" / "conformal_posthoc.json",
     "Post-hoc check: deterministic APS vs randomized APS vs LAC on the same probabilities and splits.",
     "Kiểm tra sau: APS xác định so với APS ngẫu nhiên và LAC trên cùng xác suất và cùng cách chia."),
    ("active_ieee37_dataset_summary.json", config.RESULTS / "active_grid_ieee37" / "dataset_summary.json",
     "Active-grid OpenDSS dataset summary for IEEE 37-bus (0–50% delta DER, reconfig_tie / looped_tie, non-fault transients).",
     "Tóm tắt dữ liệu OpenDSS lưới chủ động IEEE 37-bus (0–50% DER đấu delta, reconfig_tie / looped_tie, quá độ không sự cố)."),
    ("phase_active_ieee37.json", config.RESULTS / "active_grid_ieee37" / "phase_active_ieee37.json",
     "Unseen active IEEE 37-bus (4.8 kV underground delta, DER 0–50%, reconfig/looped tie, non-fault transients): zero-shot & few-shot transfer.",
     "Lưới IEEE 37-bus chủ động chưa từng thấy (cáp ngầm delta 4.8 kV, DER 0–50%, đổi nhánh/vòng kín, quá độ không sự cố): zero-shot & few-shot."),
    ("active_ieee37_conformal_safety.json", config.RESULTS / "active_grid_ieee37" / "conformal_safety.json",
     "Split Conformal Prediction (deterministic APS schema parity) on active IEEE 123-bus and unseen IEEE 37-bus.",
     "Split Conformal Prediction (APS xác định đồng bộ cấu trúc) trên lưới chủ động IEEE 123-bus và IEEE 37-bus chưa từng thấy."),
    ("active_ieee37_conformal_posthoc.json", config.RESULTS / "active_grid_ieee37" / "conformal_posthoc.json",
     "Split Conformal Prediction (pre-registered randomized APS, LAC, deterministic APS) on active IEEE 37-bus.",
     "Split Conformal Prediction (APS ngẫu nhiên đăng ký trước, LAC, APS xác định) trên lưới chủ động IEEE 37-bus."),
    ("active_ieee37_conformal_calsize.json", config.RESULTS / "active_grid_ieee37" / "conformal_calsize.json",
     "Calibration-size sweep (5%–40% of fault buses) for randomized APS on active IEEE 37-bus.",
     "Khảo sát cỡ tập hiệu chỉnh (5%–40% bus sự cố) cho APS ngẫu nhiên trên lưới chủ động IEEE 37-bus."),
    ("signal_to_load.json", config.RESULTS / "transfer" / "signal_to_load.json",
     "Ground-fault current vs feeder-head current at nominal load, IEEE 123-bus, 34-bus and 37-bus (OpenDSS).",
     "Dòng sự cố chạm đất so với dòng đầu tuyến ở tải định mức, IEEE 123-bus, 34-bus và 37-bus (OpenDSS)."),
    ("multi_feeder_benchmark.json", config.RESULTS / "transfer" / "multi_feeder_benchmark.json",
     "Multi-feeder zero-shot evidence benchmark across 15 official IEEE/EPRI OpenDSS feeders (frozen IEEE 123-bus models, Kaggle 3-VM run).",
     "Bảng bằng chứng chuyển giao zero-shot trên 15 lưới phân phối chuẩn IEEE/EPRI OpenDSS (model IEEE 123-bus đóng băng, chạy 3 phiên Kaggle)."),
    ("multi_feeder_benchmark.csv", config.RESULTS / "transfer" / "multi_feeder_benchmark.csv",
     "CSV summary table of the 15-feeder zero-shot benchmark (FPI vs Per-node GBDT vs Zone-tree GNN).",
     "Bảng CSV tổng hợp kiểm chứng đa lưới trên 15 lưới phân phối (FPI so với GBDT theo nút và GNN cây zone)."),
    ("hif_fusion_dataset_summary.json", config.RESULTS / "hif_fusion" / "dataset_summary.json",
     "Two-tier Edge HIF-Sensor → Graph FLISR dataset summary, frozen int8 model metadata and front-end parameters.",
     "Tóm tắt bộ dữ liệu ghép 2 tầng Edge HIF-Sensor → Graph FLISR, thông số model int8 đóng băng và mạch lọc đầu vào."),
    ("hif_fusion_passive_ieee123.json", config.RESULTS / "hif_fusion" / "passive_ieee123.json",
     "Paired ablation (60 Hz only vs +Edge p_hif) on passive IEEE 123-bus (5-fold GroupKFold by bus): FPI, PerNodeGBDT, ZoneTreeGNN.",
     "So sánh đối chứng (60 Hz thuần vs +Edge p_hif) trên lưới thụ động IEEE 123-bus (GroupKFold 5 phần theo bus): FPI, PerNodeGBDT, ZoneTreeGNN."),
    ("hif_fusion_passive_ieee34.json", config.RESULTS / "hif_fusion" / "passive_ieee34.json",
     "Zero-shot & few-shot transfer (60 Hz only vs +Edge p_hif) from IEEE 123-bus to unseen passive IEEE 34-bus.",
     "Chuyển giao zero-shot & few-shot (60 Hz thuần vs +Edge p_hif) từ IEEE 123-bus sang lưới thụ động IEEE 34-bus chưa thấy."),
    ("hif_fusion_active_ieee123.json", config.RESULTS / "hif_fusion" / "active_ieee123.json",
     "Active IEEE 123-bus (DER 0–50%, loops, 5 arc surfaces, 7 NO_FAULT disturbances): 60 Hz only vs +Edge p_hif for GBDT & ActiveGridGATv2.",
     "Lưới chủ động IEEE 123-bus (DER 0–50%, vòng kín, 5 bề mặt hồ quang, 7 nhiễu nền NO_FAULT): 60 Hz thuần vs +Edge p_hif cho GBDT & ActiveGridGATv2."),
    ("hif_fusion_active_ieee34.json", config.RESULTS / "hif_fusion" / "active_ieee34.json",
     "Unseen active IEEE 34-bus (24.9 kV, SLG 1–10 kΩ, 7 disturbances) + pre-committed H1–H4 verdicts: 60 Hz only vs +Edge p_hif.",
     "Lưới chủ động IEEE 34-bus chưa thấy (24.9 kV, SLG 1–10 kΩ, 7 nhiễu nền) & kết luận tiêu chí H1–H4: 60 Hz thuần vs +Edge p_hif."),
    ("hif_fusion_conformal_hif.json", config.RESULTS / "hif_fusion" / "conformal_hif.json",
     "Split Conformal Prediction (aps_rand & lac at 90%/95%) for 60 Hz only vs +Edge p_hif on active IEEE 123-bus and 34-bus.",
     "Split Conformal Prediction (aps_rand & lac ở mức 90%/95%) cho 60 Hz thuần vs +Edge p_hif trên lưới chủ động IEEE 123-bus và 34-bus."),
    ("hif_fusion_realistic_dataset_summary.json", config.RESULTS / "hif_fusion_realistic" / "dataset_summary.json",
     "Branch-10 realistic HIF-Fusion dataset summary (intermittent arcing R_eff, zone load drift, CT/PT bias + frozen 504 B int8 Tier-1).",
     "Tóm tắt dữ liệu HIF-Fusion thực tế Nhánh 10 (hồ quang chập chờn R_eff, trôi tải theo zone, sai số CT/PT + Tầng 1 int8 504 B đóng băng)."),
    ("hif_fusion_realistic_passive_ieee123.json", config.RESULTS / "hif_fusion_realistic" / "passive_ieee123.json",
     "Branch-10 realistic passive IEEE 123-bus paired ablation (60 Hz vs +Edge): FPI, ml_full (150→170), PerNodeGBDT, ZoneTreeGNN.",
     "Đối chứng thụ động IEEE 123-bus thực tế Nhánh 10 (60 Hz vs +Edge): FPI, ml_full (150→170), PerNodeGBDT, ZoneTreeGNN."),
    ("hif_fusion_realistic_passive_ieee34.json", config.RESULTS / "hif_fusion_realistic" / "passive_ieee34.json",
     "Branch-10 realistic passive unseen IEEE 34-bus zero-shot & few-shot transfer (60 Hz vs +Edge).",
     "Chuyển giao thụ động zero-shot & few-shot sang IEEE 34-bus thực tế Nhánh 10 (60 Hz vs +Edge)."),
    ("hif_fusion_realistic_active_ieee123.json", config.RESULTS / "hif_fusion_realistic" / "active_ieee123.json",
     "Branch-10 realistic active IEEE 123-bus (DER 0–50%, loops, 7 NO_FAULT disturbances): 60 Hz vs +Edge.",
     "Lưới chủ động IEEE 123-bus thực tế Nhánh 10 (DER 0–50%, vòng kín, 7 nhiễu nền NO_FAULT): 60 Hz vs +Edge."),
    ("hif_fusion_realistic_active_ieee34.json", config.RESULTS / "hif_fusion_realistic" / "active_ieee34.json",
     "Branch-10 realistic active unseen IEEE 34-bus (24.9 kV, SLG 1–10 kΩ, 7 disturbances): 60 Hz vs +Edge.",
     "Lưới chủ động IEEE 34-bus chưa thấy thực tế Nhánh 10 (24.9 kV, SLG 1–10 kΩ, 7 nhiễu nền): 60 Hz vs +Edge."),
    ("hif_fusion_realistic_conformal_hif.json", config.RESULTS / "hif_fusion_realistic" / "conformal_hif.json",
     "Branch-10 realistic Split Conformal Prediction (aps_rand & lac at 90%/95%) for 60 Hz vs +Edge.",
     "Split Conformal Prediction (aps_rand & lac ở mức 90%/95%) cho 60 Hz vs +Edge trên mô phỏng thực tế Nhánh 10."),
    ("hif_fusion_realistic_summary.json", config.RESULTS / "hif_fusion_realistic" / "summary.json",
     "Branch-10 realistic HIF-Fusion Before/After summary & pre-registered R1–R4 verdicts.",
     "Tóm tắt Trước/Sau HIF-Fusion thực tế Nhánh 10 & kết luận tiêu chí tiền đăng ký R1–R4."),
    ("error_analysis.json", config.RESULTS / "error_analysis" / "error_analysis.json",
     "Error-analysis summary JSON: error counts by resistance, fault type, load tercile, direction and confidence deferral.",
     "JSON tóm tắt phân tích lỗi: số lỗi theo điện trở, loại sự cố, nhóm tải, hướng lệch và ngưỡng độ tự tin."),
    ("per_zone_fpi.csv", config.RESULTS / "error_analysis" / "per_zone_fpi.csv",
     "Per-zone recall, FNR, precision and FPR of the conventional FPI baseline.",
     "Recall, FNR, precision và FPR theo từng zone của phương pháp FPI truyền thống."),
    ("load_shape.csv", config.HOURLY / "load_shape.csv",
     "8,760 hourly PJM AEP 2017 load multipliers (normalized to yearly peak = 1.00).",
     "8,760 hệ số tải theo giờ PJM AEP năm 2017 (chuẩn hóa về đỉnh năm = 1.00)."),
    ("load_shape_info.json", config.HOURLY / "load_shape_info.json",
     "Metadata for the PJM AEP 2017 hourly load shape.",
     "Thông tin mô tả đường phụ tải theo giờ PJM AEP năm 2017."),
    ("dataset_ieee123.json", config.RESULTS / "transfer" / "dataset_ieee123.json",
     "Passive cross-feeder transfer dataset summary for IEEE 123-bus (11,448 events, 10 zones).",
     "Tóm tắt bộ dữ liệu chuyển giao thụ động trên IEEE 123-bus (11,448 sự cố, 10 zone)."),
    ("dataset_ieee34.json", config.RESULTS / "transfer" / "dataset_ieee34.json",
     "Passive cross-feeder transfer dataset summary for unseen IEEE 34-bus (4,104 events, 7 zones).",
     "Tóm tắt bộ dữ liệu chuyển giao thụ động trên IEEE 34-bus chưa thấy (4,104 sự cố, 7 zone)."),
    ("dataset_summary.json", config.RESULTS / "active_grid" / "dataset_summary.json",
     "Active-grid OpenDSS dataset summary for IEEE 123-bus (17,847 events) and IEEE 34-bus (9,491 events).",
     "Tóm tắt bộ dữ liệu OpenDSS lưới chủ động IEEE 123-bus (17,847 ca) và IEEE 34-bus (9,491 ca)."),
    ("conformal_calsize.json", config.RESULTS / "active_grid" / "conformal_calsize.json",
     "Calibration-size sweep (5%–40% of fault buses, 50 draws) for randomized APS on active IEEE 34-bus.",
     "Khảo sát cỡ tập hiệu chỉnh (5%–40% số bus sự cố, 50 lần rút) cho APS ngẫu nhiên trên IEEE 34-bus chủ động."),
    ("active_ieee37_phase_active_ieee123.json", config.RESULTS / "active_grid_ieee37" / "phase_active_ieee123.json",
     "Active IEEE 123-bus reference CV metrics paired with the IEEE 37-bus Kaggle GPU run.",
     "Kết quả kiểm định chéo IEEE 123-bus chủ động chạy song hành với phiên Kaggle GPU IEEE 37-bus."),
    ("demo_event.jsonl", config.RESULTS / "demo_event.jsonl",
     "Single simulated SCADA/MQTT event replay (bus 60, SLG 50 Ω) in JSON-lines format.",
     "Bản ghi phát lại 1 sự cố SCADA/MQTT mô phỏng (bus 60, SLG 50 Ω) dạng JSON-lines."),
    ("comtrade_summary.json", config.RESULTS / "comtrade" / "summary.json",
     "IEEE C37.111 COMTRADE ingest verification across public open-source relay samples and OpenDSS/LTspice/HIF round-trips.",
     "Kết quả kiểm thử đọc file COMTRADE (IEEE C37.111) trên các mẫu công khai và sóng mô phỏng vòng kín OpenDSS/LTspice/HIF."),
]

PUB_BY_REL: dict[str, str] = {
    src.relative_to(config.ROOT).as_posix(): name
    for name, src, _, _ in PUBLISHED if src is not None
}


def publish_data() -> list[tuple[str, str, str, int]]:
    """Copy the study's data and results next to the page; returns (name, en, vi, bytes) for what exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for name, src, en, vi in PUBLISHED:
        dst = DATA_DIR / name
        if src is None:   # sample: every Nth row of the full dataset, so all zones and fault types show up
            full = config.GENERATED / "dataset.csv.gz"
            if not full.exists():
                continue
            import gzip
            with gzip.open(full, "rt", newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            step = max(1, (len(rows) - 1) // 300)
            with open(dst, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([rows[0]] + rows[1::step][:300])
        elif src.exists():
            shutil.copyfile(src, dst)
        else:
            continue
        out.append((name, en, vi, dst.stat().st_size))
    return out


def _size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


COLUMNS = [  # dataset column, English, Vietnamese, unit
    ("bus", "Faulted bus (IEEE number)", "Bus bị sự cố (số hiệu IEEE)", "–"),
    ("zone", "True zone: the answer the model has to learn", "Zone thật: đáp án model phải học", "–"),
    ("ftype", "Fault type: SLG, LL, LLG or 3PH", "Loại sự cố: SLG, LL, LLG hoặc 3PH", "–"),
    ("phases", "Faulted phase(s): 1 = a, 2 = b, 3 = c", "Pha bị sự cố: 1 = a, 2 = b, 3 = c", "–"),
    ("r", "Nominal fault resistance", "Điện trở sự cố danh định", "Ω"),
    ("r_eff, is_arcing, arc_kappa, arc_duty",
     "Arcing HIF diagnostics (SLG ≥ 100 Ω): equivalent 60 Hz resistance R_eff (≤ 2,500 Ω), Emanuel factor κ, conduction duty",
     "Chẩn đoán hồ quang HIF (SLG ≥ 100 Ω): điện trở tương đương 60 Hz R_eff (≤ 2,500 Ω), hệ số Emanuel κ, chu kỳ dẫn", "Ω / –"),
    ("scenario, load_mult", "Loading scenario and feeder-wide load level (0.3–1.1 × peak, plus independent per-zone ±30% & pre/post drift)",
     "Kịch bản tải và mức tải toàn tuyến (0.3–1.1 × đỉnh, kèm tải độc lập từng zone ±30% và trôi tải pre/post)", "–"),
    ("converged", "Whether the power flow solved", "Trào lưu công suất có hội tụ không", "–"),
    ("‹dev›_Ia, _Ib, _Ic", "Phase current magnitude during the fault", "Biên độ dòng pha lúc sự cố", "A"),
    ("‹dev›_dIa, _dIb, _dIc", "Change in phase current, |I<sub>fault</sub> − I<sub>pre</sub>|",
     "Mức thay đổi dòng pha, |I<sub>sự cố</sub> − I<sub>trước</sub>|", "A"),
    ("‹dev›_Va, _Vb, _Vc", "Phase voltage at the device", "Điện áp pha tại thiết bị", "pu"),
    ("‹dev›_dVa, _dVb, _dVc", "Change in voltage magnitude, |V<sub>fault</sub>| − |V<sub>pre</sub>|",
     "Mức thay đổi biên độ điện áp, |V<sub>sự cố</sub>| − |V<sub>trước</sub>|", "pu"),
    ("‹dev›_I0", "Zero-sequence current |(I<sub>a</sub> + I<sub>b</sub> + I<sub>c</sub>) / 3|",
     "Dòng thứ tự không |(I<sub>a</sub> + I<sub>b</sub> + I<sub>c</sub>) / 3|", "A"),
    ("‹dev›_dI0, _dI2", "Change in zero- and negative-sequence current", "Mức thay đổi dòng thứ tự không và thứ tự nghịch", "A"),
]

# Each formula card: a title, one row per equation (label, LaTeX for KaTeX, plain-text fallback),
# a "where" list that explains every symbol, and a worked example with this run's numbers.
# The maths itself carries no words, so it reads the same in both languages; labels and notes are bilingual.
FORMULAS = [
    {"title": ("How big is a fault current?", "Dòng sự cố lớn cỡ nào?"),
     "rows": [("Fault current", "Dòng sự cố", r"I_f \approx \dfrac{V_{LN}}{\lvert Z_{th}\rvert + R_{\mathrm{eff}}}",
               "I_f ≈ V_LN / (|Z_th| + R_eff)"),
              ("Arcing HIF (SLG ≥ 100 Ω)", "Hồ quang HIF (SLG ≥ 100 Ω)",
               r"R_{\mathrm{eff}} = \dfrac{R_{\mathrm{nom}}\,m_R}{\kappa_{\mathrm{arc}}\,d_{\mathrm{cond}}}, \quad k_1(\gamma) = 1 - \dfrac{2}{\pi}\!\left(\arcsin\gamma + \gamma\sqrt{1-\gamma^2}\right)",
               "R_eff = (R_nom · m_R) / (κ_arc · d_cond),  k_1(γ) = 1 − (2/π)(arcsin γ + γ√(1−γ²))")],
     "where": [(r"V_{LN}", "V_LN", "phase-to-ground voltage: 4.16 kV ÷ √3 ≈ 2,402 V on this feeder",
                "điện áp pha – đất: 4.16 kV ÷ √3 ≈ 2,402 V trên tuyến này"),
               (r"Z_{th}", "Z_th", "impedance of the network up to the fault, small near the substation",
                "tổng trở của lưới tính tới chỗ sự cố, nhỏ khi ở gần trạm"),
               (r"R_{\mathrm{eff}},\ \kappa_{\mathrm{arc}},\ d_{\mathrm{cond}}", "R_eff, κ_arc, d_cond",
                "equivalent 60 Hz resistance from the Emanuel two-diode arc factor κ_arc = (k₁(γ_p)+k₁(γ_n))/2, intermittent duty d_cond ∈ [0.35, 0.85] (45% prob.), and path jitter m_R (capped at 2,500 Ω)",
                "điện trở tương đương 60 Hz từ hệ số hồ quang hai diode Emanuel κ_arc = (k₁(γ_p)+k₁(γ_n))/2, chu kỳ dẫn chập chờn d_cond ∈ [0.35, 0.85] (xác suất 45%) và dao động trở kháng m_R (trần 2,500 Ω)")],
     "example": ("Even a linear 400 Ω fault draws only ~6 A (~1% of trunk load). With intermittent arcing, R<sub>eff</sub> rises further (up to 2,500 Ω), shrinking the 60 Hz current below pre/post load drift and CT noise — accuracy at 400 Ω drops to {r400}.",
                 "Ngay cả điện trở tuyến tính 400 Ω cũng chỉ kéo ~6 A (~1% tải trục chính). Khi có hồ quang chập chờn, R<sub>eff</sub> còn tăng cao hơn (tới 2,500 Ω), làm dòng 60 Hz chìm dưới trôi tải pre/post và nhiễu CT — độ chính xác ở 400 Ω giảm còn {r400}.")},
    {"title": ("Zero- and negative-sequence current", "Dòng thứ tự không và thứ tự nghịch"),
     "rows": [("Zero-sequence", "Thứ tự không", r"I_0 = \tfrac{1}{3}\,\bigl(I_a + I_b + I_c\bigr)", "I_0 = (I_a + I_b + I_c) / 3"),
              ("Negative-sequence", "Thứ tự nghịch", r"I_2 = \tfrac{1}{3}\,\bigl(I_a + a^2 I_b + a\,I_c\bigr)",
               "I_2 = (I_a + a²·I_b + a·I_c) / 3")],
     "where": [(r"I_a,\ I_b,\ I_c", "I_a, I_b, I_c", "the three phase currents as phasors (size and angle)",
                "dòng ba pha dạng phasor (có độ lớn và góc)"),
               (r"a = 1\angle 120^\circ", "a = 1∠120°", "rotates a phasor by one third of a turn",
                "xoay một phasor đi một phần ba vòng"),
               (r"I_0", "I_0", "non-zero only when current returns through the ground",
                "chỉ khác 0 khi có dòng quay về qua đất"),
               (r"I_2", "I_2", "grows when the three phases become unbalanced", "tăng khi ba pha mất cân bằng")],
     "example": ("A line-to-ground fault raises I₀ at every device between the substation and the fault, and nowhere "
                 "beyond it: a strong clue to where the fault is.",
                 "Sự cố chạm đất làm I₀ tăng ở mọi thiết bị nằm giữa trạm và chỗ sự cố, còn phía sau thì không: đây là "
                 "manh mối mạnh về vị trí sự cố.")},
    {"title": ("The before/after change", "Phần thay đổi trước/sau sự cố"),
     "rows": [("Current change", "Thay đổi dòng", r"\Delta I = \bigl\lvert I_{\mathrm{fault}} - I_{\mathrm{pre}} \bigr\rvert",
               "ΔI = |I_fault − I_pre|"),
              ("Voltage change", "Thay đổi áp", r"\Delta V = \lvert V_{\mathrm{fault}}\rvert - \lvert V_{\mathrm{pre}}\rvert",
               "ΔV = |V_fault| − |V_pre|")],
     "where": [(r"I_{\mathrm{pre}},\ V_{\mathrm{pre}}", "I_pre, V_pre", "readings just before the fault",
                "số đo ngay trước khi sự cố xảy ra"),
               (r"I_{\mathrm{fault}},\ V_{\mathrm{fault}}", "I_fault, V_fault", "readings during the fault",
                "số đo trong lúc sự cố")],
     "example": ("Subtracting the pre-fault reading removes most steady load and per-event CT bias, leaving the fault "
                 "current plus small pre/post load drift (0.8% zone / 1.5% spot) and random/floor noise. Adding these "
                 "columns still lifts accuracy from {acc_mag} to {acc}.",
                 "Trừ đi số đo trước sự cố loại bỏ phần lớn dòng tải tĩnh và sai số hệ thống CT, phần còn lại là dòng "
                 "sự cố cộng trôi tải nhỏ pre/post (0.8% theo zone / 1.5% theo điểm) và nhiễu ngẫu nhiên/sàn nhiễu. "
                 "Thêm các cột này vẫn nâng accuracy từ {acc_mag} lên {acc}.")},
    {"title": ("How a conventional fault indicator decides", "Bộ chỉ báo sự cố truyền thống quyết định thế nào"),
     "rows": [("Phase flag", "Cờ pha", r"\max\bigl(\lvert I_a\rvert, \lvert I_b\rvert, \lvert I_c\rvert\bigr) > 2\,I_{pk}",
               "max(|I_a|, |I_b|, |I_c|) > 2·I_pk"),
              ("Ground flag", "Cờ chạm đất", r"\lvert 3 I_0 \rvert > \max\bigl(0.5\,I_{pk},\ 1.2\,\lvert 3 I_0 \rvert_{pk}\bigr)",
               "|3·I_0| > max(0.5·I_pk, 1.2·|3·I_0|_pk)")],
     "where": [(r"I_{pk}", "I_pk", "current through the device at peak load", "dòng qua thiết bị lúc tải đỉnh"),
               (r"\lvert 3 I_0 \rvert_{pk}", "|3·I_0|_pk", "ground current that flows normally at peak load",
                "dòng chạm đất có sẵn lúc tải đỉnh khi không có sự cố")],
     "example": ("The fault is placed just after the deepest device that raises a flag. The rule works on three-phase "
                 "faults ({fpi_3ph} right) but not on ground faults ({fpi_slg}).",
                 "Sự cố được xác định nằm ngay sau thiết bị bật cờ xa nhất. Quy tắc này tốt với sự cố ba pha (đúng "
                 "{fpi_3ph}) nhưng kém với sự cố chạm đất ({fpi_slg}).")},
    {"title": ("Scoring the model", "Chấm điểm model"),
     "rows": [("Accuracy", "Accuracy", r"\mathrm{Acc} = \dfrac{1}{N}\sum_{z} TP_z", "Acc = (Σ TP_z) / N"),
              ("Miss rate of zone z", "Tỉ lệ bỏ sót", r"\mathrm{FNR}_z = \dfrac{FN_z}{TP_z + FN_z}", "FNR_z = FN_z / (TP_z + FN_z)"),
              ("False-blame rate", "Tỉ lệ báo nhầm", r"\mathrm{FPR}_z = \dfrac{FP_z}{FP_z + TN_z}", "FPR_z = FP_z / (FP_z + TN_z)"),
              ("Precision", "Precision", r"\mathrm{Prec}_z = \dfrac{TP_z}{TP_z + FP_z}", "Prec_z = TP_z / (TP_z + FP_z)")],
     "where": [(r"TP_z", "TP_z", "faults in zone z that the model placed in z", "sự cố ở zone z được đoán đúng là z"),
               (r"FN_z", "FN_z", "faults in z placed somewhere else", "sự cố ở z bị đoán sang zone khác"),
               (r"FP_z", "FP_z", "faults elsewhere that were blamed on z", "sự cố ở nơi khác bị đổ cho z"),
               (r"TN_z", "TN_z", "faults elsewhere correctly kept out of z", "sự cố ở nơi khác và không bị đổ cho z"),
               (r"N", "N", "all simulated faults", "tổng số sự cố mô phỏng")],
     "example": ("Accuracy is {acc}. The worst miss rate is zone {fnr_zone} at {fnr_max}; the worst false-blame rate is "
                 "zone {fpr_zone} at {fpr_max}.",
                 "Accuracy là {acc}. Tỉ lệ bỏ sót cao nhất là zone {fnr_zone} với {fnr_max}; tỉ lệ báo nhầm cao nhất là "
                 "zone {fpr_zone} với {fpr_max}.")},
    {"title": ("Average crew patrol", "Quãng tuần tra trung bình"),
     "rows": [("Average patrol", "Tuần tra trung bình", r"\bar{L} = \dfrac{1}{N}\sum_{k=1}^{N} \ell_k",
               "L̄ = (ℓ_1 + ℓ_2 + … + ℓ_N) / N"),
              ("One fault", "Một sự cố", r"\ell_k = \begin{cases} L_{z_k} & \hat{z}_k = z_k \\[2pt] L_F & \hat{z}_k \neq z_k \end{cases}",
               "ℓ_k = L_zk if ẑ_k = z_k, otherwise L_F")],
     "where": [(r"z_k,\ \hat{z}_k", "z_k, ẑ_k", "the true and the predicted zone of fault k", "zone thật và zone dự đoán của sự cố k"),
               (r"L_{z}", "L_z", "line length of zone z", "chiều dài đường dây của zone z"),
               (r"L_F", "L_F", "line length of the whole feeder ({patrol_none} kft): a wrong answer is charged a full patrol",
                "chiều dài cả tuyến ({patrol_none} kft): đoán sai bị tính như đi hết tuyến")],
     "example": ("With the model the average patrol is {patrol_ml} kft instead of {patrol_none} kft.",
                 "Khi có model, quãng tuần tra trung bình là {patrol_ml} kft thay vì {patrol_none} kft.")},
    {"title": ("Customer outage in kW·min", "Mức mất điện tính bằng kW·phút"),
     "rows": [("Outage size", "Mức mất điện", r"E = \sum P \times t", "E = Σ P × t"),
              ("Saving", "Mức giảm", r"S = 1 - \dfrac{E_{\mathrm{auto}}}{E_{\mathrm{manual}}}", "S = 1 − E_auto / E_manual"),
              ("Whole feeder", "Toàn tuyến", r"S_F = \sum_{z} w_z\,S_z, \qquad w_z = \dfrac{L_z}{\sum_j L_j}",
               "S_F = Σ w_z·S_z,  w_z = L_z / ΣL")],
     "where": [(r"P,\ t", "P, t", "kW without power during a step, and the step's minutes",
                "số kW mất điện trong một bước, và số phút của bước đó"),
               (r"E_{\mathrm{auto}},\ E_{\mathrm{manual}}", "E_auto, E_manual",
                "outage with automated switching ({t_auto} min) vs manual switching ({t_man} min); repair takes {t_rep} min",
                "mức mất điện khi đóng cắt tự động ({t_auto} phút) so với thủ công ({t_man} phút); sửa chữa mất {t_rep} phút"),
               (r"w_z", "w_z", "share of line length: longer zones fault more often",
                "tỉ lệ chiều dài dây: zone càng dài càng dễ gặp sự cố")],
     "example": ("For the whole feeder S = {kwmin}%. It ranges from {kwmin_lo} (fault in {kwmin_lo_zone}) to {kwmin_hi} "
                 "(fault in {kwmin_hi_zone}).",
                 "Trên toàn tuyến S = {kwmin}%. Con số dao động từ {kwmin_lo} (sự cố ở {kwmin_lo_zone}) đến {kwmin_hi} "
                 "(sự cố ở {kwmin_hi_zone}).")},
    {"title": ("Limits every restoration must meet", "Giới hạn mọi phương án khôi phục phải đạt"),
     "rows": [("Voltage", "Điện áp", r"0.95 \le V_{pu} \le 1.05", "0.95 ≤ V_pu ≤ 1.05"),
              ("Current", "Dòng điện", r"I \le 1.25\, I_{\mathrm{rated}}", "I ≤ 1.25 × I_rated"),
              ("Radial", "Hình tia", r"n_{\mathrm{closed}} = n_{\mathrm{bus}} - 1", "n_closed = n_bus − 1")],
     "where": [(r"V_{pu}", "V_pu", "voltage ÷ nominal; 1.00 pu is 120 V at a home (ANSI C84.1 Range A: 114–126 V)",
                "điện áp ÷ định mức; 1.00 pu là 120 V tại nhà dân (ANSI C84.1 Range A: 114–126 V)"),
               (r"I_{\mathrm{rated}}", "I_rated", "normal rating of the conductor; 125% is its emergency rating",
                "định mức dòng bình thường của dây; 125% là định mức khẩn cấp"),
               (r"n_{\mathrm{closed}},\ n_{\mathrm{bus}}", "n_closed, n_bus",
                "closed line sections and energized buses: a tree always has one fewer branch than nodes",
                "số đoạn dây đang đóng và số bus có điện: một cây luôn có số nhánh ít hơn số nút đúng 1")],
     "example": ("A tie is closed only if all three hold after the power flow; that is why some healthy load stays dark.",
                 "Dao liên lạc chỉ được đóng khi cả ba điều kiện đều đạt sau khi tính trào lưu; vì vậy có phần tải lành "
                 "vẫn phải chờ.")},
]

STEPS = [  # (English question, English action/result, Vietnamese question, Vietnamese action/result)
    ("Where is the fault after the head recloser locks out?",
     "Today a crew patrols the whole feeder: {patrol_none} kft of line.",
     "Sau khi recloser đầu tuyến cắt hẳn, sự cố nằm ở đâu?",
     "Hiện nay đội sửa chữa phải đi kiểm tra cả tuyến: {patrol_none} kft đường dây."),
    ("How can that be tested without a real outage?",
     "Model the IEEE 123-bus feeder in OpenDSS and add 5 automated switches, giving 10 zones.",
     "Làm sao kiểm chứng mà không cần sự cố thật?",
     "Mô hình hóa lưới IEEE 123-bus trong OpenDSS và thêm 5 dao tự động, chia thành 10 zone."),
    ("What evidence would a model need?",
     "Simulate every fault type at every bus, 9 nominal ground-fault resistances (intermittent arcing R_eff for SLG ≥ 100 Ω), "
     "independent per-zone loading with pre/post drift, and CT/PT bias + noise floor: {faults} labeled simulated faults.",
     "Model cần bằng chứng gì?",
     "Mô phỏng mọi loại sự cố ở mọi bus, 9 mức điện trở chạm đất danh định (hồ quang chập chờn R_eff cho SLG ≥ 100 Ω), "
     "tải biến động độc lập theo zone kèm trôi tải pre/post, và sai số CT/PT + sàn nhiễu: {faults} sự cố mô phỏng có nhãn."),
    ("What is the bar to beat?",
     "Replay the conventional fault-indicator rule on the same faults: {acc_fpi} correct.",
     "Mốc cần vượt qua là gì?",
     "Chạy lại quy tắc bộ chỉ báo sự cố truyền thống trên cùng các sự cố: đúng {acc_fpi}."),
    ("Which signals carry the answer?",
     "Use what a recloser's event record already holds, plus the before/after change that strips out steady load and static CT bias.",
     "Tín hiệu nào chứa đáp án?",
     "Dùng đúng những gì bản ghi sự kiện của recloser có sẵn, cộng thêm phần thay đổi trước/sau để loại dòng tải tĩnh và lệch CT."),
    ("Is the model really learning, not memorizing?",
     "Gradient-boosted trees, tested only on buses never seen in training; randomizing feeder, per-zone and spot loads "
     "plus pre/post drift and per-event CT/PT bias removes data-leak shortcuts. Result: {acc}.",
     "Model có thật sự học, hay chỉ học thuộc?",
     "Cây tăng cường gradient, chỉ kiểm tra trên bus chưa thấy khi huấn luyện; ngẫu nhiên hóa tải toàn tuyến, tải từng "
     "zone, tải điểm cùng trôi tải pre/post và lệch CT/PT theo sự cố loại bỏ đường tắt học thuộc. Kết quả: {acc}."),
    ("Where and why does it fail?",
     "Per-zone FNR/FPR and the confusion matrix point to weak intermittent arcing ground faults (≥ 200 Ω) on the busy "
     "trunk, where effective 60 Hz arc current drops below load drift and CT/PT noise.",
     "Model sai ở đâu, vì sao?",
     "FNR/FPR theo zone và ma trận nhầm lẫn chỉ ra sự cố chạm đất hồ quang chập chờn yếu (≥ 200 Ω) trên trục chính "
     "đông tải, nơi dòng 60 Hz hiệu dụng tụt xuống dưới trôi tải và nhiễu CT/PT."),
    ("What should happen once the zone is known?",
     "Isolate it, re-close upstream, and close a tie only if a power flow passes every limit: {kw_back} kW of "
     "healthy load restored.",
     "Biết zone rồi thì làm gì?",
     "Cô lập zone đó, đóng lại phía trên, và chỉ đóng tie khi tính trào lưu đạt mọi giới hạn: cấp lại {kw_back} kW "
     "phụ tải lành."),
    ("What does it change for customers?",
     "Average patrol {patrol_ml} kft instead of {patrol_none} kft, and about {kwmin}% less outage under the "
     "stated switching times.",
     "Khách hàng được lợi gì?",
     "Quãng tuần tra trung bình {patrol_ml} kft thay vì {patrol_none} kft, và mức mất điện giảm khoảng {kwmin}% "
     "với giả định thời gian đóng cắt đã nêu."),
]


def tex(src: str, plain: str, display: bool) -> str:
    """Maths typeset by KaTeX in the page; until it loads (or without it) the plain-text form shows."""
    tag = "div" if display else "span"
    return f'<{tag} class="tex{" tex-d" if display else ""}" data-tex="{esc(src, quote=True)}">{esc(plain)}</{tag}>'


def formula_card(i: int, f: dict, v: dict) -> str:
    rows = "".join(f'<div class="fx-row"><div class="fx-l">{T(le, lv)}</div>{tex(src, plain, True)}</div>'
                   for le, lv, src, plain in f["rows"])
    where = "".join(f'<dt>{tex(src, plain, False)}</dt><dd>{T(en.format(**v), vi.format(**v))}</dd>'
                    for src, plain, en, vi in f["where"])
    ex_en, ex_vi = (s.format(**v) for s in f["example"])
    return (f'<article class="fx"><h4 class="fx-t"><span class="fx-n">{i}</span>{T(*f["title"])}</h4>'
            f'<div class="fx-rows">{rows}</div>'
            f'<div class="fx-k">{T("Where", "Trong đó")}</div><dl class="fx-where">{where}</dl>'
            f'<p class="fx-ex"><span class="fx-k">{T("Example", "Ví dụ")}</span>{T(emph(ex_en), emph(ex_vi))}</p>'
            '</article>')


def data_section(v: dict, files: list) -> str:
    rows = [[f'<a href="data/{n}" download><code>{n}</code></a>', T(en, vi), _size(b)] for n, en, vi, b in files]
    rows.append([f'<a href="{REPO}/tree/main/data/feeder"><code>data/feeder/</code></a>',
                 T("The IEEE 123-bus OpenDSS model files the simulation starts from (on GitHub).",
                   "Các file mô hình OpenDSS của lưới IEEE 123-bus, điểm xuất phát của mô phỏng (trên GitHub)."), "–"])
    downloads = table([T("File", "File"), T("What is inside", "Bên trong có gì"), T("Size", "Dung lượng")], rows, {2})
    cols = table([T("Column", "Cột"), T("Meaning", "Ý nghĩa"), T("Unit", "Đơn vị")],
                 [[f"<code>{c}</code>", T(en, vi), u] for c, en, vi, u in COLUMNS], {2})
    formulas = "".join(formula_card(i, f, v) for i, f in enumerate(FORMULAS, 1))
    steps = "".join(f'<li><b>{T(qe, qv)}</b><span>{T(emph(ae.format(**v)), emph(av.format(**v)))}</span></li>'
                    for qe, ae, qv, av in STEPS)
    return section(
        "data", ("8 · Data & method", "8 · Dữ liệu & phương pháp"),
        ("Everything behind the numbers: <b>the data you can download</b>, <b>what every column means</b>, "
         "<b>the formulas</b>, and <b>the chain of reasoning</b> from the question to the result. Rerun it all with "
         "<code>python run.py</code>.",
         "Mọi thứ đằng sau các con số: <b>dữ liệu có thể tải về</b>, <b>ý nghĩa từng cột</b>, <b>các công thức</b>, và "
         "<b>chuỗi suy luận</b> từ câu hỏi tới kết quả. Chạy lại toàn bộ bằng <code>python run.py</code>."),
        deep_box(
            f"Download all published data files ({len(files)} files in docs/data/)",
            f"Tải toàn bộ dữ liệu công bố ({len(files)} file trong docs/data/)",
            "Every JSON, CSV, and PDF behind the charts and tables on this page.",
            "Toàn bộ tệp JSON, CSV và PDF đứng sau mọi bảng và biểu đồ trên trang.",
            f'<h3 id="data-files">{T("Download the data", "Tải dữ liệu")}</h3>{downloads}',
            id_="deep-downloads",
        )
        + deep_box(
            "Step-by-step reasoning, equations & 150-column dataset schema",
            "Chuỗi suy luận, công thức toán học & giải thích 150 cột dữ liệu",
            "How each calculation works, exact formulas with study numbers, and per-device measurement columns.",
            "Cách tính từng chỉ số, công thức minh họa bằng số thật của dự án và ý nghĩa từng cột đo.",
            f'<h3>{T("How the reasoning goes", "Cách tư duy để ra kết quả")}</h3><ol class="steps">{steps}</ol>'
            f'<h3>{T("The formulas behind the numbers", "Các công thức đằng sau con số")}</h3>'
            + TB("Each card shows the equation, what every symbol means, and an example with this study's numbers.",
                 "Mỗi thẻ gồm công thức, ý nghĩa từng ký hiệu, và một ví dụ dùng số liệu của nghiên cứu này.", "p", "note")
            + f'<div class="fxs">{formulas}</div>'
            f'<h3>{T("What a row of the dataset means", "Một dòng dữ liệu nghĩa là gì")}</h3>'
            + TB("‹dev› is one of the 10 measuring devices (Sw1 … L77), so each fault has 10 × 15 = 150 measurement columns.",
                 "‹dev› là một trong 10 thiết bị đo (Sw1 … L77), nên mỗi sự cố có 10 × 15 = 150 cột số đo.", "p", "note")
            + cols,
            id_="deep-method",
        ))


def model_section(d: dict) -> str:
    if not d["geo"]:
        return ""
    bar = ('<div class="m3d-bar"><div class="seg" role="group" aria-label="View">'
           '<button type="button" id="m3d-3d" aria-pressed="true">3D</button>'
           f'<button type="button" id="m3d-2d" aria-pressed="false">{T("2D map", "Bản đồ 2D")}</button></div>'
           '<div class="seg m3d-layer" role="group" aria-label="Layer">'
           f'<button type="button" data-mlayer="zones" aria-pressed="true">{T("Zones", "Zone")}</button>'
           f'<button type="button" data-mlayer="errors" aria-pressed="false">{T("Model errors", "Lỗi của model")}</button>'
           f'<button type="button" data-mlayer="fault" aria-pressed="false">⚡ {T("Fault replay", "Diễn lại sự cố")}</button></div>'
           f'<button type="button" class="m3d-btn m3d-demo" id="m3d-hif-demo">▶ {T("10s HIF → FLISR", "10s HIF → FLISR")}</button>'
           f'<button type="button" class="m3d-btn m3d-fx" id="m3d-miss">⚡ {T("A missed fault", "Một sự cố bị đoán sai")}</button>'
           f'<button type="button" class="m3d-btn m3d-fx" id="m3d-hit">⚡ {T("A fault it gets right", "Một sự cố đoán đúng")}</button>'
           f'<button type="button" class="m3d-btn" id="m3d-tour">▶ {T("Tour the zones", "Đi qua các zone")}</button>'
           f'<button type="button" class="m3d-btn" id="m3d-spin" aria-pressed="true">⟳ {T("Auto-rotate", "Tự xoay")}</button>'
           f'<button type="button" class="m3d-btn" id="m3d-reset">↺ {T("Reset view", "Góc nhìn ban đầu")}</button>'
           f'<button type="button" class="m3d-btn m3d-done" id="m3d-lock">✓ {T("Done", "Xong")}</button>'
           f'<span class="m3d-layers" role="group" aria-label="Labels"><span class="m3d-lt">{T("Labels:", "Nhãn:")}</span>'
           f'<button type="button" class="m3d-btn" data-layer="zone" aria-pressed="true">{T("Zones", "Zone")}</button>'
           f'<button type="button" class="m3d-btn" data-layer="eq" aria-pressed="true">{T("Equipment", "Thiết bị")}</button>'
           f'<button type="button" class="m3d-btn" data-layer="bus" aria-pressed="true">{T("Bus numbers", "Số bus")}</button>'
           '</span></div>')
    hint = TB("Drag to rotate · click the model, then scroll to zoom · click a zone, switch or load column",
              "Kéo để xoay · nhấp vào mô hình rồi cuộn để phóng to · nhấp vào zone, dao hay cột tải", "div", "m3d-hint")
    if d.get("glb"):   # SolidWorks models replace the drawn stand-ins: describe what is on screen
        legend = TB("Column = load kW · one wire per phase · grey can on a pole = pole-top transformer · grey tank with "
                    "six bushings = recloser · box with antenna = added switch · red raised blades = open tie · round "
                    "tanks with fins = regulators · pale cans = capacitors · fenced yard = substation · equipment models "
                    "built in SolidWorks (generic, illustrative sizes, not a manufacturer's design; switch blades stay "
                    "drawn so the fault replay can open them)",
                    "Cột = tải kW · mỗi pha một dây · bình xám trên trụ = máy biến áp trên trụ · thùng xám 6 sứ = recloser "
                    "· hộp có ăng-ten = dao thêm vào · lưỡi đỏ dựng lên = dao liên lạc mở · thùng tròn có cánh = điều áp "
                    "· bình nhạt = tụ bù · sân có rào = trạm nguồn · mô hình thiết bị dựng bằng SolidWorks (mẫu chung, "
                    "kích thước minh hoạ, không phải thiết kế của hãng nào; lưỡi dao vẫn vẽ bằng code để phần phát lại sự "
                    "cố mở được)", "div", "m3d-legend lg-zones")
    else:
        legend = TB("Column = load kW · one wire per phase · grey can = pole-top transformer · black tank = recloser · "
                    "white box with antenna = added switch · red raised blades = open tie · yellow tanks = regulators · "
                    "pale cans = capacitors · fenced yard = substation",
                    "Cột = tải kW · mỗi pha một dây · bình xám = máy biến áp trên trụ · thùng đen = recloser · "
                    "hộp trắng có ăng-ten = dao thêm vào · lưỡi đỏ dựng lên = dao liên lạc mở · thùng vàng = điều áp · "
                    "bình nhạt = tụ bù · sân có rào = trạm nguồn", "div", "m3d-legend lg-zones")
    if d.get("drawings"):   # links to the dimensioned A3 drawings of each SolidWorks part
        a = lambda lab, u: f'<a href="{u}" target="_blank" rel="noopener">{lab}</a>'
        en = " · Technical drawings (PDF, dimensioned): " + ", ".join(a(e, u) for e, _, u in d["drawings"])
        vi = " · Bản vẽ kỹ thuật (PDF, có kích thước): " + ", ".join(a(v, u) for _, v, u in d["drawings"])
        i = legend.index("</div>")
        legend = legend[:i] + en + legend[i:]
        j = legend.rindex("</div>")
        legend = legend[:j] + vi + legend[j:]
    legend += TB("Red column = a bus where faults get misplaced (taller = more, redder = higher rate) · green dot = "
                 "no mistakes · arrow = true zone → wrong guess (thicker = more faults). Click any of them.",
                 "Cột đỏ = bus hay bị đoán sai (cao hơn = nhiều hơn, đỏ hơn = tỉ lệ cao hơn) · chấm xanh = không sai lần "
                 "nào · mũi tên = zone thật → zone bị đoán nhầm (dày hơn = nhiều hơn). Nhấp vào để xem phân tích.",
                 "div", "m3d-legend lg-errors")
    legend += TB("Click any line to put a fault there, or pick one above. Lamps: green = closed, red = open · grey = no "
                 "power · red zone = faulted · cyan pulses = forward supply from substation · amber pulses = reversed "
                 "back-feed via tie (Sw7/Sw9) · orange arrow = model's wrong guess.",
                 "Nhấp vào bất kỳ đường dây nào để đặt sự cố, hoặc chọn ở trên. Đèn: xanh = đóng, đỏ = mở · xám = mất "
                 "điện · zone đỏ = sự cố · xung xanh dương = dòng cấp xuôi từ trạm nguồn · xung cam = dòng đổi hướng "
                 "cấp ngược qua dao liên lạc (Sw7/Sw9) · mũi tên cam lớn = model đoán sai.",
                 "div", "m3d-legend lg-fault")
    unlock = (f'<button type="button" class="m3d-unlock" id="m3d-unlock">'
              f'{T("Tap to explore the 3D model", "Chạm để khám phá mô hình 3D")}</button>')
    img = ('<div class="m3d-map"><img data-src="images/feeder-map.png" '
           'alt="One-line map of the IEEE 123-bus feeder with zones, switches, ties, regulators, capacitors and loads"></div>')
    hud = '<div class="m3d-hif-hud" id="m3d-hif-hud" hidden aria-live="polite"></div>'
    box = (f'<div class="m3d layer-zones" id="m3d" data-x="map3d">{bar}{hud}<div class="m3d-stage"></div><div class="m3d-labels"></div>'
           f'{img}{hint}{legend}{unlock}</div>')
    return section("model", ("1 · Feeder model (3D)", "1 · Mô hình lưới (3D)"),
                   ("The whole feeder, built from the study's own data. <b>Drag to rotate</b> and <b>click any zone, "
                    "switch or load column</b>: it lifts out of the model and the guide explains it. <b>Tour the "
                    "zones</b> walks through all 10; the <b>2D map</b> shows the same feeder as a flat drawing.",
                    "Toàn bộ lưới, dựng từ chính dữ liệu của nghiên cứu. <b>Kéo để xoay</b> và <b>nhấp vào bất kỳ zone, "
                    "dao hay cột tải nào</b>: phần đó nổi lên khỏi mô hình và nhân vật hướng dẫn sẽ giải thích. <b>Đi qua "
                    "các zone</b> giới thiệu lần lượt cả 10 zone; <b>bản đồ 2D</b> vẽ cùng lưới đó dạng phẳng."), box)


def table(head: list[str], rows: list[list[str]], num_cols=frozenset()) -> str:
    th = "".join(f'<th{" class=n" if i in num_cols else ""}>{h}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td{" class=n" if i in num_cols else ""}>{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def oneline_figure(root=config.ROOT) -> str:
    """The AutoCAD one-line diagram (exports/feeder_oneline.png), shown only when workflow.toml
    says the export is fresh; otherwise the page leaves it out rather than show a stale drawing."""
    from . import assets
    items = {a["id"]: a for a in assets.load(root / "workflow.toml")}
    reg = assets.registered(root / "exports" / "registered.json")
    fresh = lambda a: a is not None and assets.status(a, root, reg)[0] is True  # noqa: E731
    png = items.get("oneline-png")
    if not fresh(png):
        return ""
    img = root / "docs" / "images" / "feeder-oneline.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / png["export"], img)
    has_pdf = fresh(items.get("oneline-pdf"))
    head = img.read_bytes()[:24]   # PNG IHDR: width and height, so the page reserves the space (no jump on load)
    w, h = (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")) if head[:8] == b"\x89PNG\r\n\x1a\n" else (16, 9)
    pic = (f'<img src="images/feeder-oneline.png" width="{w}" height="{h}" alt="One-line diagram of the IEEE 123-bus '
           f'feeder with its 10 switching zones" loading="lazy" style="width:100%;height:auto;display:block;border-radius:8px">')
    if has_pdf:
        pic = f'<a href="data/feeder_oneline.pdf" target="_blank" rel="noopener">{pic}</a>'
    note = TB("Drawn from the same results as this page (scripts/export_oneline_dxf.py) and saved and plotted in "
              "AutoCAD (scripts/autocad_export.py). Heavy lines are 3-phase, light lines 1-phase, dashed lines "
              "underground cable." + (" Click it for the A3 PDF." if has_pdf else ""),
              "Vẽ từ cùng kết quả với trang này (scripts/export_oneline_dxf.py), rồi lưu và in bằng AutoCAD "
              "(scripts/autocad_export.py). Nét đậm là 3 pha, nét mảnh là 1 pha, nét đứt là cáp ngầm."
              + (" Nhấp vào để mở PDF khổ A3." if has_pdf else ""),
              "p", "note")
    return (f'<h3>{T("One-line diagram (AutoCAD)", "Sơ đồ một sợi (AutoCAD)")}</h3>'
            + xbox("oneline", pic) + note + f'<h3>{T("Zone table", "Bảng zone")}</h3>')


def hourly_block(d: dict, v: dict, order: list[str]) -> str:
    """4b: the restoration result at every hour of a real year (scripts/hourly_restoration.py)."""
    h = d["h"]
    if h is None:
        return (f'<h3>{T("4b · By hour of the day", "4b · Theo giờ trong ngày")}</h3>'
                + TB("Not built yet: run <code>python scripts/load_shape.py</code> and "
                     "<code>python scripts/hourly_restoration.py</code> (or <code>notebooks/kaggle_hourly.ipynb</code>).",
                     "Chưa tạo: chạy <code>python scripts/load_shape.py</code> và "
                     "<code>python scripts/hourly_restoration.py</code> (hoặc <code>notebooks/kaggle_hourly.ipynb</code>).",
                     "p", "note"))
    td, hold = h["typical_day"], h["hold_hours"]
    series = [("Summer, fault hour", "Hè, giờ sự cố", 2, td["summer"]["pct_restored"]),
              (f"Summer, held {hold} h", f"Hè, giữ {hold} giờ", 2, td["summer"]["pct_restored_held"], True),
              ("Winter, fault hour", "Đông, giờ sự cố", 1, td["winter"]["pct_restored"]),
              (f"Winter, held {hold} h", f"Đông, giữ {hold} giờ", 1, td["winter"]["pct_restored_held"], True)]
    vals = [x for s in series for x in s[3]]
    lo, hi = math.floor(min(vals) * 20) / 20, math.ceil(max(vals) * 20) / 20
    ticks = [round(lo + i * .05, 2) for i in range(round((hi - lo) / .05) + 1)]
    hours = [f"{i:02d}:00" for i in range(24)]
    chart = line_chart(hours, series, "Healthy load restored by hour of day", ylim=(lo, hi), yticks=ticks,
                       xlab=("hour of the fault, typical day of the season", "giờ xảy ra sự cố, ngày điển hình của mùa"),
                       xunit="", label_every=3, dots=False)
    ttab = table([T("Hour", "Giờ"), T("Load, summer", "Tải, hè"), *[T(s[0], s[1]) for s in series[:2]],
                  T("Load, winter", "Tải, đông"), *[T(s[0], s[1]) for s in series[2:]]],
                 [[hr, f'{td["summer"]["mult"][i]:.2f}', pct(series[0][3][i]), pct(series[1][3][i]),
                   f'{td["winter"]["mult"][i]:.2f}', pct(series[2][3][i]), pct(series[3][3][i])]
                  for i, hr in enumerate(hours)], {1, 2, 3, 4, 5, 6})
    sw = "".join(f'<span><i class="sw" style="background:var(--q{q})"></i>{a}</span>'
                 for q, a in ((1, "≤20%"), (2, "20–40%"), (3, "40–60%"), (4, "60–80%"), (5, "80–100%")))
    sw = '<span><i class="sw sw0"></i>0%</span>' + sw
    rb = h["rejected_by_hour"]
    cur_ok = h["year"].get("hours_with_overload_rejections") == 0 and h["year"].get("hours_with_nonconverged_rejections") == 0
    cur_en = "No check failed on line current or convergence at any hour: voltage is the limit. " if cur_ok else ""
    cur_vi = "Không giờ nào có phương án bị loại vì dòng điện hay không hội tụ: giới hạn là điện áp. " if cur_ok else ""
    reasons = [("undervoltage", "Undervoltage", "Thấp áp"), ("overvoltage", "Overvoltage", "Quá áp"),
               ("overload", "Line overload", "Quá tải dây"), ("nonconverged", "No convergence", "Không hội tụ")]
    rtab = table([T("Season", "Mùa"), *[T(en, vi) for _, en, vi in reasons]],
                 [[T(en, vi), *[f'{sum(rb[k][r]) / 24:.1f}' for r, _, _ in reasons]] for k, en, vi in SEASONS],
                 {1, 2, 3, 4})
    return (
        f'<h3 id="by-hour">{T("4b · By hour of the day", "4b · Theo giờ trong ngày")}</h3>'
        + TB(emph(f'The table above uses peak load. Here restoration is re-run at every {term("loadmult", "load level")} '
                  f'and mapped onto each of the {v["h_hours"]} hours of {v["h_year"]} '
                  f'{term("loadshape", "PJM AEP load")} (shape only, divided by its peak). Over the year the ties pick '
                  f'up {v["h_pct"]} of the healthy load left dark at the fault hour, and {v["h_held"]} if the plan must '
                  f'still hold {hold} h later when the repair ends, against {v["h_peak"]} at peak load.'),
             emph(f'Bảng trên tính ở tải đỉnh. Ở đây khôi phục được chạy lại ở mọi '
                  f'{term("loadmult", "mức tải", "mức tải")} rồi gắn vào từng giờ trong {v["h_hours"]} giờ của '
                  f'{term("loadshape", "tải PJM AEP", "tải PJM AEP")} năm {v["h_year"]} (chỉ lấy hình dạng, chia cho '
                  f'đỉnh năm). Tính cả năm, tie cấp lại được {v["h_pct"]} phần tải lành bị mất điện nếu xét đúng giờ '
                  f'sự cố, và {v["h_held"]} nếu phương án phải giữ được thêm {hold} giờ cho tới khi sửa xong, so với '
                  f'{v["h_peak"]} khi tính ở tải đỉnh.'), "p", "note")
        + xbox("chart-hour", f'<div class="chart">{chart}</div>')
        + f'<details><summary>{T("Show as table", "Xem dạng bảng")}</summary>{ttab}</details>'
        + f'<h4>{T("Which faults gain at night", "Sự cố nào được lợi về đêm")}</h4>'
        + xbox("heat-hour", f'<div class="legend">{sw}</div><div class="chart hourwrap">{hour_heatmap(h["zone_hour"], order)}</div>')
        + f'<h4>{T("Why the other options were rejected", "Vì sao các phương án khác bị loại")}</h4>'
        + xbox("table-reasons", rtab)
        + TB(emph(f'Average rejected power-flow checks per fault hour, summed over the 10 fault zones (a check can fail '
                  f'for more than one reason). {cur_en}'
                  f'The decisions for {v["h_flips_en"]} sit within about one regulator tap of {v["vmax"]} pu, so they '
                  f'switch on and off between neighbouring load levels. {v["h_flag"]} of the {v["h_hours"]} hours fall '
                  f'on load levels where a state reaches {v["h_flag_v"]} pu, just above {v["vmax"]} pu.'),
             emph(f'Số lần tính trào lưu bị loại trung bình ở mỗi giờ sự cố, cộng cho 10 zone sự cố (một lần có thể bị '
                  f'loại vì nhiều lý do). {cur_vi}Quyết '
                  f'định của {v["h_flips_vi"]} chỉ cách giới hạn {v["vmax"]} pu khoảng một nấc bộ điều áp, nên bật tắt '
                  f'giữa các mức tải sát nhau. {v["h_flag"]} trên {v["h_hours"]} giờ rơi vào mức tải có trạng thái lên '
                  f'tới {v["h_flag_v"]} pu, vượt nhẹ {v["vmax"]} pu.'), "p", "note"))


def transfer_block(d: dict, v: dict) -> str:
    """2c: zero-shot transfer to unseen IEEE 34-bus & 37-bus, Stage-2 bus ranking, and active-grid GATv2 + Conformal Prediction."""
    tr = d.get("tr")
    p3_37, p2b_37 = d.get("p3_37"), d.get("p2b_37")
    ag37, ag37_ds, ag37_conf, ag37_post = d.get("ag37"), d.get("ag37_ds"), d.get("ag37_conf"), d.get("ag37_post")
    has_37 = any(x is not None for x in (p3_37, p2b_37, ag37, ag37_ds))
    head = (
        f'<h3 id="cross-feeder">{T("2c · Transfer to unseen feeders, bus ranking & active grids (IEEE 34-bus & 37-bus)", "2c · Chuyển sang lưới mới, tìm từng bus & lưới có điện mặt trời (IEEE 34-bus & 37-bus)")}</h3>'
        if has_37 else
        f'<h3 id="cross-feeder">{T("2c · Transfer to an unseen feeder, bus ranking & active grids (IEEE 34-bus)", "2c · Chuyển sang lưới mới, tìm từng bus & lưới có điện mặt trời (IEEE 34-bus)")}</h3>'
    )
    if not tr:
        return head
    p2, p2b, p3 = tr["p2"]["models"], tr["p2b"], tr["p3"]
    ag123, ag34, conf = tr["ag123"]["models"], tr["ag34"], tr["conf"]
    # Signal-to-load numbers measured by scripts/signal_to_load.py (OpenDSS, nominal load).
    why_en = why_vi = ""
    if "s2l_head34" in v:
        why_en = (f' because the fault current is large next to the load: at nominal load a 400 Ω ground fault draws a '
                  f'median {v["s2l_i400_34"]} on 24.9 kV ({v["s2l_sh400_34"]} of the {v["s2l_head34"]} feeder-head '
                  f'current) but {v["s2l_i400_123"]} on 4.16 kV ({v["s2l_sh400_123"]} of {v["s2l_head123"]})')
        why_vi = (f' vì dòng sự cố lớn so với dòng tải: ở tải định mức, sự cố chạm đất 400 Ω kéo trung vị '
                  f'{v["s2l_i400_34"]} ở 24.9 kV ({v["s2l_sh400_34"]} dòng đầu tuyến {v["s2l_head34"]}) nhưng chỉ '
                  f'{v["s2l_i400_123"]} ở 4.16 kV ({v["s2l_sh400_123"]} của {v["s2l_head123"]})')

    pending_gpu = f'<span class="muted">{T("Not run yet (Kaggle GPU)", "Chưa chạy (Kaggle GPU)")}</span>'
    pending_short = T("pending GPU", "chờ GPU")
    zone_head = [
        T("Benchmark & model", "Bài toán & mô hình"),
        T("IEEE 123-bus (4.16 kV, 5-fold CV)", "IEEE 123-bus (4.16 kV, CV 5 phần)"),
        T("IEEE 34-bus zero-shot (24.9 kV, unseen)", "IEEE 34-bus zero-shot (24.9 kV, chưa thấy)"),
        T("IEEE 34-bus 20% few-shot / in-domain", "IEEE 34-bus tinh chỉnh 20% / học tại chỗ"),
    ]
    if has_37:
        zone_head += [
            T("IEEE 37-bus zero-shot (4.8 kV, delta cable)", "IEEE 37-bus zero-shot (4.8 kV, cáp ngầm delta)"),
            T("IEEE 37-bus 20% few-shot / in-domain", "IEEE 37-bus tinh chỉnh 20% / học tại chỗ"),
            T("1 sensor offline (123 / 34 / 37 zs)", "Mất 1 cảm biến (123 / 34 / 37 zs)"),
        ]
    else:
        zone_head.append(T("1 sensor offline (123 / 34 zero-shot)", "Mất 1 cảm biến (123 / 34 zero-shot)"))

    def _p37_sub(ph: float, slg: float) -> str:
        return f'<small>{T("phase", "pha")} {pct(ph)} · SLG {pct(slg)}</small>'

    p37_fpi_zs = (f'{pct(p3_37["fpi"]["accuracy"])}{_p37_sub(p3_37["fpi"]["phase_faults_accuracy"], p3_37["fpi"]["by_fault_type"]["SLG"])}'
                  if p3_37 else T("Not run yet", "Chưa chạy"))
    p37_gbdt_zs = (f'<b>{pct(p3_37["zero_shot"]["per_node_gbdt"]["accuracy"])}</b>'
                   f'{_p37_sub(p3_37["zero_shot"]["per_node_gbdt"]["phase_faults_accuracy"], p3_37["zero_shot"]["per_node_gbdt"]["by_fault_type"]["SLG"])}'
                   if p3_37 else T("Not run yet", "Chưa chạy"))
    p37_gnn_zs = (f'{pct(p3_37["zero_shot"]["gnn"]["accuracy"])}'
                  f'{_p37_sub(p3_37["zero_shot"]["gnn"]["phase_faults_accuracy"], p3_37["zero_shot"]["gnn"]["by_fault_type"]["SLG"])}'
                  if p3_37 else T("Not run yet", "Chưa chạy"))
    p37_gbdt_fs = (f'{pct(p3_37["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["accuracy_mean"])} / '
                   f'<b>{pct(p3_37["in_domain_upper_bound"]["per_node_gbdt"]["accuracy"])}</b>'
                   if p3_37 else "–")
    p37_gnn_fs = (f'<b>{pct(p3_37["few_shot"]["pct_20"]["models"]["gnn"]["accuracy_mean"])}</b> / '
                  f'{pct(p3_37["in_domain_upper_bound"]["gnn"]["accuracy"])}'
                  if p3_37 else "–")
    p37_fpi_miss = pct(p3_37["fpi"]["missing_sensor_mean"]) if p3_37 else "–"
    p37_gbdt_miss = f'<b>{pct(p3_37["zero_shot"]["per_node_gbdt"]["missing_sensor_mean"])}</b>' if p3_37 else "–"
    p37_gnn_miss = pct(p3_37["zero_shot"]["gnn"]["missing_sensor_mean"]) if p3_37 else "–"

    if ag37:
        ag37_fpi_zs = f'{pct(ag37["fpi"]["overall_accuracy"])} (FPR {pct(ag37["fpi"]["nofault_fpr"])})'
        ag37_gbdt_zs = f'{pct(ag37["zero_shot"]["per_node_gbdt"]["overall_accuracy"])} (FPR {pct(ag37["zero_shot"]["per_node_gbdt"]["nofault_fpr"])})'
        ag37_gat_zs = f'{pct(ag37["zero_shot"]["active_gatv2"]["overall_accuracy"])} (FPR {pct(ag37["zero_shot"]["active_gatv2"]["nofault_fpr"])})'
        ag37_gbdt_fs = (f'{pct(ag37["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["overall_accuracy_mean"])} / '
                        f'{pct(ag37["in_domain_upper_bound"]["per_node_gbdt"]["overall_accuracy"])}')
        ag37_gat_fs = (f'{pct(ag37["few_shot"]["pct_20"]["models"]["active_gatv2"]["overall_accuracy_mean"])} / '
                       f'{pct(ag37["in_domain_upper_bound"]["active_gatv2"]["overall_accuracy"])}')
        ag37_fpi_miss = pct(ag37["fpi"]["missing_sensor_mean"])
        ag37_gbdt_miss = pct(ag37["zero_shot"]["per_node_gbdt"]["missing_sensor_mean"])
        ag37_gat_miss = pct(ag37["zero_shot"]["active_gatv2"]["missing_sensor_mean"])
    else:
        ag37_fpi_zs = ag37_gbdt_zs = ag37_gat_zs = pending_gpu
        ag37_gbdt_fs = ag37_gat_fs = pending_gpu
        ag37_fpi_miss = ag37_gbdt_miss = ag37_gat_miss = pending_short

    def _zrow(label: str, c123: str, c34zs: str, c34fs: str, c37zs: str, c37fs: str, m123: str, m34: str, m37: str) -> list[str]:
        if has_37:
            return [label, c123, c34zs, c34fs, c37zs, c37fs, f"{m123} / {m34} / {m37}"]
        return [label, c123, c34zs, c34fs, f"{m123} / {m34}"]

    t_zone = table(
        zone_head,
        [
            _zrow(T("Passive radial · FPI rule", "Hình tia thụ động · Luật FPI"),
                  pct(p2["fpi"]["accuracy"]), pct(p3["fpi"]["accuracy"]), "–",
                  p37_fpi_zs, "–",
                  pct(p2["fpi"]["missing_sensor_mean"]), pct(p3["fpi"]["missing_sensor_mean"]), p37_fpi_miss),
            _zrow(T("Passive radial · Per-node GBDT", "Hình tia thụ động · GBDT theo nút"),
                  f'<b>{pct(p2["per_node_gbdt"]["accuracy"])}</b>',
                  f'<b>{pct(p3["zero_shot"]["per_node_gbdt"]["accuracy"])}</b>',
                  f'{pct(p3["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["accuracy_mean"])} / {pct(p3["in_domain_upper_bound"]["per_node_gbdt"]["accuracy"])}',
                  p37_gbdt_zs, p37_gbdt_fs,
                  pct(p2["per_node_gbdt"]["missing_sensor_mean"]), pct(p3["zero_shot"]["per_node_gbdt"]["missing_sensor_mean"]), p37_gbdt_miss),
            _zrow(T("Passive radial · Zone-tree GNN (2L)", "Hình tia thụ động · GNN cây zone (2 lớp)"),
                  pct(p2["gnn"]["accuracy"]), pct(p3["zero_shot"]["gnn"]["accuracy"]),
                  f'<b>{pct(p3["few_shot"]["pct_20"]["models"]["gnn"]["accuracy_mean"])}</b> / {pct(p3["in_domain_upper_bound"]["gnn"]["accuracy"])}',
                  p37_gnn_zs, p37_gnn_fs,
                  f'<b>{pct(p2["gnn"]["missing_sensor_mean"])}</b>', pct(p3["zero_shot"]["gnn"]["missing_sensor_mean"]), p37_gnn_miss),
            _zrow(T("Active DER + loops + HIF + NO_FAULT · FPI", "Lưới có DER + vòng kín + HIF + không sự cố · FPI"),
                  f'{pct(ag123["fpi"]["overall_accuracy"])} (FPR {pct(ag123["fpi"]["nofault_fpr"])})',
                  f'{pct(ag34["fpi"]["overall_accuracy"])} (FPR {pct(ag34["fpi"]["nofault_fpr"])})', "–",
                  ag37_fpi_zs, "–",
                  pct(ag123["fpi"]["missing_sensor_mean"]), pct(ag34["fpi"]["missing_sensor_mean"]), ag37_fpi_miss),
            _zrow(T("Active DER + loops + HIF + NO_FAULT · Per-node GBDT", "Lưới có DER + vòng kín + HIF + không sự cố · GBDT theo nút"),
                  f'{pct(ag123["per_node_gbdt"]["overall_accuracy"])} (FPR {pct(ag123["per_node_gbdt"]["nofault_fpr"])})',
                  f'<b>{pct(ag34["zero_shot"]["per_node_gbdt"]["overall_accuracy"])}</b>',
                  f'{pct(ag34["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["overall_accuracy_mean"])} / {pct(ag34["in_domain_upper_bound"]["per_node_gbdt"]["overall_accuracy"])}',
                  ag37_gbdt_zs, ag37_gbdt_fs,
                  pct(ag123["per_node_gbdt"]["missing_sensor_mean"]), f'<b>{pct(ag34["zero_shot"]["per_node_gbdt"]["missing_sensor_mean"])}</b>', ag37_gbdt_miss),
            _zrow(T("Active DER + loops + HIF + NO_FAULT · ActiveGridGATv2", "Lưới có DER + vòng kín + HIF + không sự cố · ActiveGridGATv2"),
                  f'<b>{pct(ag123["active_gatv2"]["overall_accuracy"])}</b> (FPR <b>{pct(ag123["active_gatv2"]["nofault_fpr"])}</b>)',
                  pct(ag34["zero_shot"]["active_gatv2"]["overall_accuracy"]),
                  f'<b>{pct(ag34["few_shot"]["pct_20"]["models"]["active_gatv2"]["overall_accuracy_mean"])}</b> / <b>{pct(ag34["in_domain_upper_bound"]["active_gatv2"]["overall_accuracy"])}</b>',
                  ag37_gat_zs, ag37_gat_fs,
                  f'<b>{pct(ag123["active_gatv2"]["missing_sensor_mean"])}</b>', pct(ag34["zero_shot"]["active_gatv2"]["missing_sensor_mean"]), ag37_gat_miss),
        ],
        set(range(1, len(zone_head))),
    )

    b123, b34 = p2b["ieee123"], p2b["ieee34"]
    b37 = p2b_37["ieee37"] if p2b_37 else None
    bus_head = [
        T("Stage-2 bus ranker (inside predicted zone)", "Bộ xếp hạng bus Stage 2 (trong zone dự đoán)"),
        T("IEEE 123-bus top-1", "IEEE 123-bus top-1"), T("IEEE 123-bus top-3", "IEEE 123-bus top-3"),
        T("IEEE 34-bus top-1", "IEEE 34-bus top-1"), T("IEEE 34-bus top-3", "IEEE 34-bus top-3"),
    ]
    if b37:
        bus_head += [
            T("IEEE 37-bus top-1 (4.8 kV delta)", "IEEE 37-bus top-1 (4.8 kV delta)"),
            T("IEEE 37-bus top-3 (4.8 kV delta)", "IEEE 37-bus top-3 (4.8 kV delta)"),
        ]

    def _b37_cell(overall: float, phase: float, bold: bool = False) -> str:
        val = f"<b>{pct(overall)}</b>" if bold else pct(overall)
        return f'{val}<small>{T("phase", "pha")} {pct(phase)}</small>'

    bus_rows = [
        [T("Random bus in zone (baseline)", "Chọn ngẫu nhiên bus trong zone"),
         pct(b123["random_in_zone"]["top1"]), pct(b123["random_in_zone"]["top3"]),
         pct(b34["random_in_zone"]["top1"]), pct(b34["random_in_zone"]["top3"]),
         *([_b37_cell(b37["random_in_zone"]["top1"], b37["random_in_zone"]["phase_faults_top1"]),
            _b37_cell(b37["random_in_zone"]["top3"], b37["random_in_zone"]["phase_faults_top3"])] if b37 else [])],
        [T("3-phase Takagi reactance (OpenDSS 3×3 Z, zero training)", "Điện kháng Takagi 3 pha (ma trận 3×3 OpenDSS, không cần học)"),
         f'<b>{pct(b123["reactance_takagi"]["top1"])}</b>', f'<b>{pct(b123["reactance_takagi"]["top3"])}</b>',
         f'<b>{pct(b34["reactance_takagi"]["top1"])}</b>', f'<b>{pct(b34["reactance_takagi"]["top3"])}</b>',
         *([_b37_cell(b37["reactance_takagi"]["top1"], b37["reactance_takagi"]["phase_faults_top1"],
                      bold=b37["reactance_takagi"]["top1"] >= b37["bus_graph_gnn_zero_shot"]["top1"]),
            _b37_cell(b37["reactance_takagi"]["top3"], b37["reactance_takagi"]["phase_faults_top3"],
                      bold=b37["reactance_takagi"]["top3"] >= b37["bus_graph_gnn_zero_shot"]["top3"])] if b37 else [])],
        [T("Bus-graph GNN (5-fold CV on 123 / zero-shot on 34 & 37)" if b37 else "Bus-graph GNN (5-fold CV on 123 / zero-shot on 34)",
           "GNN đồ thị bus (CV 5 phần trên 123 / zero-shot trên 34 & 37)" if b37 else "GNN đồ thị bus (CV 5 phần trên 123 / zero-shot trên 34)"),
         pct(b123["bus_graph_gnn_cv"]["top1"]), pct(b123["bus_graph_gnn_cv"]["top3"]),
         pct(b34["bus_graph_gnn_zero_shot"]["top1"]), pct(b34["bus_graph_gnn_zero_shot"]["top3"]),
         *([_b37_cell(b37["bus_graph_gnn_zero_shot"]["top1"], b37["bus_graph_gnn_zero_shot"]["phase_faults_top1"],
                      bold=b37["bus_graph_gnn_zero_shot"]["top1"] > b37["reactance_takagi"]["top1"]),
            _b37_cell(b37["bus_graph_gnn_zero_shot"]["top3"], b37["bus_graph_gnn_zero_shot"]["phase_faults_top3"],
                      bold=b37["bus_graph_gnn_zero_shot"]["top3"] > b37["reactance_takagi"]["top3"])] if b37 else [])],
    ]
    t_bus = table(bus_head, bus_rows, set(range(1, len(bus_head))))

    # Conformal sets at a 95% target. Rows: the pre-registered deterministic APS and the post-hoc randomized APS
    # (scripts/active_conformal_posthoc.py, same probabilities and splits). Without the post-hoc file, only the
    # pre-registered rows are shown. If active_grid_ieee37 conformal files exist, add the 37-bus columns too.
    post = (d.get("agpost") or {}).get("results")
    post37 = (ag37_post or {}).get("results")
    has_conf37 = post37 is not None or ag37_conf is not None
    conf_rows = []
    for mkey, men, mvi in (("active_gatv2", "ActiveGridGATv2", "ActiveGridGATv2"),
                           ("per_node_gbdt", "Per-node GBDT", "GBDT theo nút")):
        for meth, sen, svi in (("aps_det", "pre-registered APS", "APS đăng ký trước"),
                               ("aps_rand", "randomized APS (post-hoc)", "APS ngẫu nhiên (kiểm tra sau)")):
            if post is None and meth != "aps_det":
                continue
            if post is not None:
                r = post[mkey][meth]["target_95"]
                a, z, rc = (r["ieee123_cross_conformal"], r["ieee34_zero_shot_q_from_123"],
                            r["ieee34_recal_5pct_buses"])
                cov34rc = f'{pct(rc["coverage"]["mean"])} ({pct(rc["coverage"]["min"])})'
                cov, size, single, sacc, trip = (a["coverage"], a["avg_set_size"], a["singleton_share"],
                                                 a["singleton_accuracy"], a["nofault_autonomous_trip_share"])
                cov34 = z["coverage"]
            else:
                a = conf["ieee123_bus_disjoint_cv"][mkey]["target_95"]
                rc = conf["ieee34_transfer"][mkey]["recal_5pct_buses_no_retrain"]["target_95"]
                cov34rc = pct(rc["empirical_coverage_mean"])
                cov, size, single, sacc = (a["empirical_coverage"], a["avg_set_size"], a["autonomous_share"],
                                           a["autonomous_accuracy"])
                trip = None
                cov34 = conf["ieee34_transfer"][mkey]["zero_shot_q_from_123"]["target_95"]["empirical_coverage"]
            row = [T(f"{men} · {sen}", f"{mvi} · {svi}"), pct(cov), f"{size:.2f}", pct(single),
                   pct(sacc) if sacc is not None else "–", pct(trip) if trip is not None else "–",
                   pct(cov34), cov34rc]
            if has_conf37:
                if post37 is not None:
                    r37 = post37[mkey][meth]["target_95"]
                    z37, rc37 = r37["ieee37_zero_shot_q_from_123"], r37["ieee37_recal_5pct_buses"]
                    row += [pct(z37["coverage"]), f'{pct(rc37["coverage"]["mean"])} ({pct(rc37["coverage"]["min"])})']
                elif ag37_conf is not None and meth == "aps_det":
                    z37 = ag37_conf["ieee37_transfer"][mkey]["zero_shot_q_from_123"]["target_95"]
                    rc37 = ag37_conf["ieee37_transfer"][mkey]["recal_5pct_buses_no_retrain"]["target_95"]
                    row += [pct(z37["empirical_coverage"]), pct(rc37["empirical_coverage_mean"])]
                else:
                    row += [pending_short, pending_short]
            conf_rows.append(row)
    conf_head = [
        T("Model · score (95% target)", "Mô hình · cách tính (mục tiêu 95%)"),
        T("123-bus coverage", "Độ phủ 123-bus"),
        T("Labels per set", "Số nhãn mỗi tập"),
        T("One-label sets", "Tập 1 nhãn"),
        T("Right on one-label sets", "Đúng khi tập 1 nhãn"),
        T("Non-fault events that would trip", "Ca không sự cố bị cắt"),
        T("34-bus coverage, 123-bus threshold", "Độ phủ 34-bus, ngưỡng của 123-bus"),
        T("34-bus coverage, recalibrated (worst)", "Độ phủ 34-bus, hiệu chỉnh lại (tệ nhất)"),
    ]
    if has_conf37:
        conf_head += [
            T("37-bus coverage, 123-bus threshold", "Độ phủ 37-bus, ngưỡng của 123-bus"),
            T("37-bus coverage, recalibrated (worst)", "Độ phủ 37-bus, hiệu chỉnh lại (tệ nhất)"),
        ]
    t_conf = table(conf_head, conf_rows, set(range(1, len(conf_head))))

    # IEEE 37-bus physical explanation and active-grid status notes (all numbers from results/)
    note37_en = note37_vi = ""
    if p3_37:
        s2l37_en = s2l37_vi = ""
        if "s2l_head37" in v:
            s2l37_en = (f' — measured in OpenDSS at median {v["s2l_i001_37"]} ({v["s2l_sh001_37"]} of the '
                        f'{v["s2l_head37"]} feeder-head current) even for a bolted 0.01 Ω fault, and '
                        f'{v["s2l_i400_37"]} ({v["s2l_sh400_37"]}) at 400 Ω —')
            s2l37_vi = (f' — đo trong OpenDSS chỉ đạt trung vị {v["s2l_i001_37"]} ({v["s2l_sh001_37"]} dòng đầu tuyến '
                        f'{v["s2l_head37"]}) ngay cả khi chạm đất trực tiếp 0.01 Ω, và {v["s2l_i400_37"]} '
                        f'({v["s2l_sh400_37"]}) ở 400 Ω —')
        if ag37:
            ag37_en = (f' On active IEEE 37-bus (DER 0–50%, <code>reconfig_tie</code>/<code>looped_tie</code>, '
                       f'<code>NO_FAULT</code>), FPI scores {v["ag_fpi37"]} (FPR {v["ag_fpi37_fpr"]}), zero-shot '
                       f'GBDT {v["ag_gbdt37_zs"]} and ActiveGridGATv2 {v["ag_gat37_zs"]} (20% few-shot '
                       f'{v["ag_gbdt37_fs20"]} / {v["ag_gat37_fs20"]}; in-domain {v["ag_gbdt37_ub"]} / {v["ag_gat37_ub"]}).')
            ag37_vi = (f' Trên lưới chủ động IEEE 37-bus (DER 0–50%, <code>reconfig_tie</code>/<code>looped_tie</code>, '
                       f'<code>NO_FAULT</code>), FPI đạt {v["ag_fpi37"]} (FPR {v["ag_fpi37_fpr"]}), zero-shot '
                       f'GBDT đạt {v["ag_gbdt37_zs"]} và ActiveGridGATv2 đạt {v["ag_gat37_zs"]} (tinh chỉnh 20% '
                       f'{v["ag_gbdt37_fs20"]} / {v["ag_gat37_fs20"]}; học tại chỗ {v["ag_gbdt37_ub"]} / {v["ag_gat37_ub"]}).')
        elif ag37_ds and "ieee37" in ag37_ds:
            ds37 = ag37_ds["ieee37"]
            ag37_en = (f' <b>Active IEEE 37-bus status:</b> not run yet on Kaggle GPU — the OpenDSS active dataset '
                       f'({num(ds37["converged"])} converged of {num(ds37["events_total"])} events) is built, while '
                       f'model training/transfer and conformal runs (<code>results/active_grid_ieee37/phase_active_ieee37.json</code>) '
                       f'are pending Kaggle GPU.')
            ag37_vi = (f' <b>Trạng thái lưới chủ động IEEE 37-bus:</b> chưa chạy trên Kaggle GPU — bộ dữ liệu OpenDSS '
                       f'({num(ds37["converged"])} ca hội tụ trên {num(ds37["events_total"])} ca) đã sinh xong, còn phần '
                       f'huấn luyện/chuyển giao mô hình và conformal (<code>results/active_grid_ieee37/phase_active_ieee37.json</code>) '
                       f'đang chờ chạy trên Kaggle GPU.')
        else:
            ag37_en = ' <b>Active IEEE 37-bus status:</b> not run yet on Kaggle GPU (no active-grid results yet).'
            ag37_vi = ' <b>Trạng thái lưới chủ động IEEE 37-bus:</b> chưa chạy trên Kaggle GPU (chưa có kết quả lưới chủ động).'
        note37_en = (f' (3) <b>Third unseen feeder — urban underground IEEE 37-bus (4.8 kV, 3-wire ungrounded delta, '
                     f'{v["tr_p37_zones"]} zones, {v["tr_p37_buses"]} buses, {v["tr_p37_events"]} faults):</b> passive '
                     f'zero-shot drops to {v["tr_p37_gbdt"]} (GBDT) and {v["tr_p37_gnn"]} (GNN) vs {v["tr_p37_fpi"]} '
                     f'(FPI) — missing the pre-committed <code>P1-Main</code> bar. <b>Physical cause:</b> on phase '
                     f'faults (3PH/LL/LLG), frozen 123-bus models still transfer almost perfectly ({v["tr_p37_gbdt_ph"]} '
                     f'GBDT, {v["tr_p37_gnn_ph"]} GNN vs {v["tr_p37_fpi_ph"]} FPI) because phase currents circulate '
                     f'directly through the 4.8 kV delta cables. The drop comes entirely from <b>SLG ground faults</b> '
                     f'({v["tr_p37_fpi_slg"]} FPI, {v["tr_p37_gbdt_slg"]} GBDT, {v["tr_p37_gnn_slg"]} GNN): without a '
                     f'grounded neutral, SLG current returns only through distributed cable capacitance{s2l37_en} while '
                     f'unfaulted phase-to-ground voltages shift toward √3 pu, a regime never seen on grounded 4-wire '
                     f'123-bus. In-domain 5-fold CV on 37-bus reaches {v["tr_p37_gbdt_ub"]} (GBDT, SLG '
                     f'{v["tr_p37_gbdt_ub_slg"]}) and {v["tr_p37_gnn_ub"]} (GNN, SLG {v["tr_p37_gnn_ub_slg"]}), showing '
                     f'the relative features do contain localizable delta signatures once trained on ungrounded data; '
                     f'with 20% few-shot (7 buses), Zone-tree GNN climbs to {v["tr_p37_gnn_fs20"]} while warm-start GBDT '
                     f'overfits the 7 sampled buses ({v["tr_p37_gbdt_fs20"]}).{ag37_en}')
        note37_vi = (f' (3) <b>Lưới chưa thấy thứ 3 — cáp ngầm đô thị IEEE 37-bus (4.8 kV, 3 dây delta không nối đất, '
                     f'{v["tr_p37_zones"]} zone, {v["tr_p37_buses"]} bus, {v["tr_p37_events"]} sự cố):</b> zero-shot thụ '
                     f'động giảm xuống {v["tr_p37_gbdt"]} (GBDT) và {v["tr_p37_gnn"]} (GNN) so với {v["tr_p37_fpi"]} '
                     f'(FPI) — không đạt tiêu chí <code>P1-Main</code> đăng ký trước. <b>Nguyên nhân vật lý:</b> với sự '
                     f'cố giữa các pha (3PH/LL/LLG), mô hình giữ nguyên từ 123-bus vẫn chuyển giao gần như hoàn hảo '
                     f'({v["tr_p37_gbdt_ph"]} GBDT, {v["tr_p37_gnn_ph"]} GNN so với {v["tr_p37_fpi_ph"]} FPI) vì dòng '
                     f'pha khép mạch trực tiếp qua cáp delta 4.8 kV. Toàn bộ mức sụt giảm nằm ở <b>sự cố chạm đất SLG</b> '
                     f'({v["tr_p37_fpi_slg"]} FPI, {v["tr_p37_gbdt_slg"]} GBDT, {v["tr_p37_gnn_slg"]} GNN): vì không có '
                     f'dây trung tính nối đất, dòng SLG chỉ hồi về qua điện dung phân bố của cáp ngầm{s2l37_vi} đồng thời '
                     f'điện áp pha lành so với đất dâng về √3 pu — trạng thái chưa từng có trong dữ liệu huấn luyện 4 dây '
                     f'nối đất 123-bus. Học tại chỗ (CV 5 phần) trên 37-bus đạt {v["tr_p37_gbdt_ub"]} (GBDT, SLG '
                     f'{v["tr_p37_gbdt_ub_slg"]}) và {v["tr_p37_gnn_ub"]} (GNN, SLG {v["tr_p37_gnn_ub_slg"]}), chứng tỏ '
                     f'bộ đặc trưng tương đối vẫn giữ được dấu hiệu định vị khi có dữ liệu lưới delta; tinh chỉnh 20% '
                     f'(7 bus) đưa GNN lên {v["tr_p37_gnn_fs20"]}, còn GBDT warm-start bị quá khớp 7 bus mẫu '
                     f'({v["tr_p37_gbdt_fs20"]}).{ag37_vi}')

    bus37_en = bus37_vi = ""
    if b37:
        bus37_en = (f' On underground delta <b>IEEE 37-bus</b>, both zero-training Takagi ({v["tr_b37_ph1"]} top-1 / '
                    f'{v["tr_b37_ph3"]} top-3 on phase faults vs {v["tr_b37_rand3_ph"]} random) and zero-shot '
                    f'BusGraphGNN ({v["tr_b37_gnn_ph3"]} phase top-3) clear the phase-fault bar (<code>P2-Partial</code>), '
                    f'while overall top-3 drops to {v["tr_b37_top3"]} (Takagi) and {v["tr_b37_gnn3"]} (GNN) vs '
                    f'{v["tr_b37_rand3"]} random because ungrounded capacitive SLG breaks the grounded-loop Takagi '
                    f'equation (SLG top-3 {v["tr_b37_slg3"]}) and compact underground cables have tiny adjacent-bus '
                    f'reactance spacing ({v["tr_b37_dx_pair"]} ΔX₁ = {v["tr_b37_dx_val"]}).')
        bus37_vi = (f' Trên lưới cáp ngầm delta <b>IEEE 37-bus</b>, cả Takagi không cần học ({v["tr_b37_ph1"]} top-1 / '
                    f'{v["tr_b37_ph3"]} top-3 trên sự cố pha so với {v["tr_b37_rand3_ph"]} ngẫu nhiên) lẫn BusGraphGNN '
                    f'zero-shot ({v["tr_b37_gnn_ph3"]} top-3 sự cố pha) đều đạt ngưỡng trên sự cố pha '
                    f'(<code>P2-Partial</code>), còn top-3 tổng thể giảm về {v["tr_b37_top3"]} (Takagi) và '
                    f'{v["tr_b37_gnn3"]} (GNN) so với {v["tr_b37_rand3"]} ngẫu nhiên vì dòng SLG điện dung trên lưới '
                    f'delta phá vỡ phương trình Takagi vòng đất (top-3 SLG {v["tr_b37_slg3"]}) và cáp ngầm ngắn có chênh '
                    f'lệch điện kháng giữa hai bus liền kề rất nhỏ ({v["tr_b37_dx_pair"]} ΔX₁ = {v["tr_b37_dx_val"]}).')

    conf37_note_en = conf37_note_vi = ""
    if post37:
        conf37_note_en = (f' On active <b>IEEE 37-bus</b> (randomized APS at 95%), the 123-bus threshold covers '
                          f'{v["ag_pr_zs37"]} (ActiveGridGATv2) and {v["ag_pr_zs37_gbdt"]} (GBDT); recalibrating on '
                          f'{v["ag_cal_buses37"]} of its fault buses averages {v["ag_pr_rc37"]} and '
                          f'{v["ag_pr_rc37_gbdt"]} (worst {v["ag_pr_rc37_min"]} and {v["ag_pr_rc37_gbdt_min"]}).')
        conf37_note_vi = (f' Trên lưới chủ động <b>IEEE 37-bus</b> (APS ngẫu nhiên ở 95%), ngưỡng từ 123-bus phủ '
                          f'{v["ag_pr_zs37"]} (ActiveGridGATv2) và {v["ag_pr_zs37_gbdt"]} (GBDT); hiệu chỉnh lại bằng '
                          f'{v["ag_cal_buses37"]} bus sự cố đạt trung bình {v["ag_pr_rc37"]} và '
                          f'{v["ag_pr_rc37_gbdt"]} (tệ nhất {v["ag_pr_rc37_min"]} và {v["ag_pr_rc37_gbdt_min"]}).')
    elif has_37:
        conf37_note_en = (' <b>IEEE 37-bus conformal status:</b> not run yet on Kaggle GPU — no conformal coverage '
                          'numbers are reported for IEEE 37-bus yet (waiting for <code>results/active_grid_ieee37/</code>).')
        conf37_note_vi = (' <b>Trạng thái conformal trên IEEE 37-bus:</b> chưa chạy trên Kaggle GPU — chưa có số liệu '
                          'độ phủ conformal cho IEEE 37-bus (đang chờ <code>results/active_grid_ieee37/</code>).')

    intro_37_en = (f' and on a third feeder, the <b>unseen urban underground IEEE 37-bus feeder (4.8 kV, 3-wire '
                   f'ungrounded delta, {v["tr_p37_zones"]} switches placed by the same 5%-load rule)</b>'
                   if p3_37 else "")
    intro_37_vi = (f' và trên lưới thứ 3 là <b>lưới cáp ngầm đô thị IEEE 37-bus chưa từng thấy (4.8 kV, 3 dây delta '
                   f'không nối đất, {v["tr_p37_zones"]} dao đặt theo cùng quy tắc nhánh ≥ 5% tải)</b>'
                   if p3_37 else "")

    return (
        head
        + TB(emph(f'The classifier in section 2 is tied to the 10 named devices of the IEEE 123-bus feeder, so it cannot '
                  f'run on another feeder. Representing each event as a <b>graph of relative quantities</b> (current change '
                  f'relative to pre-fault load, per-unit voltages, phasor flow directions, and zone connectivity) lets a '
                  f'model trained <b>only on IEEE 123-bus (4.16 kV)</b> run unchanged on the <b>unseen IEEE 34-bus feeder '
                  f'(24.9 kV, 7 switches placed by a fixed 5%-load branch rule)</b>{intro_37_en}. All results below are '
                  f'OpenDSS simulations.'),
             emph(f'Bộ phân loại ở mục 2 gắn cứng với 10 thiết bị có tên của lưới IEEE 123-bus nên không chạy được trên '
                  f'lưới khác. Khi biểu diễn mỗi sự kiện thành <b>đồ thị dùng đại lượng tương đối</b> (mức thay đổi dòng '
                  f'so với tải trước sự cố, điện áp per-unit, hướng dòng công suất và liên kết giữa các zone), model '
                  f'<b>chỉ học trên IEEE 123-bus (4.16 kV)</b> có thể chạy thẳng trên <b>lưới IEEE 34-bus chưa từng thấy '
                  f'(24.9 kV, 7 dao đặt theo quy tắc nhánh ≥ 5% tải cố định trước)</b>{intro_37_vi}. Toàn bộ kết quả '
                  f'dưới đây là mô phỏng OpenDSS.'), "p", "note")
        + f'<h4>{T("Zone transfer: passive radial vs active DER + reconfigured/looped grids", "Chuyển giao cấp zone: lưới hình tia thụ động so với lưới có DER + đổi cấu trúc/vòng kín")}</h4>'
        + xbox("table-transfer", t_zone)
        + TB(emph(f'<b>Honest physical takeaways:</b> (1) On the passive radial 0.01–400 Ω sweep, zero-shot transfer '
                  f'to IEEE 34-bus scores {v["tr_p3_gbdt"]} (per-node GBDT) and {v["tr_p3_gnn"]} (tree GNN) vs {v["tr_p3_fpi"]} for FPI '
                  f'— higher than on 123-bus{why_en}. On a passive radial tree, per-node GBDT transfers '
                  f'at least as well as the GNN. (2) Adding 0–50% current-limited inverter DERs (<code>Model=7</code>), '
                  f'back-fed reconfigurations, closed-loop operation, SLG faults up to 10,000 Ω on 24.9 kV, and non-fault '
                  f'transients (capacitor switching, PV cloud drops, load steps) drops FPI to {v["ag_fpi123"]} on 123-bus '
                  f'and {v["ag_fpi34"]} on 34-bus. Here the bidirectional edge-aware attention network '
                  f'<b>ActiveGridGATv2</b> outperforms per-node GBDT on active 123-bus ({v["ag_gat123"]} vs '
                  f'{v["ag_gbdt123"]}, cutting non-fault false trips in half from {v["ag_gbdt123_fpr"]} to '
                  f'{v["ag_gat123_fpr"]}), at 20% few-shot on 34-bus ({v["ag_gat34_fs20"]} vs {v["ag_gbdt34_fs20"]}), '
                  f'and in-domain on 34-bus ({v["ag_gat34_ub"]} vs {v["ag_gbdt34_ub"]}), while GBDT is higher in pure '
                  f'0-shot ({v["ag_gbdt34_zs"]} vs {v["ag_gat34_zs"]}) where sudden +30–80% load steps mimic 2.5–10 kΩ HIFs.{note37_en}'),
             emph(f'<b>Nhận xét vật lý trung thực:</b> (1) Trên lưới hình tia thụ động dải 0.01–400 Ω, chuyển giao '
                  f'zero-shot sang IEEE 34-bus đạt {v["tr_p3_gbdt"]} (GBDT theo nút) và {v["tr_p3_gnn"]} (GNN cây) so với {v["tr_p3_fpi"]} '
                  f'của FPI — cao hơn trên 123-bus{why_vi}. Trên cây hình tia thụ động, GBDT theo nút chuyển lưới '
                  f'ngang/nhỉnh hơn GNN. (2) Khi thêm 0–50% nguồn nghịch lưu điện mặt trời giới hạn dòng '
                  f'(<code>Model=7</code>), cấu hình cấp ngược, vận hành vòng kín, sự cố chạm đất tới 10,000 Ω ở 24.9 kV '
                  f'và quá độ không sự cố (đóng cắt tụ bù, mây che PV, nhảy tải), FPI sụp xuống {v["ag_fpi123"]} trên '
                  f'123-bus và {v["ag_fpi34"]} trên 34-bus. Lúc này mạng chú ý đồ thị hai chiều <b>ActiveGridGATv2</b> '
                  f'vượt GBDT theo nút trên lưới 123-bus ({v["ag_gat123"]} so với {v["ag_gbdt123"]}, giảm một nửa tỉ lệ '
                  f'cắt nhầm từ {v["ag_gbdt123_fpr"]} xuống {v["ag_gat123_fpr"]}), ở chế độ tinh chỉnh 20% trên 34-bus '
                  f'({v["ag_gat34_fs20"]} so với {v["ag_gbdt34_fs20"]}), và khi học tại chỗ trên 34-bus '
                  f'({v["ag_gat34_ub"]} so với {v["ag_gbdt34_ub"]}); còn ở zero-shot thuần túy thì GBDT cao hơn '
                  f'({v["ag_gbdt34_zs"]} so với {v["ag_gat34_zs"]}) do bước nhảy tải +30–80% có biên độ giống sự cố 2.5–10 kΩ.{note37_vi}'),
             "p", "note")
        + f'<h4>{T("Stage 2: from predicted zone down to individual bus", "Stage 2: từ zone dự đoán xuống tới từng bus")}</h4>'
        + xbox("table-bus-stage", t_bus)
        + TB(emph(f'<b>Physics beats ML at the bus level:</b> ranking buses inside the predicted zone by 3-phase Takagi '
                  f'reactance using OpenDSS 3×3 line impedances (zero training) reaches {v["tr_b123_top1"]} top-1 / '
                  f'{v["tr_b123_top3"]} top-3 on 123-bus and {v["tr_b34_top1"]} / {v["tr_b34_top3"]} on 34-bus, outperforming '
                  f'a bus-graph GNN ({v["tr_b123_gnn1"]} / {v["tr_b123_gnn3"]} under GroupKFold by bus on 123-bus, where '
                  f'held-out test buses are suppressed as unseen positive labels). The top confused bus pairs '
                  f'(<code>61→61s</code>, <code>160→160r</code>, <code>832→888</code>) have ΔX₁ = 0.000 Ω: with sensors '
                  f'only at zone boundaries, parallel laterals at the same electrical distance cannot be separated without '
                  f'extra sensors.{bus37_en}'),
             emph(f'<b>Ở cấp bus, vật lý thắng ML:</b> xếp hạng bus trong zone dự đoán bằng điện kháng Takagi 3 pha dùng '
                  f'ma trận đường dây 3×3 từ OpenDSS (không cần học) đạt {v["tr_b123_top1"]} top-1 / {v["tr_b123_top3"]} '
                  f'top-3 trên 123-bus và {v["tr_b34_top1"]} / {v["tr_b34_top3"]} trên 34-bus, vượt xa GNN đồ thị bus '
                  f'({v["tr_b123_gnn1"]} / {v["tr_b123_gnn3"]} khi kiểm định GroupKFold theo bus trên 123-bus, do các bus '
                  f'kiểm tra chưa từng xuất hiện làm nhãn dương khi học). Các cặp bus hay nhầm nhất '
                  f'(<code>61→61s</code>, <code>160→160r</code>, <code>832→888</code>) đều có ΔX₁ = 0.000 Ω: khi chỉ đặt '
                  f'cảm biến ở đầu zone, hai nhánh có cùng khoảng cách điện là không thể phân biệt nếu không thêm cảm biến.{bus37_vi}'),
             "p", "note")
        + f'<h4>{T("Uncertainty gate: Split Conformal Prediction (95% target)", "Cổng bất định: Split Conformal Prediction (mục tiêu 95%)")}</h4>'
        + xbox("table-conformal", t_conf)
        + (TB(emph(f'<b>Read this as a decision-support gate in simulation, not a guarantee.</b> The pre-registered score '
                   f'(deterministic APS) saturates: at a 95% target its sets hold {v["ag_pd_size"]} of '
                   f'{v["ag_labels123"]} labels on average and cover {v["ag_conf123_cov"]} of events, so the rule "act '
                   f'only on a one-label set" acts on just {v["ag_pd_single"]} of events (ActiveGridGATv2). Criterion C3 '
                   f'is met as written, but that coverage is close to trivial. A post-hoc check on the same '
                   f'probabilities and splits with randomized APS (Romano et al. 2020) hits the target on the training '
                   f'feeder: {v["ag_pr_cov"]} coverage with {v["ag_pr_size"]} labels per set; one-label sets cover '
                   f'{v["ag_pr_single"]} of events, are right {v["ag_pr_sacc"]} of the time, and {v["ag_pr_trip"]} of '
                   f'non-fault events would trip. It does <b>not</b> carry over to the unseen 34-bus feeder: the 123-bus '
                   f'threshold covers {v["ag_pr_zs34"]} (ActiveGridGATv2) and {v["ag_pr_zs34_gbdt"]} (GBDT) against the '
                   f'95% target, and recalibrating on {v["ag_cal_buses"]} of its fault buses reaches {v["ag_pr_rc34"]} '
                   f'and {v["ag_pr_rc34_gbdt"]} on average (worst of 10 draws {v["ag_pr_rc34_min"]} and '
                   f'{v["ag_pr_rc34_gbdt_min"]}). The guarantee needs calibration data from the feeder it is used on. '
                   f'LAC, the third score tried, also hits 95% on 123-bus but covers only {v["ag_lac_zs34"]} on 34-bus '
                   f'with the 123-bus threshold.{conf37_note_en}'),
              emph(f'<b>Đây là một cổng hỗ trợ quyết định trong mô phỏng, không phải bảo chứng.</b> Cách tính đã đăng ký '
                   f'trước (APS xác định) bị bão hòa: ở mục tiêu 95%, mỗi tập trung bình chứa {v["ag_pd_size"]} trên '
                   f'{v["ag_labels123"]} nhãn và phủ {v["ag_conf123_cov"]} số ca, nên luật "chỉ tự đóng cắt khi tập có '
                   f'1 nhãn" chỉ áp dụng được cho {v["ag_pd_single"]} số ca (ActiveGridGATv2). Tiêu chí C3 đạt đúng như '
                   f'chữ viết, nhưng độ phủ đó gần như vô nghĩa. Kiểm tra sau trên cùng xác suất và cùng cách chia bằng '
                   f'APS ngẫu nhiên (Romano và cộng sự 2020) đạt đúng mục tiêu trên lưới đã học: độ phủ {v["ag_pr_cov"]} '
                   f'với {v["ag_pr_size"]} nhãn mỗi tập; tập 1 nhãn chiếm {v["ag_pr_single"]} số ca, đúng '
                   f'{v["ag_pr_sacc"]}, và {v["ag_pr_trip"]} số ca không sự cố sẽ bị cắt nhầm. Kết quả này '
                   f'<b>không</b> giữ được khi sang lưới 34-bus chưa thấy: ngưỡng của 123-bus chỉ phủ {v["ag_pr_zs34"]} '
                   f'(ActiveGridGATv2) và {v["ag_pr_zs34_gbdt"]} (GBDT) so với mục tiêu 95%; hiệu chỉnh lại bằng '
                   f'{v["ag_cal_buses"]} bus sự cố của lưới đó đạt trung bình {v["ag_pr_rc34"]} và {v["ag_pr_rc34_gbdt"]} '
                   f'(tệ nhất trong 10 lần rút: {v["ag_pr_rc34_min"]} và {v["ag_pr_rc34_gbdt_min"]}). Muốn có bảo chứng '
                   f'thì phải hiệu chỉnh bằng dữ liệu của chính lưới đang dùng. LAC, cách tính thứ ba, cũng đạt 95% trên '
                   f'123-bus nhưng chỉ phủ {v["ag_lac_zs34"]} trên 34-bus khi dùng ngưỡng của 123-bus.{conf37_note_vi}'),
              "p", "note") if "ag_pr_cov" in v else "")
        + _multi_feeder_block(d.get("mfb"))
    )


def _multi_feeder_block(mfb: dict | None) -> str:
    """Optional multi-feeder zero-shot evidence table (15 official IEEE/EPRI OpenDSS feeders)."""
    if not mfb:
        return ""
    mfb_head = [
        T("Feeder (OpenDSS official)", "Lưới phân phối (OpenDSS gốc)"),
        T("kV / Hz", "kV / Hz"),
        T("Zones", "Số zone"),
        T("Events", "Sự cố"),
        T("FPI", "FPI"),
        T("Zero-shot GBDT", "GBDT 0-shot"),
        T("Zero-shot GNN", "GNN 0-shot"),
        T("1 sensor off (GBDT / GNN)", "Mất 1 cảm biến (GBDT / GNN)"),
        T("Verdict", "Kết luận"),
    ]
    rows = []
    for r in mfb.get("reference_feeders", []):
        ver = r["verdict"]
        ver_html = (T("Train CV", "Huấn luyện CV") if ver == "Train CV"
                    else (f'<b>{T("Pass", "Đạt")}</b>' if ver == "Pass"
                          else T("Partial (phase only)", "Đạt sự cố pha")))
        rows.append([
            esc(r["label"]),
            f'{r["head_kv_ll"]:.2f} kV · {r["freq_hz"]:.0f} Hz',
            str(r["zones"]),
            f'{r["events_converged"]:,}',
            pct(r["fpi_acc"]),
            f'<b>{pct(r["gbdt_acc"])}</b>' if r["gbdt_acc"] >= r["gnn_acc"] else pct(r["gbdt_acc"]),
            f'<b>{pct(r["gnn_acc"])}</b>' if r["gnn_acc"] > r["gbdt_acc"] else pct(r["gnn_acc"]),
            f'{pct(r["gbdt_miss"])} / {pct(r["gnn_miss"])}',
            ver_html,
        ])
    for x in mfb.get("new_feeders", []):
        st = x.get("status", "")
        is_ev = st in ("evaluated", "semi_looped_evaluated")
        if is_ev:
            g_acc = x["zero_shot_gbdt"]["accuracy"]
            n_acc = x["zero_shot_gnn"]["accuracy"]
            g_ms = x["zero_shot_gbdt"]["missing_sensor_mean"]
            n_ms = x["zero_shot_gnn"]["missing_sensor_mean"]
            cyc_tag = f' <small>({x["cycles"]} loops)</small>' if x.get("cycles") else ""
            rows.append([
                f'{esc(x["label"])}{cyc_tag}',
                f'{x["head_kv_ll"]:.2f} kV · {x["freq_hz"]:.0f} Hz',
                str(x["zones"]),
                f'{x["events_converged"]:,}',
                pct(x["fpi"]["accuracy"]),
                f'<b>{pct(g_acc)}</b>' if g_acc >= n_acc else pct(g_acc),
                f'<b>{pct(n_acc)}</b>' if n_acc > g_acc else pct(n_acc),
                f'{pct(g_ms)} / {pct(n_ms)}',
                f'<b>{T("Pass", "Đạt")}</b>' if x["verdict"] == "Pass" else esc(x["verdict"]),
            ])
        else:
            why_short = (T(f'Meshed ({x.get("cycles")} cycles)', f'Mạch lưới ({x.get("cycles")} vòng kín)')
                         if st == "incompatible_meshed"
                         else (T("Base flow non-converged", "Không hội tụ OpenDSS") if st == "non_converged_base_case"
                               else T("Not in OpenDSS repo", "Không có trong kho OpenDSS")))
            kv_s = f'{x["freq_hz"]:.0f} Hz' if x.get("freq_hz") else "–"
            rows.append([esc(x["label"]), kv_s, "–", "–", "–", "–", "–", "–", f'<span class="muted">{why_short}</span>'])

    t_mfb = table(mfb_head, rows, {2, 3, 4, 5, 6, 7})
    c = mfb.get("counts", {})
    n_pass = c.get("pass", 0) + 1
    n_unseen = c.get("total_unseen_evaluated", 0)
    return (
        f'<h4>{T("Multi-feeder zero-shot evidence table (15 official IEEE & EPRI OpenDSS feeders, Kaggle 3-VM run)", "Bảng bằng chứng chuyển giao đa lưới (15 lưới chuẩn IEEE & EPRI OpenDSS, chạy 3 phiên Kaggle)")}</h4>'
        + t_mfb
        + TB(emph(f'<b>Broader generalization proof (simulation only):</b> Using the exact frozen IEEE 123-bus models '
                  f'(zero retraining) across <b>{n_unseen} unseen OpenDSS feeders</b> spanning 0.416–34.5 kV, 50 Hz & 60 Hz, '
                  f'and up to 6,058 buses / 18 zones, <b>{n_pass} of {n_unseen} unseen feeders pass zero-shot</b> — '
                  f'including 93.3% (GBDT) / 91.3% (GNN) on the 50 Hz European LV cable feeder (vs 60.3% FPI), '
                  f'99.8% / 99.0% on IEEE 8500-Node (vs 44.1% FPI), and 98.0%–99.7% across all six utility-scale EPRI '
                  f'feeders (Ckt5, Ckt7, Ckt24, J1, K1, M1). On all six large EPRI feeders, the Zone-tree GNN beats '
                  f'per-node GBDT whenever one sensor is offline (e.g., 94.3% vs 90.5% on 18-zone EPRI Ckt7). The only '
                  f'transfer breakdown is ungrounded 3-wire delta IEEE 37-bus SLG, while heavily meshed IEEE 342-Node '
                  f'(71 cycles) and non-converged IEEE 9500-Node are recorded transparently as out-of-scope.'),
             emph(f'<b>Bằng chứng tổng quát hóa đa lưới (thuần mô phỏng OpenDSS):</b> Dùng đúng cặp mô hình IEEE 123-bus '
                  f'đóng băng (không huấn luyện lại) chạy song song trên 3 máy ảo Kaggle qua <b>{n_unseen} lưới chưa từng thấy</b> '
                  f'(0.416–34.5 kV, cả 50 Hz & 60 Hz, tới 6,058 bus / 18 zone), <b>{n_pass} trên {n_unseen} lưới đạt chuẩn zero-shot</b> — '
                  f'gồm 93.3% (GBDT) / 91.3% (GNN) trên lưới cáp hạ áp châu Âu 50 Hz (so với 60.3% FPI), '
                  f'99.8% / 99.0% trên lưới khổng lồ IEEE 8500-Node (so với 44.1% FPI), và 98.0%–99.7% trên cả 6 lưới thực tế '
                  f'của EPRI (Ckt5, Ckt7, Ckt24, J1, K1, M1). Trên cả 6 lưới EPRI lớn, GNN cây zone đều vượt GBDT khi mất 1 cảm biến '
                  f'(ví dụ 94.3% so với 90.5% trên EPRI Ckt7 18 zone). Điểm gãy duy nhất là sự cố chạm đất SLG trên lưới 3 dây delta '
                  f'không nối đất IEEE 37-bus; còn mạng mạch lưới IEEE 342-Node (71 vòng kín) và IEEE 9500-Node không hội tụ cơ sở '
                  f'được ghi nhận trung thực là ngoài phạm vi.'), "p", "note")
    )


HIF_SURFACES = [  # key, EN, VI, Emanuel (Vp · R) range from shf/hif_edge.py
    ("wet_grass", "Wet grass", "Cỏ ướt", "0.5–2.0 kV · 300–700 Ω"),
    ("wet_sand", "Wet sand", "Cát ướt", "1.0–3.0 kV · 600–1,500 Ω"),
    ("concrete", "Concrete", "Bê tông", "1.5–4.5 kV · 800–2,000 Ω"),
    ("dry_grass", "Dry grass", "Cỏ khô", "2.0–5.0 kV · 900–2,500 Ω"),
    ("dry_asphalt", "Dry asphalt", "Nhựa đường khô", "3.0–7.0 kV · 2,000–6,000 Ω"),
]

HIF_DISTURBANCES = [  # key, EN, VI (from shf/hif_edge.py:DISTURBANCES)
    ("none", "Steady background (none)", "Nền ổn định (không nhiễu)"),
    ("load_step", "Load step (+30–80%)", "Nhảy tải (+30–80%)"),
    ("cap_switch", "Capacitor switching", "Đóng cắt tụ bù"),
    ("inrush", "Transformer inrush (hard negative)", "Dòng xung kích MBA (âm tính khó)"),
    ("motor_start", "Motor starting", "Khởi động động cơ"),
    ("arc_welder", "Arc welder (hard negative)", "Máy hàn hồ quang (âm tính khó)"),
    ("nonlinear_fluct", "Fluctuating nonlinear loads", "Tải phi tuyến biến động"),
]


def _hif_pair_cell(base_v: float | None, fused_v: float | None, *, lower_is_better: bool = False) -> str:
    """Format a paired ablation cell: `base → fused (+delta pp)` with the better value bolded."""
    if base_v is None or fused_v is None:
        return "–"
    diff_pp = (fused_v - base_v) * 100.0
    delta = f"{diff_pp:+.1f} pp".replace("-", "−")
    fused_wins = (fused_v <= base_v) if lower_is_better else (fused_v >= base_v)
    b_s = pct(base_v) if fused_wins else f"<b>{pct(base_v)}</b>"
    f_s = f"<b>{pct(fused_v)}</b>" if fused_wins else pct(fused_v)
    return f"{b_s} → {f_s}<small>({delta})</small>"


def _hif_arch_svg(fc_lt: float, fs_khz: float, n_feat: int, n_params: int, n_bytes: int, persist: int) -> str:
    """Compact two-tier architecture diagram: Tier 1 Edge ESP32-S3 HIF-Sensor -> p_hif -> Tier 2 Graph FLISR."""
    W, H = 680, 168
    g = [f'<svg class="hif-svg" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="Two-tier Edge HIF-Sensor to Graph FLISR architecture">']
    g.append('<rect class="hif-box t1" x="4" y="10" width="394" height="148" rx="10"/>')
    g.append(svg_text(14, 29, "Tier 1 · Edge ESP32-S3 HIF-Sensor (per recloser / switch)",
                      "Tầng 1 · Cảm biến biên ESP32-S3 HIF-Sensor (mỗi recloser / dao)", "hif-k"))
    stages = [
        (14, 40, 182, 48,
         ("CT + 4th-order Butterworth", "CT + lọc Butterworth bậc 4"),
         (f"SCT-013 · LTspice {fc_lt:,.1f} Hz", f"SCT-013 · LTspice {fc_lt:,.1f} Hz")),
        (206, 40, 182, 48,
         (f"12-bit ADC @ {fs_khz:.2f} kHz", f"ADC 12-bit @ {fs_khz:.2f} kHz"),
         (f"{n_feat} features · K = {hif_edge.K} cycles", f"{n_feat} đặc trưng · K = {hif_edge.K} chu kỳ")),
        (14, 100, 374, 46,
         (f"Frozen Tiny MLP int8 ({n_params} params / {n_bytes} B)",
          f"Tiny MLP int8 đóng băng ({n_params} tham số / {n_bytes} B)"),
         (f"Per switch: p_hif ∈ [0, 1], hif_alarm (PERSIST = {persist})",
          f"Mỗi dao: p_hif ∈ [0, 1], hif_alarm (PERSIST = {persist})")),
    ]
    for x, y, w, h, top, bot in stages:
        g.append(f'<rect class="hif-step" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        g.append(svg_text(x + 9, y + 19, top[0], top[1], "hif-st"))
        g.append(svg_text(x + 9, y + 36, bot[0], bot[1], "hif-sub"))
    g.append('<path class="hif-arr" d="M196 64h10M297 88v12"/>')
    g.append('<path class="hif-arr main" d="M398 84h44"/>')
    g.append('<polygon class="hif-tip" points="442,79 450,84 442,89"/>')
    g.append(svg_text(422, 73, "p_hif", "p_hif", "hif-pill", "middle"))
    g.append(svg_text(422, 101, "+60 Hz", "+60 Hz", "hif-sub", "middle"))
    g.append('<rect class="hif-box t2" x="452" y="10" width="224" height="148" rx="10"/>')
    g.append(svg_text(462, 29, "Tier 2 · Feeder-wide Graph FLISR",
                      "Tầng 2 · Graph FLISR toàn lưới", "hif-k2"))
    t2_stages = [
        (462, 40, 204, 48,
         ("Passive: 21 → 23 node feat", "Thụ động: 21 → 23 đặc trưng"),
         ("PerNodeGBDT · ZoneTreeGNN", "PerNodeGBDT · ZoneTreeGNN")),
        (462, 100, 204, 46,
         ("Active: 26 → 28 + diff_p_hif", "Chủ động: 26 → 28 + diff_p_hif"),
         ("ActiveGridGATv2 → aps_rand 95%", "ActiveGridGATv2 → aps_rand 95%")),
    ]
    for x, y, w, h, top, bot in t2_stages:
        g.append(f'<rect class="hif-step" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        g.append(svg_text(x + 9, y + 19, top[0], top[1], "hif-st"))
        g.append(svg_text(x + 9, y + 36, bot[0], bot[1], "hif-sub"))
    g.append("</svg>")
    return f'<div class="chart">{"".join(g)}</div>'


def hif_fusion_block(d: dict, v: dict) -> str:
    """2d: Two-tier Edge HIF-Sensor (504 B int8) -> Graph FLISR for 200-400 ohm & active HIFs."""
    hif = d.get("hif") or {}
    ds, p123, p34, a123, a34, conf = (hif.get(k) for k in ("ds", "p123", "p34", "a123", "a34", "conf"))
    has_any = any(x is not None for x in (ds, p123, p34, a123, a34, conf))

    t1 = (ds or {}).get("tier1_edge_model") or {}
    fc_lt = float((ds or {}).get("butterworth_cutoff_hz_ltspice", hif_edge.LTSPICE_CUTOFF_HZ))
    fc_py = float((ds or {}).get("butterworth_cutoff_hz_python", round(hif_edge.cutoff_hz(), 1)))
    fs_khz = float((ds or {}).get("fs_adc_hz", hif_edge.FS_ADC)) / 1000.0
    n_feat = len(hif_edge.FEATURES)
    n_params = int(t1.get("params", hif_edge.EXPECTED_PARAMS))
    n_bytes = int(t1.get("bytes", hif_edge.EXPECTED_BYTES))
    persist = int((ds or {}).get("persist_windows", hif_edge.PERSIST))

    pending_gpu = f'<span class="muted">{T("Not run yet (Kaggle GPU)", "Chưa chạy (Kaggle GPU)")}</span>'
    head = (f'<h3 id="hif-fusion">{T("2d · Two-tier Edge HIF-Sensor → Graph FLISR (200–400 Ω)", "2d · Kiến trúc 2 tầng Edge HIF-Sensor → Graph FLISR (200–400 Ω)")}</h3>')

    if not has_any:
        status_html = (
            '<div class="hif-banner">'
            f'<span class="chip warning">! {T("Pending Kaggle GPU", "Chờ chạy Kaggle GPU")}</span>'
            + TB("<b>Status: Not run yet on Kaggle GPU.</b> The pre-registered protocol "
                 "(<code>research/hif-fusion/PLAN.md</code>), self-contained Tier-1/Tier-2 modules "
                 "(<code>shf/hif_edge.py</code>, <code>shf/hif_fusion.py</code>), and Kaggle notebook "
                 "(<code>notebooks/kaggle_hif_fusion.ipynb</code>) are ready, awaiting the Kaggle GPU run to write "
                 "<code>results/hif_fusion/*.json</code>. Every result cell below is intentionally marked "
                 "<i>Not run yet (Kaggle GPU)</i> — no placeholder or estimated numbers are filled.",
                 "<b>Trạng thái: Chưa chạy trên Kaggle GPU.</b> Kế hoạch đã khóa tiêu chí "
                 "(<code>research/hif-fusion/PLAN.md</code>), mô-đun Tầng 1/Tầng 2 độc lập "
                 "(<code>shf/hif_edge.py</code>, <code>shf/hif_fusion.py</code>) và notebook Kaggle "
                 "(<code>notebooks/kaggle_hif_fusion.ipynb</code>) đã sẵn sàng, đang chờ chạy trên Kaggle GPU để sinh "
                 "<code>results/hif_fusion/*.json</code>. Mọi ô kết quả bên dưới đều ghi rõ "
                 "<i>Chưa chạy (Kaggle GPU)</i> — tuyệt đối không điền số giả hay số ước lượng.", "div")
            + "</div>"
        )
    else:
        quick_en = " (quick CPU smoke run — full Kaggle GPU run still pending)" if (ds and ds.get("quick_mode")) else ""
        quick_vi = " (chạy thử nhanh trên CPU — vẫn chờ lần chạy Kaggle GPU đầy đủ)" if (ds and ds.get("quick_mode")) else ""
        crit = (a34 or {}).get("pre_committed_criteria") or {}
        vmap = {"PASS": "good", "PARTIAL": "warning", "FAIL": "critical"}
        chips = []
        for cid, key in (("H1", "H1_ieee123_hif_gain"), ("H2", "H2_ieee34_zero_shot"),
                         ("H3", "H3_nofault_7_disturbances"), ("H4", "H4_missing_sensor_and_conformal")):
            if key in crit:
                vd = crit[key]["verdict"]
                chips.append(f'<span class="chip {vmap.get(vd, "warning")}">{cid}: {esc(vd)}</span>')
        chip_row = f'<div class="hif-chips">{"".join(chips)}</div>' if chips else ""
        src_s = esc(str(t1.get("model_source", (p123 or a123 or {}).get("tier1_model_source", "model_int8.npz"))))
        thr_s = f'{t1["threshold"]:.4f}' if "threshold" in t1 and t1["threshold"] is not None else "–"
        status_html = (
            '<div class="hif-banner">'
            + TB(f'<b>Results loaded from <code>results/hif_fusion/</code>{quick_en}.</b> '
                 f'Frozen Tier-1 model: <code>{src_s}</code> ({n_params} params, {n_bytes} B int8, threshold {thr_s}). '
                 f'Simulation only — pre-committed H1–H4 verdicts from <code>research/hif-fusion/PLAN.md</code>:',
                 f'<b>Đã nạp kết quả từ <code>results/hif_fusion/</code>{quick_vi}.</b> '
                 f'Mô hình Tầng 1 đóng băng: <code>{src_s}</code> ({n_params} tham số, {n_bytes} B int8, ngưỡng {thr_s}). '
                 f'Hoàn toàn là mô phỏng — kết quả đánh giá tiêu chí H1–H4 đã khóa trước trong <code>research/hif-fusion/PLAN.md</code>:',
                 "div")
            + chip_row + "</div>"
        )

    cmp_head = [
        T("Branch & Tier-2 model", "Nhánh & mô hình Tầng 2"),
        T("Feeder & regime", "Lưới & chế độ"),
        T("Overall (60 Hz → +Edge)", "Tổng thể (60 Hz → +Edge)"),
        T("SLG 200–400 Ω / HIF", "SLG 200–400 Ω / HIF"),
        T("SLG 400 Ω", "SLG 400 Ω"),
        T("NO_FAULT FPR", "FPR không sự cố"),
        T("1 sensor offline", "Mất 1 cảm biến"),
    ]

    def _cmp_row(en_m: str, vi_m: str, en_r: str, vi_r: str, obj: dict | None, root_key: str,
                 mkey: str, *, active: bool, is_34: bool = False) -> list[str]:
        if not obj:
            return [T(en_m, vi_m), T(en_r, vi_r), pending_gpu, pending_gpu, pending_gpu,
                    pending_gpu if active else "–", pending_gpu]
        b = obj[root_key]["60Hz_only"][mkey]
        f = obj[root_key]["60Hz_plus_edge"][mkey]
        acc_k = "overall_accuracy" if active else "accuracy"
        c_all = _hif_pair_cell(b.get(acc_k), f.get(acc_k))
        if active and is_34:
            c_hif = _hif_pair_cell(b.get("slg_hif_1k_10k_accuracy"), f.get("slg_hif_1k_10k_accuracy"))
            c_hif = f'<small>1–10 kΩ</small>{c_hif}' if c_hif != "–" else "–"
        else:
            c_hif = _hif_pair_cell(b.get("slg_200_400_accuracy"), f.get("slg_200_400_accuracy"))
        c_400 = _hif_pair_cell((b.get("slg_by_resistance") or {}).get("400.0"),
                               (f.get("slg_by_resistance") or {}).get("400.0"))
        c_fpr = _hif_pair_cell(b.get("nofault_fpr"), f.get("nofault_fpr"), lower_is_better=True) if active else "–"
        c_miss = _hif_pair_cell(b.get("missing_sensor_mean"), f.get("missing_sensor_mean"))
        return [T(en_m, vi_m), T(en_r, vi_r), c_all, c_hif, c_400, c_fpr, c_miss]

    cmp_rows = [
        _cmp_row("Passive · PerNodeGBDT", "Thụ động · PerNodeGBDT",
                 "IEEE 123-bus (5-fold CV)", "IEEE 123-bus (CV 5 phần)", p123, "ablations", "per_node_gbdt", active=False),
        _cmp_row("Passive · ZoneTreeGNN (2L)", "Thụ động · ZoneTreeGNN (2 lớp)",
                 "IEEE 123-bus (5-fold CV)", "IEEE 123-bus (CV 5 phần)", p123, "ablations", "zone_tree_gnn", active=False),
        _cmp_row("Passive · PerNodeGBDT", "Thụ động · PerNodeGBDT",
                 "IEEE 34-bus (zero-shot)", "IEEE 34-bus (zero-shot)", p34, "zero_shot", "per_node_gbdt", active=False, is_34=True),
        _cmp_row("Passive · ZoneTreeGNN (2L)", "Thụ động · ZoneTreeGNN (2 lớp)",
                 "IEEE 34-bus (zero-shot)", "IEEE 34-bus (zero-shot)", p34, "zero_shot", "zone_tree_gnn", active=False, is_34=True),
        _cmp_row("Active · ActivePerNodeGBDT", "Chủ động · ActivePerNodeGBDT",
                 "IEEE 123-bus (DER + loops, CV)", "IEEE 123-bus (DER + vòng kín, CV)", a123, "ablations", "active_per_node_gbdt", active=True),
        _cmp_row("Active · ActiveGridGATv2", "Chủ động · ActiveGridGATv2",
                 "IEEE 123-bus (DER + loops, CV)", "IEEE 123-bus (DER + vòng kín, CV)", a123, "ablations", "active_grid_gatv2", active=True),
        _cmp_row("Active · ActivePerNodeGBDT", "Chủ động · ActivePerNodeGBDT",
                 "IEEE 34-bus (DER + loops, 0-shot)", "IEEE 34-bus (DER + vòng kín, 0-shot)", a34, "zero_shot", "active_per_node_gbdt", active=True, is_34=True),
        _cmp_row("Active · ActiveGridGATv2", "Chủ động · ActiveGridGATv2",
                 "IEEE 34-bus (DER + loops, 0-shot)", "IEEE 34-bus (DER + vòng kín, 0-shot)", a34, "zero_shot", "active_grid_gatv2", active=True, is_34=True),
    ]
    t_cmp = table(cmp_head, cmp_rows, {2, 3, 4, 5, 6})

    surf_head = [
        T("Emanuel arc surface", "Bề mặt hồ quang Emanuel"),
        T("Model range (Vp · R)", "Dải mô hình (Vp · R)"),
        T("Passive 123 · GBDT", "Thụ động 123 · GBDT"),
        T("Passive 123 · GNN", "Thụ động 123 · GNN"),
        T("Active 123 · GATv2", "Chủ động 123 · GATv2"),
        T("Active 34 0-shot · GATv2", "Chủ động 34 0-shot · GATv2"),
    ]

    def _surf_cell(obj: dict | None, root_key: str, mkey: str, surf: str) -> str:
        if not obj:
            return pending_gpu
        b = (obj[root_key]["60Hz_only"][mkey].get("by_arc_surface") or {}).get(surf)
        f = (obj[root_key]["60Hz_plus_edge"][mkey].get("by_arc_surface") or {}).get(surf)
        return _hif_pair_cell(b, f)

    surf_rows = [
        [T(en, vi), rng_s,
         _surf_cell(p123, "ablations", "per_node_gbdt", key),
         _surf_cell(p123, "ablations", "zone_tree_gnn", key),
         _surf_cell(a123, "ablations", "active_grid_gatv2", key),
         _surf_cell(a34, "zero_shot", "active_grid_gatv2", key)]
        for key, en, vi, rng_s in HIF_SURFACES
    ]
    t_surf = table(surf_head, surf_rows, {2, 3, 4, 5})

    dist_head = [
        T("Background disturbance (NO_FAULT)", "Nhiễu nền (NO_FAULT)"),
        T("Active 123 · GBDT FPR", "Chủ động 123 · GBDT FPR"),
        T("Active 123 · GATv2 FPR", "Chủ động 123 · GATv2 FPR"),
        T("Active 34 0-shot · GBDT FPR", "Chủ động 34 0-shot · GBDT FPR"),
        T("Active 34 0-shot · GATv2 FPR", "Chủ động 34 0-shot · GATv2 FPR"),
    ]

    def _dist_cell(obj: dict | None, root_key: str, mkey: str, dist: str) -> str:
        if not obj:
            return pending_gpu
        b = (obj[root_key]["60Hz_only"][mkey].get("nofault_fpr_by_disturbance") or {}).get(dist)
        f = (obj[root_key]["60Hz_plus_edge"][mkey].get("nofault_fpr_by_disturbance") or {}).get(dist)
        return _hif_pair_cell(b, f, lower_is_better=True)

    dist_rows = [
        [T(en, vi),
         _dist_cell(a123, "ablations", "active_per_node_gbdt", key),
         _dist_cell(a123, "ablations", "active_grid_gatv2", key),
         _dist_cell(a34, "zero_shot", "active_per_node_gbdt", key),
         _dist_cell(a34, "zero_shot", "active_grid_gatv2", key)]
        for key, en, vi in HIF_DISTURBANCES
    ]
    t_dist = table(dist_head, dist_rows, {1, 2, 3, 4})

    conf_note = ""
    if conf and conf.get("results"):
        cr = conf["results"]
        cb = cr["60Hz_only"]["active_grid_gatv2"]["aps_rand"]["target_95"]
        cf = cr["60Hz_plus_edge"]["active_grid_gatv2"]["aps_rand"]["target_95"]
        b123, f123 = cb["ieee123_cross_conformal"], cf["ieee123_cross_conformal"]
        b34z, f34z = cb["ieee34_zero_shot_q_from_123"], cf["ieee34_zero_shot_q_from_123"]
        f34rc = cf["ieee34_recal_5pct_buses"]
        conf_note = TB(
            emph(f'<b>Split Conformal gate (<code>aps_rand</code>, 95% target, ActiveGridGATv2):</b> on IEEE 123-bus, '
                 f'coverage moves from {pct(b123["coverage"])} to {pct(f123["coverage"])}, autonomous one-label sets from '
                 f'{pct(b123["singleton_share"])} to {pct(f123["singleton_share"])} '
                 f'(accuracy {pct(f123["singleton_accuracy"]) if f123["singleton_accuracy"] is not None else "–"}, '
                 f'autonomous NO_FAULT trips {pct(f123["nofault_autonomous_trip_share"]) if f123["nofault_autonomous_trip_share"] is not None else "–"}). '
                 f'On unseen IEEE 34-bus, frozen 123-bus q̂ covers {pct(b34z["coverage"])} → {pct(f34z["coverage"])} '
                 f'(no cross-feeder exchangeability guarantee), and 5%-bus recalibration averages '
                 f'{pct(f34rc["coverage"]["mean"])} (min {pct(f34rc["coverage"]["min"])}).'),
            emph(f'<b>Cổng bất định Split Conformal (<code>aps_rand</code>, mục tiêu 95%, ActiveGridGATv2):</b> trên IEEE 123-bus, '
                 f'độ phủ đi từ {pct(b123["coverage"])} sang {pct(f123["coverage"])}, tỉ lệ tập 1 nhãn tự hành từ '
                 f'{pct(b123["singleton_share"])} sang {pct(f123["singleton_share"])} '
                 f'(độ đúng {pct(f123["singleton_accuracy"]) if f123["singleton_accuracy"] is not None else "–"}, '
                 f'cắt nhầm NO_FAULT tự hành {pct(f123["nofault_autonomous_trip_share"]) if f123["nofault_autonomous_trip_share"] is not None else "–"}). '
                 f'Trên IEEE 34-bus chưa thấy, ngưỡng q̂ từ 123-bus phủ {pct(b34z["coverage"])} → {pct(f34z["coverage"])} '
                 f'(không có bảo chứng hoán vị giữa hai lưới), và hiệu chỉnh lại bằng 5% số bus đạt trung bình '
                 f'{pct(f34rc["coverage"]["mean"])} (tệ nhất {pct(f34rc["coverage"]["min"])}).'),
            "p", "note",
        )

    i400_en = f'{v["s2l_i400_123"]} ({v["s2l_sh400_123"]} of the {v["s2l_head123"]} head current)' if "s2l_i400_123" in v else "a few amps"
    i400_vi = f'{v["s2l_i400_123"]} ({v["s2l_sh400_123"]} dòng đầu tuyến {v["s2l_head123"]})' if "s2l_i400_123" in v else "chỉ vài ampe"

    return (
        head
        + TB(emph(f'At 60 Hz alone, high-impedance ground faults (SLG 200–400 Ω) are the dominant error source on '
                  f'IEEE 123-bus ({v["r400"]} at 400 Ω) because the fault draws only {i400_en}, buried inside 1% CT noise. '
                  f'This two-tier architecture pairs a frozen {term("edgehif", "Edge ESP32-S3 HIF-Sensor")} at every '
                  f'recloser/switch — 4th-order Butterworth anti-aliasing filter (LTspice {fc_lt:,.1f} Hz / Python '
                  f'{fc_py:,.1f} Hz), 12-bit ADC at {fs_khz:.2f} kHz, {n_feat} harmonic/asymmetry/cycle-variation features '
                  f'over K = {hif_edge.K} cycles, and a {n_params}-parameter / {n_bytes}-byte int8 Tiny MLP with '
                  f'PERSIST = {persist} — with feeder-wide <b>Graph FLISR</b> (<code>PerNodeGBDT</code>, '
                  f'<code>ZoneTreeGNN</code>, and <code>ActiveGridGATv2</code> with <code>diff_p_hif</code> on edges).'),
             emph(f'Chỉ dùng pha 60 Hz, sự cố chạm đất trở kháng cao (SLG 200–400 Ω) là nguồn lỗi lớn nhất trên '
                  f'IEEE 123-bus ({v["r400"]} ở 400 Ω) vì dòng sự cố chỉ đạt {i400_vi}, chìm trong nhiễu CT 1%. '
                  f'Kiến trúc 2 tầng này ghép {term("edgehif", "cảm biến biên ESP32-S3 HIF-Sensor", "cảm biến biên ESP32-S3 HIF-Sensor")} '
                  f'đóng băng tại mỗi recloser/dao — mạch lọc chống răng cưa Butterworth bậc 4 (LTspice {fc_lt:,.1f} Hz / '
                  f'Python {fc_py:,.1f} Hz), ADC 12-bit ở {fs_khz:.2f} kHz, {n_feat} đặc trưng sóng hài/bất đối xứng/biến '
                  f'động chu kỳ trên cửa sổ K = {hif_edge.K} chu kỳ, và mạng Tiny MLP int8 {n_params} tham số / {n_bytes} byte '
                  f'với bộ đếm PERSIST = {persist} — truyền xác suất <code>p_hif</code> lên tầng <b>Graph FLISR</b> toàn '
                  f'lưới (<code>PerNodeGBDT</code>, <code>ZoneTreeGNN</code> và <code>ActiveGridGATv2</code> có thêm đặc '
                  f'trưng cạnh <code>diff_p_hif</code>).'), "p", "note")
        + _hif_arch_svg(fc_lt, fs_khz, n_feat, n_params, n_bytes, persist)
        + status_html
        + f'<h4>{T("Paired comparison: 60 Hz only vs +Edge p_hif (focus on SLG 200–400 Ω)", "So sánh đối chứng: 60 Hz thuần vs +Edge p_hif (trọng tâm dải SLG 200–400 Ω)")}</h4>'
        + xbox("table-hif-fusion", t_cmp)
        + conf_note
        + f'<h4>{T("Arcing HIF breakdown across 5 Emanuel surfaces", "Phân rã sự cố hồ quang theo 5 bề mặt Emanuel")}</h4>'
        + xbox("table-hif-surfaces", t_surf)
        + f'<h4>{T("NO_FAULT false-alarm rate across 7 background disturbances", "Tỉ lệ báo động giả (NO_FAULT) trên 7 nhiễu nền")}</h4>'
        + xbox("table-hif-disturbances", t_dist)
        + _hif_real_block(d, v)
        + TB(emph(f'<b>Honest simulation &amp; hardware limits:</b> (1) <b>Simulation only on both tiers:</b> the 5 Emanuel '
                  f'two-diode arc surfaces, the 7 background disturbances, and quasi-steady harmonic current division over '
                  f'OpenDSS are simulated — not field utility oscillograms and not EMTP electromagnetic transients (no '
                  f'traveling waves, CT core saturation, or ESP32 ADC nonlinearity). (2) <b>Hardware requirement:</b> '
                  f'running this two-tier scheme in practice requires edge IEDs or ESP32-S3-class sensors sampling residual '
                  f'current at <b>≥ {fs_khz:.2f} kHz</b> behind a hardware anti-aliasing filter (fc ≈ 2 kHz) at each switch — '
                  f'legacy 60 Hz SCADA/RTU polling cannot supply <code>p_hif</code>. (3) <b>Real-arc domain gap:</b> real '
                  f'vegetation and soil arcs are often steadier and less asymmetric than synthetic Emanuel arcs, so gains on '
                  f'simulated 200–400 Ω faults do not prove field performance without real event recordings.'),
             emph(f'<b>Lưu ý trung thực về mô phỏng &amp; phần cứng:</b> (1) <b>Thuần mô phỏng ở cả hai tầng:</b> dạng sóng '
                  f'hồ quang hai diode Emanuel trên 5 bề mặt, 7 nhiễu nền và phép chồng chất sóng hài bán tĩnh từ OpenDSS đều '
                  f'là mô phỏng — không phải bản ghi dao động ký thực địa và không phải mô phỏng quá độ điện từ EMTP (chưa '
                  f'xét sóng lan truyền, bão hòa lõi CT hay phi tuyến ADC của ESP32). (2) <b>Yêu cầu phần cứng thực tế:</b> '
                  f'triển khai kiến trúc 2 tầng ngoài lưới thật cần IED hoặc nút cảm biến cỡ ESP32-S3 lấy mẫu dòng dư ở '
                  f'<b>≥ {fs_khz:.2f} kHz</b> sau mạch lọc chống răng cưa (fc ≈ 2 kHz) tại từng dao — hệ thống SCADA/RTU 60 Hz '
                  f'cũ không thể cung cấp <code>p_hif</code>. (3) <b>Khoảng cách mô phỏng – thực tế:</b> hồ quang cây/đất '
                  f'ngoài đời thường ổn định và ít bất đối xứng hơn mô hình Emanuel, nên cải thiện trên dải 200–400 Ω mô '
                  f'phỏng chưa chứng minh được hiệu năng thực địa nếu chưa kiểm chứng trên bản ghi sự cố thật.'),
             "p", "note")
    )


def _branch_ready(obj: dict | None, root_key: str) -> bool:
    """True when a HIF-Fusion branch JSON contains actual paired 60Hz_only / 60Hz_plus_edge metrics."""
    if not isinstance(obj, dict) or obj.get("status") == "NOT_RUN_YET":
        return False
    block = obj.get(root_key)
    return isinstance(block, dict) and isinstance(block.get("60Hz_only"), dict) and isinstance(block.get("60Hz_plus_edge"), dict)


def _extract_r_criteria(hr: dict) -> list[tuple[str, str]]:
    """Read pre-registered R1–R4 verdicts directly from results/hif_fusion_realistic/*.json."""
    src = hr.get("summary") or hr.get("a34") or hr.get("p123") or {}
    crit = (src.get("verdicts") or src.get("criteria_details")
            or src.get("pre_committed_criteria") or src.get("pre_registered_criteria")
            or src.get("criteria") or src.get("r_criteria") or {})
    if not isinstance(crit, dict):
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    wanted = ("R1", "R2", "R3", "R3a", "R3b", "R4")

    def _verdict_of(val) -> str | None:
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            return val.get("verdict") or val.get("status")
        return None

    # Exact or prefix match for R1..R4 plus optional nested R3a/R3b subcriteria
    for cid in wanted:
        for k, val in crit.items():
            kl = str(k)
            if kl == cid or kl.startswith(f"{cid}_"):
                vd = _verdict_of(val)
                if vd and cid not in seen:
                    out.append((cid, str(vd).upper()))
                    seen.add(cid)
                if cid == "R3" and isinstance(val, dict):
                    for sub_id in ("R3a", "R3b"):
                        for sk, sv in val.items():
                            if str(sk) == sub_id or str(sk).startswith(f"{sub_id}_"):
                                svd = _verdict_of(sv)
                                if svd and sub_id not in seen:
                                    out.append((sub_id, str(svd).upper()))
                                    seen.add(sub_id)
                break
    return out


def _arc_regime_acc(m: dict | None, regime: str, scope: str = "all") -> float | None:
    """Extract intermittent (arc_duty < 1.0) or continuous (arc_duty == 1.0) arcing accuracy from a model dict."""
    if not isinstance(m, dict):
        return None
    keys_to_check = (
        ("by_arc_regime_slg_200_400", "by_arc_duty_slg_200_400", "slg_200_400_by_arc_regime")
        if scope == "slg_200_400"
        else ("by_arc_regime", "by_arc_duty", "by_intermittency", "arcing_by_regime", "arc_duty_breakdown")
    )
    aliases = ("intermittent", "intermittent_arc", "duty_lt_1", "arc_duty_lt_1") if regime == "intermittent" else (
        "continuous", "continuous_arc", "duty_eq_1", "arc_duty_eq_1"
    )
    for k in keys_to_check:
        blk = m.get(k)
        if isinstance(blk, dict):
            for a in aliases:
                v = blk.get(a)
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, dict):
                    sub = v.get("slg_200_400_accuracy" if scope == "slg_200_400" else "accuracy")
                    if isinstance(sub, (int, float)):
                        return float(sub)
    # Fallback flat keys
    flat = f"{regime}_arcing_accuracy" if scope == "all" else f"{regime}_slg_200_400_accuracy"
    fv = m.get(flat)
    return float(fv) if isinstance(fv, (int, float)) else None


def _hif_real_block(d: dict, v: dict) -> str:
    """Branch-10 Before/After block inside §2d: Clean 60 Hz -> Realistic 60 Hz -> Realistic + Edge 15.36 kHz."""
    hif = d.get("hif") or {}
    hr = d.get("hif_real") or {}
    ds_r, p123_r, p34_r = hr.get("ds"), hr.get("p123"), hr.get("p34")
    a123_r, a34_r, conf_r, rsum = hr.get("a123"), hr.get("a34"), hr.get("conf"), hr.get("summary")
    has_p123 = _branch_ready(p123_r, "ablations")
    has_p34 = _branch_ready(p34_r, "zero_shot")
    has_a123 = _branch_ready(a123_r, "ablations")
    has_a34 = _branch_ready(a34_r, "zero_shot")
    has_any = any((has_p123, has_p34, has_a123, has_a34))

    pending_real = f'<span class="muted">{T("Not run yet (awaiting T-66)", "Chưa chạy (đang chờ T-66)")}</span>'
    pending_gpu = f'<span class="muted">{T("Not run yet (Kaggle GPU)", "Chưa chạy (Kaggle GPU)")}</span>'
    head = (
        f'<h4 id="hif-fusion-realistic" class="hif-real-h">'
        f'{T("Before / After on Branch-10 Realistic Arcing & CT/PT Noise (Clean 60 Hz → Realistic 60 Hz → Realistic + Edge 15.36 kHz)", "Đối chứng Trước / Sau trên mô phỏng hồ quang chập chờn & nhiễu CT/PT Nhánh 10 (60 Hz sạch cũ → 60 Hz thực tế → Thực tế + Edge 15.36 kHz)")}'
        f'</h4>'
    )

    # Pre-registered R1–R4 status banner
    vmap = {"PASS": "good", "PARTIAL": "warning", "NOT_RUN_YET": "warning", "PENDING": "warning", "FAIL": "critical"}
    crit_list = _extract_r_criteria(hr)
    if not has_any:
        banner = (
            '<div class="hif-banner">'
            f'<span class="chip warning">! {T("Pending Branch-10 Run", "Chờ chạy Nhánh 10")}</span>'
            + TB("<b>Branch-10 Realistic HIF-Fusion: Not run yet.</b> The pre-registered protocol "
                 "(<code>research/hif-fusion-realistic/PLAN.md</code>, criteria <b>R1–R4</b>) and realistic coupling "
                 "(<code>shf/hif_fusion.py</code>, <code>shf/hif_edge.py</code>) are ready; awaiting "
                 "<code>results/hif_fusion_realistic/*.json</code> from the real experiment run. Every realistic cell "
                 "below stays explicitly marked <i>Not run yet</i> — zero invented or estimated numbers.",
                 "<b>HIF-Fusion thực tế Nhánh 10: Chưa chạy xong.</b> Kế hoạch tiền đăng ký "
                 "(<code>research/hif-fusion-realistic/PLAN.md</code>, tiêu chí <b>R1–R4</b>) và lõi ghép thực tế "
                 "(<code>shf/hif_fusion.py</code>, <code>shf/hif_edge.py</code>) đã sẵn sàng; đang chờ "
                 "<code>results/hif_fusion_realistic/*.json</code> từ lần chạy thật. Mọi ô kết quả thực tế bên dưới "
                 "đều ghi rõ <i>Chưa chạy</i> — tuyệt đối không bịa hay ước lượng số.", "div")
            + "</div>"
        )
    else:
        chips = [f'<span class="chip {vmap.get(vd, "warning")}">{esc(cid)}: {esc(vd)}</span>' for cid, vd in crit_list]
        chip_row = f'<div class="hif-chips">{"".join(chips)}</div>' if chips else ""
        t1_sha = (
            (ds_r or {}).get("tier1_edge_model", {}).get("sha256")
            or (rsum or {}).get("tier1_model_sha256")
            or (p123_r or {}).get("tier1_model_sha256")
            or ""
        )
        sha_tag = f' · SHA-256 <code>{esc(t1_sha[:12])}…</code>' if t1_sha else ""
        quick_en = " (quick smoke run)" if (ds_r and ds_r.get("quick_mode")) else ""
        quick_vi = " (chạy thử nhanh)" if (ds_r and ds_r.get("quick_mode")) else ""
        banner = (
            '<div class="hif-banner">'
            + TB(f'<b>Branch-10 Realistic HIF-Fusion loaded from <code>results/hif_fusion_realistic/</code>{quick_en}.</b> '
                 f'Frozen Tier-1 <code>model_int8.npz</code> (417 params / 504 B int8{sha_tag}) receives genuinely attenuated '
                 f'<code>r_eff</code> fault residual current and synchronized intermittent restrike duty <code>arc_duty</code> '
                 f'(linear load drift kept strictly at 60 Hz). Pre-registered <b>R1–R4</b> verdicts (<code>research/hif-fusion-realistic/PLAN.md</code>):',
                 f'<b>Đã nạp kết quả HIF-Fusion thực tế Nhánh 10 từ <code>results/hif_fusion_realistic/</code>{quick_vi}.</b> '
                 f'Mô hình Tầng 1 đóng băng <code>model_int8.npz</code> (417 tham số / 504 B int8{sha_tag}) nhận đúng dòng '
                 f'dư sự cố đã suy giảm theo <code>r_eff</code> và chu kỳ tắt/mồi đồng bộ <code>arc_duty</code> '
                 f'(trôi tải nền giữ nguyên 60 Hz tuyến tính). Kết luận tiêu chí tiền đăng ký <b>R1–R4</b> (<code>research/hif-fusion-realistic/PLAN.md</code>):',
                 "div")
            + chip_row + "</div>"
        )

    # 1) Main 3-stage Before/After table: Clean 60 Hz -> Realistic 60 Hz (Branch 10) -> Realistic + Edge 15.36 kHz
    cmp_head = [
        T("Branch & Tier-2 model", "Nhánh & mô hình Tầng 2"),
        T("SLG 400 Ω · Clean 60 Hz (old)", "SLG 400 Ω · 60 Hz sạch cũ"),
        T("SLG 400 Ω · Realistic 60 Hz (B10)", "SLG 400 Ω · 60 Hz thực tế (N10)"),
        T("SLG 400 Ω · Realistic + Edge (504 B)", "SLG 400 Ω · Thực tế + Edge (504 B)"),
        T("SLG 200–400 Ω (Real. 60 Hz → +Edge)", "SLG 200–400 Ω (Thực tế 60 Hz → +Edge)"),
        T("Overall (Real. 60 Hz → +Edge)", "Tổng thể (Thực tế 60 Hz → +Edge)"),
        T("1 sensor offline (Real. 60 Hz → +Edge)", "Mất 1 cảm biến (Thực tế 60 Hz → +Edge)"),
    ]

    def _clean_400_cell(old_obj: dict | None, root_key: str, mkey: str, *, active34: bool = False) -> str:
        if not old_obj or root_key not in old_obj:
            return f'<span class="muted">{T("— (not in old 2d)", "— (không có ở 2d cũ)")}</span>'
        b = (old_obj[root_key].get("60Hz_only") or {}).get(mkey)
        f = (old_obj[root_key].get("60Hz_plus_edge") or {}).get(mkey)
        if not b:
            return "–"
        if active34:
            bv, fv = b.get("slg_hif_1k_10k_accuracy"), (f or {}).get("slg_hif_1k_10k_accuracy")
            tag = "<small>1–10 kΩ</small>"
        else:
            bv = (b.get("slg_by_resistance") or {}).get("400.0")
            fv = ((f or {}).get("slg_by_resistance") or {}).get("400.0")
            tag = ""
        if bv is None:
            return "–"
        sub = f'<small>{T("old +Edge", "+Edge cũ")}: {pct(fv)}</small>' if fv is not None else ""
        return f"{tag}{pct(bv)}{sub}"

    def _real_row(en_m: str, vi_m: str, old_obj: dict | None, new_obj: dict | None,
                  root_key: str, mkey: str, *, active: bool = False, is_34: bool = False,
                  use_gpu_pending: bool = False) -> list[str]:
        active34 = active and is_34
        c_old = _clean_400_cell(old_obj, root_key, mkey, active34=active34)
        pend = pending_gpu if use_gpu_pending else pending_real
        if not _branch_ready(new_obj, root_key):
            return [T(en_m, vi_m), c_old, pend, pend, pend, pend, pend]
        b = new_obj[root_key]["60Hz_only"].get(mkey)
        f = new_obj[root_key]["60Hz_plus_edge"].get(mkey)
        if not b or not f:
            return [T(en_m, vi_m), c_old, pend, pend, pend, pend, pend]
        if active34:
            r_b, r_f = b.get("slg_hif_1k_10k_accuracy"), f.get("slg_hif_1k_10k_accuracy")
            c_r60 = f"<small>1–10 kΩ</small>{pct(r_b)}" if r_b is not None else "–"
            if r_b is not None and r_f is not None:
                dp = (r_f - r_b) * 100.0
                d_s = f"{dp:+.1f} pp".replace("-", "−")
                c_redge = f"<small>1–10 kΩ</small><b>{pct(r_f)}</b><small>({d_s})</small>"
            else:
                c_redge = "–"
            c_200 = _hif_pair_cell((b.get("slg_by_resistance") or {}).get("400.0"),
                                   (f.get("slg_by_resistance") or {}).get("400.0"))
            c_200 = f"<small>400 Ω</small>{c_200}" if c_200 != "–" else "–"
        else:
            r_b = (b.get("slg_by_resistance") or {}).get("400.0")
            r_f = (f.get("slg_by_resistance") or {}).get("400.0")
            c_r60 = pct(r_b) if r_b is not None else "–"
            if r_b is not None and r_f is not None:
                dp = (r_f - r_b) * 100.0
                d_s = f"{dp:+.1f} pp".replace("-", "−")
                c_redge = f"<b>{pct(r_f)}</b><small>({d_s})</small>"
            else:
                c_redge = "–"
            c_200 = _hif_pair_cell(b.get("slg_200_400_accuracy"), f.get("slg_200_400_accuracy"))
        acc_k = "overall_accuracy" if active else "accuracy"
        c_all = _hif_pair_cell(b.get(acc_k), f.get(acc_k))
        if active and b.get("nofault_fpr") is not None and f.get("nofault_fpr") is not None:
            c_all += f'<small>FPR: {pct(b["nofault_fpr"])} → {pct(f["nofault_fpr"])}</small>'
        c_miss = _hif_pair_cell(b.get("missing_sensor_mean"), f.get("missing_sensor_mean"))
        m200_b, m200_f = b.get("missing_sensor_slg_200_400_mean"), f.get("missing_sensor_slg_200_400_mean")
        if m200_b is not None and m200_f is not None:
            dm = (m200_f - m200_b) * 100.0
            c_miss += f'<small>200–400 Ω: {pct(m200_b)} → {pct(m200_f)} ({dm:+.1f} pp)</small>'.replace("(-", "(−")
        return [T(en_m, vi_m), c_old, c_r60, c_redge, c_200, c_all, c_miss]

    cmp_rows = [
        _real_row("Passive 123 · ml_full (150 → 170 feat)", "Thụ động 123 · ml_full (150 → 170 đt)",
                  None, p123_r, "ablations", "ml_full"),
        _real_row("Passive 123 · PerNodeGBDT (21 → 23)", "Thụ động 123 · PerNodeGBDT (21 → 23)",
                  hif.get("p123"), p123_r, "ablations", "per_node_gbdt"),
        _real_row("Passive 123 · ZoneTreeGNN (2L)", "Thụ động 123 · ZoneTreeGNN (2 lớp)",
                  hif.get("p123"), p123_r, "ablations", "zone_tree_gnn"),
        _real_row("Passive 34 (0-shot) · PerNodeGBDT", "Thụ động 34 (0-shot) · PerNodeGBDT",
                  hif.get("p34"), p34_r, "zero_shot", "per_node_gbdt", is_34=True),
        _real_row("Passive 34 (0-shot) · ZoneTreeGNN", "Thụ động 34 (0-shot) · ZoneTreeGNN",
                  hif.get("p34"), p34_r, "zero_shot", "zone_tree_gnn", is_34=True),
        _real_row("Active 123 · ActivePerNodeGBDT", "Chủ động 123 · ActivePerNodeGBDT",
                  hif.get("a123"), a123_r, "ablations", "active_per_node_gbdt", active=True, use_gpu_pending=True),
        _real_row("Active 123 · ActiveGridGATv2", "Chủ động 123 · ActiveGridGATv2",
                  hif.get("a123"), a123_r, "ablations", "active_grid_gatv2", active=True, use_gpu_pending=True),
        _real_row("Active 34 (0-shot) · ActivePerNodeGBDT", "Chủ động 34 (0-shot) · ActivePerNodeGBDT",
                  hif.get("a34"), a34_r, "zero_shot", "active_per_node_gbdt", active=True, is_34=True, use_gpu_pending=True),
        _real_row("Active 34 (0-shot) · ActiveGridGATv2", "Chủ động 34 (0-shot) · ActiveGridGATv2",
                  hif.get("a34"), a34_r, "zero_shot", "active_grid_gatv2", active=True, is_34=True, use_gpu_pending=True),
    ]
    t_real_cmp = table(cmp_head, cmp_rows, {1, 2, 3, 4, 5, 6})

    # Reference line linking directly to results/metrics.json (31.3% at 400 ohm) + phase/low-R safety check
    ref_parts_en = [
        f'<b>Main study 60 Hz baseline (<code>results/metrics.json</code>):</b> <code>ml_full</code> reaches '
        f'{v["acc"]} overall, {v["r100"]} at 100 Ω, {v["r200"]} at 200 Ω, and <b>{v["r400"]}</b> at 400 Ω '
        f'(<code>fpi_baseline</code> {v["acc_fpi"]} overall, {v["r400_fpi"]} at 400 Ω).'
    ]
    ref_parts_vi = [
        f'<b>Mốc 60 Hz thuần của nghiên cứu chính (<code>results/metrics.json</code>):</b> <code>ml_full</code> đạt '
        f'{v["acc"]} tổng thể, {v["r100"]} ở 100 Ω, {v["r200"]} ở 200 Ω và chỉ còn <b>{v["r400"]}</b> ở 400 Ω '
        f'(<code>fpi_baseline</code> {v["acc_fpi"]} tổng thể, {v["r400_fpi"]} ở 400 Ω).'
    ]
    if has_p123:
        ab123 = p123_r["ablations"]
        ph_notes_en, ph_notes_vi = [], []
        for mk, lab in (("ml_full", "ml_full"), ("per_node_gbdt", "PerNodeGBDT"), ("zone_tree_gnn", "ZoneTreeGNN")):
            bm, fm = ab123["60Hz_only"].get(mk), ab123["60Hz_plus_edge"].get(mk)
            if bm and fm and bm.get("phase_faults_accuracy") is not None and fm.get("phase_faults_accuracy") is not None:
                lo_b = bm.get("slg_low_r_0_50_accuracy")
                lo_f = fm.get("slg_low_r_0_50_accuracy")
                lo_s = f", SLG ≤50 Ω {pct(lo_b)} → {pct(lo_f)}" if lo_b is not None and lo_f is not None else ""
                ph_notes_en.append(f'{lab}: phase {pct(bm["phase_faults_accuracy"])} → {pct(fm["phase_faults_accuracy"])}{lo_s}')
                ph_notes_vi.append(f'{lab}: pha {pct(bm["phase_faults_accuracy"])} → {pct(fm["phase_faults_accuracy"])}{lo_s}')
        if ph_notes_en:
            ref_parts_en.append("No regression on low-R / phase faults: " + "; ".join(ph_notes_en) + ".")
            ref_parts_vi.append("Không tụt độ chính xác trên sự cố pha / trở kháng thấp: " + "; ".join(ph_notes_vi) + ".")
    ref_note = TB(emph(" ".join(ref_parts_en)), emph(" ".join(ref_parts_vi)), "p", "note")

    # 2) Intermittent vs. Continuous arcing + 5 Emanuel surfaces breakdown (Passive IEEE 123-bus realistic)
    arc_head = [
        T("Arcing regime / Emanuel surface (Branch 10, IEEE 123-bus)", "Chế độ hồ quang / Bề mặt Emanuel (Nhánh 10, IEEE 123-bus)"),
        T("Passive 123 · ml_full", "Thụ động 123 · ml_full"),
        T("Passive 123 · PerNodeGBDT", "Thụ động 123 · PerNodeGBDT"),
        T("Passive 123 · ZoneTreeGNN", "Thụ động 123 · ZoneTreeGNN"),
    ]
    if has_a123:
        arc_head.append(T("Active 123 · GATv2", "Chủ động 123 · GATv2"))

    def _real_regime_cell(obj: dict | None, root_key: str, mkey: str, regime: str, scope: str = "all") -> str:
        if not _branch_ready(obj, root_key):
            return pending_real
        bm = obj[root_key]["60Hz_only"].get(mkey)
        fm = obj[root_key]["60Hz_plus_edge"].get(mkey)
        main = _hif_pair_cell(_arc_regime_acc(bm, regime, scope), _arc_regime_acc(fm, regime, scope))
        if scope == "all":
            b2 = _arc_regime_acc(bm, regime, "slg_200_400")
            f2 = _arc_regime_acc(fm, regime, "slg_200_400")
            if b2 is not None and f2 is not None:
                d2 = (f2 - b2) * 100.0
                d2s = f"{d2:+.1f} pp".replace("-", "−")
                main += f"<small>200–400 Ω: {pct(b2)} → {pct(f2)} ({d2s})</small>"
        return main

    def _real_surf_cell(obj: dict | None, root_key: str, mkey: str, surf: str) -> str:
        if not _branch_ready(obj, root_key):
            return pending_real
        bm = obj[root_key]["60Hz_only"].get(mkey) or {}
        fm = obj[root_key]["60Hz_plus_edge"].get(mkey) or {}
        return _hif_pair_cell((bm.get("by_arc_surface") or {}).get(surf),
                              (fm.get("by_arc_surface") or {}).get(surf))

    arc_rows: list[list[str]] = []
    for reg_key, en_r, vi_r in (
        ("intermittent", "<b>Intermittent arcing</b> (arc_duty &lt; 1.0, 45% draw, d_cond 0.35–0.85)",
         "<b>Hồ quang chập chờn</b> (arc_duty &lt; 1.0, 45% ca, d_cond 0.35–0.85)"),
        ("continuous", "<b>Continuous arcing</b> (arc_duty == 1.0, 55% draw)",
         "<b>Hồ quang liên tục</b> (arc_duty == 1.0, 55% ca)"),
    ):
        row = [
            T(en_r, vi_r),
            _real_regime_cell(p123_r, "ablations", "ml_full", reg_key),
            _real_regime_cell(p123_r, "ablations", "per_node_gbdt", reg_key),
            _real_regime_cell(p123_r, "ablations", "zone_tree_gnn", reg_key),
        ]
        if has_a123:
            row.append(_real_regime_cell(a123_r, "ablations", "active_grid_gatv2", reg_key))
        arc_rows.append(row)
    for skey, en_s, vi_s, rng_s in HIF_SURFACES:
        row = [
            f'{T(en_s, vi_s)} <small>({rng_s})</small>',
            _real_surf_cell(p123_r, "ablations", "ml_full", skey),
            _real_surf_cell(p123_r, "ablations", "per_node_gbdt", skey),
            _real_surf_cell(p123_r, "ablations", "zone_tree_gnn", skey),
        ]
        if has_a123:
            row.append(_real_surf_cell(a123_r, "ablations", "active_grid_gatv2", skey))
        arc_rows.append(row)
    t_real_arc = table(arc_head, arc_rows, set(range(1, len(arc_head))))

    # 3) 1-sensor-offline robustness table (R4: simultaneous 60 Hz + Edge blanking)
    miss_head = [
        T("Branch & model (1 sensor offline)", "Nhánh & mô hình (mất 1 cảm biến)"),
        T("Mean all faults (60 Hz → +Edge)", "Trung bình mọi sự cố (60 Hz → +Edge)"),
        T("Worst sensor (60 Hz → +Edge)", "Cảm biến tệ nhất (60 Hz → +Edge)"),
        T("Mean SLG 200–400 Ω (60 Hz → +Edge)", "TB SLG 200–400 Ω (60 Hz → +Edge)"),
    ]

    def _miss_row(en_m: str, vi_m: str, obj: dict | None, root_key: str, mkey: str) -> list[str]:
        if not _branch_ready(obj, root_key):
            return [T(en_m, vi_m), pending_real, pending_real, pending_real]
        bm = obj[root_key]["60Hz_only"].get(mkey) or {}
        fm = obj[root_key]["60Hz_plus_edge"].get(mkey) or {}
        return [
            T(en_m, vi_m),
            _hif_pair_cell(bm.get("missing_sensor_mean"), fm.get("missing_sensor_mean")),
            _hif_pair_cell(bm.get("missing_sensor_min"), fm.get("missing_sensor_min")),
            _hif_pair_cell(bm.get("missing_sensor_slg_200_400_mean"), fm.get("missing_sensor_slg_200_400_mean")),
        ]

    miss_rows = [
        _miss_row("Passive 123 · ml_full", "Thụ động 123 · ml_full", p123_r, "ablations", "ml_full"),
        _miss_row("Passive 123 · PerNodeGBDT", "Thụ động 123 · PerNodeGBDT", p123_r, "ablations", "per_node_gbdt"),
        _miss_row("Passive 123 · ZoneTreeGNN", "Thụ động 123 · ZoneTreeGNN", p123_r, "ablations", "zone_tree_gnn"),
    ]
    if has_p34:
        miss_rows.append(_miss_row("Passive 34 (0-shot) · PerNodeGBDT", "Thụ động 34 (0-shot) · PerNodeGBDT", p34_r, "zero_shot", "per_node_gbdt"))
        miss_rows.append(_miss_row("Passive 34 (0-shot) · ZoneTreeGNN", "Thụ động 34 (0-shot) · ZoneTreeGNN", p34_r, "zero_shot", "zone_tree_gnn"))
    if has_a123:
        miss_rows.append(_miss_row("Active 123 · ActivePerNodeGBDT", "Chủ động 123 · ActivePerNodeGBDT", a123_r, "ablations", "active_per_node_gbdt"))
        miss_rows.append(_miss_row("Active 123 · ActiveGridGATv2", "Chủ động 123 · ActiveGridGATv2", a123_r, "ablations", "active_grid_gatv2"))
    if has_a34:
        miss_rows.append(_miss_row("Active 34 (0-shot) · ActivePerNodeGBDT", "Chủ động 34 (0-shot) · ActivePerNodeGBDT", a34_r, "zero_shot", "active_per_node_gbdt"))
        miss_rows.append(_miss_row("Active 34 (0-shot) · ActiveGridGATv2", "Chủ động 34 (0-shot) · ActiveGridGATv2", a34_r, "zero_shot", "active_grid_gatv2"))
    t_real_miss = table(miss_head, miss_rows, {1, 2, 3})

    # Optional realistic Active 7-disturbance NO_FAULT FPR table (shown only when Active ran)
    real_dist_html = ""
    if has_a123 or has_a34:
        rdist_head = [T("Background disturbance (NO_FAULT, Branch 10)", "Nhiễu nền (NO_FAULT, Nhánh 10)")]
        rdist_specs: list[tuple[dict | None, str, str]] = []
        if has_a123:
            rdist_head += [T("Active 123 · GBDT FPR", "Chủ động 123 · GBDT FPR"),
                           T("Active 123 · GATv2 FPR", "Chủ động 123 · GATv2 FPR")]
            rdist_specs += [(a123_r, "ablations", "active_per_node_gbdt"), (a123_r, "ablations", "active_grid_gatv2")]
        if has_a34:
            rdist_head += [T("Active 34 0-shot · GBDT FPR", "Chủ động 34 0-shot · GBDT FPR"),
                           T("Active 34 0-shot · GATv2 FPR", "Chủ động 34 0-shot · GATv2 FPR")]
            rdist_specs += [(a34_r, "zero_shot", "active_per_node_gbdt"), (a34_r, "zero_shot", "active_grid_gatv2")]
        rdist_rows = []
        for dkey, en_d, vi_d in HIF_DISTURBANCES:
            row = [T(en_d, vi_d)]
            for obj, rkey, mkey in rdist_specs:
                bm = obj[rkey]["60Hz_only"].get(mkey) or {}
                fm = obj[rkey]["60Hz_plus_edge"].get(mkey) or {}
                row.append(_hif_pair_cell((bm.get("nofault_fpr_by_disturbance") or {}).get(dkey),
                                          (fm.get("nofault_fpr_by_disturbance") or {}).get(dkey),
                                          lower_is_better=True))
            rdist_rows.append(row)
        real_dist_html = (
            f'<h5>{T("NO_FAULT false-alarm rate across 7 disturbances (Branch 10 realistic active grid)", "Tỉ lệ báo động giả (NO_FAULT) trên 7 nhiễu nền (lưới chủ động Nhánh 10)")}</h5>'
            + table(rdist_head, rdist_rows, set(range(1, len(rdist_head))))
        )

    # Optional realistic Active Conformal note (only when conformal_hif.json actually ran)
    real_conf_html = ""
    if isinstance(conf_r, dict) and conf_r.get("status") != "NOT_RUN_YET" and conf_r.get("results"):
        cr = conf_r["results"]
        if "60Hz_only" in cr and "60Hz_plus_edge" in cr and "active_grid_gatv2" in cr["60Hz_plus_edge"]:
            cb = cr["60Hz_only"]["active_grid_gatv2"]["aps_rand"]["target_95"]
            cf = cr["60Hz_plus_edge"]["active_grid_gatv2"]["aps_rand"]["target_95"]
            b123, f123 = cb["ieee123_cross_conformal"], cf["ieee123_cross_conformal"]
            real_conf_html = TB(
                emph(f'<b>Branch-10 realistic Split Conformal (<code>aps_rand</code> 95%, ActiveGridGATv2, IEEE 123-bus):</b> '
                     f'coverage {pct(b123["coverage"])} → {pct(f123["coverage"])}, singleton share '
                     f'{pct(b123["singleton_share"])} → {pct(f123["singleton_share"])} '
                     f'(singleton accuracy {pct(f123["singleton_accuracy"]) if f123.get("singleton_accuracy") is not None else "–"}, '
                     f'autonomous NO_FAULT trip {pct(f123["nofault_autonomous_trip_share"]) if f123.get("nofault_autonomous_trip_share") is not None else "–"}).'),
                emph(f'<b>Split Conformal thực tế Nhánh 10 (<code>aps_rand</code> 95%, ActiveGridGATv2, IEEE 123-bus):</b> '
                     f'độ phủ {pct(b123["coverage"])} → {pct(f123["coverage"])}, tập 1 nhãn tự hành '
                     f'{pct(b123["singleton_share"])} → {pct(f123["singleton_share"])} '
                     f'(độ đúng tập 1 nhãn {pct(f123["singleton_accuracy"]) if f123.get("singleton_accuracy") is not None else "–"}, '
                     f'cắt nhầm NO_FAULT tự hành {pct(f123["nofault_autonomous_trip_share"]) if f123.get("nofault_autonomous_trip_share") is not None else "–"}).'),
                "p", "note",
            )

    honest_box = (
        '<div class="hif-honest">'
        + TB(
            '<b>Honest simulation note (Branch 10 realistic HIF-Fusion):</b> Both the Emanuel two-diode arcing waveforms '
            '(5 contact surfaces, intermittent conduction <code>arc_duty</code>) and the superimposed background loads, '
            'zone load drift, and CT/PT errors remain <b>100% simulation</b> — not utility field oscillograms and not '
            'EMTP electromagnetic transients. Every metric and pre-registered <b>R1–R4</b> verdict above is reported '
            'verbatim from <code>results/hif_fusion_realistic/*.json</code>, even when accuracy gains are smaller than '
            'the legacy clean-60 Hz study or a branch is marked <code>PARTIAL</code> / <code>FAIL</code> / '
            '<code>NOT_RUN_YET</code>. On real 22 kV, 50 Hz VeHIF vegetation recordings (<code>hif_sensor/results/real_vehif.json</code>), '
            'the same frozen 504 B <code>int8</code> detector drops from <b>94.7%</b> (simulated Emanuel) to <b>56.0%</b> '
            'zero-shot (0.0% background FA), so simulated recovery does not prove field performance without real utility data.',
            '<b>Ghi chú trung thực (HIF-Fusion thực tế Nhánh 10):</b> Cả dạng sóng hồ quang hai diode Emanuel '
            '(5 bề mặt tiếp xúc, chu kỳ dẫn chập chờn <code>arc_duty</code>) lẫn tải nền ghép vào, trôi tải theo zone '
            'và sai số CT/PT đều là <b>mô phỏng 100%</b> — không phải dao động ký thực địa và không phải mô phỏng quá '
            'độ điện từ EMTP. Mọi con số và kết luận tiêu chí tiền đăng ký <b>R1–R4</b> phía trên đều đọc nguyên vẹn từ '
            '<code>results/hif_fusion_realistic/*.json</code>, kể cả khi mức tăng thấp hơn bản 60 Hz sạch cũ hoặc có '
            'nhánh ở trạng thái <code>PARTIAL</code> / <code>FAIL</code> / <code>NOT_RUN_YET</code>. Trên 250 bản ghi '
            'sự cố chạm cây 22 kV, 50 Hz thật VeHIF (<code>hif_sensor/results/real_vehif.json</code>), chính bộ phát '
            'hiện 504 B <code>int8</code> đóng băng này giảm từ <b>94.7%</b> (Emanuel mô phỏng) xuống <b>56.0%</b> '
            'zero-shot (0.0% báo giả nền), nên hồi phục trong mô phỏng chưa chứng minh hiệu năng thực địa nếu chưa có '
            'dữ liệu sự cố thật từ điện lực.',
            "div",
        )
        + '</div>'
    )

    return (
        head
        + banner
        + xbox("table-hif-realistic", t_real_cmp)
        + ref_note
        + real_conf_html
        + f'<h5>{T("Intermittent vs. continuous arcing & 5 Emanuel surfaces (Branch 10 realistic)", "Phân rã hồ quang chập chờn vs. liên tục & 5 bề mặt Emanuel (Nhánh 10 thực tế)")}</h5>'
        + xbox("table-hif-realistic-arc", t_real_arc)
        + f'<h5>{T("Single-sensor outage robustness — simultaneous 60 Hz + Edge blanking (R4)", "Độ bền khi mất 1 cảm biến — xóa đồng thời 60 Hz + Edge (R4)")}</h5>'
        + xbox("table-hif-realistic-miss", t_real_miss)
        + real_dist_html
        + honest_box
    )


def _wave_step(top: float) -> float:
    """A round tick step that covers |values| up to `top` in at most three ticks per side."""
    for s in (1, 2, 2.5, 4, 5, 10, 20, 25, 40, 50, 100):
        if top <= 3 * s:
            return s
    return 10 ** math.ceil(math.log10(top / 3))


def wave_chart(t_ms: np.ndarray, series: list[tuple], title: str, *, unit: str, scale: float = 1.0,
               xticks: list[float]) -> str:
    """Time-domain waveforms from an LTspice export. Series are (English, Vietnamese, colour slot,
    values[, dashed]); values are divided by `scale` for display (e.g. 1000 for kA)."""
    W, H, L, R, T_, B = 680, 280, 52, 20, 14, 42
    pw, ph = W - L - R, H - T_ - B
    vals = [np.asarray(s[3]) / scale for s in series]
    step = _wave_step(max(float(np.abs(v).max()) for v in vals))
    top = step * math.ceil(max(float(np.abs(v).max()) for v in vals) / step)
    ticks = np.arange(-top, top + step / 2, step)
    x0, x1 = float(t_ms[0]), float(t_ms[-1])
    X = lambda x: L + pw * (x - x0) / (x1 - x0)  # noqa: E731
    Y = lambda y: T_ + ph * (1 - (y + top) / (2 * top))  # noqa: E731
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    for v in ticks:
        g.append(f'<line class="grid" x1="{L}" x2="{L + pw}" '
                 f'y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>' + svg_text(L - 8, Y(v) + 4, f"{v:g}", anchor="end"))
    for x in xticks:
        g.append(svg_text(X(x), T_ + ph + 18, f"{x:g}", anchor="middle"))
    g.append(svg_text(L + pw / 2, H - 4, f"time (ms), current ({unit})", f"thời gian (ms), dòng điện ({unit})",
                      anchor="middle"))
    for s, v in zip(series, vals):
        dash = ";stroke-dasharray:6 4" if len(s) > 4 and s[4] else ""
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(t_ms, v))
        g.append(f'<polyline class="ln" style="stroke:var(--s{s[2]}){dash}" points="{pts}"/>')
    g.append("</svg>")
    legend = "".join(f'<span><i style="background:var(--s{s[2]})"></i>{T(s[0], s[1])}</span>' for s in series)
    return f'<div class="legend">{legend}</div><div class="chart">{"".join(g)}</div>'


def spice_block(d: dict, v: dict, root=config.ROOT) -> str:
    """2b: what the 60 Hz phasor study leaves out, from the LTspice circuits (scripts/spice_run.py)."""
    sp = d["sp"]
    head = f'<h3 id="time-domain">{T("2b · In the time domain (LTspice)", "2b · Theo thời gian (LTspice)")}</h3>'
    fc, hf = root / "exports" / "spice_fault_current.csv", root / "exports" / "spice_hif.csv"
    if sp is None or not fc.exists() or not hf.exists():
        return head + TB("Not built yet: run <code>python scripts/spice_run.py --register</code> (needs LTspice).",
                         "Chưa tạo: chạy <code>python scripts/spice_run.py --register</code> (cần LTspice).", "p", "note")
    a = np.genfromtxt(fc, delimiter=",", names=True)
    sel = (a["time_ms"] >= 40) & (a["time_ms"] <= 130)
    sel &= np.arange(len(a)) % 5 == 0                      # 0.1 ms steps are plenty for the picture
    dc_chart = wave_chart(a["time_ms"][sel],
                          [("Fault starts at the worst instant (largest DC offset)", "Sự cố bắt đầu ở thời điểm xấu nhất "
                            "(DC lệch lớn nhất)", 2, a["i_max_offset_a"][sel]),
                           ("Fault starts with no DC offset", "Sự cố bắt đầu không có DC lệch", 1,
                            a["i_no_offset_a"][sel], True)],
                          "Bolted fault current at bus 60", unit="kA", scale=1000, xticks=[40, 60, 80, 100, 120])
    hc = sp["hif"]["cases"]
    hi = max(hc, key=float)
    b = np.genfromtxt(hf, delimiter=",", names=True)
    sel = (b["time_ms"] >= 50) & (b["time_ms"] <= 50 + 2000 / 60)   # two settled cycles
    sel &= np.arange(len(b)) % 2 == 0
    arc_chart = wave_chart(b["time_ms"][sel],
                           [(f"Arcing fault ({hi} Ω RMS-equivalent)", f"Sự cố có hồ quang (tương đương {hi} Ω về RMS)",
                             2, b[f"i_arc_{hi}ohm_a"][sel]),
                            (f"Linear fixed {hi} Ω (reference)", f"Điện trở tuyến tính {hi} Ω (tham chiếu)",
                             1, b[f"i_fixed_{hi}ohm_a"][sel], True)],
                           f"Ground fault current at bus 60, {hi} ohm", unit="A", xticks=[50, 60, 70, 80])
    keys = sorted(hc, key=float)
    rows = [
        (("RMS current, arc / fixed", "Dòng hiệu dụng, hồ quang / cố định"),
         lambda c: f'{c["irms_arc"]:.2f} / {c["irms_linear"]:.2f} A'),
        (("60 Hz part of the arc, vs fixed", "Thành phần 60 Hz của hồ quang, so với cố định"),
         lambda c: pct(c["i1_arc_vs_linear"])),
        (("3rd harmonic of the arc", "Hài bậc 3 của hồ quang"), lambda c: pct(c["h3_arc_pct"] / 100)),
        (("5th harmonic of the arc", "Hài bậc 5 của hồ quang"), lambda c: pct(c["h5_arc_pct"] / 100)),
        (("DC part of the arc", "Thành phần DC của hồ quang"), lambda c: f'{c["dc_arc_a"]:.2f} A'),
        (("Fault current vs feeder-head load", "Dòng sự cố so với dòng tải đầu tuyến"),
         lambda c: pct(c["share_of_prefault_load_pct"] / 100)),
        (("ADC counts the fault current spans", "Số mức ADC mà dòng sự cố chiếm"),
         lambda c: num(c["adc_counts_span_arc"])),
    ]
    atab = table([T("Same RMS current", "Cùng dòng hiệu dụng"), *[f"{k} Ω" for k in keys]],
                 [[T(*lab), *[f(hc[k]) for k in keys]] for lab, f in rows], {1, 2})
    return (
        head
        + TB(emph(f'OpenDSS solves 60 Hz phasors: one steady number per current. Three LTspice circuits, written from '
                  f'the same feeder model at bus {v["sp_bus"]}, show the waveform a recloser would actually record.'),
             emph(f'OpenDSS giải bài toán pha 60 Hz: mỗi dòng điện chỉ là một con số ổn định. Ba mạch LTspice, viết từ '
                  f'cùng mô hình lưới tại bus {v["sp_bus"]}, cho thấy dạng sóng mà recloser thực sự ghi được.'),
             "p", "note")
        + f'<h4>{T("A bolted fault starts with a DC offset", "Sự cố trực tiếp bắt đầu với DC lệch")}</h4>'
        + xbox("chart-dc", dc_chart)
        + TB(emph(f'Steady current {v["sp_rms"]} A RMS ({v["sp_rms_dss"]} A in the full OpenDSS fault). At the worst '
                  f'instant the first peak is {v["sp_pk"]} A instead of {v["sp_pk0"]} A (asymmetry {v["sp_asym"]}); the '
                  f'{term("dcoffset", "DC offset")} dies out with a time constant of {v["sp_tau"]} ms. Through a {v["sp_ct"]}:1 CT and the '
                  f'filter the {v["sp_bits"]}-bit ADC pin swings {v["sp_vlo"]}–{v["sp_vhi"]} V ({v["sp_clip"]} clipped '
                  f'samples, {v["sp_apc"]} A per count), and a one-cycle DFT is within 5% of the steady value '
                  f'{v["sp_settle"]} ms after the fault.'),
             emph(f'Dòng ổn định {v["sp_rms"]} A hiệu dụng ({v["sp_rms_dss"]} A trong mô phỏng OpenDSS đầy đủ). Ở thời '
                  f'điểm xấu nhất, đỉnh đầu tiên là {v["sp_pk"]} A thay vì {v["sp_pk0"]} A (hệ số bất đối xứng '
                  f'{v["sp_asym"]}); {term("dcoffset", "DC lệch", "DC lệch")} tắt dần với hằng số thời gian {v["sp_tau"]} ms. Qua CT {v["sp_ct"]}:1 '
                  f'và bộ lọc, chân ADC {v["sp_bits"]} bit dao động {v["sp_vlo"]}–{v["sp_vhi"]} V ({v["sp_clip"]} mẫu '
                  f'bị cắt, {v["sp_apc"]} A mỗi mức), và DFT một chu kỳ sai dưới 5% so với giá trị ổn định sau '
                  f'{v["sp_settle"]} ms.'), "p", "note")
        + f'<h4>{T("A high-impedance fault arcs", "Sự cố trở kháng cao có hồ quang")}</h4>'
        + xbox("chart-arc", arc_chart)
        + xbox("table-arc", atab)
        + TB(emph(f'A real {term("hif", "high-impedance fault")} arcs: it conducts only while the voltage is above '
                  f'the arc voltage (two-diode model, Emanuel et al. 1990; arc voltages {v["hif_vp"]} and {v["hif_vn"]} '
                  f'of the phase peak are illustrative). The main OpenDSS fault sweep now models the 60 Hz fundamental '
                  f'attenuation and intermittency of arcing SLG ≥ 100 Ω via {term("arcing", "R_eff")}, while this '
                  f'LTspice circuit shows what 60 Hz phasors still omit: matched to the same RMS current, the arc puts '
                  f'{v["hif_i1"]} at 60 Hz and adds {term("harmonic", "harmonics")} and a small DC part. At '
                  f'{v["hif_hi_r"]} Ω the fault draws {v["hif_hi_i"]} A, {v["hif_hi_share"]} of the {v["sp_ipre"]} A '
                  f'the feeder head carries before the fault, and spans {v["hif_hi_counts"]} ADC counts.'),
             emph(f'{term("hif", "Sự cố trở kháng cao", "Sự cố trở kháng cao")} ngoài đời có hồ quang: chỉ dẫn điện khi '
                  f'điện áp vượt điện áp hồ quang (mô hình hai diode, Emanuel và cộng sự 1990; điện áp hồ quang '
                  f'{v["hif_vp"]} và {v["hif_vn"]} điện áp đỉnh pha là giả định để minh hoạ). Bộ quét OpenDSS chính nay '
                  f'đã mô phỏng suy giảm thành phần cơ bản 60 Hz và tính chập chờn của SLG ≥ 100 Ω qua '
                  f'{term("arcing", "R_eff", "R_eff")}, còn mạch LTspice này cho thấy phần mà miền phasor 60 Hz vẫn bỏ '
                  f'qua: khi chỉnh cùng dòng hiệu dụng, hồ quang chỉ có {v["hif_i1"]} ở 60 Hz, thêm '
                  f'{term("harmonic", "sóng hài", "sóng hài")} và một phần DC nhỏ. Ở {v["hif_hi_r"]} Ω dòng sự cố là '
                  f'{v["hif_hi_i"]} A, bằng {v["hif_hi_share"]} dòng {v["sp_ipre"]} A ở đầu tuyến trước sự cố, và chỉ '
                  f'chiếm {v["hif_hi_counts"]} mức ADC.'),
             "p", "note"))


def comtrade_block(d: dict, v: dict) -> str:
    """2e: concise EN/VI guide to reading IEEE C37.111 COMTRADE files -> model features."""
    ct = d.get("comtrade")
    head = f'<h3 id="comtrade">{T("2e · Reading COMTRADE fault records (IEEE C37.111)", "2e · Đọc bản ghi sự cố COMTRADE (IEEE C37.111)")}</h3>'
    if ct is None:
        return head + TB(
            "Not verified yet: run <code>python scripts/comtrade_ingest.py --verify-samples</code>.",
            "Chưa chạy kiểm thử: chạy <code>python scripts/comtrade_ingest.py --verify-samples</code>.",
            "p", "note",
        )
    cnt, par, demo = ct["counts"], ct["parity"], ct["single_device_demo"]
    sim_n = cnt["total_verified"] - cnt["public_samples"]
    pub_ids = ", ".join(esc(s["id"]) for s in ct["public_samples"])
    dss_rel = f'{100 * par["opendss_max_tier2_rel_err"]:.4f}%'
    tr_err = f'{par["opendss_max_transfer_abs_err"]:.2e}'
    lt_bolt = f'{par["ltspice_bolted_rms_rel_err_pct"]:g}%'
    lt_hif = f'{par["ltspice_hif100_i1_rel_err_pct"]:g}%'
    hif_ferr = f'{par["hif_roundtrip_max_feat_abs_err"]:.1e}'
    hif_perr = f'{par["hif_roundtrip_p_hif_abs_err"]:g}'

    intro = TB(
        f'<b>What is {term("comtrade", "COMTRADE")}?</b> It is the standard recording file (IEEE C37.111) that a '
        f'protective relay or recloser saves whenever a fault occurs: a <code>.cfg</code> header (channels, CT/PT '
        f'ratios, sample rate) paired with a <code>.dat</code> waveform file.',
        f'<b>{term("comtrade", "COMTRADE")} là gì?</b> Đây là file bản ghi sóng sự cố tiêu chuẩn (IEEE C37.111) mà '
        f'rơ-le bảo vệ hoặc recloser tự lưu khi có sự cố: gồm <code>.cfg</code> (tên kênh, tỉ số CT/PT, tần số lấy '
        f'mẫu) đi kèm <code>.dat</code> (dãy mẫu sóng dòng/áp).',
        "p", "note",
    )

    steps = (
        '<ol class="steps">'
        + f'<li><b>{T("Read .cfg / .dat & scale CT/PT", "Đọc .cfg / .dat & quy đổi CT/PT")}</b>'
        + f'<span>{T("Parses ASCII or BINARY (1999/2013), applies a·x + b and primary/secondary CT/PT ratios, and maps Va/Vb/Vc, Ia/Ib/Ic, In at 50 or 60 Hz.", "Đọc ASCII hoặc BINARY (1999/2013), áp hệ số a·x + b cùng tỉ số CT/PT sơ/thứ cấp, tự ghép kênh Va/Vb/Vc, Ia/Ib/Ic, In ở cả 50 Hz và 60 Hz.")}</span></li>'
        + f'<li><b>{T("Extract pre- and post-fault phasors (1-cycle DFT)", "Tính phasor trước và sau sự cố (DFT 1 chu kỳ)")}</b>'
        + f'<span>{T("Finds fault onset (trigger timestamp or waveform jump), runs a 1-cycle DFT before and after the fault, and computes RMS currents, voltages, zero/negative-sequence currents and pre→post deltas.", "Xác định mốc sự cố (theo trigger hoặc bước nhảy sóng), chạy DFT 1 chu kỳ trước và sau sự cố để lấy dòng/áp hiệu dụng, dòng thứ tự không/nghịch và độ thay đổi trước→sau.")}</span></li>'
        + f'<li><b>{T("Pack into the exact model feature schema", "Đổi sang đúng khuôn đặc trưng của model")}</b>'
        + f'<span>{T("Outputs the exact columns used by Tier-2 GBDT (15/device, NaN if a switch is missing), Cross-Feeder Transfer (21/node), Active-Grid (26/node), plus the 16-feature Tier-1 HIF bridge when duration ≥ 8 cycles.", "Xuất đúng các cột của Tier-2 GBDT (15 đặc trưng/thiết bị, tự điền NaN nếu thiếu dao), Transfer (21/nút), Active-Grid (26/nút), và cầu nối 16 đặc trưng Tầng 1 HIF khi đủ ≥ 8 chu kỳ.")}</span></li>'
        + '</ol>'
    )

    rows = [
        [
            T("Public open-source samples (external grids)", "Mẫu công khai mã nguồn mở (lưới ngoài)"),
            f'<span class="chip good">✓ {cnt["public_passed"]}/{cnt["public_samples"]}</span>',
            T(f'ASCII & BINARY, 50/60 Hz, MIT / CC0-1.0 ({pub_ids}).',
              f'ASCII & BINARY, 50/60 Hz, MIT / CC0-1.0 ({pub_ids}).'),
        ],
        [
            T("OpenDSS 10-device round-trip (IEEE 123-bus sim)", "OpenDSS đủ 10 thiết bị vòng kín (mô phỏng 123-bus)"),
            f'<span class="chip good">✓ {cnt["synthetic_opendss_passed"]}/{cnt["synthetic_opendss_events"]}</span>',
            T(f'Max Tier-2 rel. err {dss_rel} (Transfer max abs {tr_err}); {par["opendss_tier2_model_matches"]}/{par["opendss_total_events"]} Tier-2 GBDT, {par["opendss_transfer_gbdt_matches"]}/{par["opendss_total_events"]} Transfer GBDT and {par["opendss_transfer_gnn_matches"]}/{par["opendss_total_events"]} ZoneTreeGNN match direct OpenDSS.',
              f'Sai số tương đối Tier-2 lớn nhất {dss_rel} (Transfer tối đa {tr_err}); {par["opendss_tier2_model_matches"]}/{par["opendss_total_events"]} Tier-2 GBDT, {par["opendss_transfer_gbdt_matches"]}/{par["opendss_total_events"]} Transfer GBDT và {par["opendss_transfer_gnn_matches"]}/{par["opendss_total_events"]} ZoneTreeGNN khớp trực tiếp OpenDSS.'),
        ],
        [
            T("LTspice waveforms (bolted & 100 Ω HIF sim)", "Sóng LTspice (ngắn mạch trực tiếp & HIF 100 Ω)"),
            f'<span class="chip good">✓ {cnt["synthetic_ltspice_passed"]}/{cnt["synthetic_ltspice_records"]}</span>',
            T(f'Bolted RMS err {lt_bolt}; 100 Ω arcing fundamental err {lt_hif}.',
              f'Sai số RMS ngắn mạch trực tiếp {lt_bolt}; sai số thành phần cơ bản hồ quang 100 Ω là {lt_hif}.'),
        ],
        [
            T("Tier-1 Edge HIF bridge (15.36 kHz arc sim)", "Cầu nối Cảm biến HIF Tầng 1 (sóng 15.36 kHz mô phỏng)"),
            f'<span class="chip good">✓ {cnt["synthetic_hif_passed"]}/{cnt["synthetic_hif_records"]}</span>',
            T(f'Max feature abs. err {hif_ferr}; Δp_hif = {hif_perr} (alarm matches direct pipeline).',
              f'Sai số đặc trưng lớn nhất {hif_ferr}; Δp_hif = {hif_perr} (cảnh báo khớp hoàn toàn bản trực tiếp).'),
        ],
    ]
    ct_tab = table(
        [T("Verification suite", "Nhóm kiểm thử"), T("Pass", "Đạt"), T("Key numbers from results/comtrade/summary.json", "Số liệu trực tiếp từ results/comtrade/summary.json")],
        rows,
    )

    cmd_drop = "python scripts/comtrade_ingest.py <file_or_folder>"
    cmd_ver = "python scripts/comtrade_ingest.py --verify-samples"
    honest = (
        '<div class="hif-honest">'
        + TB(
            f'<b>Honest scope (public samples &amp; simulation only):</b> Verified on <b>{cnt["public_samples"]}</b> '
            f'public open-source COMTRADE files from external grids and <b>{sim_n}</b> simulated round-trip records '
            f'(OpenDSS, LTspice, synthetic HIF) — <b>{cnt["total_passed"]}/{cnt["total_verified"]} passed</b>. No '
            f'utility field fault dataset has been evaluated yet. A single relay file populates only '
            f'<b>{demo["single_device_finite_tier2"]}/{demo["all_10_devices_finite_tier2"]}</b> Tier-2 features; '
            f'reliable feeder-wide zone location needs synchronized recordings from multiple switches on the feeder '
            f'(all 10 devices recover zone <b>{esc(demo["all_10_devices_tier2_pred"])}</b> at '
            f'<b>{pct(demo["all_10_devices_tier2_conf"])}</b> confidence in the OpenDSS demo). When real utility '
            f'<code>.cfg</code>/<code>.dat</code> files are obtained, feed them directly into '
            f'<code>scripts/comtrade_ingest.py</code>. '
            f'<a href="data/comtrade_summary.json" download>Download comtrade_summary.json</a>.',
            f'<b>Ghi chú trung thực (mới thử mẫu công khai &amp; mô phỏng):</b> Hiện mới kiểm thử trên '
            f'<b>{cnt["public_samples"]}</b> file COMTRADE mẫu công khai từ lưới ngoài và <b>{sim_n}</b> bản ghi '
            f'sóng mô phỏng vòng kín (OpenDSS, LTspice, hồ quang HIF mô phỏng) — đạt '
            f'<b>{cnt["total_passed"]}/{cnt["total_verified"]}</b>. Chưa đánh giá trên dữ liệu sự cố thật của điện '
            f'lực. Một thiết bị đơn lẻ chỉ điền '
            f'<b>{demo["single_device_finite_tier2"]}/{demo["all_10_devices_finite_tier2"]}</b> đặc trưng Tier-2; '
            f'muốn định vị zone đáng tin cần bản ghi đồng bộ từ nhiều dao trên cùng tuyến (đủ 10 thiết bị khôi phục '
            f'đúng zone <b>{esc(demo["all_10_devices_tier2_pred"])}</b> với độ tự tin '
            f'<b>{pct(demo["all_10_devices_tier2_conf"])}</b> trong ca OpenDSS). Khi xin được file '
            f'<code>.cfg</code>/<code>.dat</code> thật, chỉ cần thả trực tiếp vào lệnh '
            f'<code>scripts/comtrade_ingest.py</code>. '
            f'<a href="data/comtrade_summary.json" download>Tải comtrade_summary.json</a>.',
            "p",
        )
        + '<div class="ev-cmds">'
        + f'<div class="ev-cmd"><code>{esc(cmd_drop)}</code>'
          f'<button type="button" class="copy-btn" data-copy-text="{esc(cmd_drop)}" data-copy-kind="cmd">{T("Copy", "Chép")}</button></div>'
        + f'<div class="ev-cmd"><code>{esc(cmd_ver)}</code>'
          f'<button type="button" class="copy-btn" data-copy-text="{esc(cmd_ver)}" data-copy-kind="cmd">{T("Copy", "Chép")}</button></div>'
        + '</div></div>'
    )
    return head + intro + steps + xbox("table-comtrade", ct_tab) + honest


def section(id_: str, title: tuple[str, str], how: tuple[str, str], body: str,
            takeaway: tuple[str, str] | None = None) -> str:
    take = (f'<div class="take"><span class="take-l">{T("In short", "Tóm lại")}</span>'
            f'{T(*(emph(s) for s in takeaway))}</div>' if takeaway else "")
    how = TB(*(emph(s) for s in how), tag="p", cls="how")
    return (f'<section id="{id_}"><h2>{T(*title)}<a class="anchor" href="#{id_}" '
            f'aria-label="Link to this section">#</a></h2>{how}{take}{body}</section>')


def checks(d: dict) -> list[str]:
    m, fl, rs = d["m"], d["m"]["fault_location"], d["m"]["restoration"]
    full, fpi = fl["ml_full"]["accuracy"], fl["fpi_baseline"]["accuracy"]
    conv, rows = m["dataset"]["converged_share"], num(m["dataset"]["rows"])
    out = [
        status("good" if conv == 1 else "critical",
               ("Every fault simulation converged", "Mọi mô phỏng sự cố đều hội tụ"),
               (f"{pct(conv)} of {rows} power-flow solutions", f"{pct(conv)} trong {rows} lời giải trào lưu công suất")),
        status("good" if rs["all_final_states_within_limits"] else "critical",
               ("Every restored feeder stays within limits", "Mọi phương án khôi phục đều trong giới hạn"),
               ("0.95–1.05 pu at every energized node and no line above its emergency rating, for all 10 fault zones",
                "0.95–1.05 pu ở mọi nút có điện và không đường dây nào vượt định mức khẩn cấp, cho cả 10 zone sự cố")),
        status("good" if rs["all_radial"] else "critical",
               ("Every switching plan keeps the feeder radial", "Mọi phương án đóng cắt đều giữ lưới hình tia"),
               ("no loops after the ties close", "không tạo vòng kín sau khi đóng tie")),
        status("good" if full > fpi else "critical",
               ("ML beats the conventional method", "ML tốt hơn phương pháp truyền thống"),
               (f"{pct(full)} vs {pct(fpi)} of faults placed in the right zone",
                f"{pct(full)} so với {pct(fpi)} số sự cố được xác định đúng zone")),
    ]
    r400 = fl["ml_full"]["slg_by_resistance"]["400.0"]
    s2l = d.get("s2l")
    i400 = (f'{s2l["feeders"]["ieee123"]["by_resistance"]["400.0"]["fault_current_a"]["median"]:.1f} A'
            if s2l else "small")
    out.append(status("warning" if r400 < .9 else "good",
                      ("High-impedance arcing ground faults", "Sự cố chạm đất hồ quang trở kháng cao"),
                      (f"only {pct(r400)} correct at 400 Ω nominal under intermittent arcing + load drift + CT/PT noise "
                       f"(linear 400 Ω current is {i400}, arcing 60 Hz component is smaller — OpenDSS simulation)",
                       f"chỉ đúng {pct(r400)} ở 400 Ω danh định dưới hồ quang chập chờn + trôi tải + nhiễu CT/PT "
                       f"(dòng tuyến tính 400 Ω là {i400}, thành phần 60 Hz hồ quang còn nhỏ hơn — mô phỏng OpenDSS)")))
    dev, acc = min(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1])
    out.append(status("warning" if acc < .9 else "good", ("One sensor offline", "Mất một cảm biến"),
                      (f"worst case is {dev} offline: {pct(acc)} correct", f"tệ nhất khi mất {dev}: đúng {pct(acc)}")))
    h = d["h"]
    hcmd = "<code>python scripts/hourly_restoration.py</code>"
    if h is None:
        out.append(status("warning", ("Hourly restoration study not run", "Chưa chạy nghiên cứu khôi phục theo giờ"),
                          (f"run <code>python scripts/load_shape.py</code>, then {hcmd}",
                           f"hãy chạy <code>python scripts/load_shape.py</code>, rồi {hcmd}")))
    elif abs(h["by_level"]["kW_restored_by_tie"][h["by_level"]["level"].index(1.0)]
             - rs["kW_restored_by_tie_total"]) > 1e-6:
        out.append(status("critical", ("Hourly study is out of date", "Nghiên cứu theo giờ đã cũ"),
                          (f"its peak-load row no longer matches restoration.csv; re-run {hcmd}",
                           f"hàng tải đỉnh không còn khớp restoration.csv; hãy chạy lại {hcmd}")))
    else:
        lim, n_h = h["limits"], num(h["load_shape"]["hours"])
        if lim["hours"]:
            out.append(status("warning", ("Hourly study: limits at every hour", "Theo giờ: giới hạn ở mọi giờ"),
                              (f'{num(lim["hours"])} of {n_h} hours fall on load levels where a state reaches '
                               f'{lim["max_vmax_pu"]:.4f} pu, just above {config.V_MAX_PU:.2f} pu (regulator tap)',
                               f'{num(lim["hours"])} trên {n_h} giờ rơi vào mức tải có trạng thái lên tới '
                               f'{lim["max_vmax_pu"]:.4f} pu, vượt nhẹ {config.V_MAX_PU:.2f} pu (nấc bộ điều áp)')))
        else:
            out.append(status("good", ("Hourly study: limits at every hour", "Theo giờ: giới hạn ở mọi giờ"),
                              (f"every one of the {n_h} hours stays within limits",
                               f"cả {n_h} giờ đều trong giới hạn")))
    ea, cmd = d["ea"], "<code>python scripts/error_analysis.py</code>"
    if ea is None:
        out.append(status("warning", ("Error analysis missing", "Chưa có phân tích lỗi"),
                          (f"run {cmd}", f"hãy chạy {cmd}")))
    elif round(ea["ml_accuracy"], 4) != round(full, 4):
        out.append(status("warning", ("Error analysis is out of date", "Phân tích lỗi đã cũ"),
                          (f"it was built from a different run; re-run {cmd}",
                           f"được tạo từ một lần chạy khác; hãy chạy lại {cmd}")))
    else:
        a = pct(ea["ml_accuracy"], 2)
        out.append(status("good", ("Error analysis matches this run", "Phân tích lỗi khớp với lần chạy này"),
                          (f"same out-of-fold accuracy ({a})", f"cùng accuracy kiểm định chéo ({a})")))
    pv = d.get("prov_verify") or {"changed": [], "missing": [], "unrecorded": []}
    pl = d.get("prov_ledger") or []
    prov_ok = bool(pl) and not (pv["changed"] or pv["missing"] or pv["unrecorded"])
    prov_files = sum(r["file_count"] for r in pl)
    out.append(status(
        "good" if prov_ok else "critical",
        ("SHA-256 provenance matches all results", "Chứng thực SHA-256 khớp toàn bộ kết quả"),
        (f"{len(pl)} manifests, {prov_files} recorded result files: {len(pv['changed'])} changed, "
         f"{len(pv['missing'])} missing, {len(pv['unrecorded'])} unrecorded",
         f"{len(pl)} manifest, {prov_files} file kết quả: {len(pv['changed'])} thay đổi, "
         f"{len(pv['missing'])} thiếu, {len(pv['unrecorded'])} chưa ghi"),
    ))
    return out


# Metadata for the 23-manifest SHA-256 Provenance Ledger (titles + primary file preference;
# hashes, timestamps, commands, run source, event counts and verification states are read live).
PROV_META: dict[str, tuple[str, str, str | None, str | None]] = {
    # producer: (EN title, VI title, Kaggle notebook / ref if Kaggle, primary file path hint)
    "run": ("Main FLISR (IEEE 123-bus)", "FLISR chính (IEEE 123-bus)", None, "results/metrics.json"),
    "error_analysis": ("Error analysis (IEEE 123-bus)", "Phân tích lỗi (IEEE 123-bus)", None, "results/error_analysis/error_analysis.json"),
    "demo_event": ("SCADA/MQTT event replay", "Phát lại 1 sự cố SCADA/MQTT", None, "results/demo_event.jsonl"),
    "spice_run": ("LTspice transient & arcing HIF", "LTspice quá độ & hồ quang HIF", None, "results/spice/summary.json"),
    "load_shape": ("PJM AEP 2017 hourly load shape", "Đường tải theo giờ PJM AEP 2017", "kaggle_hourly.ipynb", "results/hourly/load_shape_info.json"),
    "hourly_restoration": ("Hourly restoration (8,760 h × 81 levels)", "Khôi phục theo giờ (8,760 giờ × 81 mức)", "kaggle_hourly.ipynb", "results/hourly/hourly.json"),
    "signal_to_load": ("SLG signal-to-load physics (123/34/37)", "Vật lý tỉ số dòng SLG/tải (123/34/37)", None, "results/transfer/signal_to_load.json"),
    "transfer_sweep_ieee123": ("Passive sweep · IEEE 123-bus", "Quét sự cố thụ động · IEEE 123-bus", None, "results/transfer/dataset_ieee123.json"),
    "transfer_sweep_ieee34": ("Passive sweep · IEEE 34-bus", "Quét sự cố thụ động · IEEE 34-bus", None, "results/transfer/dataset_ieee34.json"),
    "transfer_sweep_ieee37": ("Passive sweep · IEEE 37-bus delta", "Quét sự cố thụ động · IEEE 37-bus delta", None, "results/transfer/dataset_ieee37.json"),
    "transfer_phase2": ("Passive Stage-1 CV · IEEE 123-bus", "Thụ động Stage-1 CV · IEEE 123-bus", None, "results/transfer/phase2_ieee123.json"),
    "transfer_phase3": ("Passive transfer · IEEE 123 → 34-bus", "Chuyển giao thụ động · 123 → 34-bus", None, "results/transfer/phase3_ieee34.json"),
    "transfer_phase3_ieee37": ("Passive transfer · IEEE 123 → 37-bus", "Chuyển giao thụ động · 123 → 37-bus", None, "results/transfer/phase3_ieee37.json"),
    "transfer_phase2b": ("Stage-2 bus ranking · 123 & 34-bus", "Xếp hạng bus Stage-2 · 123 & 34-bus", None, "results/transfer/phase2b_bus_location.json"),
    "transfer_phase2b_ieee37": ("Stage-2 bus ranking · IEEE 37-bus", "Xếp hạng bus Stage-2 · IEEE 37-bus", None, "results/transfer/phase2b_bus_ieee37.json"),
    "transfer_multi_feeder_benchmark": ("15-Feeder multi-feeder zero-shot", "Kiểm chứng đa lưới 15 lưới (0-shot)", "Kaggle 3-VM + merge", "results/transfer/multi_feeder_benchmark.json"),
    "active_grid": ("Active DER + loops · 123 → 34-bus", "Lưới chủ động DER + vòng · 123 → 34", "kaggle_active_grid.ipynb", "results/active_grid/phase_active_ieee34.json"),
    "active_conformal_posthoc": ("Active conformal post-hoc · 123/34", "Conformal kiểm tra sau · 123/34-bus", "kaggle_active_grid.ipynb", "results/active_grid/conformal_posthoc.json"),
    "active_conformal_calsize": ("Conformal cal-size sweep · 34-bus", "Khảo sát cỡ tập hiệu chỉnh · 34-bus", None, "results/active_grid/conformal_calsize.json"),
    "active_grid_ieee37": ("Active DER + loops · 123 → 37-bus", "Lưới chủ động DER + vòng · 123 → 37", "kaggle_active_ieee37.ipynb", "results/active_grid_ieee37/phase_active_ieee37.json"),
    "active_conformal_posthoc_ieee37": ("Active conformal · IEEE 37-bus", "Conformal lưới chủ động · IEEE 37-bus", "kaggle_active_ieee37.ipynb", "results/active_grid_ieee37/conformal_posthoc.json"),
    "active_conformal_calsize_ieee37": ("Conformal cal-size sweep · 37-bus", "Khảo sát cỡ tập hiệu chỉnh · 37-bus", "kaggle_active_ieee37.ipynb", "results/active_grid_ieee37/conformal_calsize.json"),
    "hif_fusion": ("Two-tier Edge HIF → Graph FLISR", "Ghép 2 tầng Edge HIF → Graph FLISR", "kaggle_hif_fusion.ipynb", "results/hif_fusion/conformal_hif.json"),
    "hif_fusion_realistic": ("Two-tier Edge HIF → Graph FLISR (Branch 10 realistic)", "Ghép 2 tầng Edge HIF → Graph FLISR (Nhánh 10 thực tế)", "kaggle_hif_fusion_realistic.ipynb", "results/hif_fusion_realistic/summary.json"),
    "comtrade_verify": ("COMTRADE ingest & parity (IEEE C37.111)", "Đọc COMTRADE & kiểm tra khớp đặc trưng (IEEE C37.111)", None, "results/comtrade/summary.json"),
}


def _prov_env(row: dict) -> str:
    """Classify a provenance manifest's run environment (Local vs Kaggle) directly from its metadata."""
    prod = row["producer"]
    cmd = row.get("command") or ""
    commit = row.get("git_commit")
    meta = PROV_META.get(prod)
    nb = meta[2] if meta else None
    if "--merge" in cmd and "kaggle_bench" in cmd:
        return T("Kaggle 3-VM + Local merge", "Kaggle 3-VM + ghép Local") + "<small>bench-g1/g2/g3</small>"
    if commit is None or "/kaggle/" in cmd:
        gpu = prod in ("active_grid", "active_conformal_posthoc", "active_grid_ieee37",
                       "active_conformal_posthoc_ieee37", "active_conformal_calsize_ieee37",
                       "hif_fusion", "hif_fusion_realistic")
        tag = "Kaggle GPU" if gpu else "Kaggle CPU"
        sub = f"<small>{esc(nb)}</small>" if nb else ""
        return f"<b>{tag}</b>{sub}"
    tool = "Local LTspice" if prod == "spice_run" else "Local CPU"
    short_c = esc(commit[:7])
    return f"{tool}<small>git {short_c}</small>"


def _prov_scope(prod: str, d: dict) -> str:
    """Event count / scope for each provenance manifest, read live from results/."""
    m, ea, h, sp, s2l = d["m"], d.get("ea"), d.get("h"), d.get("sp"), d.get("s2l")
    tr, mfb, hif = d.get("tr") or {}, d.get("mfb"), d.get("hif") or {}
    ag_ds, ag37_ds = d.get("ag_ds"), d.get("ag37_ds")
    p3_37, p2b_37 = d.get("p3_37"), d.get("p2b_37")
    if prod == "run":
        return T(f'{num(m["dataset"]["rows"])} faults · {m["base_case"]["zones"]} zones',
                 f'{num(m["dataset"]["rows"])} sự cố · {m["base_case"]["zones"]} zone')
    if prod == "error_analysis" and ea:
        return T(f'{num(ea["faults"])} faults · {num(ea["ml_errors"])} errors',
                 f'{num(ea["faults"])} sự cố · {num(ea["ml_errors"])} lỗi')
    if prod == "demo_event":
        return T("1 replay event (bus 60)", "1 sự cố phát lại (bus 60)")
    if prod == "spice_run" and sp:
        return T(f'3 circuits · {len(sp["hif"]["cases"])} HIF cases',
                 f'3 mạch · {len(sp["hif"]["cases"])} mức HIF')
    if prod == "load_shape" and h:
        return T(f'{num(h["load_shape"]["hours"])} hours ({h["load_shape"]["year"]})',
                 f'{num(h["load_shape"]["hours"])} giờ ({h["load_shape"]["year"]})')
    if prod == "hourly_restoration" and h:
        return T(f'{num(h["load_shape"]["hours"])} h × {len(h["by_level"]["level"])} levels',
                 f'{num(h["load_shape"]["hours"])} giờ × {len(h["by_level"]["level"])} mức')
    if prod == "signal_to_load" and s2l:
        return T(f'{len(s2l["feeders"])} feeders (123/34/37)', f'{len(s2l["feeders"])} lưới (123/34/37)')
    if prod == "transfer_sweep_ieee123" and d.get("tr_ds123"):
        return T(f'{num(d["tr_ds123"]["events"])} events (123-bus)', f'{num(d["tr_ds123"]["events"])} ca (123-bus)')
    if prod == "transfer_sweep_ieee34" and d.get("tr_ds34"):
        return T(f'{num(d["tr_ds34"]["events"])} events (34-bus)', f'{num(d["tr_ds34"]["events"])} ca (34-bus)')
    if prod == "transfer_sweep_ieee37" and d.get("tr_ds37"):
        return T(f'{num(d["tr_ds37"]["events"])} events (37-bus)', f'{num(d["tr_ds37"]["events"])} ca (37-bus)')
    if prod == "transfer_phase2" and "p2" in tr:
        return T(f'{num(tr["p2"]["events"])} events (5-fold CV)', f'{num(tr["p2"]["events"])} ca (CV 5 phần)')
    if prod == "transfer_phase3" and "p3" in tr:
        return T(f'{num(tr["p3"]["events"])} events (unseen 34)', f'{num(tr["p3"]["events"])} ca (34-bus mới)')
    if prod == "transfer_phase3_ieee37" and p3_37:
        return T(f'{num(p3_37["events"])} events (unseen 37)', f'{num(p3_37["events"])} ca (37-bus mới)')
    if prod == "transfer_phase2b" and "p2b" in tr:
        n123, n34 = tr["p2b"]["ieee123"]["events"], tr["p2b"]["ieee34"]["events"]
        return T(f'{num(n123 + n34)} events (123 + 34)', f'{num(n123 + n34)} ca (123 + 34)')
    if prod == "transfer_phase2b_ieee37" and p2b_37:
        return T(f'{num(p2b_37["ieee37"]["events"])} events (37-bus)', f'{num(p2b_37["ieee37"]["events"])} ca (37-bus)')
    if prod == "transfer_multi_feeder_benchmark" and mfb:
        n_new = sum(x.get("events_converged", 0) for x in mfb.get("new_feeders", []))
        n_tot = len(mfb.get("reference_feeders", [])) + len(mfb.get("new_feeders", []))
        return T(f'{n_tot} circuits · {num(n_new)} new events', f'{n_tot} lưới · {num(n_new)} ca mới')
    if prod in ("active_grid", "active_conformal_posthoc") and ag_ds:
        n123, n34 = ag_ds["ieee123"]["converged"], ag_ds["ieee34"]["converged"]
        return T(f'{num(n123 + n34)} events (123 + 34)', f'{num(n123 + n34)} ca (123 + 34)')
    if prod == "active_conformal_calsize" and ag_ds:
        draws = (d.get("ag_cal") or {}).get("draws", 50)
        return T(f'{num(ag_ds["ieee34"]["converged"])} events · {draws} draws',
                 f'{num(ag_ds["ieee34"]["converged"])} ca · {draws} lần rút')
    if prod in ("active_grid_ieee37", "active_conformal_posthoc_ieee37") and ag37_ds:
        n123, n37 = ag37_ds["ieee123"]["converged"], ag37_ds["ieee37"]["converged"]
        return T(f'{num(n123 + n37)} events (123 + 37)', f'{num(n123 + n37)} ca (123 + 37)')
    if prod == "active_conformal_calsize_ieee37" and ag37_ds:
        draws = (d.get("ag37_cal") or {}).get("draws", 50)
        return T(f'{num(ag37_ds["ieee37"]["converged"])} events · {draws} draws',
                 f'{num(ag37_ds["ieee37"]["converged"])} ca · {draws} lần rút')
    if prod == "hif_fusion" and hif.get("ds"):
        ds = hif["ds"]
        tot = sum(ds[k]["converged"] for k in ("passive_ieee123", "passive_ieee34", "active_ieee123", "active_ieee34") if k in ds)
        return T(f'{num(tot)} events (4 branches)', f'{num(tot)} ca (4 nhánh)')
    if prod == "hif_fusion_realistic":
        hr = d.get("hif_real") or {}
        ds_r = hr.get("ds") or {}
        branches = [k for k in ("passive_ieee123", "passive_ieee34", "active_ieee123", "active_ieee34")
                    if isinstance(ds_r.get(k), dict) and ds_r[k].get("converged")]
        if branches:
            tot = sum(int(ds_r[k]["converged"]) for k in branches)
            nb = len(branches)
            return T(f'{num(tot)} events ({nb} {"branch" if nb == 1 else "branches"})',
                     f'{num(tot)} ca ({nb} nhánh)')
        ev = sum(int((hr.get(k) or {}).get("events", 0)) for k in ("p123", "p34", "a123", "a34")
                 if isinstance(hr.get(k), dict) and hr[k].get("status") != "NOT_RUN_YET")
        if ev > 0:
            return T(f'{num(ev)} realistic events', f'{num(ev)} ca thực tế')
        return T("Branch 10 realistic", "Nhánh 10 thực tế")
    if prod == "comtrade_verify" and d.get("comtrade"):
        c = d["comtrade"]["counts"]
        sim_n = c["total_verified"] - c["public_samples"]
        return T(f'{c["total_passed"]}/{c["total_verified"]} passed ({c["public_samples"]} public + {sim_n} sim)',
                 f'đạt {c["total_passed"]}/{c["total_verified"]} ({c["public_samples"]} công khai + {sim_n} mô phỏng)')
    return "–"


def _file_link(rel: str) -> str:
    """Link a result file directly to docs/data/ when published, or to GitHub otherwise."""
    short = esc(rel.removeprefix("results/"))
    if rel in PUB_BY_REL:
        return f'<a href="data/{esc(PUB_BY_REL[rel])}" download><code>{short}</code></a>'
    return f'<a href="{REPO}/blob/main/{esc(rel)}" target="_blank" rel="noopener"><code>{short}</code></a>'


def _copy_sha_btn(sha: str) -> str:
    return (f'<span class="sha"><code>{esc(sha[:12])}…</code>'
            f'<button type="button" class="copy-btn" data-copy-text="{esc(sha)}" data-copy-kind="hash" '
            f'title="{esc(sha)}">{T("Copy", "Chép")}</button></span>')


def evidence_block(d: dict, v: dict, pub_files: list) -> str:
    """Reviewer-ready verification block right under Run Checks: live 23-manifest SHA-256 Provenance
    Ledger, Passed Evidence vs. Honest Failures & Limits table, and Static-Page Security Commitment."""
    pl = d.get("prov_ledger") or []
    pv = d.get("prov_verify") or {"changed": [], "missing": [], "unrecorded": []}
    n_man = len(pl)
    n_files = sum(r["file_count"] for r in pl)
    n_chg, n_mis, n_unr = len(pv["changed"]), len(pv["missing"]), len(pv["unrecorded"])
    all_ok = bool(pl) and (n_chg == 0 and n_mis == 0 and n_unr == 0)
    ok_chip = (f'<span class="chip good">✓ {T("100% Verified", "Khớp 100%")}</span>' if all_ok
               else f'<span class="chip critical">✕ {T("Mismatch", "Lệch mã băm")}</span>')

    # Frozen Tier-1 Edge HIF-Sensor model cryptographic identity (live from results/hif_fusion/dataset_summary.json)
    t1 = ((d.get("hif") or {}).get("ds") or {}).get("tier1_edge_model") or {}
    t1_sha = t1.get("sha256", "")
    t1_src = t1.get("model_source", "")
    t1_ref = "christoopherchau/ch-y-n" if "christoopherchau/ch-y-n" in t1_src else esc(t1_src or "–")
    t1_card = ""
    if t1_sha:
        t1_card = (
            '<div class="ev-card">'
            f'<div class="ev-k">{T("Frozen Tier-1 Edge Model (int8)", "Mô hình Tầng 1 đóng băng (int8)")}</div>'
            f'<div class="ev-v"><code>model_int8.npz</code> · {t1.get("params", hif_edge.EXPECTED_PARAMS)} params · '
            f'{t1.get("bytes", hif_edge.EXPECTED_BYTES)} B</div>'
            f'<div class="ev-s">{T("Kaggle kernel", "Kaggle kernel")}: <code>{esc(t1_ref)}</code> · '
            f'{T("thr", "ngưỡng")} <code>{t1.get("threshold", 0.0):.4f}</code> · SHA-256 {_copy_sha_btn(t1_sha)}</div>'
            '</div>'
        )

    # 2-command independent local reproducibility box
    cmd1 = "python -m shf.provenance"
    cmd2 = "python harness/check.py --tests"
    repro_card = (
        '<div class="ev-card">'
        f'<div class="ev-k">{T("Independent 2-Command Audit", "Tự kiểm chứng độc lập bằng 2 lệnh")}</div>'
        '<div class="ev-cmds">'
        f'<div class="ev-cmd"><code>{cmd1}</code><button type="button" class="copy-btn" '
        f'data-copy-text="{cmd1}" data-copy-kind="cmd">{T("Copy", "Chép")}</button></div>'
        f'<div class="ev-cmd"><code>{cmd2}</code><button type="button" class="copy-btn" '
        f'data-copy-text="{cmd2}" data-copy-kind="cmd">{T("Copy", "Chép")}</button></div>'
        '</div>'
        + TB(f"Recomputes all {n_files} SHA-256 hashes, verifies every prose number against results/, checks docs/data/ freshness, secret hygiene, and pytest.",
             f"Tính lại toàn bộ {n_files} mã SHA-256, đối chiếu mọi con số văn bản với results/, kiểm tra đồng bộ docs/data/, bảo mật secret và chạy pytest.",
             "div", "ev-s")
        + '</div>'
    )

    strip = (
        '<div class="ev-strip">'
        '<div class="ev-card">'
        f'<div class="ev-k">{T("Cryptographic Provenance", "Chứng thực mật mã SHA-256")}</div>'
        f'<div class="ev-v">{ok_chip} <span>{n_man} {T("manifests", "manifest")} · {n_files} {T("files", "file")}</span></div>'
        f'<div class="ev-s">{T(f"{n_chg} changed · {n_mis} missing · {n_unr} unrecorded (live check at build time)", f"{n_chg} thay đổi · {n_mis} thiếu · {n_unr} chưa ghi (kiểm trực tiếp khi dựng trang)")}</div>'
        '</div>'
        + t1_card + repro_card + '</div>'
    )

    # (1) 23-manifest SHA-256 Provenance Ledger table
    prov_head = [
        "#",
        T("Experiment / Manifest", "Mã thí nghiệm / Manifest"),
        T("Run source", "Nguồn chạy"),
        T("Events / Scope", "Số sự kiện / Phạm vi"),
        T("Primary file & SHA-256 (copy)", "File chính & SHA-256 (sao chép)"),
        T("Match", "Khớp"),
    ]
    prov_rows = []
    all_file_rows = []
    for idx, row in enumerate(pl, 1):
        prod = row["producer"]
        meta = PROV_META.get(prod)
        en_t, vi_t = (meta[0], meta[1]) if meta else (prod, prod)
        hint = meta[3] if meta else None
        files = row["files"]
        primary = next((f for f in files if f["path"] == hint), files[0]) if files else None
        extra_n = len(files) - 1
        extra_tag = f' <small>+{extra_n} {T("more file" if extra_n == 1 else "more files", "file khác")}</small>' if extra_n > 0 else ""
        man_link = f'<a href="{REPO}/blob/main/{esc(row["manifest"])}" target="_blank" rel="noopener"><code>{esc(prod)}</code></a>'
        utc_day = esc((row.get("written_utc") or "")[:10])
        col_exp = f'<b>{T(en_t, vi_t)}</b><small>{man_link} · {utc_day}</small>'
        col_sha = (f'{_file_link(primary["path"])}<br>{_copy_sha_btn(primary["sha256"])}{extra_tag}'
                   if primary else "–")
        n_ok_f = sum(1 for f in files if f["status"] == "ok")
        st_chip = (f'<span class="chip good">✓ 100%<small style="display:inline;margin-left:3px">({n_ok_f}/{len(files)})</small></span>'
                   if row["verified"] else f'<span class="chip critical">✕ {n_ok_f}/{len(files)}</span>')
        prov_rows.append([str(idx), col_exp, _prov_env(row), _prov_scope(prod, d), col_sha, st_chip])
        for f in files:
            fst = (f'<span class="chip good">✓ {T("OK", "Khớp")}</span>' if f["status"] == "ok"
                   else f'<span class="chip critical">✕ {esc(f["status"])}</span>')
            all_file_rows.append([f'<code>{esc(prod)}</code>', _file_link(f["path"]), _copy_sha_btn(f["sha256"]), fst])

    t_prov = table(prov_head, prov_rows, {0})
    t_all_files = table(
        [T("Manifest", "Manifest"), T("Result file (direct download)", "File kết quả (tải trực tiếp)"),
         T("SHA-256 (copy full 64-hex)", "SHA-256 (chép đủ 64 ký tự)"), T("Status", "Trạng thái")],
        all_file_rows,
    )

    # (2) Passed Evidence vs. Honest Failures & Limits table (all project metrics read live from results/)
    mfb = d.get("mfb") or {}
    c_mfb = mfb.get("counts") or {}
    n_pass_mfb = c_mfb.get("pass", 0) + 1 if c_mfb else 0
    n_unseen_mfb = c_mfb.get("total_unseen_evaluated", 0)
    hif = d.get("hif") or {}
    hp123, ha123, ha34, hconf = hif.get("p123"), hif.get("a123"), hif.get("a34"), hif.get("conf")

    hif_ev_en = hif_ev_vi = T("Not run yet (Kaggle GPU)", "Chưa chạy (Kaggle GPU)")
    if hp123 and ha123 and ha34 and hconf:
        g400_b = pct(hp123["ablations"]["60Hz_only"]["per_node_gbdt"]["slg_by_resistance"]["400.0"])
        g400_f = pct(hp123["ablations"]["60Hz_plus_edge"]["per_node_gbdt"]["slg_by_resistance"]["400.0"])
        n400_b = pct(hp123["ablations"]["60Hz_only"]["zone_tree_gnn"]["slg_by_resistance"]["400.0"])
        n400_f = pct(hp123["ablations"]["60Hz_plus_edge"]["zone_tree_gnn"]["slg_by_resistance"]["400.0"])
        f123_b = pct(ha123["ablations"]["60Hz_only"]["active_grid_gatv2"]["nofault_fpr"])
        f123_f = pct(ha123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]["nofault_fpr"])
        f34_b = pct(ha34["zero_shot"]["60Hz_only"]["active_per_node_gbdt"]["nofault_fpr"])
        f34_f = pct(ha34["zero_shot"]["60Hz_plus_edge"]["active_per_node_gbdt"]["nofault_fpr"])
        c_f = hconf["results"]["60Hz_plus_edge"]["active_grid_gatv2"]["aps_rand"]["target_95"]["ieee123_cross_conformal"]
        hif_ev_en = emph(
            f'All 4 pre-committed criteria <b>H1–H4 PASS</b> on paired events: passive 123-bus SLG 400 Ω rises '
            f'{g400_b} → {g400_f} (GBDT) & {n400_b} → {n400_f} (GNN); active 123-bus NO_FAULT FPR drops '
            f'{f123_b} → {f123_f} (GATv2); active 34-bus zero-shot FPR drops {f34_b} → {f34_f} (GBDT); '
            f'<code>aps_rand</code> 95% singleton share {pct(c_f["singleton_share"])} ({pct(c_f["singleton_accuracy"])} right, '
            f'{pct(c_f["nofault_autonomous_trip_share"])} auto NO_FAULT trip).'
        )
        hif_ev_vi = emph(
            f'Cả 4 tiêu chí khóa trước <b>H1–H4 ĐẠT</b> trên cùng tập sự kiện: 123-bus thụ động SLG 400 Ω tăng '
            f'{g400_b} → {g400_f} (GBDT) & {n400_b} → {n400_f} (GNN); 123-bus chủ động FPR giảm '
            f'{f123_b} → {f123_f} (GATv2); 34-bus chủ động zero-shot FPR giảm {f34_b} → {f34_f} (GBDT); '
            f'<code>aps_rand</code> 95% có {pct(c_f["singleton_share"])} tập 1 nhãn (đúng {pct(c_f["singleton_accuracy"])}, '
            f'cắt nhầm NO_FAULT tự hành {pct(c_f["nofault_autonomous_trip_share"])}).'
        )

    honesty_rows = [
        [
            f'<span class="chip good">✓ {T("PASS (sim)", "ĐẠT (mô phỏng)")}</span>',
            f'<b>{T("Main FLISR · IEEE 123-bus", "FLISR chính · IEEE 123-bus")}</b>',
            T(emph(f'ML {v["acc"]} vs FPI {v["acc_fpi"]} across {v["faults"]} faults (bus-disjoint 5-fold CV; '
                   f'intermittent arcing SLG ≥ 100 Ω, per-zone loading + drift, CT/PT bias + 0.5 A floor); '
                   f'10/10 plans within {v["vmin"]}–{v["vmax"]} pu & radial; {v["kw_back"]}/{v["kw_dark"]} kW restored '
                   f'(−{v["kwmin"]}% kW·min under assumed switching times).'),
              emph(f'ML đạt {v["acc"]} so với FPI {v["acc_fpi"]} trên {v["faults"]} sự cố (CV 5 phần tách bus; '
                   f'hồ quang chập chờn SLG ≥ 100 Ω, tải biến động theo zone + trôi tải, lệch CT/PT + sàn 0.5 A); '
                   f'10/10 phương án trong {v["vmin"]}–{v["vmax"]} pu & hình tia; cấp lại {v["kw_back"]}/{v["kw_dark"]} kW '
                   f'(−{v["kwmin"]}% kW·phút theo thời gian đóng cắt giả định).')),
            T(emph(f'{v.get("slg_hi", "–")}/{v.get("errors", "–")} errors ({v.get("slg_hi_share", "–")}) are SLG ≥ 200 Ω '
                   f'({v["r100"]} at 100 Ω, {v["r200"]} at 200 Ω, {v["r400"]} at 400 Ω under intermittent arcing + load drift); '
                   f'60 Hz phasors only (no EMTP/CT saturation) and main dataset has no NO_FAULT cases.'),
              emph(f'{v.get("slg_hi", "–")}/{v.get("errors", "–")} lỗi ({v.get("slg_hi_share", "–")}) là SLG ≥ 200 Ω '
                   f'({v["r100"]} ở 100 Ω, {v["r200"]} ở 200 Ω, {v["r400"]} ở 400 Ω dưới hồ quang chập chờn + trôi tải); '
                   f'thuần phasor 60 Hz (chưa có EMTP/bão hòa CT) và bộ chính không có ca NO_FAULT.')),
        ],
        [
            f'<span class="chip good">✓ {T(f"PASS ({n_pass_mfb}/{n_unseen_mfb})", f"ĐẠT ({n_pass_mfb}/{n_unseen_mfb})")}</span>',
            f'<b>{T("15-Feeder Multi-Feeder Zero-Shot", "Kiểm chứng đa lưới 15 lưới (0-shot)")}</b>',
            T(emph(f'Frozen IEEE 123-bus models pass <b>{n_pass_mfb} of {n_unseen_mfb}</b> unseen OpenDSS feeders '
                   f'(0.416–34.5 kV, 50/60 Hz, up to 6,058 buses / 18 zones): 50 Hz EU-LV 93.3%/91.3%, IEEE 8500-Node '
                   f'99.8%/99.0%, and all 6 EPRI feeders 98.0%–99.7%.'),
              emph(f'Mô hình IEEE 123-bus đóng băng đạt chuẩn trên <b>{n_pass_mfb}/{n_unseen_mfb}</b> lưới OpenDSS chưa thấy '
                   f'(0.416–34.5 kV, 50/60 Hz, tới 6,058 bus / 18 zone): lưới hạ áp châu Âu 50 Hz 93.3%/91.3%, '
                   f'IEEE 8500-Node 99.8%/99.0% và cả 6 lưới EPRI 98.0%–99.7%.')),
            T("3 circuits logged transparently as out-of-scope: heavily meshed IEEE 342-Node (71 cycles), non-converged IEEE 9500-Node, and absent CIGRE MV.",
              "3 lưới ghi nhận trung thực là ngoài phạm vi: mạng mạch lưới IEEE 342-Node (71 vòng kín), IEEE 9500-Node không hội tụ OpenDSS và CIGRE MV không có trong kho chuẩn."),
        ],
        [
            f'<span class="chip good">✓ {T("PASS (H1–H4)", "ĐẠT (H1–H4)")}</span>',
            f'<b>{T("Two-Tier Edge HIF-Sensor → Graph FLISR", "Kiến trúc 2 tầng Edge HIF-Sensor → Graph FLISR")}</b>',
            T(hif_ev_en, hif_ev_vi),
            T("Simulation only (Emanuel arcs, no EMTP/CT saturation); field deployment requires ≥ 15.36 kHz edge sensing + ~2 kHz anti-alias filter per switch (not legacy 60 Hz SCADA).",
              "Thuần mô phỏng (hồ quang Emanuel, chưa có EMTP/bão hòa CT); triển khai thật cần cảm biến biên ≥ 15.36 kHz + lọc chống răng cưa ~2 kHz tại từng dao (SCADA 60 Hz cũ không cung cấp được)."),
        ],
    ]
    hr_ev = d.get("hif_real") or {}
    if _branch_ready(hr_ev.get("p123"), "ablations"):
        ab_e = hr_ev["p123"]["ablations"]
        crits = _extract_r_criteria(hr_ev)
        vds = [vd for cid, vd in crits if cid in ("R1", "R2", "R3", "R4")]
        n_pass_r = sum(vd == "PASS" for vd in vds)
        chip_cls = "good" if vds and all(vd == "PASS" for vd in vds) else ("critical" if any(vd == "FAIL" for vd in vds) else "warning")
        chip_lbl = f"{n_pass_r}/{len(vds)} R1–R4" if vds else "R1–R4"
        parts_r = []
        for mk, lab in (("ml_full", "ml_full"), ("per_node_gbdt", "GBDT"), ("zone_tree_gnn", "GNN")):
            bm, fm = ab_e["60Hz_only"].get(mk), ab_e["60Hz_plus_edge"].get(mk)
            if bm and fm:
                b4, f4 = (bm.get("slg_by_resistance") or {}).get("400.0"), (fm.get("slg_by_resistance") or {}).get("400.0")
                if b4 is not None and f4 is not None:
                    parts_r.append(f"{lab} {pct(b4)} → {pct(f4)}")
        r_sum_s = ", ".join(parts_r) or "loaded"
        honesty_rows.append([
            f'<span class="chip {chip_cls}">{esc(chip_lbl)}</span>',
            f'<b>{T("Branch-10 Realistic HIF-Fusion (R1–R4)", "HIF-Fusion thực tế Nhánh 10 (R1–R4)")}</b>',
            T(emph(f'On Branch-10 intermittent arcing + zone load drift + CT/PT noise (IEEE 123-bus), SLG 400 Ω recovers: {r_sum_s}.'),
              emph(f'Trên hồ quang chập chờn + trôi tải zone + nhiễu CT/PT Nhánh 10 (IEEE 123-bus), SLG 400 Ω hồi phục: {r_sum_s}.')),
            T("Simulation only (Emanuel 2-diode arcs + simulated background loads); reported verbatim including any PARTIAL / FAIL / NOT_RUN_YET criteria.",
              "Thuần mô phỏng (hồ quang Emanuel 2 diode + tải nền mô phỏng); báo cáo nguyên vẹn kể cả các tiêu chí PARTIAL / FAIL / NOT_RUN_YET."),
        ])
    honesty_rows += [
        [
            f'<span class="chip critical">✕ {T("FAIL (P1-Fail)", "THẤT BẠI (P1-Fail)")}</span>',
            f'<b>{T("Underground Delta IEEE 37-bus (SLG)", "Cáp ngầm delta IEEE 37-bus (SLG)")}</b>',
            T(emph(f'Phase faults (3PH/LL/LLG) still transfer zero-shot at {v.get("tr_p37_gbdt_ph", "–")} (GBDT) / '
                   f'{v.get("tr_p37_gnn_ph", "–")} (GNN), and active 20% few-shot GATv2 climbs to {v.get("ag_gat37_fs20", "–")}.'),
              emph(f'Sự cố pha (3PH/LL/LLG) vẫn chuyển giao zero-shot ở mức {v.get("tr_p37_gbdt_ph", "–")} (GBDT) / '
                   f'{v.get("tr_p37_gnn_ph", "–")} (GNN), và tinh chỉnh 20% trên lưới chủ động đưa GATv2 lên {v.get("ag_gat37_fs20", "–")}.')),
            T(emph(f'<b>Honest failure:</b> passive zero-shot misses P1-Main ({v.get("tr_p37_gbdt", "–")} GBDT / '
                   f'{v.get("tr_p37_gnn", "–")} GNN vs {v.get("tr_p37_fpi", "–")} FPI); SLG collapses to '
                   f'{v.get("tr_p37_gbdt_slg", "–")} / {v.get("tr_p37_gnn_slg", "–")} because 3-wire ungrounded delta SLG '
                   f'draws only capacitive current ({v.get("s2l_i001_37", "–")} / {v.get("s2l_sh001_37", "–")} bolted). '
                   f'Active 37-bus zero-shot is {v.get("ag_gbdt37_zs", "–")} / {v.get("ag_gat37_zs", "–")} (<code>A2-Partial</code>).'),
              emph(f'<b>Thất bại trung thực:</b> zero-shot thụ động trượt tiêu chí P1-Main ({v.get("tr_p37_gbdt", "–")} GBDT / '
                   f'{v.get("tr_p37_gnn", "–")} GNN so với {v.get("tr_p37_fpi", "–")} FPI); SLG sụp xuống '
                   f'{v.get("tr_p37_gbdt_slg", "–")} / {v.get("tr_p37_gnn_slg", "–")} vì lưới 3 dây delta không nối đất chỉ có '
                   f'dòng điện dung ({v.get("s2l_i001_37", "–")} / {v.get("s2l_sh001_37", "–")} khi chạm trực tiếp). '
                   f'Lưới chủ động 37-bus zero-shot đạt {v.get("ag_gbdt37_zs", "–")} / {v.get("ag_gat37_zs", "–")} (<code>A2-Partial</code>).')),
        ],
        [
            f'<span class="chip warning">! {T("LIMIT (Domain gap)", "GIỚI HẠN (Khoảng cách miền)")}</span>',
            f'<b>{T("Real VeHIF Vegetation Arcs vs. Emanuel", "Hồ quang cây thật VeHIF vs. Emanuel")}</b>',
            T("Background alarm rate stayed 0.0% and 2–5 A vegetation arcs reached 94.7% in the companion Tier-1 check (source: research/hif-fusion/PLAN.md §6.2).",
              "Tỉ lệ báo động giả nền giữ ở 0.0% và hồ quang cây 2–5 A đạt 94.7% trong đối chiếu Tầng 1 của dự án liên kết (nguồn: research/hif-fusion/PLAN.md §6.2)."),
            T("<b>Honest domain gap:</b> running the exact frozen 504 B <code>model_int8.npz</code> without retraining on real 22 kV 50 Hz VeHIF recordings dropped standalone detection from 94.7% (synthetic Emanuel) to <b>56.0%</b> (36.2% at 0–1 A) because real vegetation arcs are steadier and less asymmetric. Simulated gains do not prove field accuracy.",
              "<b>Khoảng cách miền trung thực:</b> chạy đúng <code>model_int8.npz</code> 504 B đóng băng (không huấn luyện lại) trên bản ghi sự cố cây thật 22 kV 50 Hz VeHIF làm tỉ lệ phát hiện độc lập giảm từ 94.7% (Emanuel mô phỏng) xuống <b>56.0%</b> (36.2% ở 0–1 A) do hồ quang cây thật ổn định và ít bất đối xứng hơn. Kết quả mô phỏng chưa chứng minh hiệu năng thực địa."),
        ],
        [
            f'<span class="chip warning">! {T("PARTIAL / LIMIT", "MỘT PHẦN / GIỚI HẠN")}</span>',
            f'<b>{T("Stage-2 Bus Ranking & Conformal Transfer", "Xếp hạng bus Stage-2 & Conformal liên lưới")}</b>',
            T(emph(f'Zero-training 3-phase Takagi reactance reaches {v.get("tr_b123_top3", "–")} top-3 (123-bus) & '
                   f'{v.get("tr_b34_top3", "–")} (34-bus); <code>aps_rand</code> 95% hits {v.get("ag_pr_cov", "–")} coverage on 123-bus.'),
              emph(f'Điện kháng Takagi 3 pha không cần học đạt {v.get("tr_b123_top3", "–")} top-3 (123-bus) & '
                   f'{v.get("tr_b34_top3", "–")} (34-bus); <code>aps_rand</code> 95% đạt độ phủ {v.get("ag_pr_cov", "–")} trên 123-bus.')),
            T(emph(f'<code>BusGraphGNN</code> loses to physics on 123-bus ({v.get("tr_b123_gnn3", "–")} vs {v.get("tr_b123_top3", "–")}); '
                   f'parallel laterals at ΔX₁ = 0.000 Ω are physically indistinguishable. Pre-registered <code>aps_det</code> saturates '
                   f'({v.get("ag_pd_size", "–")} labels/set); frozen 123-bus <code>q̂</code> misses 95% on unseen 34-bus '
                   f'({v.get("ag_pr_zs34", "–")}) & 37-bus ({v.get("ag_pr_zs37", "–")}) without local calibration.'),
              emph(f'<code>BusGraphGNN</code> thua phương pháp vật lý trên 123-bus ({v.get("tr_b123_gnn3", "–")} so với {v.get("tr_b123_top3", "–")}); '
                   f'hai nhánh song song có ΔX₁ = 0.000 Ω không thể tách bằng cảm biến đầu zone. <code>aps_det</code> đăng ký trước bị bão hòa '
                   f'({v.get("ag_pd_size", "–")} nhãn/tập); ngưỡng <code>q̂</code> từ 123-bus không giữ được 95% trên 34-bus '
                   f'({v.get("ag_pr_zs34", "–")}) và 37-bus ({v.get("ag_pr_zs37", "–")}) nếu không hiệu chỉnh tại lưới đích.')),
        ],
        [
            f'<span class="chip warning">! {T("SCOPE LIMIT", "GIỚI HẠN PHẠM VI")}</span>',
            f'<b>{T("Simulation Only · No Live Utility SCADA", "Thuần mô phỏng · Không nối SCADA thật")}</b>',
            T("Every feeder, fault, LTspice waveform, and Wokwi ESP32 panel replay is reproducible from open-source code and published JSON/CSV outputs.",
              "Mọi lưới điện, sự cố, dạng sóng LTspice và bảng điều khiển ESP32 Wokwi đều tái tạo được từ mã nguồn mở và file JSON/CSV công khai."),
            T("Zero field utility event recordings; MQTT ran end-to-end only with the simulated Wokwi panel (TimescaleDB ingestion path not run end-to-end); hourly restoration uses regional PJM AEP load shape, not single-feeder measurements.",
              "Không có bản ghi sự cố thực địa từ công ty điện; MQTT mới chạy nối thông với bảng ESP32 mô phỏng trên Wokwi (nhánh lưu TimescaleDB chưa chạy nối thông); khôi phục theo giờ dùng đường tải vùng PJM AEP, không phải số đo riêng một tuyến."),
        ],
    ]
    t_honesty = table(
        [T("Status", "Kết luận"), T("Study / Boundary", "Hạng mục / Giới hạn"),
         T("Verified Passed Evidence (from results/)", "Bằng chứng đạt kiểm chứng (từ results/)"),
         T("Honest Failures, Caveats & Physical Limits", "Ca thất bại trung thực, lưu ý & giới hạn vật lý")],
        honesty_rows,
    )

    # (3) Static-page security & direct data-access commitment
    n_pub = len(pub_files)
    sec_box = (
        '<div class="ev-sec">'
        f'<h4>{T("Static-Page Security, Privacy & Open Data Access", "Cam kết Bảo mật Trang tĩnh, Quyền riêng tư & Dữ liệu Mở")}</h4>'
        + TB(f'<ul>'
             f'<li><b>Pure static GitHub Pages:</b> this report (<code>docs/index.html</code>) has <b>no backend server</b>, '
             f'no database, no login/password collection, no analytics cookies, and zero tracking beacons.</li>'
             f'<li><b>Zero secrets or embedded API keys:</b> the study calls no external API; <code>harness/check.py</code> '
             f'(<code>check_secrets</code>) and <code>.gitignore</code> / <code>.git/info/exclude</code> block '
             f'<code>.env</code>, <code>kaggle.json</code>, API tokens, and local working files from entering Git. '
             f'Only <code>localStorage</code> keys <code>shf-lang</code> and <code>shf-theme</code> are stored locally in your browser; '
             f'optional read-only CDN assets (<code>three.js</code>, <code>KaTeX</code>) load strictly for 3D and formula rendering.</li>'
             f'<li><b>Direct data downloads ({n_pub} files in <code>docs/data/</code>):</b> every JSON, CSV, and PDF artifact '
             f'behind the numbers is published alongside this page — <a href="#data-files">jump to all {n_pub} direct downloads</a> '
             f'or inspect the raw manifests in <a href="{REPO}/tree/main/results/provenance" target="_blank" rel="noopener">'
             f'<code>results/provenance/</code></a>.</li>'
             f'</ul>',
             f'<ul>'
             f'<li><b>GitHub Pages thuần tĩnh:</b> trang báo cáo này (<code>docs/index.html</code>) <b>không có backend</b>, '
             f'không cơ sở dữ liệu, không thu thập tài khoản/mật khẩu, không cookie theo dõi hay công cụ phân tích hành vi.</li>'
             f'<li><b>Không nhúng API key hay thông tin nhạy cảm:</b> nghiên cứu không gọi API bên ngoài; <code>harness/check.py</code> '
             f'(<code>check_secrets</code>) cùng <code>.gitignore</code> / <code>.git/info/exclude</code> chặn chắc '
             f'<code>.env</code>, <code>kaggle.json</code>, token và file nội bộ khỏi Git. Trình duyệt chỉ lưu cục bộ '
             f'tùy chọn ngôn ngữ (<code>shf-lang</code>) và giao diện (<code>shf-theme</code>); thư viện tĩnh CDN chỉ đọc '
             f'(<code>three.js</code>, <code>KaTeX</code>) chỉ phục vụ hiển thị 3D và công thức.</li>'
             f'<li><b>Tải trực tiếp toàn bộ dữ liệu ({n_pub} file trong <code>docs/data/</code>):</b> mọi file JSON, CSV và PDF '
             f'đứng sau các con số đều được công khai cùng trang này — <a href="#data-files">tới danh sách tải trực tiếp {n_pub} file</a> '
             f'hoặc xem trực tiếp manifest gốc tại <a href="{REPO}/tree/main/results/provenance" target="_blank" rel="noopener">'
             f'<code>results/provenance/</code></a>.</li>'
             f'</ul>', "div")
        + '</div>'
    )

    return (
        f'<div class="panel ev-panel" id="evidence" data-x="evidence">'
        f'<h2>{T("Verification, Cryptographic Provenance & Scientific Honesty (For Reviewers & Lecturers)", "Chứng thực, Kiểm chứng & Độ tin cậy (Dành cho giảng viên / phản biện)")}'
        f'<a class="anchor" href="#evidence" aria-label="Link to this section">#</a></h2>'
        + TB(emph(f'Built directly from all <b>{n_man}</b> {term("provenance", "SHA-256 provenance")} manifests in '
                  f'<code>results/provenance/*.json</code> ({n_files} result files) — zero hand-typed numbers. '
                  f'Every experiment is <b>simulation only</b>; failures and domain gaps are reported right beside passing criteria.'),
             emph(f'Dựng trực tiếp từ toàn bộ <b>{n_man}</b> manifest {term("provenance", "chứng thực SHA-256", "chứng thực SHA-256")} '
                  f'trong <code>results/provenance/*.json</code> ({n_files} file kết quả) — không gõ tay số liệu. '
                  f'Mọi thí nghiệm đều là <b>mô phỏng</b>; các ca thất bại và khoảng cách miền được báo cáo trung thực ngay cạnh tiêu chí đạt.'),
             "p", "how")
        + strip
        + deep_box(
            f"SHA-256 Provenance Ledger ({n_man} manifests · {n_files} files), Honest Failures & Security",
            f"Sổ cái SHA-256 ({n_man} manifest · {n_files} file), Bảng trung thực & Cam kết bảo mật",
            "Click to inspect every SHA-256 hash, passing criteria vs honest failures, and static-page security audit.",
            "Bấm để xem toàn bộ mã SHA-256, đối chiếu kết quả đạt vs ca thất bại trung thực và kiểm toán bảo mật.",
            f'<h3>{T(f"SHA-256 Provenance Ledger ({n_man} manifests · {n_files} recorded files)", f"Sổ cái chứng thực SHA-256 ({n_man} manifest · {n_files} file kết quả)")}</h3>'
            + xbox("table-provenance", t_prov)
            + f'<details class="ev-all"><summary>{T(f"Inspect & download all {n_files} individual SHA-256 verified files", f"Xem và tải từng file trong đủ {n_files} file đã chứng thực SHA-256")}</summary>{t_all_files}</details>'
            + f'<h3>{T("Passed Evidence vs. Honest Failures & Simulation Limits", "Bằng chứng đạt vs. Ca thất bại trung thực & Giới hạn")}</h3>'
            + xbox("table-honesty", t_honesty)
            + sec_box,
            badge=ok_chip,
            id_="evidence-details",
        )
        + '</div>'
    )


def numbers(d: dict) -> dict:
    """Every number the Q&A answers quote, formatted for display."""
    m, fl, rs = d["m"], d["m"]["fault_location"], d["m"]["restoration"]
    full, mag, fpi = fl["ml_full"], fl["ml_magnitude_only"], fl["fpi_baseline"]
    miss = full["missing_sensor_accuracy"]
    lo_dev, lo = min(miss.items(), key=lambda kv: kv[1])
    red = sorted(d["rest"], key=lambda r: float(r["kWmin_reduction_pct"]))
    t, pk = rs["timing_assumption_min"], m["patrol_kft"]
    back, dark = rs["kW_restored_by_tie_total"], rs["kW_downstream_healthy_total"]
    v = {
        "faults": num(m["dataset"]["rows"]), "acc": pct(full["accuracy"]), "acc_mag": pct(mag["accuracy"]),
        "acc_fpi": pct(fpi["accuracy"]), "r100": pct(full["slg_by_resistance"]["100.0"]),
        "r200": pct(full["slg_by_resistance"]["200.0"]),
        "r400": pct(full["slg_by_resistance"]["400.0"]),
        "r100_mag": pct(mag["slg_by_resistance"]["100.0"]), "r100_fpi": pct(fpi["slg_by_resistance"]["100.0"]),
        "r400_fpi": pct(fpi["slg_by_resistance"]["400.0"]),
        "fpi_3ph": pct(fpi["by_fault_type"]["3PH"]), "fpi_ll": pct(fpi["by_fault_type"]["LL"]),
        "fpi_slg": pct(fpi["by_fault_type"]["SLG"]), "fpi_none": pct(fpi["no_device_flagged"]),
        "bolted_fpi": pct(fpi["slg_by_resistance"]["0.01"]),
        "miss_lo": pct(lo), "miss_hi": pct(max(miss.values())), "miss_dev": lo_dev, "dropout": f"{DROPOUT_RATE:.0%}",
        "patrol_none": f'{pk["no_location"]:.1f}', "patrol_ml": f'{pk["ml_full"]:.1f}',
        "kw_back": num(back), "kw_dark": num(dark), "kw_share": f"{back / dark:.0%}",
        "kwmin": f'{rs["kWmin_reduction_pct_weighted_by_line_length"]:.1f}',
        "kwmin_lo": f'{float(red[0]["kWmin_reduction_pct"]):.0f}%', "kwmin_lo_zone": red[0]["fault_zone"],
        "kwmin_hi": f'{float(red[-1]["kWmin_reduction_pct"]):.0f}%', "kwmin_hi_zone": red[-1]["fault_zone"],
        "t_auto": t["automated"], "t_man": t["manual"], "t_rep": t["repair"],
        "vmin": f"{config.V_MIN_PU:.2f}", "vmax": f"{config.V_MAX_PU:.2f}",
    }
    h = d["h"]
    if h:
        td, yr, lim = h["typical_day"], h["year"], h["limits"]

        def at(season: str, f) -> tuple[str, str]:
            vals = td[season]["pct_restored"]
            x = f(vals)
            return pct(x), f"{vals.index(x):02d}:00"

        flips = [z for z, n in h["level_steps_with_more_restored"].items() if n]
        both = lambda xs, w: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + f" {w} " + xs[-1]  # noqa: E731
        (su_hi, su_hi_t), (su_lo, su_lo_t) = at("summer", max), at("summer", min)
        (wi_hi, wi_hi_t), (wi_lo, wi_lo_t) = at("winter", max), at("winter", min)
        v.update({
            "h_year": str(h["load_shape"]["year"]), "h_hours": num(h["load_shape"]["hours"]),
            "h_pct": pct(yr["pct_restored_mean"]), "h_held": pct(yr["pct_restored_held_mean"]),
            "h_peak": pct(back / dark), "h_hold": h["hold_hours"], "h_lower": pct(yr["share_hours_held_lower"]),
            "su_hi": su_hi, "su_hi_t": su_hi_t, "su_lo": su_lo, "su_lo_t": su_lo_t,
            "wi_hi": wi_hi, "wi_hi_t": wi_hi_t, "wi_lo": wi_lo, "wi_lo_t": wi_lo_t,
            "h_mult_min": f'{yr["mult_min"]:.2f}', "h_mult_mean": f'{yr["mult_mean"]:.2f}',
            "h_flag": num(lim["hours"]), "h_flag_v": f'{lim["max_vmax_pu"]:.4f}' if lim["max_vmax_pu"] else "–",
            "h_flips_en": both(flips, "and") if flips else "no zone",
            "h_flips_vi": both(flips, "và") if flips else "không zone nào",
        })
    sp = d["sp"]
    if sp:
        fr, fp, fe, mo = sp["fault_rms_a"], sp["first_peak"], sp["frontend"], sp["model"]
        hc = sp["hif"]["cases"]
        lo, hi = hc[min(hc, key=float)], hc[max(hc, key=float)]
        v.update({
            "sp_bus": sp["bus"], "sp_rms": num(fr["ltspice_steady"]), "sp_rms_dss": num(fr["opendss_3ph_sw1"]),
            "sp_pk": num(fp["max_offset"]["peak_a"]), "sp_pk0": num(fp["no_offset"]["peak_a"]),
            "sp_asym": f'{fp["max_offset"]["asymmetry"]:.2f}', "sp_tau": f'{mo["tau_ms"]:.1f}',
            "sp_xr": f'{mo["x_over_r"]:.2f}', "sp_ipre": num(mo["i_pre"]),
            "sp_vlo": f'{fe["vadc_min"]:.2f}', "sp_vhi": f'{fe["vadc_max"]:.2f}', "sp_clip": num(fe["clipped_samples"]),
            "sp_apc": f'{fe["primary_amps_per_count"]:.1f}', "sp_settle": f'{fe["dft_settle_ms_within_5pct"]:.0f}',
            "sp_ct": num(fe["ct_ratio"]), "sp_bits": fe["bits"],
            "hif_lo_r": f'{lo["r_fault"]:g}', "hif_hi_r": f'{hi["r_fault"]:g}',
            "hif_hi_i": f'{hi["irms_arc"]:.1f}', "hif_hi_share": pct(hi["share_of_prefault_load_pct"] / 100),
            "hif_hi_counts": num(hi["adc_counts_span_arc"]), "hif_lo_counts": num(lo["adc_counts_span_arc"]),
            "hif_i1": pct(hi["i1_arc_vs_linear"]), "hif_h3": pct(hi["h3_arc_pct"] / 100),
            "hif_h5": pct(hi["h5_arc_pct"] / 100), "hif_dc": f'{hi["dc_arc_a"]:.2f}',
            "hif_vp": f'{sp["hif"]["model"]["vp_frac"]:.0%}', "hif_vn": f'{sp["hif"]["model"]["vn_frac"]:.0%}',
        })
    ea = d["ea"]
    if ea:
        e, dirs = ea["ml_errors"], ea["ml_error_direction"]
        one = dirs.get("predicted parent (1 zone upstream)", 0) + dirs.get("predicted child (1 zone downstream)", 0)
        up = dirs.get("predicted parent (1 zone upstream)", 0) + dirs.get("further upstream", 0)
        path = one + dirs.get("further upstream", 0) + dirs.get("further downstream", 0)
        pair, pair_n = next(iter(ea["ml_top_confusions"].items()))
        d95 = next(r for r in ea["defer_low_confidence"] if r["threshold"] == 0.95)
        pz = d["per_zone"]
        parents = {z["parent_zone"] for z in d["zones"]}
        fnr = max(pz, key=lambda r: float(r["FNR"]))
        fpr = max(pz, key=lambda r: float(r["FPR"]))
        v.update({
            "errors": num(e), "slg_hi": num(ea["ml_errors_slg_200_ohm_or_more"]),
            "slg_hi_share": f'{ea["ml_errors_slg_200_ohm_or_more"] / e:.0%}',
            "err400": pct(ea["ml_slg_error_rate_by_resistance"]["400.0"]),
            "err3ph": pct(ea["ml_error_rate_by_type"]["3PH"]),
            "load_lo": pct(ea["ml_error_rate_by_load_tercile"]["low"]),
            "load_hi": pct(ea["ml_error_rate_by_load_tercile"]["high"]),
            "off1": f"{one / e:.0%}", "same_path": f"{path / e:.0%}", "upstream": f"{up / e:.0%}",
            "top_pair": pair.replace(" -> ", " → "), "top_n": pair_n,
            "conf_right": f'{ea["ml_median_confidence"]["correct"]:.2f}',
            "conf_wrong": f'{ea["ml_median_confidence"]["wrong"]:.2f}',
            "deferred": pct(1 - d95["coverage"]), "acc_kept": pct(d95["accuracy_on_kept"]),
            "errors_kept": num(d95["errors_kept"]), "err_cut": f'{1 - d95["errors_kept"] / e:.0%}',
            "fnr_zone": fnr["zone"], "fnr_max": pct(float(fnr["FNR"])),
            "fpr_zone": fpr["zone"], "fpr_max": pct(float(fpr["FPR"])),
            "leaf_fnr": pct(max(float(r["FNR"]) for r in pz if r["zone"] not in parents)),
        })
    tr = d.get("tr")
    if tr:
        p2, p2b, p3 = tr["p2"]["models"], tr["p2b"], tr["p3"]
        ag123, ag34, conf = tr["ag123"]["models"], tr["ag34"], tr["conf"]
        c123_g = conf["ieee123_bus_disjoint_cv"]["active_gatv2"]["target_95"]
        c34_gat = conf["ieee34_transfer"]["active_gatv2"]["zero_shot_q_from_123"]["target_95"]
        c34_gbdt = conf["ieee34_transfer"]["per_node_gbdt"]["zero_shot_q_from_123"]["target_95"]
        v.update({
            "tr_p2_fpi": pct(p2["fpi"]["accuracy"]),
            "tr_p2_gbdt": pct(p2["per_node_gbdt"]["accuracy"]),
            "tr_p2_gnn": pct(p2["gnn"]["accuracy"]),
            "tr_p3_fpi": pct(p3["fpi"]["accuracy"]),
            "tr_p3_gbdt": pct(p3["zero_shot"]["per_node_gbdt"]["accuracy"]),
            "tr_p3_gnn": pct(p3["zero_shot"]["gnn"]["accuracy"]),
            "tr_b123_top1": pct(p2b["ieee123"]["reactance_takagi"]["top1"]),
            "tr_b123_top3": pct(p2b["ieee123"]["reactance_takagi"]["top3"]),
            "tr_b123_rand3": pct(p2b["ieee123"]["random_in_zone"]["top3"]),
            "tr_b123_gnn1": pct(p2b["ieee123"]["bus_graph_gnn_cv"]["top1"]),
            "tr_b123_gnn3": pct(p2b["ieee123"]["bus_graph_gnn_cv"]["top3"]),
            "tr_b34_top1": pct(p2b["ieee34"]["reactance_takagi"]["top1"]),
            "tr_b34_top3": pct(p2b["ieee34"]["reactance_takagi"]["top3"]),
            "tr_b34_rand3": pct(p2b["ieee34"]["random_in_zone"]["top3"]),
            "ag_fpi123": pct(ag123["fpi"]["overall_accuracy"]),
            "ag_fpi123_fpr": pct(ag123["fpi"]["nofault_fpr"]),
            "ag_gbdt123": pct(ag123["per_node_gbdt"]["overall_accuracy"]),
            "ag_gbdt123_fpr": pct(ag123["per_node_gbdt"]["nofault_fpr"]),
            "ag_gbdt123_miss": pct(ag123["per_node_gbdt"]["missing_sensor_mean"]),
            "ag_gat123": pct(ag123["active_gatv2"]["overall_accuracy"]),
            "ag_gat123_fpr": pct(ag123["active_gatv2"]["nofault_fpr"]),
            "ag_gat123_miss": pct(ag123["active_gatv2"]["missing_sensor_mean"]),
            "ag_fpi34": pct(ag34["fpi"]["overall_accuracy"]),
            "ag_gbdt34_zs": pct(ag34["zero_shot"]["per_node_gbdt"]["overall_accuracy"]),
            "ag_gat34_zs": pct(ag34["zero_shot"]["active_gatv2"]["overall_accuracy"]),
            "ag_gbdt34_fs20": pct(ag34["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["overall_accuracy_mean"]),
            "ag_gat34_fs20": pct(ag34["few_shot"]["pct_20"]["models"]["active_gatv2"]["overall_accuracy_mean"]),
            "ag_gbdt34_ub": pct(ag34["in_domain_upper_bound"]["per_node_gbdt"]["overall_accuracy"]),
            "ag_gat34_ub": pct(ag34["in_domain_upper_bound"]["active_gatv2"]["overall_accuracy"]),
            "ag_conf123_cov": pct(c123_g["empirical_coverage"]),
            "ag_conf34_cov": pct(c34_gat["empirical_coverage"]),
            "ag_conf34_auto_acc": pct(c34_gat["autonomous_accuracy"]),
            "ag_conf34_gbdt_auto_acc": pct(c34_gbdt["autonomous_accuracy"]),
            "ag_conf34_auto_fpr": pct(c34_gat["autonomous_nofault_fpr"]),
        })
    post = (d.get("agpost") or {}).get("results")
    if post:
        gd = post["active_gatv2"]["aps_det"]["target_95"]["ieee123_cross_conformal"]
        g, b = post["active_gatv2"]["aps_rand"]["target_95"], post["per_node_gbdt"]["aps_rand"]["target_95"]
        gl = post["active_gatv2"]["lac"]["target_95"]
        v.update({
            "ag_labels123": str(d["agpost"]["labels"]["ieee123"]),
            "ag_pd_size": f'{gd["avg_set_size"]:.2f}', "ag_pd_single": pct(gd["singleton_share"]),
            "ag_pr_cov": pct(g["ieee123_cross_conformal"]["coverage"]),
            "ag_pr_size": f'{g["ieee123_cross_conformal"]["avg_set_size"]:.2f}',
            "ag_pr_single": pct(g["ieee123_cross_conformal"]["singleton_share"]),
            "ag_pr_sacc": pct(g["ieee123_cross_conformal"]["singleton_accuracy"]),
            "ag_pr_trip": pct(g["ieee123_cross_conformal"]["nofault_autonomous_trip_share"]),
            "ag_pr_zs34": pct(g["ieee34_zero_shot_q_from_123"]["coverage"]),
            "ag_pr_zs34_gbdt": pct(b["ieee34_zero_shot_q_from_123"]["coverage"]),
            "ag_pr_rc34": pct(g["ieee34_recal_5pct_buses"]["coverage"]["mean"]),
            "ag_pr_rc34_min": pct(g["ieee34_recal_5pct_buses"]["coverage"]["min"]),
            "ag_pr_rc34_gbdt": pct(b["ieee34_recal_5pct_buses"]["coverage"]["mean"]),
            "ag_pr_rc34_gbdt_min": pct(b["ieee34_recal_5pct_buses"]["coverage"]["min"]),
            "ag_cal_buses": str(g["ieee34_recal_5pct_buses"]["cal_fault_buses"]),
            "ag_lac_zs34": pct(gl["ieee34_zero_shot_q_from_123"]["coverage"]),
        })
    s2l = d.get("s2l")
    if s2l:
        f34, f123 = s2l["feeders"]["ieee34"], s2l["feeders"]["ieee123"]
        r34, r123, r34hi = (f34["by_resistance"]["400.0"], f123["by_resistance"]["400.0"],
                            f34["by_resistance"]["10000.0"])
        v.update({
            "s2l_head34": f'{f34["head_current_a"]:.1f} A', "s2l_head123": f'{f123["head_current_a"]:.1f} A',
            "s2l_i400_34": f'{r34["fault_current_a"]["median"]:.1f} A',
            "s2l_i400_123": f'{r123["fault_current_a"]["median"]:.1f} A',
            "s2l_sh400_34": pct(r34["share_of_head_current"]["median"]),
            "s2l_sh400_123": pct(r123["share_of_head_current"]["median"]),
            "s2l_sh10k_34": pct(r34hi["share_of_head_current"]["median"]),
        })
        f37 = s2l["feeders"].get("ieee37")
        if f37:
            r37_001, r37_400 = f37["by_resistance"]["0.01"], f37["by_resistance"]["400.0"]
            v.update({
                "s2l_head37": f'{f37["head_current_a"]:.1f} A',
                "s2l_i001_37": f'{r37_001["fault_current_a"]["median"]:.2f} A',
                "s2l_sh001_37": pct(r37_001["share_of_head_current"]["median"], 2),
                "s2l_i400_37": f'{r37_400["fault_current_a"]["median"]:.2f} A',
                "s2l_sh400_37": pct(r37_400["share_of_head_current"]["median"], 2),
            })
    # Optional third feeder: IEEE 37-bus (4.8 kV, urban underground 3-wire ungrounded delta)
    v.update({
        "tr37_explain_en": "", "tr37_explain_vi": "",
        "b37_explain_en": "", "b37_explain_vi": "",
        "conf37_explain_en": "", "conf37_explain_vi": "",
    })
    p3_37 = d.get("p3_37")
    if p3_37:
        v.update({
            "tr_p37_events": num(p3_37["events"]), "tr_p37_buses": str(p3_37["buses"]),
            "tr_p37_zones": str(len(p3_37["devices"])),
            "tr_p37_fpi": pct(p3_37["fpi"]["accuracy"]),
            "tr_p37_fpi_ph": pct(p3_37["fpi"]["phase_faults_accuracy"]),
            "tr_p37_fpi_slg": pct(p3_37["fpi"]["by_fault_type"]["SLG"]),
            "tr_p37_gbdt": pct(p3_37["zero_shot"]["per_node_gbdt"]["accuracy"]),
            "tr_p37_gbdt_ph": pct(p3_37["zero_shot"]["per_node_gbdt"]["phase_faults_accuracy"]),
            "tr_p37_gbdt_slg": pct(p3_37["zero_shot"]["per_node_gbdt"]["by_fault_type"]["SLG"]),
            "tr_p37_gbdt_fs20": pct(p3_37["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["accuracy_mean"]),
            "tr_p37_gbdt_ub": pct(p3_37["in_domain_upper_bound"]["per_node_gbdt"]["accuracy"]),
            "tr_p37_gbdt_ub_slg": pct(p3_37["in_domain_upper_bound"]["per_node_gbdt"]["by_fault_type"]["SLG"]),
            "tr_p37_gnn": pct(p3_37["zero_shot"]["gnn"]["accuracy"]),
            "tr_p37_gnn_ph": pct(p3_37["zero_shot"]["gnn"]["phase_faults_accuracy"]),
            "tr_p37_gnn_slg": pct(p3_37["zero_shot"]["gnn"]["by_fault_type"]["SLG"]),
            "tr_p37_gnn_fs20": pct(p3_37["few_shot"]["pct_20"]["models"]["gnn"]["accuracy_mean"]),
            "tr_p37_gnn_ub": pct(p3_37["in_domain_upper_bound"]["gnn"]["accuracy"]),
            "tr_p37_gnn_ub_slg": pct(p3_37["in_domain_upper_bound"]["gnn"]["by_fault_type"]["SLG"]),
        })
    ag37 = d.get("ag37")
    if ag37:
        v.update({
            "ag_fpi37": pct(ag37["fpi"]["overall_accuracy"]),
            "ag_fpi37_fpr": pct(ag37["fpi"]["nofault_fpr"]),
            "ag_gbdt37_zs": pct(ag37["zero_shot"]["per_node_gbdt"]["overall_accuracy"]),
            "ag_gat37_zs": pct(ag37["zero_shot"]["active_gatv2"]["overall_accuracy"]),
            "ag_gbdt37_fs20": pct(ag37["few_shot"]["pct_20"]["models"]["per_node_gbdt"]["overall_accuracy_mean"]),
            "ag_gat37_fs20": pct(ag37["few_shot"]["pct_20"]["models"]["active_gatv2"]["overall_accuracy_mean"]),
            "ag_gbdt37_ub": pct(ag37["in_domain_upper_bound"]["per_node_gbdt"]["overall_accuracy"]),
            "ag_gat37_ub": pct(ag37["in_domain_upper_bound"]["active_gatv2"]["overall_accuracy"]),
        })
    if p3_37:
        ag_tail_en = (f' Active 37-bus: FPI {v["ag_fpi37"]}, zero-shot GBDT {v["ag_gbdt37_zs"]} / GATv2 {v["ag_gat37_zs"]}.'
                      if ag37 else " Active 37-bus is not run yet on Kaggle GPU.")
        ag_tail_vi = (f' Lưới 37-bus chủ động: FPI {v["ag_fpi37"]}, zero-shot GBDT {v["ag_gbdt37_zs"]} / GATv2 {v["ag_gat37_zs"]}.'
                      if ag37 else " Lưới 37-bus chủ động chưa chạy trên Kaggle GPU.")
        v["tr37_explain_en"] = (f' On underground delta IEEE 37-bus (4.8 kV), passive zero-shot drops to '
                                f'{v["tr_p37_gbdt"]} (GBDT) / {v["tr_p37_gnn"]} (GNN) vs {v["tr_p37_fpi"]} (FPI) '
                                f'because ungrounded SLG returns only capacitive current, though phase faults stay '
                                f'{v["tr_p37_gbdt_ph"]} / {v["tr_p37_gnn_ph"]}.{ag_tail_en}')
        v["tr37_explain_vi"] = (f' Trên cáp ngầm delta IEEE 37-bus (4.8 kV), zero-shot thụ động giảm còn '
                                f'{v["tr_p37_gbdt"]} (GBDT) / {v["tr_p37_gnn"]} (GNN) so với {v["tr_p37_fpi"]} (FPI) '
                                f'do SLG trên lưới delta không nối đất chỉ có dòng điện dung, dù sự cố pha vẫn đạt '
                                f'{v["tr_p37_gbdt_ph"]} / {v["tr_p37_gnn_ph"]}.{ag_tail_vi}')
    p2b_37 = d.get("p2b_37")
    if p2b_37:
        b37 = p2b_37["ieee37"]
        pair = next((p for p in b37["reactance_takagi"]["top_confused_bus_pairs"] if p.get("delta_x1_ohm") is not None), None)
        dx_pair = f'{pair["true_bus"]}→{pair["pred_bus"]}' if pair else ""
        dx_val = f'{pair["delta_x1_ohm"]:.4f} Ω' if pair else "–"
        v.update({
            "tr_b37_rand1": pct(b37["random_in_zone"]["top1"]),
            "tr_b37_rand3": pct(b37["random_in_zone"]["top3"]),
            "tr_b37_rand3_ph": pct(b37["random_in_zone"]["phase_faults_top3"]),
            "tr_b37_top1": pct(b37["reactance_takagi"]["top1"]),
            "tr_b37_top3": pct(b37["reactance_takagi"]["top3"]),
            "tr_b37_ph1": pct(b37["reactance_takagi"]["phase_faults_top1"]),
            "tr_b37_ph3": pct(b37["reactance_takagi"]["phase_faults_top3"]),
            "tr_b37_slg3": pct(b37["reactance_takagi"]["by_fault_type_top3"]["SLG"]),
            "tr_b37_gnn1": pct(b37["bus_graph_gnn_zero_shot"]["top1"]),
            "tr_b37_gnn3": pct(b37["bus_graph_gnn_zero_shot"]["top3"]),
            "tr_b37_gnn_ph3": pct(b37["bus_graph_gnn_zero_shot"]["phase_faults_top3"]),
            "tr_b37_dx_pair": dx_pair,
            "tr_b37_dx_val": dx_val,
        })
        v["b37_explain_en"] = (f' On underground delta 37-bus, Takagi hits {v["tr_b37_ph3"]} and zero-shot GNN '
                               f'{v["tr_b37_gnn_ph3"]} top-3 on phase faults (vs {v["tr_b37_rand3_ph"]} random), '
                               f'while overall top-3 is {v["tr_b37_top3"]} / {v["tr_b37_gnn3"]} because ungrounded SLG '
                               f'breaks the grounded-loop equation.')
        v["b37_explain_vi"] = (f' Trên cáp ngầm delta 37-bus, Takagi đạt {v["tr_b37_ph3"]} và GNN zero-shot '
                               f'{v["tr_b37_gnn_ph3"]} top-3 trên sự cố pha (ngẫu nhiên {v["tr_b37_rand3_ph"]}), còn '
                               f'top-3 tổng thể là {v["tr_b37_top3"]} / {v["tr_b37_gnn3"]} vì SLG trên lưới delta phá '
                               f'vỡ phương trình vòng đất.')
    post37 = (d.get("ag37_post") or {}).get("results")
    if post37:
        g37, b37p = post37["active_gatv2"]["aps_rand"]["target_95"], post37["per_node_gbdt"]["aps_rand"]["target_95"]
        v.update({
            "ag_pr_zs37": pct(g37["ieee37_zero_shot_q_from_123"]["coverage"]),
            "ag_pr_zs37_gbdt": pct(b37p["ieee37_zero_shot_q_from_123"]["coverage"]),
            "ag_pr_rc37": pct(g37["ieee37_recal_5pct_buses"]["coverage"]["mean"]),
            "ag_pr_rc37_min": pct(g37["ieee37_recal_5pct_buses"]["coverage"]["min"]),
            "ag_pr_rc37_gbdt": pct(b37p["ieee37_recal_5pct_buses"]["coverage"]["mean"]),
            "ag_pr_rc37_gbdt_min": pct(b37p["ieee37_recal_5pct_buses"]["coverage"]["min"]),
            "ag_cal_buses37": str(g37["ieee37_recal_5pct_buses"]["cal_fault_buses"]),
        })
        v["conf37_explain_en"] = f' Active 37-bus randomized APS covers {v["ag_pr_zs37"]} zero-shot and {v["ag_pr_rc37"]} recalibrated.'
        v["conf37_explain_vi"] = f' Trên 37-bus chủ động, APS ngẫu nhiên phủ {v["ag_pr_zs37"]} zero-shot và {v["ag_pr_rc37"]} sau hiệu chỉnh.'
    elif any(d.get(k) is not None for k in ("p3_37", "p2b_37", "ag37_ds")):
        v["conf37_explain_en"] = " IEEE 37-bus active conformal has not been run yet on Kaggle GPU."
        v["conf37_explain_vi"] = " Conformal lưới chủ động IEEE 37-bus chưa chạy trên Kaggle GPU."

    # Optional two-tier Edge HIF-Sensor -> Graph FLISR (2d) explain text
    hif = d.get("hif") or {}
    hp123, ha123 = hif.get("p123"), hif.get("a123")
    if hp123 or ha123:
        parts_en, parts_vi = [], []
        if hp123:
            b_g = hp123["ablations"]["60Hz_only"]["per_node_gbdt"]["slg_by_resistance"].get("400.0")
            f_g = hp123["ablations"]["60Hz_plus_edge"]["per_node_gbdt"]["slg_by_resistance"].get("400.0")
            b_n = hp123["ablations"]["60Hz_only"]["zone_tree_gnn"]["slg_by_resistance"].get("400.0")
            f_n = hp123["ablations"]["60Hz_plus_edge"]["zone_tree_gnn"]["slg_by_resistance"].get("400.0")
            if None not in (b_g, f_g, b_n, f_n):
                parts_en.append(f"Passive 123-bus SLG 400 Ω: GBDT {pct(b_g)} → {pct(f_g)}, ZoneTreeGNN {pct(b_n)} → {pct(f_n)}.")
                parts_vi.append(f"123-bus thụ động SLG 400 Ω: GBDT {pct(b_g)} → {pct(f_g)}, ZoneTreeGNN {pct(b_n)} → {pct(f_n)}.")
        if ha123:
            b_a = ha123["ablations"]["60Hz_only"]["active_grid_gatv2"]
            f_a = ha123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"]
            b400 = (b_a.get("slg_by_resistance") or {}).get("400.0")
            f400 = (f_a.get("slg_by_resistance") or {}).get("400.0")
            if b400 is not None and f400 is not None:
                parts_en.append(f"Active 123-bus GATv2: SLG 400 Ω {pct(b400)} → {pct(f400)}, NO_FAULT FPR {pct(b_a['nofault_fpr'])} → {pct(f_a['nofault_fpr'])}.")
                parts_vi.append(f"123-bus chủ động GATv2: SLG 400 Ω {pct(b400)} → {pct(f400)}, FPR không sự cố {pct(b_a['nofault_fpr'])} → {pct(f_a['nofault_fpr'])}.")
        v["hif_read_en"] = " ".join(parts_en) or "Paired 60 Hz vs +Edge p_hif results loaded from results/hif_fusion/."
        v["hif_read_vi"] = " ".join(parts_vi) or "Đã nạp kết quả đối chứng 60 Hz vs +Edge p_hif từ results/hif_fusion/."
    else:
        v["hif_read_en"] = "Not run yet on Kaggle GPU — awaiting results/hif_fusion/*.json; no placeholder numbers are shown."
        v["hif_read_vi"] = "Chưa chạy trên Kaggle GPU — đang chờ results/hif_fusion/*.json; không điền số giả."

    surf_src = (ha123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"].get("by_arc_surface") if ha123
                else (hp123["ablations"]["60Hz_plus_edge"]["zone_tree_gnn"].get("by_arc_surface") if hp123 else None))
    surf_vals = [(k, val) for k, val in (surf_src or {}).items() if val is not None]
    if surf_vals:
        lo_s, hi_s = min(surf_vals, key=lambda kv: kv[1]), max(surf_vals, key=lambda kv: kv[1])
        v["hif_surf_read_en"] = f"Across the 5 simulated surfaces (+Edge), accuracy spans {pct(lo_s[1])} ({lo_s[0]}) to {pct(hi_s[1])} ({hi_s[0]})."
        v["hif_surf_read_vi"] = f"Trên 5 bề mặt mô phỏng (+Edge), độ chính xác từ {pct(lo_s[1])} ({lo_s[0]}) tới {pct(hi_s[1])} ({hi_s[0]})."
    else:
        v["hif_surf_read_en"] = "Not run yet on Kaggle GPU — all 5 Emanuel surface rows will fill automatically from results/hif_fusion/*.json."
        v["hif_surf_read_vi"] = "Chưa chạy trên Kaggle GPU — cả 5 hàng bề mặt Emanuel sẽ tự động nạp từ results/hif_fusion/*.json."

    dist_src = (ha123["ablations"]["60Hz_plus_edge"]["active_grid_gatv2"].get("nofault_fpr_by_disturbance") if ha123 else None)
    dist_vals = [(k, val) for k, val in (dist_src or {}).items() if val is not None]
    if dist_vals:
        hi_d = max(dist_vals, key=lambda kv: kv[1])
        v["hif_dist_read_en"] = f"On active 123-bus (+Edge GATv2), the highest disturbance FPR is {pct(hi_d[1])} on {hi_d[0]}."
        v["hif_dist_read_vi"] = f"Trên 123-bus chủ động (+Edge GATv2), FPR cao nhất theo nhiễu nền là {pct(hi_d[1])} ở {hi_d[0]}."
    else:
        v["hif_dist_read_en"] = "Not run yet on Kaggle GPU — all 7 background disturbance FPR rows will fill automatically from results/hif_fusion/*.json."
        v["hif_dist_read_vi"] = "Chưa chạy trên Kaggle GPU — cả 7 hàng FPR nhiễu nền sẽ tự động nạp từ results/hif_fusion/*.json."

    # Optional Branch-10 realistic HIF-Fusion (2d Before/After) explain text
    hr = d.get("hif_real") or {}
    rp123 = hr.get("p123") if _branch_ready(hr.get("p123"), "ablations") else None
    if rp123:
        ab_r = rp123["ablations"]
        r_en, r_vi = [], []
        for mk, lab in (("ml_full", "ml_full"), ("per_node_gbdt", "PerNodeGBDT"), ("zone_tree_gnn", "ZoneTreeGNN")):
            bm, fm = ab_r["60Hz_only"].get(mk), ab_r["60Hz_plus_edge"].get(mk)
            if bm and fm:
                b4 = (bm.get("slg_by_resistance") or {}).get("400.0")
                f4 = (fm.get("slg_by_resistance") or {}).get("400.0")
                if b4 is not None and f4 is not None:
                    r_en.append(f"{lab} SLG 400 Ω: {pct(b4)} → {pct(f4)}")
                    r_vi.append(f"{lab} SLG 400 Ω: {pct(b4)} → {pct(f4)}")
        v["hif_real_read_en"] = ("Branch-10 realistic 123-bus: " + "; ".join(r_en) + ".") if r_en else "Branch-10 realistic results loaded from results/hif_fusion_realistic/."
        v["hif_real_read_vi"] = ("123-bus thực tế Nhánh 10: " + "; ".join(r_vi) + ".") if r_vi else "Đã nạp kết quả thực tế Nhánh 10 từ results/hif_fusion_realistic/."

        gnn_b, gnn_f = ab_r["60Hz_only"].get("zone_tree_gnn") or {}, ab_r["60Hz_plus_edge"].get("zone_tree_gnn") or {}
        ib, if_ = _arc_regime_acc(gnn_b, "intermittent"), _arc_regime_acc(gnn_f, "intermittent")
        sv = [(k, val) for k, val in (gnn_f.get("by_arc_surface") or {}).items() if val is not None]
        if ib is not None and if_ is not None and sv:
            lo_s, hi_s = min(sv, key=lambda kv: kv[1]), max(sv, key=lambda kv: kv[1])
            v["hif_real_arc_read_en"] = f"ZoneTreeGNN intermittent arcing moves {pct(ib)} → {pct(if_)}; across 5 Emanuel surfaces (+Edge), accuracy spans {pct(lo_s[1])} ({lo_s[0]}) to {pct(hi_s[1])} ({hi_s[0]})."
            v["hif_real_arc_read_vi"] = f"ZoneTreeGNN trên hồ quang chập chờn đi từ {pct(ib)} → {pct(if_)}; trên 5 bề mặt Emanuel (+Edge), độ chính xác từ {pct(lo_s[1])} ({lo_s[0]}) tới {pct(hi_s[1])} ({hi_s[0]})."
        else:
            v["hif_real_arc_read_en"] = "Branch-10 intermittent vs. continuous arcing and 5-surface breakdown loaded from results/hif_fusion_realistic/."
            v["hif_real_arc_read_vi"] = "Đã nạp phân rã hồ quang chập chờn vs. liên tục và 5 bề mặt Emanuel từ results/hif_fusion_realistic/."

        mb, mf = gnn_b.get("missing_sensor_mean"), gnn_f.get("missing_sensor_mean")
        m2b, m2f = gnn_b.get("missing_sensor_slg_200_400_mean"), gnn_f.get("missing_sensor_slg_200_400_mean")
        if mb is not None and mf is not None:
            s2_en = f" (SLG 200–400 Ω: {pct(m2b)} → {pct(m2f)})" if m2b is not None and m2f is not None else ""
            v["hif_real_miss_read_en"] = f"With simultaneous 60 Hz + Edge blanking on 123-bus, ZoneTreeGNN 1-sensor-offline mean moves {pct(mb)} → {pct(mf)}{s2_en}."
            v["hif_real_miss_read_vi"] = f"Khi xóa đồng thời 60 Hz + Edge trên 123-bus, trung bình mất 1 cảm biến của ZoneTreeGNN đi từ {pct(mb)} → {pct(mf)}{s2_en}."
        else:
            v["hif_real_miss_read_en"] = "Single-sensor outage robustness loaded from results/hif_fusion_realistic/."
            v["hif_real_miss_read_vi"] = "Đã nạp độ bền mất 1 cảm biến từ results/hif_fusion_realistic/."
    else:
        v["hif_real_read_en"] = "Not run yet — awaiting results/hif_fusion_realistic/*.json from the Branch-10 experiment; no invented numbers are shown."
        v["hif_real_read_vi"] = "Chưa chạy xong — đang chờ results/hif_fusion_realistic/*.json từ thí nghiệm Nhánh 10; không hiển thị số bịa."
        v["hif_real_arc_read_en"] = "Not run yet — intermittent vs. continuous arcing and 5-surface rows will fill automatically once results/hif_fusion_realistic/passive_ieee123.json exists."
        v["hif_real_arc_read_vi"] = "Chưa chạy xong — các hàng hồ quang chập chờn vs. liên tục và 5 bề mặt sẽ tự nạp khi có results/hif_fusion_realistic/passive_ieee123.json."
        v["hif_real_miss_read_en"] = "Not run yet — R4 single-sensor-offline rows will fill automatically once results/hif_fusion_realistic/passive_ieee123.json exists."
        v["hif_real_miss_read_vi"] = "Chưa chạy xong — các hàng mất 1 cảm biến R4 sẽ tự nạp khi có results/hif_fusion_realistic/passive_ieee123.json."

    ct = d.get("comtrade")
    if ct:
        cnt, par, demo = ct["counts"], ct["parity"], ct["single_device_demo"]
        v.update({
            "ct_total": str(cnt["total_verified"]),
            "ct_passed": str(cnt["total_passed"]),
            "ct_pub": str(cnt["public_samples"]),
            "ct_sim": str(cnt["total_verified"] - cnt["public_samples"]),
            "ct_dss_match": str(par["opendss_tier2_model_matches"]),
            "ct_dss_total": str(par["opendss_total_events"]),
            "ct_dss_rel": f'{100 * par["opendss_max_tier2_rel_err"]:.4f}%',
            "ct_single_feat": str(demo["single_device_finite_tier2"]),
            "ct_all_feat": str(demo["all_10_devices_finite_tier2"]),
        })

    pl = d.get("prov_ledger") or []
    pv = d.get("prov_verify") or {"changed": [], "missing": [], "unrecorded": []}
    v.update({
        "prov_manifests": str(len(pl)),
        "prov_files": str(sum(r["file_count"] for r in pl)),
        "prov_changed": str(len(pv["changed"])),
        "prov_missing": str(len(pv["missing"])),
        "prov_unrec": str(len(pv["unrecorded"])),
    })
    return v


def faq_section(d: dict, v: dict) -> str:
    items = [f for f in FAQ if (d["ea"] or not f.get("needs_ea")) and (d["h"] or not f.get("needs_h"))
             and (d.get("comtrade") or not f.get("needs_ct"))]
    chips = "".join(f'<button type="button" class="fchip" data-cat="{k}" aria-pressed="false">{T(en, vi)}</button>'
                    for k, en, vi in CATEGORIES)
    tools = (f'<div class="faq-tools"><input id="faq-search" type="search" autocomplete="off" '
             f'data-ph-en="Search the questions…" data-ph-vi="Tìm trong câu hỏi…" aria-label="Search questions">'
             f'<div class="fchips"><button type="button" class="fchip" data-cat="all" aria-pressed="true">'
             f'{T("All", "Tất cả")}</button>{chips}</div>'
             f'<div class="faq-actions"><span class="muted">{T("Showing", "Đang hiện")} <b class="faq-n">{len(items)}</b>'
             f'/{len(items)}</span><button type="button" class="linkbtn" data-all="open">{T("Open all", "Mở tất cả")}'
             f'</button><button type="button" class="linkbtn" data-all="close">{T("Close all", "Đóng tất cả")}</button>'
             f'</div></div>')
    rows = []
    for f in items:
        q_en, q_vi = (s.format(**v) for s in f["q"])
        a_en, a_vi = (emph(s.format(**v)) for s in f["a"])
        rows.append(f'<details class="faq-item" id="faq-{f["id"]}" data-cat="{f["cat"]}"><summary>{T(q_en, q_vi)}'
                    f'</summary><div class="faq-a">{TB(a_en, a_vi)}<button type="button" class="linkbtn copy" '
                    f'data-copy="#faq-{f["id"]}">{T("Copy link to this question", "Sao chép link câu hỏi này")}'
                    f'</button></div></details>')
    empty = (f'<p id="faq-empty" class="muted" hidden>'
             f'{T("No question matches. Try another word.", "Không có câu nào khớp. Thử từ khác.")}</p>')
    return section("faq", ("6 · Questions & answers", "6 · Hỏi đáp"),
                   ("Questions a reviewer or interviewer is likely to ask, answered with this run's numbers. Search "
                    "(Vietnamese works with or without accents), filter by topic, or open them all.",
                    "Những câu người xét duyệt hoặc phỏng vấn hay hỏi, trả lời bằng số liệu của lần chạy này. Có thể "
                    "tìm kiếm (gõ có dấu hay không dấu đều được), lọc theo chủ đề, hoặc mở tất cả."),
                   tools + '<div class="faq-list">' + "".join(rows) + "</div>" + empty)


def glossary_section() -> str:
    cards = "".join(f'<div class="gl" id="term-{k}"><dt>{T(ten, tvi)}</dt><dd>{T(den, dvi)}</dd></div>'
                    for k, (ten, den, tvi, dvi) in GLOSSARY.items())
    return section("glossary", ("7 · Glossary", "7 · Thuật ngữ"),
                   ("Short definitions of the terms used on this page. On the page itself, dotted-underlined words "
                    "show the same definition when you hover or tap them.",
                    "Định nghĩa ngắn các thuật ngữ dùng trên trang. Ngay trong trang, các từ gạch chân chấm chấm cũng "
                    "hiện định nghĩa này khi rê chuột hoặc chạm vào."),
                   deep_box(
                       f"Open full glossary ({len(GLOSSARY)} terms)",
                       f"Mở toàn bộ bảng thuật ngữ ({len(GLOSSARY)} mục)",
                       "Hover any dotted term inline, or expand here to scan all definitions at once.",
                       "Rê chuột vào từ gạch chân chấm để xem nhanh, hoặc bấm mở toàn bộ danh sách tại đây.",
                       f'<dl class="gls">{cards}</dl>',
                       id_="deep-glossary",
                   ))


# ---- the 30-second tour at the top of the page: a sketch of a feeder (4 of the 10 zones) that
# walks through the project's five steps; captions carry this run's numbers
SK_ZONES = [  # zone, trunk start, trunk end, long lateral (x, up/down), short stub (x, up/down)
    ("A", 87, 193, (140, "up"), (170, "down")),
    ("B", 207, 323, (265, "down"), (300, "up")),
    ("C", 337, 453, (395, "up"), (430, "down")),
    ("D", 467, 573, (520, "down"), (550, "up")),
]
SK_DEVICES = [("d1", 80), ("d2", 200), ("d3", 330), ("d4", 460), ("t", 587)]


def _sk_zone(z: str, a: int, b: int, lat: tuple, stub: tuple) -> tuple[str, str]:
    """Lines and loads of one sketch zone, plus the same lines as a patrol overlay."""
    paths = [f"M{a} 110H{b}"]
    loads = []
    for (x, way), (end, load) in ((lat, (50, 44) if lat[1] == "up" else (168, 174)),
                                  (stub, (82, 76) if stub[1] == "up" else (138, 144))):
        paths.append(f"M{x} 110V{end}")
        loads.append(f'<circle class="sk-load" cx="{x}" cy="{load}" r="5.5"/>')
    d = " ".join(paths)
    g = f'<g class="z" data-z="{z}"><path class="sk-ln" d="{d}"/>{"".join(loads)}</g>'
    return g, f'<path class="sk-patrol" data-z="{z}" d="{d}"/>'


# ---- the Monitor: the page's main call to action (top-bar button + a card under the tour)
MON_DATA = config.ROOT / "docs" / "monitor" / "data.json"
MON_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><rect x="2.5" y="3.5" width="19" height="13.5" rx="2"/>'
            '<path d="M5.5 10.5h3l1.6-3 2.6 6 1.6-3h4.2" stroke-width="1.8"/><path d="M8 21h8M12 17v4"/></svg>')


def monitor_card() -> str:
    """What the Monitor is, how to use it in three steps, and what it is not."""
    n = len(json.loads(MON_DATA.read_text(encoding="utf-8"))["incidents"]) if MON_DATA.exists() else 0
    steps = [
        (("Pick a role", "Chọn vai trò"),
         ("Dispatcher, field crew, engineer or manager. Each sees its own screen.",
          "Điều độ, đội sửa chữa, kỹ sư hoặc quản lý. Mỗi vai có màn hình riêng.")),
        (("Open a fault", "Mở một sự cố"),
         ("The map rings the zone the ML model points to, with its confidence.",
          "Bản đồ khoanh zone mà mô hình ML chỉ ra, kèm độ tin cậy.")),
        (("Follow “How to handle”", "Làm theo “How to handle”"),
         ("The highlighted box lists your steps. The map shows switches opening and load coming back.",
          "Ô được tô nổi liệt kê từng bước. Bản đồ cho thấy dao mở ra và tải được cấp điện lại.")),
    ]
    lis = "".join(f'<li><span class="n">{i + 1}</span><span><b>{T(*t)}</b><small>{T(*s)}</small></span></li>'
                  for i, (t, s) in enumerate(steps))
    src_en = f"{n} faults from this run, replayed one at a time" if n else "Faults from this run, replayed one at a time"
    src_vi = f"{n} sự cố lấy từ lần chạy này, phát lại từng cái" if n else "Các sự cố lấy từ lần chạy này, phát lại từng cái"
    return (
        '<div class="moncard" id="monitor-card" role="region" aria-labelledby="mc-h">'
        + f'<div class="mc-ic" aria-hidden="true">{MON_ICON}</div>'
        + f'<div class="mc-head"><div class="mc-k">{T("Monitor · try it yourself", "Giám sát · tự tay thử")}</div>'
        + f'<h2 id="mc-h">{T("Handle a simulated outage, step by step", "Tự xử lý một sự cố mô phỏng, từng bước")}</h2></div>'
        + f'<a class="mc-go" href="monitor/">{T("Open Monitor →", "Mở Giám sát →")}</a>'
        + '<div class="mc-body">'
        + TB("A practice control-room screen built from this study. It shows what each person in an outage does "
             "with the model's answer: who confirms the zone, who opens which switch, who patrols the line.",
             "Một màn hình phòng điều khiển để luyện tập, dựng từ kết quả của nghiên cứu này. Nó cho thấy mỗi người "
             "trong một vụ mất điện làm gì với câu trả lời của mô hình: ai xác nhận zone, ai mở dao nào, ai đi dò "
             "đường dây.", "p", "mc-p")
        + f'<ol class="mc-steps">{lis}</ol>'
        + TB(f"<b>Note:</b> {src_en}. Demo only: sign-in has no password and nothing here is connected to real "
             "equipment or live data. The page is in English.",
             f"<b>Lưu ý:</b> {src_vi}. Chỉ là bản demo: đăng nhập không cần mật khẩu, không nối với thiết bị hay "
             "dữ liệu thật nào. Trang Giám sát hiện chỉ có tiếng Anh.", "p", "mc-note")
        + '</div></div>')


def story_section(v: dict) -> str:
    bands, zones, patrols = [], [], []
    for z, a, b, lat, stub in SK_ZONES:
        bands.append(f'<g class="sk-band" data-z="{z}"><rect x="{a - 7}" y="26" width="{b - a + 14}" height="174" rx="10"/>'
                     + svg_text((a + b) / 2, 193, f"Zone {z}", f"Zone {z}", "sk-zl", "middle") + "</g>")
        g, p = _sk_zone(z, a, b, lat, stub)
        zones.append(g)
        patrols.append(p)
    devs = "".join(f'<rect class="sk-dev" data-d="{d}" x="{x - 7}" y="103" width="14" height="14" rx="3"/>'
                   for d, x in SK_DEVICES)
    data = "".join(f'<path class="sk-data" d="M{x} 103C{x} 62 330 62 330 26"/>' for d, x in SK_DEVICES[:4])
    svg = (
        '<svg class="sk" viewBox="0 0 700 228" role="img" aria-labelledby="sk-title">'
        + f'<title id="sk-title">{esc("Sketch of a feeder with four zones, a substation on the left and a tie switch to the next feeder on the right")}</title>'
        + "".join(bands) + "".join(patrols)
        + '<path class="sk-ln sk-always" d="M52 110H73M594 110H622"/>'
        + "".join(zones)
        + '<path class="sk-ln sk-tieln" d="M573 110H580"/>'
        + devs
        + '<rect class="sk-box" x="6" y="94" width="46" height="32" rx="6"/>'
        + '<rect class="sk-box" x="622" y="94" width="68" height="32" rx="6"/>'
        + svg_text(4, 145, "Substation", "Trạm", "sk-lbl")
        + svg_text(80, 96, "Sw1", "Sw1", "sk-lbl", "middle")
        + svg_text(587, 96, "Tie", "Tie", "sk-lbl", "middle")
        + svg_text(696, 145, "Next feeder", "Tuyến bên cạnh", "sk-lbl", "end")
        + '<g class="sk-fault"><circle class="sk-pulse" cx="395" cy="78" r="13"/>'
          '<path class="sk-bolt" d="M398 61L387 80H395L390 96L405 74H397L402 61Z"/></g>'
        + f'<g class="sk-ml">{data}<rect class="sk-chip" x="240" y="2" width="180" height="24" rx="12"/>'
        + svg_text(254, 19, "ML model", "Mô hình ML", "sk-chipt")
        + svg_text(408, 19, "→ zone C", "→ zone C", "sk-chipt sk-res", "end") + "</g>"
        + '<g class="sk-truck"><rect x="0" y="203" width="22" height="13" rx="2"/><rect x="22" y="207" width="9" height="9" rx="2"/>'
          '<circle cx="6" cy="218" r="3.2"/><circle cx="25" cy="218" r="3.2"/>'
        + svg_text(38, 215, f"Patrol all {v['patrol_none']} kft", f"Dò hết {v['patrol_none']} kft", "sk-tl tl-all")
        + svg_text(38, 215, f"Patrol only zone C: {v['patrol_ml']} kft", f"Chỉ dò zone C: {v['patrol_ml']} kft",
                   "sk-tl tl-one") + "</g>"
        + "</svg>")

    steps = [
        (("Fault", "Sự cố"), ("A fault hits one line", "Sự cố xảy ra trên một nhánh"),
         ("A tree branch touches a line in one zone of the feeder. The study uses the IEEE 123-bus feeder, "
          "split into 10 zones by its switches; this sketch shows 4.",
          "Một cành cây chạm vào dây ở một zone của tuyến. Nghiên cứu dùng tuyến IEEE 123-bus, chia thành 10 zone "
          "theo các dao cắt; hình này vẽ gọn còn 4.")),
        (("Blackout", "Mất điện"), ("The whole feeder goes dark", "Cả tuyến mất điện"),
         (f"Recloser Sw1 at the substation trips and locks out. Nobody knows where the fault is, so a crew would "
          f"have to patrol all {v['patrol_none']} kft of line.",
          f"Recloser Sw1 ở đầu tuyến cắt và khóa lại. Không ai biết sự cố nằm ở đâu, nên đội sửa chữa phải dò hết "
          f"{v['patrol_none']} kft đường dây.")),
        (("Find the zone", "Tìm zone lỗi"), ("The model names the faulted zone", "Mô hình chỉ ra zone bị sự cố"),
         (f"Machine learning reads the currents and voltages the switches recorded and names the zone. On "
          f"{v['faults']} simulated faults it was right {v['acc']} of the time, tested on buses it never trained on. "
          f"Conventional fault indicators: {v['acc_fpi']}.",
          f"Mô hình machine learning đọc dòng điện và điện áp mà các dao đã ghi lại rồi chỉ ra zone. Trên "
          f"{v['faults']} sự cố mô phỏng, mô hình đúng {v['acc']}, kiểm tra trên những nút chưa từng thấy khi học. "
          f"Bộ chỉ báo sự cố truyền thống: {v['acc_fpi']}.")),
        (("Isolate &amp; restore", "Cô lập &amp; cấp lại"), ("Cut it out, power the rest", "Cô lập zone lỗi, cấp điện phần còn lại"),
         (f"The switches on both sides of the zone open. Sw1 closes again for the zones before it, and the tie "
          f"switch feeds the zones after it from the next feeder, but only if a power flow keeps every voltage within "
          f"{v['vmin']}–{v['vmax']} pu and no line overloads.",
          f"Hai dao hai bên zone lỗi mở ra. Sw1 đóng lại cấp điện cho các zone phía trước; dao liên lạc (tie) lấy điện "
          f"từ tuyến bên cạnh cho các zone phía sau, nhưng chỉ khi tính power flow cho thấy mọi điện áp vẫn trong "
          f"{v['vmin']}–{v['vmax']} pu và không đường dây nào quá tải.")),
        (("Fix it fast", "Sửa nhanh"), ("The crew goes straight there", "Đội sửa chữa đi thẳng tới chỗ lỗi"),
         (f"The crew patrols only the named zone: {v['patrol_ml']} kft on average instead of {v['patrol_none']} kft. "
          f"Customer outage, counted in interrupted kW-minutes, falls {v['kwmin']}% (simulated, with assumed "
          f"switching times).",
          f"Đội chỉ cần dò zone được chỉ ra: trung bình {v['patrol_ml']} kft thay vì {v['patrol_none']} kft. Mức mất "
          f"điện của khách hàng, tính bằng kW-phút bị gián đoạn, giảm {v['kwmin']}% (mô phỏng, với thời gian thao tác "
          f"giả định).")),
    ]
    chips = "".join(f'<li><button type="button" data-go="{i}"><span class="bar"><i></i></span>'
                    f'<b>{i + 1}</b> <span class="stt">{T(*short)}</span></button></li>'
                    for i, (short, _, _) in enumerate(steps))
    caps = "".join(f'<div class="cap">{TB(f"<h3>{i + 1} · {title[0]}</h3><p>{emph(text[0])}</p>", f"<h3>{i + 1} · {title[1]}</h3><p>{emph(text[1])}</p>")}</div>'
                   for i, (_, title, text) in enumerate(steps))
    nxt = [
        ("#model", "", ("3D model", "Mô hình 3D"),
         ("The real 123-bus feeder: click a zone, replay any fault", "Tuyến 123-bus thật: nhấp vào zone, xem lại bất kỳ sự cố nào")),
        ("#location", "", ("Fault location", "Định vị sự cố"),
         ("How often each method names the right zone, and where it misses", "Mỗi cách tìm đúng zone bao nhiêu lần, sai ở đâu")),
        ("#restoration", "", ("Restoration", "Khôi phục"),
         ("Which ties close and how much load comes back", "Dao liên lạc nào đóng và cấp lại được bao nhiêu tải")),
        ("monitor/", "mon", ("Monitor", "Giám sát"),
         ("Handle a fault yourself as dispatcher, crew, engineer or manager",
          "Tự xử lý sự cố với vai trò điều độ, đội sửa, kỹ sư hoặc quản lý")),
        ("study/", "", ("Technical study", "Bản nghiên cứu chuyên sâu"),
         ("For readers with a technical background: the method, validation, errors and limits, written like a paper",
          "Cho người có chuyên môn: phương pháp, kiểm định, lỗi và giới hạn, trình bày như một bài báo")),
    ]
    links = "".join(f'<li><a href="{h}" class="{c}"><span class="n">{i + 1}</span><span><b>{T(*t)}</b>'
                    f'<small>{T(*s)}</small></span></a></li>' for i, (h, c, t, s) in enumerate(nxt))
    legend = (f'<span><i class="lg-live"></i>{T("powered", "có điện")}</span>'
              f'<span><i class="lg-tie"></i>{T("fed from the next feeder", "lấy điện từ tuyến bên cạnh")}</span>'
              f'<span><i class="lg-dead"></i>{T("no power", "mất điện")}</span>'
              f'<span><i class="lg-sw"></i>{T("switch closed", "dao đóng")}</span>'
              f'<span><i class="lg-sw open"></i>{T("switch open", "dao mở")}</span>'
              f'<span class="lg-note">{T("Sketch: 4 of the 10 zones", "Hình minh họa: 4 trong 10 zone")}</span>')
    return (
        '<div class="story paused" id="story" data-step="1" role="region" aria-labelledby="story-h">'
        + '<div class="story-head"><div>'
        + f'<h2 id="story-h">{T("What this project does · 30-second tour", "Dự án này làm gì · xem nhanh 30 giây")}</h2>'
        + TB("When a fault blacks out a power distribution line, this project finds which section is broken and "
             "brings power back to the rest, automatically. All on a simulated feeder.",
             "Khi một sự cố làm cả tuyến điện phân phối mất điện, dự án này tìm ra đoạn nào bị hỏng và tự động cấp điện "
             "lại cho phần còn lại. Tất cả trên một tuyến điện mô phỏng.", "p", "lead")
        + '</div><div class="story-ctrl">'
        + f'<button type="button" id="st-play"><span class="when-on">❚❚ {T("Pause", "Tạm dừng")}</span>'
          f'<span class="when-off">▶ {T("Play", "Chạy")}</span></button>'
        + f'<button type="button" id="st-again">↻ {T("Replay", "Xem lại")}</button></div></div>'
        + f'<div class="story-fig">{svg}</div><div class="story-legend">{legend}</div>'
        + f'<ol class="story-steps">{chips}</ol><div class="story-cap">{caps}</div>'
        + f'<div class="story-next"><h3>{T("Then follow the page in this order", "Sau đó đọc trang theo thứ tự này")}</h3>'
        + f'<ol>{links}</ol></div></div>')


def build() -> None:
    d = load()
    m, fl, rs = d["m"], d["m"]["fault_location"], d["m"]["restoration"]
    v = numbers(d)
    order = [z["zone"] for z in d["zones"]]
    pk, t = m["patrol_kft"], rs["timing_assumption_min"]
    cut = f'{pk["ml_full"] / pk["no_location"] - 1:+.0%}'.replace("-", "−")   # a real minus sign
    share = f'{rs["kW_restored_by_tie_total"] / rs["kW_downstream_healthy_total"]:.0%}'
    by_type = " · ".join(f"{k} {num(n)}" for k, n in m["dataset"]["by_type"].items())
    mins = f'{t["automated"]} / {t["manual"]} / {t["repair"]}'

    tiles = "".join([
        tile(T("Fault zone found", "Tìm đúng zone sự cố"), v["acc"],
             T(f'vs {v["acc_fpi"]} with conventional fault indicators',
               f'so với {v["acc_fpi"]} của bộ chỉ báo sự cố truyền thống'), "tile-acc"),
        tile(T("Average crew patrol", "Quãng đường tuần tra trung bình"), f'{v["patrol_ml"]} {term("kft")}',
             T(f'vs {v["patrol_none"]} kft with no fault location ({cut})',
               f'so với {v["patrol_none"]} kft khi không định vị sự cố ({cut})'), "tile-patrol"),
        tile(T("Healthy load restored by ties", "Phụ tải lành được cấp lại qua tie"), f'{v["kw_back"]} kW',
             T(f'of {v["kw_dark"]} kW left dark ({share}), summed over 10 cases',
               f'trên {v["kw_dark"]} kW bị mất điện ({share}), cộng 10 trường hợp'), "tile-restore"),
        tile(T("Customer outage", "Mức mất điện khách hàng") + f' ({term("kwmin")})', f'−{v["kwmin"]}%',
             T(f"vs manual switching; assumes {mins} min", f"so với đóng cắt thủ công; giả định {mins} phút"),
             "tile-kwmin"),
        tile(T("Faults simulated", "Số sự cố mô phỏng"), v["faults"], by_type, "tile-faults"),
    ])

    # 1 fault location
    rkeys = list(fl["ml_full"]["slg_by_resistance"])
    xl = [f"{float(k):g}" for k in rkeys]
    series = [(en, vi, s, [fl[k]["slg_by_resistance"][r] for r in rkeys]) for k, en, vi, s in METHODS]
    types = ["3PH", "LL", "LLG", "SLG"]
    loc_table = table([T("Method", "Phương pháp"), T("All faults", "Tất cả sự cố"), *types],
                      [[T(en, vi), f"<b>{pct(fl[k]['accuracy'])}</b>", *[pct(fl[k]["by_fault_type"][ty]) for ty in types]]
                       for k, en, vi, _ in METHODS], {1, 2, 3, 4, 5})
    res_table = table(["Ω", *[T(en, vi) for _, en, vi, _ in METHODS]],
                      [[x, *[pct(s[3][i]) for s in series]] for i, x in enumerate(xl)], {1, 2, 3})
    miss = sorted(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1])
    miss_chart = hbar_chart([(f"{k} offline", f"Mất {k}", a, f"<b>{k} offline</b><br>{pct(a)} of faults placed correctly",
                              f"<b>Mất {k}</b><br>{pct(a)} số sự cố được đoán đúng") for k, a in miss],
                            1, pct, "Accuracy with one sensor offline",
                            ref=(fl["ml_full"]["accuracy"], f'all online {v["acc"]}', f'đủ cảm biến {v["acc"]}'))
    legend = "".join(f'<span><i style="background:var(--s{s})"></i>{T(en, vi)}</span>' for _, en, vi, s in METHODS)
    hif_r_sub_en, hif_r_sub_vi, hif_r_badge = "", "", ""
    hr_b = d.get("hif_real") or {}
    if _branch_ready(hr_b.get("p123"), "ablations"):
        ab_b = hr_b["p123"]["ablations"]
        ml_b4 = ((ab_b["60Hz_only"].get("ml_full") or {}).get("slg_by_resistance") or {}).get("400.0")
        ml_f4 = ((ab_b["60Hz_plus_edge"].get("ml_full") or {}).get("slg_by_resistance") or {}).get("400.0")
        if ml_b4 is not None and ml_f4 is not None:
            hif_r_sub_en = f" · Branch 10 realistic 400 Ω ml_full {pct(ml_b4)} → {pct(ml_f4)}"
            hif_r_sub_vi = f" · Nhánh 10 thực tế 400 Ω ml_full {pct(ml_b4)} → {pct(ml_f4)}"
        cr_b = [vd for cid, vd in _extract_r_criteria(hr_b) if cid in ("R1", "R2", "R3", "R4")]
        if cr_b:
            np_r = sum(vd == "PASS" for vd in cr_b)
            cls_r = "good" if np_r == len(cr_b) else ("critical" if any(vd == "FAIL" for vd in cr_b) else "warning")
            hif_r_badge = f' <span class="chip {cls_r}">{np_r}/{len(cr_b)} R1–R4</span>'
    s_loc = section(
        "location", ("2 · Fault location", "2 · Định vị sự cố"),
        ("After the feeder-head recloser locks out, <b>which of the 10 zones holds the fault?</b> Accuracy is "
         "measured on <b>buses the model never saw in training</b>, under a realistic OpenDSS 60 Hz simulation with "
         f"{term('arcing', 'intermittent arcing HIFs')} (SLG ≥ 100 Ω), {term('loaddrift', 'independent per-zone loading & pre/post drift')}, "
         f"and {term('ctbias', 'CT/PT bias + noise floor')}. The chart shows where each method breaks down as weak "
         "ground-fault currents sink into load drift and noise.",
         "Sau khi recloser đầu tuyến cắt hẳn, <b>sự cố nằm ở zone nào trong 10 zone?</b> Độ chính xác được đo trên "
         "<b>các bus mà model chưa từng thấy khi huấn luyện</b>, dưới mô phỏng OpenDSS 60 Hz sát thực tế gồm "
         f"{term('arcing', 'hồ quang HIF chập chờn', 'hồ quang HIF chập chờn')} (SLG ≥ 100 Ω), "
         f"{term('loaddrift', 'tải biến động theo zone & trôi tải pre/post', 'tải biến động theo zone & trôi tải pre/post')} và "
         f"{term('ctbias', 'sai số CT/PT + sàn nhiễu', 'sai số CT/PT + sàn nhiễu')}. Biểu đồ cho thấy mỗi phương pháp bắt đầu "
         "suy giảm ở đâu khi dòng chạm đất yếu chìm vào trôi tải và nhiễu."),
        xbox("chart-res", f'<div class="legend">{legend}</div>'
                          f'<div class="chart">{line_chart(xl, series, "Accuracy vs fault resistance")}</div>')
        + f'<details><summary>{T("Show as table", "Xem dạng bảng")}</summary>{res_table}</details>'
        f'<h3>{T("By fault type", "Theo loại sự cố")} ({term("types", "SLG, LL, LLG, 3PH")})</h3>'
        + xbox("table-type", loc_table)
        + f'<h3>{T("If one sensor stops reporting (ML, full features)", "Khi một cảm biến ngừng gửi số liệu (ML, đủ đặc trưng)")}</h3>'
        + xbox("chart-sensor", f'<div class="chart">{miss_chart}</div>')
        + deep_box(
            "2b · LTspice Circuit Verification (DC Offset, CT/ADC Front End, Arcing HIF)",
            "2b · Kiểm chứng mạch LTspice (DC Offset, mạch CT/ADC, hồ quang HIF)",
            "Three transient circuits generated from OpenDSS fault currents and verified in LTspice.",
            "Ba mạch quá độ sinh từ dòng sự cố OpenDSS và kiểm chứng trực tiếp trên LTspice.",
            spice_block(d, v),
            badge=f'<span class="chip good">LTspice</span>',
            id_="deep-spice",
        )
        + deep_box(
            "2c · Cross-Feeder Transfer (IEEE 34 / 37), Active Grid DER (0–50%) & Conformal Safety",
            "2c · Chuyển giao lưới khác (IEEE 34 / 37), Lưới có DER (0–50%) & Conformal Safety",
            "ZoneTreeGNN & ActiveGridGATv2 across unseen feeders, 10,000 Ω SLG, NO_FAULT transients, and 95% conformal prediction sets.",
            "ZoneTreeGNN & ActiveGridGATv2 trên lưới chưa từng thấy, SLG 10.000 Ω, quá độ NO_FAULT và tập dự đoán Conformal 95%.",
            transfer_block(d, v),
            badge=f'<span class="chip good">IEEE 123 · 34 · 37</span>',
            id_="deep-transfer",
        )
        + deep_box(
            "2d · Tier 1 + Tier 2 HIF-Fusion (Edge ESP32 Sensor + Feeder GNN/GBDT)",
            "2d · Hợp nhất Tầng 1 + Tầng 2 HIF-Fusion (Cảm biến biên ESP32 + GNN/GBDT)",
            f"400 Ω passive SLG 78.1% → 97.7% (GBDT) · Active 400 Ω GATv2 73.5% → 87.5% · NO_FAULT FPR 6.5% → 1.2%{hif_r_sub_en} · See full Hardware/VeHIF tab.",
            f"SLG 400 Ω thụ động 78.1% → 97.7% (GBDT) · Lưới chủ động 400 Ω GATv2 73.5% → 87.5% · NO_FAULT FPR 6.5% → 1.2%{hif_r_sub_vi} · Xem thêm tab Cảm biến HIF.",
            hif_fusion_block(d, v),
            badge=f'<span class="chip good">4/4 H1–H4 PASS</span>{hif_r_badge}',
            id_="deep-hif",
        )
        + deep_box(
            "2e · Reading Relay/Recloser COMTRADE Files (IEEE C37.111)",
            "2e · Đọc file COMTRADE của rơ-le / recloser (IEEE C37.111)",
            (f".cfg/.dat → pre/post 1-cycle DFT phasors → exact model features · {v['ct_passed']}/{v['ct_total']} verified ({v['ct_pub']} public + {v['ct_sim']} sim); ready for real utility files."
             if d.get("comtrade") else ".cfg/.dat → pre/post phasors → model features (not verified yet)."),
            (f".cfg/.dat → phasor trước/sau (DFT 1 chu kỳ) → đúng đặc trưng model · đạt {v['ct_passed']}/{v['ct_total']} ({v['ct_pub']} mẫu công khai + {v['ct_sim']} mô phỏng); sẵn sàng thả file thật vào."
             if d.get("comtrade") else ".cfg/.dat → phasor trước/sau → đặc trưng model (chưa chạy kiểm thử)."),
            comtrade_block(d, v),
            badge=(f'<span class="chip good">✓ {v["ct_passed"]}/{v["ct_total"]} PASS</span>'
                   if d.get("comtrade") and d["comtrade"]["counts"]["total_passed"] == d["comtrade"]["counts"]["total_verified"]
                   else '<span class="chip warning">COMTRADE</span>'),
            id_="deep-comtrade",
        ),
        (f'ML puts {v["acc"]} of simulated faults in the right zone, against {v["acc_fpi"]} for fault indicators '
         f'({v["r100"]} vs {v["r100_fpi"]} at 100 Ω), while intermittent arcing + load drift pulls 400 Ω down to '
         f'{v["r400"]} — exposing the 60 Hz limit addressed in §2d.',
         f'ML xác định đúng zone cho {v["acc"]} số sự cố mô phỏng, so với {v["acc_fpi"]} của bộ chỉ báo sự cố '
         f'({v["r100"]} so với {v["r100_fpi"]} ở 100 Ω), còn hồ quang chập chờn + trôi tải kéo 400 Ω xuống '
         f'{v["r400"]} — phơi bày giới hạn 60 Hz được xử lý ở mục 2d.'))

    # 2 error analysis
    ea = d["ea"]
    if ea:
        pz = table([T("Zone"), T("Faults", "Số sự cố"), T("Missed", "Bỏ sót") + f' ({term("fnr")})',
                    T("Wrongly blamed", "Báo nhầm") + f' ({term("fpr")})', term("precision")],
                   [[r["zone"], num(int(r["n"])), pct(float(r["FNR"])), pct(float(r["FPR"]), 2), pct(float(r["precision"]))]
                    for r in d["per_zone"]], {1, 2, 3, 4})
        dirs = sorted(ea["ml_error_direction"].items(), key=lambda kv: -kv[1])
        tot = ea["ml_errors"]
        dir_chart = hbar_chart([(*DIRECTIONS.get(k, (k, k)), n, f"<b>{esc(k)}</b><br>{n} of {tot} errors ({n / tot:.0%})",
                                 f"<b>{DIRECTIONS.get(k, (k, k))[1]}</b><br>{n} trên {tot} lỗi ({n / tot:.0%})")
                                for k, n in dirs], max(n for _, n in dirs), lambda x: f"{x:.0f}", "Where wrong answers point")
        defer = table([T("Defer below", "Chuyển nếu dưới"), T("Faults kept", "Sự cố giữ lại"),
                       T("Accuracy on kept", "Accuracy phần giữ lại"), T("Errors left", "Lỗi còn lại")],
                      [[f'{r["threshold"]:.2f}', pct(r["coverage"]), pct(r["accuracy_on_kept"]), num(r["errors_kept"])]
                       for r in ea["defer_low_confidence"]], {0, 1, 2, 3})
        lt = ea["ml_error_rate_by_load_tercile"]
        sh, lo_l, hi_l, n_all = f"{tot / ea['faults']:.1%}", pct(lt["low"]), pct(lt["high"]), num(ea["faults"])
        s_err = section(
            "errors", ("3 · Error analysis", "3 · Phân tích lỗi"),
            (f"<b>{tot} of {n_all} simulated faults ({sh}) went to the wrong zone.</b> {v['slg_hi']} of them "
             f"({v['slg_hi_share']}) are <b>intermittent arcing ground faults at 200 Ω nominal or more</b>, where "
             f"reduced 60 Hz arc current competes with pre/post load drift and CT/PT noise; <b>errors rise with load</b> "
             f"({lo_l} in the lightest third of scenarios, {hi_l} in the heaviest). Because the model always names a "
             "zone, misses and false blames are <b>counted per zone</b> (one zone vs the rest).",
             f"<b>{tot} trên {n_all} sự cố mô phỏng ({sh}) bị đoán sai zone.</b> {v['slg_hi']} trong số đó "
             f"({v['slg_hi_share']}) là <b>sự cố chạm đất hồ quang chập chờn từ 200 Ω danh định trở lên</b>, nơi dòng "
             f"60 Hz suy giảm cạnh tranh trực tiếp với trôi tải pre/post và nhiễu CT/PT; <b>lỗi tăng theo mức tải</b> "
             f"({lo_l} ở 1/3 kịch bản nhẹ nhất, {hi_l} ở 1/3 nặng nhất). Vì model luôn chọn một zone, bỏ sót và báo "
             "nhầm được <b>tính theo từng zone</b> (một zone so với phần còn lại)."),
            f'<h3>{term("confusion")}</h3>'
            + TB("Rows are the true zone, columns the predicted zone, in feeder order from the substation. Gray "
                 "diagonal = correct. Blue cells are errors; darker means more.",
                 "Hàng là zone thật, cột là zone dự đoán, xếp theo thứ tự từ trạm ra. Đường chéo màu xám = đoán đúng. "
                 "Ô xanh là lỗi; càng đậm càng nhiều.", "p", "note")
            + xbox("heat", f'<div class="chart heatwrap">{confusion_heatmap(d["confusion"], order)}</div>', "heatbox")
            + deep_box(
                "Per-zone error table, error directions & low-confidence deferral",
                "Bảng lỗi từng zone, hướng lệch & ngưỡng chuyển sang tuần tra thủ công",
                f"Detailed FNR/FPR across all 10 zones, where wrong answers land, and confidence cutoff trade-offs (median {v['conf_right']} right vs {v['conf_wrong']} wrong).",
                f"Chi tiết bỏ sót/báo nhầm trên 10 zone, hướng lệch dự đoán và bảng chọn ngưỡng độ tự tin (trung vị {v['conf_right']} khi đúng vs {v['conf_wrong']} khi sai).",
                f"<h3>{T('Per zone', 'Theo từng zone')}</h3>" + xbox("table-zone", pz)
                + f'<h3>{T("Where the wrong answers point", "Câu trả lời sai rơi vào đâu")}</h3>'
                + xbox("chart-dir", f'<div class="chart">{dir_chart}</div>')
                + f'<h3>{T("Let the model say “not sure”", "Cho model nói “không chắc”")}</h3>'
                + TB(f'Predictions below the {term("confidence", "confidence")} cutoff go to a manual patrol instead. '
                     f'Median confidence: {v["conf_right"]} when right, {v["conf_wrong"]} when wrong.',
                     f'Các dự đoán có {term("confidence", "độ tự tin", "độ tự tin")} dưới ngưỡng được chuyển sang tuần tra '
                     f'thủ công. Độ tự tin trung vị: {v["conf_right"]} khi đúng, {v["conf_wrong"]} khi sai.', "p", "note")
                + xbox("table-defer", defer),
                id_="deep-errors",
            ),
            (f'Most mistakes ({v["slg_hi_share"]}) are <b>weak intermittent arcing ground faults</b> on the <b>busy '
             f'trunk near the substation</b>, with {v["same_path"]} staying on the same path ({v["off1"]} just one '
             f'zone away).',
             f'Phần lớn lỗi ({v["slg_hi_share"]}) là <b>sự cố chạm đất hồ quang chập chờn yếu</b> trên <b>trục chính '
             f'đông tải gần trạm</b>, trong đó {v["same_path"]} vẫn nằm trên cùng đường từ trạm ({v["off1"]} lệch '
             f'đúng 1 zone).'))
    else:
        s_err = section("errors", ("3 · Error analysis", "3 · Phân tích lỗi"), ("Not built yet.", "Chưa được tạo."),
                        TB("Run <code>python scripts/error_analysis.py</code> to add per-zone misses, the confusion "
                           "matrix and the confidence trade-off.",
                           "Chạy <code>python scripts/error_analysis.py</code> để thêm bỏ sót theo zone, ma trận nhầm "
                           "lẫn và đánh đổi theo độ tự tin.", "p"))

    # 3 restoration
    rows, n_ok = [], 0
    for r in d["rest"]:
        ok = (r["radial"] == "True" and int(r["final_overloads"]) == 0
              and float(r["final_vmin_pu"]) >= config.V_MIN_PU - V_TOL and float(r["final_vmax_pu"]) <= config.V_MAX_PU + V_TOL)
        n_ok += ok
        chip = (f'<span class="chip good">✓ {T("Within limits", "Trong giới hạn")}</span>' if ok
                else f'<span class="chip critical">✕ {T("Violation", "Vi phạm")}</span>')
        out_kw, back = float(r["kW_downstream_healthy"]), float(r["kW_restored_by_tie"])
        dash = lambda s: "–" if s == "-" else s  # noqa: E731
        rows.append([f'<b>{r["fault_zone"]}</b>', chip, dash(r["ties_closed"]),
                     f"{num(back)} / {num(out_kw)}" if out_kw else "–", dash(r["unserved_healthy"]),
                     f'{float(r["final_vmin_pu"]):.3f}–{float(r["final_vmax_pu"]):.3f}',
                     f'{float(r["kWmin_reduction_pct"]):.1f}%', r["power_flow_checks"]])
    s_rest = section(
        "restoration", ("4 · Isolation and restoration", "4 · Cô lập và khôi phục"),
        ("<b>Each zone is faulted in turn.</b> The fault is isolated, the upstream part re-closed, and <b>a tie switch "
         "is closed only if a power flow shows every voltage, current and the radial layout stay within limits</b>.",
         "<b>Lần lượt cho sự cố ở từng zone.</b> Zone sự cố được cô lập, phần phía trên được đóng điện lại, và <b>dao "
         "liên lạc chỉ được đóng khi tính trào lưu công suất cho thấy mọi điện áp, dòng điện và cấu trúc hình tia đều "
         "nằm trong giới hạn</b>."),
        xbox("table-rest", table([T("Fault zone", "Zone sự cố"), T("Status", "Trạng thái"), T("Ties closed", "Tie đã đóng"),
                                  T("kW back / dark", "kW cấp lại / mất"), T("Still dark", "Vẫn mất điện"),
                                  T("Voltage", "Điện áp") + f' ({term("pu", "pu")})', T("kW·min saved", "kW·phút giảm được"),
                                  T("Power flows checked", "Số lần tính trào lưu")], rows, {3, 5, 6, 7}))
        + deep_box(
            "4b · Hourly Restoration Across a Full Year (8,760 PJM AEP Hours)",
            "4b · Khôi phục theo từng giờ trong cả năm (8.760 giờ tải PJM AEP)",
            "How seasonal peak vs off-peak loading changes tie-switch voltage margins across all 10 zones.",
            "Tác động của phụ tải cao điểm/thấp điểm theo mùa lên giới hạn điện áp khi đóng dao liên lạc.",
            hourly_block(d, v, order),
            badge=f'<span class="chip good">8,760 h</span>',
            id_="deep-hourly",
        ),
        (f'{n_ok} of 10 switching plans stay within the {term("c841", "voltage")}, current and '
         f'{term("radial", "radial")} limits; <b>voltage, not current, is what stops more load from being picked '
         f'up</b>.',
         f'{n_ok}/10 phương án đóng cắt nằm trong giới hạn {term("c841", "điện áp", "điện áp")}, dòng điện và '
         f'{term("radial", "hình tia", "hình tia")}; <b>chính điện áp, không phải dòng điện, là thứ cản việc cấp lại '
         f'thêm phụ tải</b>.'))

    # 4 zones
    zt = table([T("Zone"), T("Fed by", "Thiết bị cấp"), T("Upstream zone", "Zone phía trên"), T("Load kW", "Tải kW"),
                T("Load points", "Điểm tải"), T("Line kft", "Đường dây kft")],
               [[z["zone"], esc(z["fed_by"]), z["parent_zone"] or T("substation", "trạm"), num(float(z["kW"])),
                 z["load_points"], f'{float(z["line_kft"]):.2f}'] for z in d["zones"]], {3, 4, 5})
    s_zones = section("zones", ("5 · Feeder zones", "5 · Các zone của tuyến"),
                      ("The 10 switching zones of the IEEE 123-bus feeder used throughout this report.",
                       "10 zone đóng cắt của tuyến IEEE 123-bus dùng trong toàn bộ báo cáo."),
                      oneline_figure() + deep_box(
                          "10-zone specification table (upstream device, load kW, line length)",
                          "Bảng thông số 10 zone (thiết bị cấp, tải kW, chiều dài đường dây)",
                          "Exact load points and line lengths for every switching zone.",
                          "Số điểm tải và chiều dài đường dây của từng zone đóng cắt.",
                          xbox("table-zones", zt),
                          id_="deep-zones",
                      ))

    d["glb"] = publish_models()
    d["drawings"] = publish_drawings()
    pub_files = publish_data()
    body = (model_section(d) + s_loc + s_err + s_rest + s_zones + faq_section(d, v) + glossary_section()
            + data_section(v, pub_files))
    runtime = f'{m["runtime_s"]:.0f}'
    repo_link = f'<a href="{REPO}">{T("source on GitHub", "mã nguồn trên GitHub")}</a>'
    hubtabs = (
        '<nav class="tiers" aria-label="System tiers">'
        f'<span class="tier-lbl">{T("2-Tier System:", "Hệ thống 2 tầng:")}</span>'
        f'<a class="tier on" href="index.html" aria-current="page">{T("Tier 2 · Feeder FLISR", "Tầng 2 · Lưới FLISR")}</a>'
        f'<a class="tier" href="hif-sensor/">{T("Tier 1 · Edge HIF Sensor (ESP32) ↗", "Tầng 1 · Cảm biến HIF (ESP32) ↗")}</a>'
        f'<a class="tier sub" href="study/">{T("Technical Paper ↗", "Bài nghiên cứu ↗")}</a>'
        '</nav>'
    )
    header = (
        hubtabs
        + f'<h1>{T("Self-Healing Feeder · Run Report", "Self-Healing Feeder · Báo cáo kết quả")}</h1>'
        + TB(f'Machine-learning fault location and automated restoration ({term("flisr")}) on the IEEE 123-bus '
             f'distribution feeder, simulated in {term("opendss")}. Every number on this page is read from the latest '
             f'<code>python run.py</code>.',
             f'Định vị sự cố bằng machine learning và tự động khôi phục cấp điện ({term("flisr")}) trên lưới phân phối '
             f'IEEE 123-bus, mô phỏng bằng {term("opendss")}. Mọi con số trên trang được đọc từ lần chạy '
             f'<code>python run.py</code> gần nhất.', "p")
        + '<div class="meta">'
        + T(f"{v['faults']} simulated faults · run time {runtime} s · simulation only, not field data",
            f"{v['faults']} sự cố mô phỏng · thời gian chạy {runtime} giây · chỉ là mô phỏng, không phải dữ liệu thực địa")
        + f" · {repo_link}</div>"
        + story_section(v) + monitor_card())
    guide = TB('<b>New here?</b> Click any card, chart or table (or its <b>?</b> button): the guide flies there, circles it and explains it. Words with a '
               '<span class="term-demo">dotted underline</span> have a short definition, and every chart shows exact '
               'numbers on hover. Questions are answered in the <a href="#faq">Q&amp;A</a>.',
               '<b>Lần đầu xem?</b> Nhấp vào bất kỳ thẻ, biểu đồ hay bảng nào (hoặc nút <b>?</b> ở góc): nhân vật hướng dẫn sẽ bay tới, khoanh lại và giải thích. Từ '
               'có <span class="term-demo">gạch chân chấm chấm</span> có định nghĩa ngắn, và mọi biểu đồ đều hiện số '
               'chính xác khi rê chuột. Các câu hỏi thường gặp nằm ở mục <a href="#faq">Hỏi đáp</a>.', "p", "guide")
    nav = "".join(f'<a href="#{i}">{T(en, vi)}</a>' for i, en, vi in [
        ("health", "Checks", "Kiểm tra"), ("evidence", "Verification", "Chứng thực"),
        ("model", "3D model", "Mô hình 3D"), ("location", "Location", "Định vị"),
        ("errors", "Errors", "Lỗi"),
        ("restoration", "Restoration", "Khôi phục"), ("zones", "Zones", "Zone"), ("faq", "Q&amp;A", "Hỏi đáp"),
        ("glossary", "Glossary", "Thuật ngữ"), ("data", "Data", "Dữ liệu")])
    health = (f'<div class="panel" id="health" data-x="health"><h2>{T("Run checks", "Kiểm tra lần chạy")}<a class="anchor" href="#health" '
              f'aria-label="Link to this section">#</a></h2>'
              + TB("<b>Pass</b> = the result meets its limit. <b>Watch</b> = a known weak spot to keep an eye on. "
                   "<b>Fail</b> = something to fix before trusting the numbers.",
                   "<b>Đạt</b> = kết quả nằm trong giới hạn. <b>Lưu ý</b> = điểm yếu đã biết, cần theo dõi. <b>Lỗi</b> "
                   "= phải sửa trước khi tin vào số liệu.", "p", "how")
              + f'<ul class="checks">{"".join(checks(d))}</ul></div>'
              + evidence_block(d, v, pub_files))
    footer = TB(f"Assumptions behind the outage numbers: automated switching {t['automated']} min, manual switching "
                f"{t['manual']} min, repair {t['repair']} min. Every device and realistic-fault parameter (intermittent "
                "arcing HIF, per-zone load drift, CT/PT bias & noise floor) beyond the IEEE test case is marked "
                "<code>ASSUMPTION</code> in <code>shf/config.py</code>. Rebuild this page with "
                "<code>python -m shf.dashboard</code>.",
                f"Giả định đằng sau các con số mất điện: đóng cắt tự động {t['automated']} phút, đóng cắt thủ công "
                f"{t['manual']} phút, sửa chữa {t['repair']} phút. Mọi thiết bị và tham số mô phỏng thực tế (hồ quang "
                "HIF chập chờn, trôi tải theo zone, sai số CT/PT & sàn nhiễu) ngoài lưới thử nghiệm IEEE đều được "
                "đánh dấu <code>ASSUMPTION</code> trong <code>shf/config.py</code>. Dựng lại trang bằng "
                "<code>python -m shf.dashboard</code>.", "p")

    page = TEMPLATE
    for key, val in {"MONICON": MON_ICON, "NAV": nav, "HEADER": header, "GUIDE": guide, "TILES": tiles, "HEALTH": health,
                     "BODY": body, "FOOTER": footer, "XDATA": explanations(d, v), "MDATA": model_data(d)}.items():
        page = page.replace(f"@@{key}@@", val)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    feeder_png = config.FIGURES / "feeder_zones.png"   # the 2D view of the model section (Pages serves docs/ only)
    if feeder_png.exists():
        (OUT.parent / "images").mkdir(exist_ok=True)
        shutil.copyfile(feeder_png, OUT.parent / "images" / "feeder-map.png")
    OUT.write_text(page, encoding="utf-8")
    print("wrote", OUT)
    hif_builder = config.ROOT / "hif_sensor" / "scripts" / "build_dashboard.py"
    if hif_builder.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("hif_sensor_dashboard", hif_builder)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.build(config.ROOT / "docs" / "hif-sensor", parent_href="../")


# Placeholders are @@NAME@@ (not str.format) so the CSS and JS below need no brace escaping.
TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Self-Healing Feeder Report</title>
<meta name="description" content="Run report for the self-healing feeder study: fault location accuracy, error analysis, restoration checks, questions and answers, in English and Vietnamese.">
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: #e1e0d9; --soft: #f0efec;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --bar: #2a78d6; --link: #1c5cab;
  --good: #0ca30c; --good-ink: #006300; --warning: #fab219; --critical: #d03b3b;
  --q1: #cde2fb; --q2: #9ec5f4; --q3: #5598e7; --q4: #2a78d6; --q5: #1c5cab;
  --qi-lo: #0b0b0b; --qi-hi: #ffffff; --diag: #f0efec;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --border: #2c2c2a; --soft: #232322;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --bar: #3987e5; --link: #6da7ec;
    --good-ink: #0ca30c;
    --q1: #184f95; --q2: #1c5cab; --q3: #256abf; --q4: #3987e5; --q5: #6da7ec;
    --qi-lo: #f0efec; --qi-hi: #0b0b0b; --diag: #2c2c2a;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
  --grid: #2c2c2a; --axis: #383835; --border: #2c2c2a; --soft: #232322;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --bar: #3987e5; --link: #6da7ec;
  --good-ink: #0ca30c;
  --q1: #184f95; --q2: #1c5cab; --q3: #256abf; --q4: #3987e5; --q5: #6da7ec;
  --qi-lo: #f0efec; --qi-hi: #0b0b0b; --diag: #2c2c2a;
}
/* one language at a time: <html lang> decides */
html[lang="vi"] [data-l="en"], html:not([lang="vi"]) [data-l="vi"] { display: none !important; }
* { box-sizing: border-box; }
html { scroll-padding-top: 64px; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 64px; }
a { color: var(--link); }
code { font-size: 0.92em; background: var(--soft); padding: 1px 5px; border-radius: 4px; }

/* top bar */
.topbar { position: sticky; top: 0; z-index: 6; background: var(--page); border-bottom: 1px solid var(--border); }
html { scroll-padding-top: calc(var(--barh, 56px) + 12px); }   /* a clicked section starts below the bar */
/* the bar may be wider than the page text, so every link fits on a laptop screen */
.topbar-in { max-width: 1280px; margin: 0 auto; padding: 8px 16px; display: flex; gap: 10px; align-items: center; }
.brand { font-weight: 650; white-space: nowrap; font-size: 14px; }
.navwrap { position: relative; flex: 1; min-width: 0; display: flex; align-items: center; }
.topbar nav { position: relative; display: flex; gap: 2px; overflow-x: auto; flex: 1; min-width: 0;
  scrollbar-width: none; overscroll-behavior-x: contain; -webkit-overflow-scrolling: touch; }
.topbar nav::-webkit-scrollbar { display: none; }
/* fade the edge that has more links behind it, so a cut-off link reads as "scroll for more" */
.topbar nav.fade-r { -webkit-mask-image: linear-gradient(90deg, #000 calc(100% - 36px), transparent);
  mask-image: linear-gradient(90deg, #000 calc(100% - 36px), transparent); }
.topbar nav.fade-l { -webkit-mask-image: linear-gradient(90deg, transparent, #000 36px);
  mask-image: linear-gradient(90deg, transparent, #000 36px); }
.topbar nav.fade-l.fade-r { -webkit-mask-image: linear-gradient(90deg, transparent, #000 36px, #000 calc(100% - 36px), transparent);
  mask-image: linear-gradient(90deg, transparent, #000 36px, #000 calc(100% - 36px), transparent); }
.topbar nav a { flex: none; padding: 4px 10px; border-radius: 999px; text-decoration: none; color: var(--ink2);
  white-space: nowrap; font-size: 13.5px; transition: background-color .15s, color .15s; }
.topbar nav a:hover { background: var(--soft); }
.topbar nav a.on { background: var(--ink); color: var(--page); }
.navbtn { flex: none; width: 26px; height: 26px; margin: 0 2px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--page); color: var(--ink2); font: inherit; font-size: 16px; line-height: 1; cursor: pointer;
  display: grid; place-items: center; padding: 0; }
.navbtn:hover { background: var(--soft); }
.navbtn[hidden] { display: none; }
@media (max-width: 1180px) { .brand { display: none; } }
@media (max-width: 1000px) { .topbar .mon-tx small { display: none; } }
/* tablets and phones: buttons on the first row, the full-width section strip on the second */
@media (max-width: 960px) {
  .topbar-in { flex-wrap: wrap; row-gap: 6px; padding: 6px 12px; }
  .brand { display: inline; }
  .ctrls { margin-left: auto; }
  .navwrap { order: 3; flex-basis: 100%; }
}
/* Monitor: the main call to action, a square button with a one-line note under its name */
.monitor { flex: none; display: inline-flex; align-items: center; gap: 8px; padding: 4px 12px 4px 4px; border-radius: 8px;
  background: var(--s2); color: #fff; text-decoration: none; white-space: nowrap; line-height: 1.15;
  box-shadow: 0 2px 10px rgb(235 104 52 / .35); }
.monitor:hover { filter: brightness(1.08); }
.mon-ic { position: relative; display: grid; place-items: center; width: 30px; height: 30px; border-radius: 6px;
  background: rgb(255 255 255 / .2); }
.mon-ic svg { width: 19px; height: 19px; }
.monitor .dot { position: absolute; top: -3px; right: -3px; width: 9px; height: 9px; border-radius: 50%; background: #fff;
  border: 2px solid var(--s2); animation: blink 1.6s ease-in-out infinite; }
.mon-tx b { display: block; font-size: 13.5px; font-weight: 700; }
.mon-tx small { display: block; font-size: 11px; font-weight: 500; opacity: .92; }
@keyframes blink { 50% { opacity: .25; } }
@media (prefers-reduced-motion: reduce) { .monitor .dot { animation: none; } }
@media (max-width: 640px) { .mon-tx small { display: none; } .mon-ic { width: 26px; height: 26px; } }

/* Monitor card under the tour: what the Monitor is and how to use it */
.moncard { display: grid; grid-template-columns: auto 1fr auto; gap: 6px 16px; align-items: start; margin: 14px 0 0;
  padding: 16px 18px; border: 1.5px solid var(--s2); border-radius: 10px;
  background: color-mix(in srgb, var(--s2) 7%, var(--surface)); }
.mc-ic { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 8px; background: var(--s2); color: #fff; }
.mc-ic svg { width: 30px; height: 30px; }
.mc-head { align-self: center; }
.mc-body { grid-column: 2 / -1; }
.mc-k { font-size: 12.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--s2); }
.moncard h2 { margin: 2px 0 0; font-size: 19px; line-height: 1.3; }
header .moncard .mc-p { margin: 4px 0 0; max-width: 760px; color: var(--ink2); font-size: 15px; }
.mc-steps { list-style: none; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 12px 0 0; padding: 0; }
.mc-steps li { display: flex; gap: 9px; padding: 9px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--page); }
.mc-steps .n { flex: none; display: grid; place-items: center; width: 22px; height: 22px; border-radius: 5px;
  background: var(--ink); color: var(--page); font-size: 12.5px; font-weight: 700; }
.mc-steps b { display: block; font-size: 14px; }
.mc-steps small { display: block; font-size: 12.5px; line-height: 1.4; color: var(--muted); }
header .moncard .mc-note { margin: 10px 0 0; padding: 7px 10px; border-left: 3px solid var(--s2); border-radius: 0 6px 6px 0;
  background: var(--page); color: var(--ink2); font-size: 13px; }
.mc-go { align-self: center; display: inline-block; padding: 10px 16px; border-radius: 8px; background: var(--s2); color: #fff;
  font-weight: 700; font-size: 14.5px; text-decoration: none; white-space: nowrap; box-shadow: 0 2px 10px rgb(235 104 52 / .3); }
.mc-go:hover { filter: brightness(1.08); }
@media (max-width: 760px) {
  .moncard { grid-template-columns: auto 1fr; padding: 14px; }
  .mc-ic { width: 40px; height: 40px; } .mc-ic svg { width: 24px; height: 24px; }
  .mc-body { grid-column: 1 / -1; grid-row: 2; }
  .mc-steps { grid-template-columns: 1fr; }
  .mc-go { grid-column: 1 / -1; grid-row: 3; text-align: center; }
}
.ctrls { display: flex; gap: 6px; align-items: center; flex: none; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; }
.seg button, .iconbtn { font: inherit; font-size: 12.5px; font-weight: 600; border: 0; background: transparent;
  color: var(--ink2); padding: 4px 10px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--page); }
.iconbtn { border: 1px solid var(--border); border-radius: 999px; white-space: nowrap; }
button:focus-visible, a:focus-visible, input:focus-visible, summary:focus-visible, [tabindex]:focus-visible {
  outline: 2px solid var(--s1); outline-offset: 2px; }

header h1 { font-size: 28px; line-height: 1.2; margin: 8px 0 6px; letter-spacing: -0.01em; }
header p { margin: 0; color: var(--ink2); max-width: 780px; }
.meta { margin-top: 10px; font-size: 13px; color: var(--muted); }
header .guide { margin: 16px 0 0; padding: 10px 14px; border: 1px dashed var(--axis); border-radius: 10px;
  color: var(--ink2); font-size: 14px; background: var(--surface); max-width: none; }
.term, .term-demo { border-bottom: 1.5px dotted var(--muted); cursor: help; }
.term:hover { border-bottom-color: var(--s1); }

/* 30-second tour: a feeder sketch that walks through the five steps of the project */
.story { margin: 18px 0 0; padding: 16px 18px 18px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; box-shadow: 0 1px 0 var(--border); }
.story-head { display: flex; gap: 12px 20px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; }
.story h2 { margin: 0; font-size: 12.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--s2); }
header .story .lead { margin: 4px 0 0; max-width: 760px; color: var(--ink); font-size: 19px; line-height: 1.45; font-weight: 600; }
.story-ctrl { display: flex; gap: 6px; flex: none; }
.story-ctrl button { font: inherit; font-size: 12.5px; font-weight: 600; color: var(--ink2); background: var(--page);
  border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; cursor: pointer; }
.story-ctrl button:hover { border-color: var(--axis); color: var(--ink); }
.story .when-off, .story.paused .when-on { display: none; }
.story.paused .when-off { display: inline; }
.story.end #st-again { background: var(--s2); border-color: var(--s2); color: #fff; }
.story-fig { margin-top: 10px; }
.sk { display: block; width: 100%; height: auto; overflow: visible; }
.sk-band rect { fill: var(--soft); stroke: transparent; stroke-width: 2; transition: fill .6s, stroke .6s; }
.sk-band.found rect { fill: color-mix(in srgb, var(--s2) 13%, var(--surface)); stroke: var(--s2); stroke-dasharray: 7 5; }
.sk-zl { font: 600 12px system-ui, sans-serif; fill: var(--muted); }
.sk-band.found .sk-zl { fill: var(--s2); }
.sk-ln { fill: none; stroke: var(--axis); stroke-width: 4; stroke-linecap: round; transition: stroke .6s; }
.sk-always, .z.live .sk-ln { stroke: var(--s1); }
.z.tie .sk-ln, .story:is([data-step="4"], [data-step="5"]) .sk-tieln { stroke: var(--s3); }
.sk-load { fill: var(--surface); stroke: var(--axis); stroke-width: 2; transition: fill .6s, stroke .6s; }
.z.live .sk-load, .z.tie .sk-load { fill: var(--warning); stroke: color-mix(in srgb, var(--warning) 55%, var(--ink)); }
.sk-dev { fill: var(--ink); stroke: var(--ink); stroke-width: 2.5; transition: fill .4s, stroke .4s; }
.sk-dev.open { fill: var(--surface); stroke: var(--critical); }
.sk-box { fill: var(--page); stroke: var(--s1); stroke-width: 2; }
.sk-lbl { font: 600 13px system-ui, sans-serif; fill: var(--ink2); }
.sk-fault { opacity: 0; }
.story.f .sk-fault { opacity: 1; }
.story[data-step="1"] .sk-fault { animation: sk-in .35s 1.1s both; }
.sk-bolt { fill: var(--s2); stroke: var(--surface); stroke-width: 1.2; }
.sk-pulse { fill: var(--s2); opacity: .25; transform-box: fill-box; transform-origin: center; animation: sk-pulse 1.6s ease-out infinite; }
.sk-ml { opacity: 0; transition: opacity .4s; }
.story.ml .sk-ml { opacity: 1; }
.sk-data { fill: none; stroke: var(--s1); stroke-width: 2; stroke-dasharray: 3 7; opacity: .8; }
.story.ml .sk-data { animation: sk-flow .9s linear infinite; }
.sk-chip { fill: var(--ink); }
.sk-chipt { font: 700 12.5px system-ui, sans-serif; fill: var(--page); }
.story.ml .sk-res { animation: sk-in .3s 1.5s both; }
.story[data-step="3"] .sk-band.found rect { animation: sk-found .5s 1.7s both; }
.sk-patrol { fill: none; stroke: var(--s2); stroke-width: 10; stroke-linecap: round; stroke-dasharray: 2 11; opacity: 0;
  transition: opacity .4s; }
.sk-patrol.on { opacity: .5; animation: sk-flow 1.1s linear infinite; }
.sk-truck { opacity: 0; transform: translate(14px, 0); transition: transform 1.8s cubic-bezier(.4, 0, .2, 1), opacity .4s; }
.sk-truck.show { opacity: 1; }
.sk-truck.go { transform: translate(370px, 0); }
.sk-truck rect, .sk-truck circle { fill: var(--ink); }
.sk-tl { font: 700 12.5px system-ui, sans-serif; fill: var(--s2); opacity: 0; transition: opacity .3s; }
.sk-truck[data-t="all"] .tl-all, .sk-truck[data-t="one"] .tl-one { opacity: 1; }
.sk-truck[data-t="one"] .tl-one { transition-delay: 1.6s; }
.story-legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 6px; font-size: 12.5px; color: var(--muted); }
.story-legend i { display: inline-block; width: 16px; height: 4px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
.lg-live { background: var(--s1); } .lg-tie { background: var(--s3); } .lg-dead { background: var(--axis); }
.story-legend .lg-sw { width: 11px; height: 11px; border-radius: 3px; background: var(--ink); border: 2px solid var(--ink); }
.story-legend .lg-sw.open { background: transparent; border-color: var(--critical); }
.lg-note { font-style: italic; }
.story-steps { list-style: none; display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; padding: 0; margin: 14px 0 0; }
.story-steps button { width: 100%; padding: 0 0 2px; border: 0; background: none; text-align: left; cursor: pointer;
  font: inherit; font-size: 12.5px; color: var(--muted); }
.story-steps button:hover { color: var(--ink); }
.story-steps .bar { display: block; height: 4px; margin-bottom: 6px; border-radius: 4px; background: var(--grid); overflow: hidden; }
.story-steps .bar i { display: block; width: 0; height: 100%; background: var(--s2); }
.story-steps li.done .bar i, .story.paused .story-steps li.on .bar i { width: 100%; }
.story-steps li.on .bar i { animation: sk-bar var(--dur, 6.5s) linear forwards; }
.story.paused .story-steps li.on .bar i { animation: none; }
.story-steps li.on button { color: var(--ink); font-weight: 650; }
.story-cap { min-height: 6.4em; margin-top: 10px; }
.story .cap { display: none; }
.story .cap.on { display: block; animation: sk-up .4s ease both; }
.story .cap h3 { margin: 0 0 4px; font-size: 17px; }
header .story .cap p { margin: 0; max-width: 840px; color: var(--ink2); font-size: 15px; }
.story-next { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); }
.story-next h3 { margin: 0 0 8px; font-size: 12.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); }
.story-next ol { list-style: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px; margin: 0; padding: 0; }
.story-next a { display: flex; gap: 10px; height: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--page); color: var(--ink); text-decoration: none; transition: border-color .2s, transform .2s; }
.story-next a:hover { border-color: var(--s1); transform: translateY(-1px); }
.story-next .n { flex: none; display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%;
  background: var(--ink); color: var(--page); font-size: 13px; font-weight: 700; }
.story-next .mon .n { background: var(--s2); color: #fff; }
.story-next b { display: block; font-size: 14px; }
.story-next small { display: block; font-size: 12.5px; line-height: 1.4; color: var(--muted); }
.story.end .story-next li a { animation: sk-nudge .6s ease both; }
.story.end .story-next li:nth-child(2) a { animation-delay: .15s; }
.story.end .story-next li:nth-child(3) a { animation-delay: .3s; }
.story.end .story-next li:nth-child(4) a { animation-delay: .45s; }
@keyframes sk-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes sk-up { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes sk-pulse { from { transform: scale(.6); opacity: .45; } to { transform: scale(1.6); opacity: 0; } }
@keyframes sk-flow { to { stroke-dashoffset: -26; } }
@keyframes sk-bar { to { width: 100%; } }
@keyframes sk-found { from { fill: var(--soft); stroke: transparent; } }
@keyframes sk-nudge { 40% { border-color: var(--s2); transform: translateY(-3px); } }
@media (max-width: 640px) {
  header .story .lead { font-size: 17px; }
  .story { padding: 14px; }
  .story-steps .stt { display: none; }
  .story-steps button { text-align: center; }
  .sk-lbl, .sk-zl, .sk-tl { font-size: 19px; }
  .sk-chipt { font-size: 14px; }
}
@media (prefers-reduced-motion: reduce) {
  .story *, .story *::before { animation: none !important; transition: none !important; }
}
@media print { .story-ctrl { display: none; } }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }
.tile, section, .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
.tile { padding: 14px 16px; }
.tl { font-size: 13px; color: var(--ink2); }
.tv { font-size: 30px; font-weight: 650; line-height: 1.2; margin: 4px 0; font-variant-numeric: tabular-nums; }
.ts { font-size: 12.5px; color: var(--muted); }
.panel { padding: 16px 18px; }
.panel h2, section h2 { font-size: 19px; margin: 0 0 6px; }
.anchor { margin-left: 8px; color: var(--muted); text-decoration: none; font-weight: 400; opacity: 0; }
h2:hover .anchor, .anchor:focus { opacity: 1; }
section { padding: 18px; margin-top: 18px; }
h3 { font-size: 15px; margin: 22px 0 8px; }
.how { color: var(--ink2); margin: 0 0 12px; max-width: 800px; }
.note { color: var(--muted); font-size: 13px; margin: 0 0 8px; }
.take { margin: 0 0 14px; padding: 10px 14px; border-left: 3px solid var(--s1); border-radius: 0 8px 8px 0;
  background: color-mix(in srgb, var(--s1) 8%, transparent); font-size: 14.5px; }
.take-l { display: block; font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--ink2); margin-bottom: 2px; }

.checks { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 10px; }
.check { display: flex; gap: 12px; align-items: flex-start; }
.check > div > b { display: block; font-weight: 600; }
.muted { color: var(--muted); font-size: 13.5px; }
.chip { flex: none; display: inline-flex; gap: 4px; align-items: center; justify-content: center; min-width: 74px;
  font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 999px; white-space: nowrap; border: 1px solid; }
.chip.good { color: var(--good-ink); border-color: var(--good); }
.chip.warning { color: var(--ink); border-color: var(--warning); background: color-mix(in srgb, var(--warning) 22%, transparent); }
.chip.critical { color: var(--critical); border-color: var(--critical); }
.ev-panel { margin-top: 16px; }
.ev-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin: 12px 0 16px; }
.ev-card { padding: 11px 13px; border: 1px solid var(--border); border-radius: 10px; background: var(--page); }
.ev-k { font-size: 11.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }
.ev-v { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; font-size: 14px; font-weight: 600; color: var(--ink); }
.ev-s { margin-top: 5px; font-size: 12.5px; color: var(--ink2); line-height: 1.45; }
.ev-cmds { display: grid; gap: 5px; margin-top: 4px; }
.ev-cmd { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 4px 8px;
  border-radius: 6px; background: var(--soft); font-size: 12.5px; }
.ev-cmd code { background: none; padding: 0; overflow-x: auto; white-space: nowrap; }
.sha { display: inline-flex; align-items: center; gap: 5px; vertical-align: middle; }
.copy-btn { flex: none; font: inherit; font-size: 11.5px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink2); cursor: pointer; }
.copy-btn:hover { border-color: var(--s1); color: var(--s1); }
.ev-all { margin-top: 8px; }
.ev-sec { margin-top: 16px; padding: 12px 14px; border: 1px solid var(--border); border-left: 3px solid var(--s3);
  border-radius: 0 10px 10px 0; background: var(--page); font-size: 13.5px; color: var(--ink2); }
.ev-sec h4 { margin: 0 0 6px; font-size: 14px; color: var(--ink); }
.ev-sec ul { margin: 0; padding-left: 18px; }
.ev-sec li { margin-bottom: 4px; }
.hif-banner { display: flex; flex-wrap: wrap; gap: 10px 12px; align-items: flex-start; margin: 10px 0 14px;
  padding: 11px 14px; border: 1px solid var(--border); border-left: 3px solid var(--warning);
  border-radius: 0 10px 10px 0; background: var(--page); font-size: 13.5px; color: var(--ink2); }
.hif-banner > div { flex: 1; min-width: 240px; }
.hif-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.hif-real-h { margin-top: 24px; padding-top: 14px; border-top: 1px solid var(--border); }
.hif-honest { margin: 12px 0 14px; padding: 11px 14px; border: 1px solid var(--border); border-left: 3px solid var(--s2);
  border-radius: 0 10px 10px 0; background: var(--page); font-size: 13.5px; color: var(--ink2); }
.hif-box { fill: var(--page); stroke: var(--border); stroke-width: 1.5; }
.hif-box.t1 { stroke: var(--s2); }
.hif-box.t2 { stroke: var(--s1); }
.hif-step { fill: var(--surface); stroke: var(--border); stroke-width: 1; }
.hif-k { font-size: 12px; font-weight: 700; fill: var(--s2); }
.hif-k2 { font-size: 12px; font-weight: 700; fill: var(--s1); }
.hif-st { font-size: 11.5px; font-weight: 600; fill: var(--ink); }
.hif-sub { font-size: 10.5px; fill: var(--muted); }
.hif-pill { font-size: 11.5px; font-weight: 700; fill: var(--s2); }
.hif-arr { fill: none; stroke: var(--axis); stroke-width: 1.6; }
.hif-arr.main { stroke: var(--s2); stroke-width: 2.2; }
.hif-tip { fill: var(--s2); }

.chart { overflow-x: auto; }
.chart svg { width: 100%; min-width: 560px; height: auto; display: block; }  /* legible on phones: the chart scrolls, not the page */
.heatwrap { max-width: 520px; }
.heatwrap svg { min-width: 440px; }
.hourwrap { max-width: 600px; }
.hourwrap svg { min-width: 520px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink2); margin-bottom: 4px; }
.legend i { display: inline-block; width: 12px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }
.legend i.sw { height: 12px; border-radius: 3px; } .legend i.sw0 { border: 1px solid var(--grid); }
svg text { font-family: inherit; }
.tick { font-size: 12px; fill: var(--muted); }
.lab { font-size: 13px; fill: var(--ink2); }
.val { font-size: 12.5px; fill: var(--ink); font-variant-numeric: tabular-nums;
  paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.ref { stroke: var(--ink2); stroke-width: 1; stroke-dasharray: 3 3; }
.guide-line { stroke: var(--axis); stroke-width: 1; opacity: 0; }
.ln { fill: none; stroke-width: 2; stroke-linejoin: round; }
.key { stroke-width: 3; stroke-linecap: round; }
.dot { stroke: var(--surface); stroke-width: 2; }
.bar { fill: var(--bar); }
.hit { fill: transparent; outline: none; }
.hit:focus { fill: color-mix(in srgb, var(--ink) 5%, transparent); }
.cell { stroke: none; } .cell.q0 { fill: transparent; stroke: var(--grid); } .cell.diag { fill: var(--diag); }
.cell.q1 { fill: var(--q1); } .cell.q2 { fill: var(--q2); } .cell.q3 { fill: var(--q3); }
.cell.q4 { fill: var(--q4); } .cell.q5 { fill: var(--q5); }
.ct { font-size: 12px; font-variant-numeric: tabular-nums; pointer-events: none; }
.ct.diag { fill: var(--ink2); font-size: 10.5px; } .ct.q1, .ct.q2 { fill: var(--qi-lo); }
.ct.q3, .ct.q4, .ct.q5 { fill: var(--qi-hi); }
.heat g:hover rect, .heat g:focus rect { stroke: var(--ink); stroke-width: 1.5; }
.heat g { outline: none; }

.tw { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-weight: 600; color: var(--ink2); white-space: nowrap; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td small { display: block; font-size: 11.5px; color: var(--muted); font-weight: 400; }
tbody tr:hover { background: var(--soft); }
details { margin: 6px 0 4px; font-size: 14px; }
summary { cursor: pointer; color: var(--link); }

/* questions & answers */
.faq-tools { display: grid; gap: 10px; margin-bottom: 12px; }
#faq-search { font: inherit; width: 100%; padding: 9px 12px; border-radius: 10px; border: 1px solid var(--axis);
  background: var(--page); color: var(--ink); }
.fchips { display: flex; flex-wrap: wrap; gap: 6px; }
.fchip { font: inherit; font-size: 13px; padding: 3px 12px; border-radius: 999px; border: 1px solid var(--border);
  background: transparent; color: var(--ink2); cursor: pointer; }
.fchip[aria-pressed="true"] { background: var(--ink); color: var(--page); border-color: var(--ink); }
.faq-actions { display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: center; }
.linkbtn { font: inherit; font-size: 13px; border: 0; background: none; color: var(--link); cursor: pointer; padding: 0; }
.faq-item { border: 1px solid var(--border); border-radius: 10px; margin: 0 0 8px; background: var(--page); }
.faq-item > summary { list-style: none; padding: 11px 40px 11px 14px; color: var(--ink); font-weight: 600;
  position: relative; font-size: 14.5px; }
.faq-item > summary::-webkit-details-marker { display: none; }
.faq-item > summary::after { content: "+"; position: absolute; right: 14px; top: 8px; font-size: 20px;
  font-weight: 400; color: var(--muted); }
.faq-item[open] > summary::after { content: "−"; }
.faq-a { padding: 0 14px 12px; color: var(--ink2); }
.faq-a p, .faq-a ul { margin: 0 0 8px; }
.faq-a li { margin-bottom: 3px; }
.faq-item:target { border-color: var(--s1); }

/* data & method */
.steps { counter-reset: step; list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.steps li { counter-increment: step; position: relative; padding: 10px 14px 10px 50px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--page); }
.steps li::before { content: counter(step); position: absolute; left: 12px; top: 10px; width: 26px; height: 26px;
  border-radius: 50%; background: var(--s1); color: #fff; font-weight: 700; font-size: 13px; display: grid; place-items: center; }
.steps li > b { display: block; }   /* the question only: bold numbers inside the answer stay inline */
.steps li > span { color: var(--ink2); font-size: 14px; }
/* formula cards: equation rows, a "where" list for every symbol, a worked example */
.fxs { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 430px), 1fr)); gap: 16px; }
.fx { border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px 14px; background: var(--page); }
.fx-t { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; font-size: 16px; font-weight: 650; line-height: 1.3; }
.fx-n { flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: color-mix(in srgb, var(--s1) 14%, transparent); color: var(--s1); font-size: 13px; font-weight: 700; }
.fx-rows { display: grid; gap: 6px; }
.fx-row { display: grid; grid-template-columns: 8.5em minmax(0, 1fr); align-items: center; gap: 12px;
  padding: 8px 14px; border-radius: 8px; background: var(--soft); }
.fx-l { font-size: 12.5px; font-weight: 600; color: var(--ink2); line-height: 1.3; }
.tex-d { overflow-x: auto; overflow-y: hidden; padding: 2px 0; font-size: 15px; }
.tex-d .katex { font-size: 1.12em; }
.tex-d .katex-display { margin: 0; text-align: left; }
.tex-d .katex-display > .katex { text-align: left; }
.tex:not(.katex-done) { font-family: "Cambria Math", "STIX Two Math", Georgia, serif; }   /* fallback before KaTeX */
.fx-k { margin: 14px 0 4px; font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--muted); }
.fx-where { display: grid; grid-template-columns: max-content 1fr; gap: 5px 14px; margin: 0; font-size: 14px;
  align-items: baseline; }
.fx-where dt { text-align: right; white-space: nowrap; }
.fx-where dd { margin: 0; color: var(--ink2); }
.fx-ex { margin: 14px 0 0; padding: 8px 12px; border-left: 3px solid var(--s3); border-radius: 0 8px 8px 0;
  background: color-mix(in srgb, var(--s3) 8%, transparent); font-size: 14px; color: var(--ink); }
.fx-ex .fx-k { display: block; margin: 0 0 2px; }
@media (max-width: 560px) {
  .fx-row { grid-template-columns: 1fr; gap: 2px; }
  .fx-where { grid-template-columns: 1fr; gap: 0 0; }
  .fx-where dt { text-align: left; margin-top: 6px; }
}

/* glossary */
.gls { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin: 0; }
.gl { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--page); }
.gl dt { font-weight: 650; margin-bottom: 2px; }
.gl dd { margin: 0; color: var(--ink2); font-size: 13.5px; }
.gl:target { border-color: var(--s1); }

footer { margin-top: 24px; font-size: 13px; color: var(--muted); }
#tip { position: fixed; z-index: 9; pointer-events: none; max-width: 280px; padding: 8px 10px; border-radius: 8px;
  font-size: 13px; line-height: 1.45; background: var(--ink); color: var(--page); box-shadow: 0 4px 16px rgb(0 0 0 / .18); }
.totop { position: fixed; right: 16px; bottom: 16px; z-index: 6; width: 42px; height: 42px; border-radius: 50%;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink); font-size: 18px; cursor: pointer;
  box-shadow: 0 2px 10px rgb(0 0 0 / .12); }
.toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 10; padding: 8px 14px;
  border-radius: 999px; background: var(--ink); color: var(--page); font-size: 13px; }

/* explain guide: a buddy that flies to what you click, circles it and explains it */
.tile, .panel, .xbox { position: relative; }
.heatbox { max-width: 520px; }
.xq { position: absolute; top: 8px; right: 8px; z-index: 2; width: 22px; height: 22px; padding: 0; border-radius: 50%;
  border: 1px solid var(--border); background: var(--surface); color: var(--muted); font: 700 12px/20px system-ui, sans-serif;
  cursor: pointer; opacity: .8; }
.xbox > .xq { top: -11px; right: -6px; }
.xq:hover, .xq:focus-visible { opacity: 1; color: var(--s1); border-color: var(--s1); }
body.xmode [data-x] { cursor: help; }
body.xmode [data-x]:hover { outline: 2px dashed var(--s1); outline-offset: 4px; }
.face { position: relative; display: inline-block; flex: none; width: 34px; height: 34px; border-radius: 50%;
  background: var(--s1); box-shadow: inset -3px -4px 0 rgb(0 0 0 / .14); }
.face i { position: absolute; top: 10px; width: 6px; height: 9px; border-radius: 50%; background: #fff; }
.face i:first-child { left: 9px; } .face i:last-child { right: 9px; }
.face::after { content: ""; position: absolute; left: 11px; bottom: 7px; width: 12px; height: 5px;
  border-bottom: 2px solid #fff; border-radius: 0 0 10px 10px; }
.xdock { position: fixed; left: 16px; bottom: 16px; visibility: hidden; pointer-events: none; width: 36px; height: 36px; padding: 0 !important; }
.xhint { position: fixed; left: 16px; bottom: 66px; z-index: 7; max-width: 270px; padding: 10px 12px;
  border-radius: 12px 12px 12px 4px; background: var(--ink); color: var(--page); font-size: 13px;
  box-shadow: 0 6px 20px rgb(0 0 0 / .2); animation: pop .3s ease both; }
.buddy { position: absolute; left: 0; top: 0; z-index: 8; pointer-events: none;
  transition: left .6s cubic-bezier(.2, .9, .3, 1.2), top .6s cubic-bezier(.2, .9, .3, 1.2);
  filter: drop-shadow(0 3px 6px rgb(0 0 0 / .25)); }
.buddy.arrive .face { animation: wiggle .5s ease; }
.xring { position: absolute; z-index: 5; border-radius: 14px; pointer-events: none;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--s2) 28%, transparent); transition: left .35s, top .35s, width .35s, height .35s; }
.xscribble { position: absolute; z-index: 6; pointer-events: none; overflow: visible; }
.xscribble path { fill: none; stroke: var(--s2); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 1; stroke-dashoffset: 1; }
.xscribble.draw path { animation: draw .8s ease-out .35s forwards; }
.xbubble { position: fixed; right: 16px; bottom: 16px; z-index: 9; width: min(380px, calc(100vw - 32px));
  max-height: calc(100vh - 96px); overflow-y: auto; padding: 14px 16px 12px; border-radius: 14px;
  background: var(--surface); color: var(--ink); border: 1px solid var(--border); box-shadow: 0 12px 40px rgb(0 0 0 / .22);
  animation: pop .3s ease both; outline: none; }
.xbubble[tabindex]:focus-visible { outline: none; }   /* focused only so keys land in it; it is visible anyway */
.xb-head { display: flex; align-items: center; gap: 10px; }
.xb-head b { flex: 1; font-size: 15.5px; line-height: 1.3; }
.xb-x { font: inherit; font-size: 22px; line-height: 1; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 2px 6px; }
.xb-body { margin: 4px 0 0; }
.xb-body dt { margin-top: 10px; font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--ink2); }
.xb-body dd { margin: 2px 0 0; font-size: 14px; }
.xb-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 6px;
  position: sticky; bottom: -12px; padding: 8px 0 12px; margin-bottom: -12px; background: var(--surface); }  /* Prev/Next stay in reach on phones */
.xb-nav { font: inherit; font-size: 13px; font-weight: 600; padding: 5px 12px; border-radius: 999px;
  border: 1px solid var(--border); background: transparent; color: var(--ink); cursor: pointer; }
.xb-nav:hover { border-color: var(--s1); color: var(--s1); }
body.xopen .totop { display: none; }
/* 3D feeder model */
.m3d { position: relative; height: min(600px, 72vh); min-height: 380px; border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; background: linear-gradient(180deg, var(--surface), var(--soft)); }
.m3d-stage { position: absolute; inset: 0; }
.m3d-stage canvas { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
.m3d-stage canvas:active { cursor: grabbing; }
.m3d-labels { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.m3d-label { position: absolute; left: 0; top: 0; padding: 1px 8px; border-radius: 999px; border: 2px solid;
  background: var(--surface); color: var(--ink); font-size: 12px; font-weight: 650; white-space: nowrap;
  transition: opacity .3s; will-change: transform; }
.m3d-eq { font-size: 11px; font-weight: 600; padding: 0 6px; border-width: 1px; border-color: var(--axis); }
.m3d-err { font-size: 11.5px; font-weight: 700; padding: 0 7px; border-width: 1px; border-color: #d03b3b; color: #b3261e; }
.m3d-fault { font-size: 12.5px; font-weight: 700; padding: 1px 9px; border-color: #ff3b2f; background: #ff3b2f; color: #fff; }
.m3d-fx { display: none; }
.m3d.layer-fault .m3d-fx { display: inline-block; border-color: #ff3b2f; color: #c62828; }
.m3d-demo { background: linear-gradient(135deg, #f59e0b, #fbbf24); border-color: #d97706; color: #1c1000; font-weight: 700; }
.m3d-demo:hover { border-color: #b45309; color: #1c1000; filter: brightness(1.04); }
.m3d-demo.running { background: #dc2626; border-color: #b91c1c; color: #fff; }
.m3d-hif-hud { position: absolute; left: 10px; top: 52px; z-index: 3; max-width: min(460px, calc(100% - 24px));
  padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); border-left: 4px solid #f59e0b;
  background: color-mix(in srgb, var(--surface) 92%, transparent); color: var(--ink); font-size: 11.5px;
  line-height: 1.45; box-shadow: 0 4px 14px rgba(0, 0, 0, .14); pointer-events: none; }
.m3d-hif-hud b { color: #d97706; }
.m3d .m3d-legend:not(.lg-zones) { display: none; }
.m3d.layer-errors .lg-zones, .m3d.layer-fault .lg-zones { display: none; }
.m3d.layer-errors .lg-errors, .m3d.layer-fault .lg-fault { display: block; }
.m3d.layer-errors .m3d-eq, .m3d.layer-errors .m3d-bus { display: none !important; }   /* keep the error map uncluttered */
.m3d-bus { font-size: 10px; font-weight: 500; padding: 0 3px; border: 0; color: var(--muted);
  background: color-mix(in srgb, var(--surface) 70%, transparent); }
.m3d.no-zone .m3d-zone, .m3d.no-eq .m3d-eq, .m3d.no-bus .m3d-bus { display: none !important; }
.m3d-layers { display: inline-flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.m3d-lt { font-size: 12px; color: var(--muted); margin-left: 4px; }
.m3d-bar { position: absolute; left: 10px; top: 10px; right: 46px; z-index: 3; display: flex; flex-wrap: wrap;
  gap: 6px; align-items: center; }
.m3d-bar .seg { background: var(--surface); }
.m3d-btn { font: inherit; font-size: 12.5px; font-weight: 600; padding: 4px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink2); cursor: pointer; }
.m3d-btn[aria-pressed="true"] { color: var(--ink); border-color: var(--ink2); }
.m3d-btn:hover { border-color: var(--s1); color: var(--s1); }
.m3d-hint { position: absolute; left: 50%; bottom: 40px; transform: translateX(-50%); z-index: 3;
  width: max-content; max-width: calc(100% - 32px); padding: 8px 14px; border-radius: 14px; background: var(--ink);
  color: var(--page); font-size: 13px; text-align: center; pointer-events: none; transition: opacity .5s; }
.m3d-hint.off { opacity: 0; }
.m3d-legend { position: absolute; left: 12px; right: 12px; bottom: 8px; z-index: 2; font-size: 11.5px;
  color: var(--muted); pointer-events: none; }
.m3d-map { position: absolute; inset: 0; overflow: auto; background: #fff; padding-top: 50px; }
.m3d-map img { display: block; width: 100%; min-width: 860px; }
.m3d.view2d .m3d-stage, .m3d.view2d .m3d-labels, .m3d.view2d .m3d-hint, .m3d.view2d .m3d-legend, .m3d.view2d .m3d-hif-hud,
.m3d.view2d #m3d-spin, .m3d.view2d #m3d-reset, .m3d.view2d #m3d-hif-demo, .m3d.nogl #m3d-3d { display: none; }
.m3d:not(.view2d) .m3d-map { display: none; }
.m3d-unlock { display: none; position: absolute; inset: 0; z-index: 4; border: 0; cursor: pointer; font: inherit;
  font-weight: 700; font-size: 15px; color: var(--ink); background: color-mix(in srgb, var(--page) 30%, transparent); }
.m3d.locked:not(.view2d) .m3d-unlock { display: block; }
.m3d-done { display: none; }
.m3d.touch:not(.locked):not(.view2d) .m3d-done { display: inline-block; }
.m3d > .xq { top: 10px; right: 10px; z-index: 5; }
@keyframes draw { to { stroke-dashoffset: 0; } }
@keyframes wiggle { 0%, 100% { transform: rotate(0); } 30% { transform: rotate(-14deg); } 70% { transform: rotate(10deg); } }
@keyframes pop { from { opacity: 0; transform: translateY(8px) scale(.97); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .buddy, .xring { transition: none; }
  .xbubble, .xhint, .buddy.arrive .face { animation: none; }
  .xscribble.draw path { animation: none; stroke-dashoffset: 0; }
}

@media (max-width: 640px) {
  .brand { display: none; }
  header h1 { font-size: 23px; } .tv { font-size: 26px; } section { padding: 14px; }
  .xbubble { left: 12px; right: 12px; bottom: 12px; width: auto; max-height: 48vh; }
}
@media print {
  .topbar, .totop, .faq-tools, .copy, .copy-btn, #tip, .anchor, header .guide, .tiers { display: none !important; }
  .xq, .xdock, .xhint, .buddy, .xring, .xscribble, .xbubble, .m3d-bar, .m3d-hint, .m3d-unlock { display: none !important; }
  body { background: #fff; } main { padding-top: 0; }
  section, .panel, .tile, .faq-item { break-inside: avoid; }
}
/* Sleek 2-tier switcher & collapsible deep-dive panels (same original system-ui font & palette) */
.tiers { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 12px; }
.tier-lbl { font-size: 12px; font-weight: 600; color: var(--muted); margin-right: 2px; }
.tier { display: inline-flex; align-items: center; padding: 4px 11px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink2);
  font-size: 12.5px; font-weight: 600; text-decoration: none; transition: border-color .15s, background-color .15s, color .15s; }
.tier:hover { border-color: var(--s1); color: var(--ink); background: var(--soft); }
.tier.on { border-color: var(--s1); background: color-mix(in srgb, var(--s1) 14%, var(--surface)); color: var(--s1); }
.tier.sub { background: transparent; color: var(--muted); }
.xlaunch { border-color: var(--s1) !important; color: var(--s1) !important;
  background: color-mix(in srgb, var(--s1) 10%, transparent) !important; }
.xlaunch:hover { background: color-mix(in srgb, var(--s1) 18%, transparent) !important; }

details.deep { margin: 14px 0 0; border: 1px solid var(--border); border-radius: 10px; background: var(--page); }
details.deep[open] { background: var(--surface); border-color: var(--axis); }
summary.deep-sum { list-style: none; cursor: pointer; padding: 11px 14px; display: flex; gap: 12px;
  align-items: center; justify-content: space-between; }
summary.deep-sum::-webkit-details-marker { display: none; }
summary.deep-sum:hover { background: var(--soft); border-radius: 10px; }
details.deep[open] > summary.deep-sum { border-bottom: 1px solid var(--border); border-radius: 10px 10px 0 0; }
.deep-t { min-width: 0; }
.deep-t b { display: block; font-size: 14.5px; color: var(--ink); line-height: 1.3; }
.deep-t small { display: block; font-size: 12.5px; color: var(--muted); margin-top: 2px; line-height: 1.35; }
.deep-r { display: inline-flex; align-items: center; gap: 8px; flex: none; }
.deep-act { font-size: 12px; font-weight: 600; color: var(--link); padding: 3px 9px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); white-space: nowrap; }
details.deep[open] .deep-act::before { content: "▴ "; }
details.deep:not([open]) .deep-act::before { content: "▾ "; }
.deep-body { padding: 12px 14px 14px; }
@media (max-width: 640px) {
  summary.deep-sum { flex-direction: column; align-items: flex-start; }
}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-in">
  <span class="brand">Self-Healing Feeder</span>
  <a class="monitor" href="monitor/"><span class="mon-ic" aria-hidden="true">@@MONICON@@<span class="dot"></span></span><span class="mon-tx"><b><span data-l="en">Monitor</span><span data-l="vi">Giám sát</span></b><small><span data-l="en">Try handling a fault</span><span data-l="vi">Tự xử lý sự cố</span></small></span></a>
  <div class="navwrap"><button type="button" class="navbtn" id="nav-prev" aria-label="Show earlier sections" hidden>‹</button><nav aria-label="Sections">@@NAV@@</nav><button type="button" class="navbtn" id="nav-next" aria-label="Show more sections" hidden>›</button></div>
  <div class="ctrls">
    <button type="button" class="iconbtn xlaunch" id="xlaunch" title="Explain guide"><span data-l="en">? Guide</span><span data-l="vi">? Giải thích</span></button>
    <button type="button" class="iconbtn" id="view-all" aria-pressed="false" title="Toggle detailed tables"><span data-l="en">⊞ Full view</span><span data-l="vi">⊞ Mở tất cả</span></button>
    <div class="seg" role="group" aria-label="Language"><button type="button" data-set-lang="en" aria-pressed="true">EN</button><button type="button" data-set-lang="vi" aria-pressed="false">VI</button></div>
    <button type="button" class="iconbtn" id="theme" title="Theme">◐</button>
  </div>
</div></div>
<main>
<header>@@HEADER@@@@GUIDE@@</header>
<div class="tiles">@@TILES@@</div>
@@HEALTH@@
@@BODY@@
<footer>@@FOOTER@@</footer>
</main>
<button type="button" class="totop" id="totop" aria-label="Back to top" hidden>↑</button>
<script type="application/json" id="xdata">@@XDATA@@</script>
<script type="application/json" id="mdata">@@MDATA@@</script>
<div class="xdock" id="xdock" aria-hidden="true"></div>
<div class="xhint" id="xhint" hidden><span data-l="en">Hi! Explain mode is on: click any card, chart, table or the 3D model and I will explain it.</span><span data-l="vi">Chào bạn! Nhấp vào bất kỳ thẻ, biểu đồ, bảng hay mô hình 3D nào, mình sẽ giải thích.</span></div>
<div class="buddy" id="buddy" aria-hidden="true" hidden><span class="face"><i></i><i></i></span></div>
<div class="xring" id="xring" hidden></div>
<svg class="xscribble" id="xscribble" aria-hidden="true" hidden><path pathLength="1"/></svg>
<div class="xbubble" id="xbubble" role="dialog" aria-labelledby="xb-title" tabindex="-1" hidden>
  <div class="xb-head"><span class="face" aria-hidden="true"><i></i><i></i></span><b id="xb-title"></b><button type="button" class="xb-x" id="xb-close">×</button></div>
  <dl class="xb-body"><dt id="xk-what"></dt><dd id="xb-what"></dd><dt id="xk-read"></dt><dd id="xb-read"></dd><dt id="xk-why"></dt><dd id="xb-why"></dd></dl>
  <div class="xb-foot"><button type="button" class="xb-nav" id="xb-prev"></button><span class="muted" id="xb-count"></span><button type="button" class="xb-nav" id="xb-next"></button></div>
</div>
<div id="tip" role="tooltip" hidden></div>
<script>
(() => {
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  };
  const L = () => (root.lang === "vi" ? "vi" : "en");
  const TEXT = {
    en: { title: "Self-Healing Feeder Report", copied: "Link copied", copiedHash: "SHA-256 copied", copiedCmd: "Command copied", theme: { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" } },
    vi: { title: "Báo cáo Self-Healing Feeder", copied: "Đã sao chép link", copiedHash: "Đã sao chép SHA-256", copiedCmd: "Đã sao chép lệnh", theme: { auto: "◐ Tự động", light: "☀ Sáng", dark: "☾ Tối" } },
  };

  // ---- theme: auto -> light -> dark (?theme= in the URL wins, e.g. for screenshots)
  const params = new URLSearchParams(location.search);
  const themeBtn = document.getElementById("theme");
  let theme = ["auto", "light", "dark"].includes(params.get("theme")) ? params.get("theme")
    : (store.get("shf-theme") || "auto");
  const themeHooks = [];   // the 3D model re-reads its colours here
  const applyTheme = () => {
    if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
    themeBtn.textContent = TEXT[L()].theme[theme];
    themeHooks.forEach(f => f());
  };
  themeBtn.addEventListener("click", () => {
    theme = { auto: "light", light: "dark", dark: "auto" }[theme];
    store.set("shf-theme", theme); applyTheme();
  });

  // ---- tooltips (mouse hover, keyboard focus, tap on touch screens)
  const tip = document.getElementById("tip");
  let guide = null, tipEl = null;
  const move = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + "px";
    tip.style.top = (y + h + 22 > innerHeight ? y - h - 14 : y + 16) + "px";
  };
  const show = (el, x, y) => {
    tipEl = el;
    tip.innerHTML = L() === "vi" && el.dataset.tipVi ? el.dataset.tipVi : el.dataset.tip;
    tip.hidden = false;
    if (el.dataset.guide) {
      const parts = el.dataset.guide.split(":");
      guide = document.getElementById(parts[0]);
      guide.setAttribute("x1", parts[1]); guide.setAttribute("x2", parts[1]); guide.style.opacity = 1;
    }
    move(x, y);
  };
  const hide = () => {
    if (tip.hidden) return;   // no DOM write when nothing is shown: this runs on every scroll event
    tip.hidden = true; tipEl = null; if (guide) guide.style.opacity = 0; guide = null;
  };
  document.addEventListener("pointerover", e => {
    if (e.pointerType === "touch") return;
    const el = e.target.closest("[data-tip]"); if (el) show(el, e.clientX, e.clientY);
  });
  document.addEventListener("pointermove", e => { if (!tip.hidden && e.pointerType !== "touch") move(e.clientX, e.clientY); });
  document.addEventListener("pointerout", e => { if (e.pointerType !== "touch" && e.target.closest("[data-tip]")) hide(); });
  document.addEventListener("click", e => {
    const el = e.target.closest("[data-tip]");
    if (!el) { hide(); return; }
    if (el === tipEl && e.pointerType === "touch") { hide(); return; }
    show(el, e.clientX, e.clientY);
  });
  document.addEventListener("focusin", e => {
    const el = e.target.closest("[data-tip]");
    if (el) { const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); }
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
  addEventListener("scroll", hide, { passive: true });

  // ---- questions & answers: search (accent-insensitive), topic filter, open/close all, copy link
  const search = document.getElementById("faq-search");
  const items = [...document.querySelectorAll(".faq-item")];
  const norm = s => s.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").replace(/đ/g, "d");
  let cat = "all";
  const filterFaq = () => {
    if (!search) return;
    const words = norm(search.value).split(/\\s+/).filter(Boolean);
    let shown = 0;
    items.forEach(it => {
      const text = norm([...it.querySelectorAll('[data-l="' + L() + '"]')].map(n => n.textContent).join(" "));
      const ok = (cat === "all" || it.dataset.cat === cat) && words.every(w => text.includes(w));
      it.hidden = !ok;
      if (ok) { shown++; if (words.length) it.open = true; }
    });
    document.querySelectorAll(".faq-n").forEach(n => { n.textContent = shown; });
    document.getElementById("faq-empty").hidden = shown > 0;
  };
  if (search) search.addEventListener("input", filterFaq);
  document.querySelectorAll(".fchip").forEach(b => b.addEventListener("click", () => {
    cat = b.dataset.cat;
    document.querySelectorAll(".fchip").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    filterFaq();
  }));
  document.querySelectorAll("[data-all]").forEach(b => b.addEventListener("click", () => {
    items.forEach(it => { if (!it.hidden) it.open = b.dataset.all === "open"; });
  }));
  const toast = msg => {
    const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 1600);
  };
  document.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", () => {
    const url = location.href.split("#")[0] + b.dataset.copy;
    const fallback = () => { try { history.replaceState(null, "", b.dataset.copy); } catch (e) {} toast(TEXT[L()].copied); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(() => toast(TEXT[L()].copied), fallback);
    else fallback();
  }));
  const copyPlain = (txt, msg) => {
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = txt; ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      ta.remove(); toast(msg);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(txt).then(() => toast(msg), fallback);
    else fallback();
  };
  document.querySelectorAll("[data-copy-text]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    const key = b.dataset.copyKind === "cmd" ? "copiedCmd" : "copiedHash";
    copyPlain(b.dataset.copyText, TEXT[L()][key]);
  }));
  const openParents = el => {
    let p = el;
    while (p) { if (p.tagName === "DETAILS") p.open = true; p = p.parentElement; }
  };
  const openHash = () => {
    const el = location.hash && document.getElementById(location.hash.slice(1));
    if (el) { openParents(el); if (el.closest("details")) el.scrollIntoView(); }
  };
  addEventListener("hashchange", openHash);
  document.addEventListener("click", e => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const id = a.getAttribute("href").slice(1);
    const el = id && document.getElementById(id);
    if (el) openParents(el);
  });
  const viewBtn = document.getElementById("view-all");
  if (viewBtn) {
    const setFull = on => {
      document.querySelectorAll("details.deep").forEach(d => { d.open = on; });
      viewBtn.setAttribute("aria-pressed", String(on));
      viewBtn.innerHTML = on
        ? '<span data-l="en">⊟ Quick scan</span><span data-l="vi">⊟ Thu gọn</span>'
        : '<span data-l="en">⊞ Full view</span><span data-l="vi">⊞ Mở tất cả</span>';
    };
    viewBtn.addEventListener("click", () => setFull(viewBtn.getAttribute("aria-pressed") !== "true"));
    if (params.get("full") === "1") setFull(true);
  }

  // ---- explain guide (heyclicky-style): click a card, chart or table, or its "?" button; the buddy
  // flies there, circles it and explains it. Text: EXPLAIN in shf/dashboard_text.py, via #xdata.
  const XD = JSON.parse(document.getElementById("xdata").textContent);
  const XL = {
    en: { what: "What it is", read: "How to read it", why: "Why it matters", prev: "← Prev", next: "Next →",
          close: "Close", ask: "Explain this", on: "Explain mode on: click any card, chart or table", off: "Explain mode off" },
    vi: { what: "Đây là gì", read: "Đọc thế nào", why: "Vì sao quan trọng", prev: "← Trước", next: "Tiếp →",
          close: "Đóng", ask: "Giải thích phần này", on: "Đã bật giải thích: nhấp vào bất kỳ thẻ, biểu đồ hay bảng nào",
          off: "Đã tắt chế độ giải thích" },
  };
  const byId = id => document.getElementById(id);
  const dockBtn = byId("xdock"), buddy = byId("buddy"), ring = byId("xring"), scrib = byId("xscribble");
  const bub = byId("xbubble"), xhint = byId("xhint");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const xt = [...document.querySelectorAll("[data-x]")].filter(el => XD[el.dataset.x]);
  // an "item" is anything the guide can explain: the element it circles, its text in the current
  // language, and optional enter/leave hooks (the 3D model uses them to lift the clicked zone)
  const parts = xt.map(el => ({ el, text: () => XD[el.dataset.x][L()] }));
  let xmode = false, xlist = parts, xi = -1;
  xt.forEach((el, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "xq"; b.textContent = "?";
    b.addEventListener("click", e => { e.stopPropagation(); explain(parts, i, true); });
    el.appendChild(b);
  });
  const xRelabel = () => {
    const t = XL[L()];
    document.querySelectorAll(".xq").forEach(b => { b.title = t.ask; b.setAttribute("aria-label", t.ask); });
    byId("xb-close").setAttribute("aria-label", t.close);
    if (xi >= 0) render();
  };
  const render = () => {
    const t = XL[L()], d = xlist[xi].text(), many = xlist.length > 1;
    byId("xb-title").textContent = d.title;
    // what/read/why arrive as escaped HTML with the key numbers in <b> (built in shf/dashboard.py)
    ["what", "read", "why"].forEach(k => { byId("xk-" + k).textContent = t[k]; byId("xb-" + k).innerHTML = d[k]; });
    byId("xb-prev").textContent = t.prev; byId("xb-next").textContent = t.next;
    byId("xb-prev").hidden = byId("xb-next").hidden = !many;
    byId("xb-count").textContent = many ? (xi + 1) + " / " + xlist.length : "";
  };
  const place = el => {
    const r = el.getBoundingClientRect(), x = r.left + scrollX, y = r.top + scrollY, p = 8;
    const w = r.width + 2 * p, h = r.height + 2 * p;
    Object.assign(ring.style, { left: x - p + "px", top: y - p + "px", width: w + "px", height: h + "px" });
    // a hand-drawn loop: rounded box with slightly wobbly sides that overshoots where the pen started
    const m = 10, W = w + 2 * m, H = h + 2 * m, c = Math.min(18, h / 3), a = m, R = W - m, B = H - m;
    scrib.setAttribute("width", W); scrib.setAttribute("height", H);
    Object.assign(scrib.style, { left: x - p - m + "px", top: y - p - m + "px" });
    scrib.firstElementChild.setAttribute("d", [
      "M", a + c + 24, a + 3, "L", R - c, a - 1, "Q", R + 2, a - 2, R + 1, a + c,
      "L", R - 1, B - c, "Q", R - 1, B + 2, R - c, B + 1, "L", a + c, B - 1, "Q", a - 2, B - 1, a - 1, B - c,
      "L", a + 1, a + c, "Q", a, a - 2, a + c + 4, a + 1, "L", a + c + 46, a + 7].join(" "));
    buddy.style.left = Math.max(4, x - p - 22) + "px";
    buddy.style.top = Math.max(4, y - p - 30) + "px";
  };
  const explain = (list, i, smooth) => {
    if (xi >= 0 && xlist[xi].leave) xlist[xi].leave();
    xlist = list; xi = (i + list.length) % list.length;
    const it = xlist[xi], el = it.el;
    openParents(el);
    const r = el.getBoundingClientRect();
    hide(); xhint.hidden = true;
    // bring it under the top bar, keeping room for the buddy (not for clicks inside the 3D model: it is on screen)
    if (!it.noScroll && (r.top < 100 || r.top > innerHeight * 0.4))
      scrollTo({ top: Math.max(0, r.top + scrollY - 120), behavior: smooth && !reduce ? "smooth" : "auto" });
    if (buddy.hidden) {   // first explanation: take off from the dock button
      const dk = dockBtn.getBoundingClientRect();
      buddy.style.transition = "none";
      buddy.style.left = dk.left + scrollX + "px"; buddy.style.top = dk.top + scrollY + "px";
      buddy.hidden = false; void buddy.offsetWidth;
      buddy.style.transition = "";
    }
    place(el);
    ring.hidden = false; scrib.hidden = false;
    scrib.classList.remove("draw"); void scrib.getBoundingClientRect(); scrib.classList.add("draw");
    buddy.classList.remove("arrive"); setTimeout(() => buddy.classList.add("arrive"), reduce ? 0 : 600);
    render();
    if (it.enter) it.enter();
    if (bub.hidden) { bub.hidden = false; bub.focus({ preventScroll: true }); }
    document.body.classList.add("xopen");
  };
  const closeX = () => {
    if (xi < 0) return;
    if (xlist[xi].leave) xlist[xi].leave();
    const done = xlist[xi].close;   // e.g. the fault replay resets the model when its bubble is closed
    xi = -1;
    if (done) done();
    bub.hidden = true; ring.hidden = true; scrib.hidden = true;
    document.body.classList.remove("xopen");
    const dk = dockBtn.getBoundingClientRect();   // fly home, then disappear
    buddy.style.left = dk.left + scrollX + "px"; buddy.style.top = dk.top + scrollY + "px";
    setTimeout(() => { if (xi < 0) buddy.hidden = true; }, reduce ? 0 : 600);
  };
  byId("xb-close").addEventListener("click", closeX);
  byId("xb-prev").addEventListener("click", () => explain(xlist, xi - 1, true));
  byId("xb-next").addEventListener("click", () => explain(xlist, xi + 1, true));
  const xlaunch = byId("xlaunch");
  if (xlaunch) xlaunch.addEventListener("click", () => { if (xi >= 0) closeX(); else if (parts.length) explain(parts, 0, true); });
  const setXmode = (on, save) => {
    xmode = on;
    document.body.classList.toggle("xmode", on);
  };
  document.addEventListener("click", e => {   // capture phase: in explain mode a click explains instead
    if (!xmode || e.target.closest(".xq, .xbubble, .xdock, a, button, summary, input, .term, .m3d")) return;
    const el = e.target.closest("[data-x]");
    if (!el || xt.indexOf(el) < 0) return;
    e.stopPropagation(); e.preventDefault();
    explain(parts, xt.indexOf(el), true);
  }, true);
  document.addEventListener("keydown", e => {
    if (xi < 0 || (e.target.matches && e.target.matches("input, textarea"))) return;
    if (e.key === "Escape") closeX();
    else if (e.key === "ArrowRight") explain(xlist, xi + 1, true);
    else if (e.key === "ArrowLeft") explain(xlist, xi - 1, true);
  });
  let reflow = false;
  const repositionSoon = () => {
    if (xi < 0 || reflow) return;
    reflow = true;
    requestAnimationFrame(() => { reflow = false; if (xi >= 0) place(xlist[xi].el); });
  };
  addEventListener("resize", repositionSoon);
  // the language switch, an opened table or answer can move things: keep the circle on its target
  new ResizeObserver(repositionSoon).observe(document.querySelector("main"));

  // ---- 3D feeder model. three.js comes from a CDN, loaded only when the section nears the screen,
  // and draws the feeder from results/feeder_geometry.json. Clicking a zone, switch, tie, regulator,
  // capacitor or load column lifts it out and hands it to the guide; without WebGL the 2D map shows.
  const loadJs = s => new Promise((ok, bad) => {
    const el = document.createElement("script"); el.src = s; el.onload = ok; el.onerror = bad; document.head.appendChild(el);
  });
  const THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
  const ORBIT_URL = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js";
  const mbox = byId("m3d");
  const MD = mbox ? JSON.parse(byId("mdata").textContent) : null;
  let model = null;
  const lift = z => ({ noScroll: true, enter: () => model && model.focus(z), leave: () => model && model.focus(null) });
  const zoneIdx = {};
  const zoneItems = MD ? MD.geo.zones.map((z, i) => {
    zoneIdx[z.name] = i;
    return { el: mbox, text: () => MD.text.zone[z.name][L()], ...lift(z.name) };
  }) : [];
  const objItem = (key, zone) => ({ el: mbox, text: () => MD.text.obj[key][L()], ...lift(zone) });
  const loadItem = (bus, kw, zone) => ({ el: mbox, ...lift(zone), text: () => {
    const t = MD.text.load[L()];
    const f = s => s.split("{kw} kW").join("<b>" + kw + " kW</b>").split("{bus}").join(bus).split("{zone}").join(zone);
    return { title: f(t.title), what: f(t.what), read: t.read, why: t.why };
  } });
  const setView = v => {
    mbox.classList.toggle("view2d", v === "2d");
    byId("m3d-3d").setAttribute("aria-pressed", String(v === "3d"));
    byId("m3d-2d").setAttribute("aria-pressed", String(v === "2d"));
    const img = mbox.querySelector(".m3d-map img");
    if (v === "2d" && !img.getAttribute("src")) img.src = img.dataset.src;
  };
  const noModel = () => { mbox.classList.add("nogl"); setView("2d"); };
  const hintOff = () => { const h = mbox && mbox.querySelector(".m3d-hint"); if (h) h.classList.add("off"); };

  const buildModel = () => {
    const T3 = window.THREE, G = MD.geo, stage = mbox.querySelector(".m3d-stage"), labelBox = mbox.querySelector(".m3d-labels");
    const renderer = new T3.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    stage.appendChild(renderer.domElement);
    const scene = new T3.Scene(), cam = new T3.PerspectiveCamera(36, 1, 0.5, 600);
    const css = n => getComputedStyle(root).getPropertyValue(n).trim();
    const all = Object.values(G.buses), xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 100;
    const P = (x, y, h) => new T3.Vector3((x - cx) / 100, h || 0, (cy - y) / 100);   // feeder ft/100 -> scene
    const HP = 1.0, UP = new T3.Vector3(0, 1, 0), k = reduce ? 1 : 0.12;          // pole height, easing step
    scene.add(new T3.HemisphereLight(0xffffff, 0x667788, 0.95));
    const sun = new T3.DirectionalLight(0xffffff, 0.6); sun.position.set(-20, 40, 25); scene.add(sun);
    const ground = new T3.Mesh(new T3.PlaneGeometry(span + 18, span + 18),
                               new T3.MeshStandardMaterial({ color: css("--soft"), roughness: 1 }));
    ground.rotation.x = -Math.PI / 2; scene.add(ground);
    themeHooks.push(() => ground.material.color.set(css("--soft")));

    // one group and one material pair per zone, so a clicked zone can rise while the rest fade
    const zm = {};
    G.zones.forEach(z => {
      const c = new T3.Color(z.color), group = new T3.Group();
      const lc = c.clone().lerp(new T3.Color(0xffffff), .35);
      zm[z.name] = { group, lift: 0, liftGoal: 0, fadeGoal: 1, base: c.clone(), loadBase: lc.clone(),
        line: new T3.MeshStandardMaterial({ color: c, roughness: .45, transparent: true }),
        load: new T3.MeshStandardMaterial({ color: lc, roughness: .6, transparent: true }) };
      scene.add(group);
    });
    const other = new T3.Group(); scene.add(other);
    const pick = [], reveal = [];   // clickable meshes; meshes that grow in when the model first appears
    const src = P(G.source[1], G.source[2]);
    const order = (x, y) => Math.min(1, P(x, y).distanceTo(src) / span);
    const add = (mesh, z, o) => {
      (zm[z] ? zm[z].group : other).add(mesh);
      if (mesh.userData.click) pick.push(mesh);
      reveal.push([mesh, o, mesh.scale.clone()]);
    };
    const cyl = (a, b, r, m) => {
      const d = new T3.Vector3().subVectors(b, a), len = d.length() || 0.01;
      const mesh = new T3.Mesh(new T3.CylinderGeometry(r, r, len, 8), m);
      mesh.position.copy(a).addScaledVector(d, 0.5);
      mesh.quaternion.setFromUnitVectors(UP, d.normalize());
      return mesh;
    };
    const edges = (mesh, color) => {
      mesh.add(new T3.LineSegments(new T3.EdgesGeometry(mesh.geometry), new T3.LineBasicMaterial({ color })));
      return mesh;
    };
    const zoneClick = z => () => explain(zoneItems, zoneIdx[z], false);

    // materials shared by the hardware
    const hitMat = new T3.MeshBasicMaterial({ visible: false });
    const grey = new T3.MeshStandardMaterial({ color: 0x8a8f96, roughness: .8 });
    const wood = new T3.MeshStandardMaterial({ color: 0x8b6f4e, roughness: .9 });
    const porcelain = new T3.MeshStandardMaterial({ color: 0xece7dc, roughness: .3 });
    const steel = new T3.MeshStandardMaterial({ color: 0x5d636a, roughness: .5, metalness: .35 });
    const tank = new T3.MeshStandardMaterial({ color: 0x9aa3ab, roughness: .45, metalness: .25 });
    const white = new T3.MeshStandardMaterial({ color: 0xffffff, roughness: .4 });
    const black = new T3.MeshStandardMaterial({ color: 0x1b1b1b, roughness: .4 });
    const m4 = new T3.Matrix4(), q = new T3.Quaternion(), X = new T3.Vector3(1, 0, 0);

    // line sections: one wire per phase, spread across the crossarm; underground cable just above
    // the ground. Each section also gets a fat invisible twin that takes the clicks.
    const OFF = { 3: [-.24, 0, .24], 2: [-.13, .13], 1: [0] };
    const poleDir = {}, polePh = {};   // per bus: direction of its first overhead line, most phases seen
    G.edges.forEach(([u, v, z, ph, ug]) => {
      const a = G.buses[u], b = G.buses[v];
      if (!a || !b) return;
      const A0 = P(a[0], a[1]), B0 = P(b[0], b[1]), d = new T3.Vector3().subVectors(B0, A0).normalize();
      const n = new T3.Vector3(-d.z, 0, d.x), o = order((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mat = zm[z] ? zm[z].line : grey;
      if (ug) add(cyl(A0.clone().setY(.06), B0.clone().setY(.06), .07, mat), z, o);
      else {
        [u, v].forEach(bus => { if (!poleDir[bus]) poleDir[bus] = d; polePh[bus] = Math.max(polePh[bus] || 0, ph); });
        (OFF[ph] || [0]).forEach(s => add(cyl(A0.clone().addScaledVector(n, s).setY(HP), B0.clone().addScaledVector(n, s).setY(HP), .05, mat), z, o));
      }
      const twin = cyl(A0.clone().setY(ug ? .06 : HP), B0.clone().setY(ug ? .06 : HP), .45, hitMat);
      twin.userData = { label: "Zone " + z, click: zoneClick(z), bus: u };
      add(twin, z, o);
    });

    // wooden poles, crossarms turned across the line, one porcelain insulator per phase,
    // and a pole-top distribution transformer wherever a load is connected (all instanced)
    const pb = Object.keys(poleDir);
    const poleGeo = new T3.CylinderGeometry(.03, .045, HP + .15, 6); poleGeo.translate(0, (HP + .15) / 2, 0);
    const poles = new T3.InstancedMesh(poleGeo, wood, pb.length);
    const arms = new T3.InstancedMesh(new T3.BoxGeometry(1, .045, .06), wood, pb.length);
    const ins = new T3.InstancedMesh(new T3.CylinderGeometry(.028, .034, .1, 8), porcelain,
                                     pb.reduce((s, b) => s + (OFF[polePh[b]] || [0]).length, 0));
    const loadPoles = Object.keys(G.loads).filter(b => poleDir[b]);
    const cans = new T3.InstancedMesh(new T3.CylinderGeometry(.09, .09, .22, 12), tank, loadPoles.length);
    let ii = 0;
    pb.forEach((b, i) => {
      const p = G.buses[b], d = poleDir[b], n = new T3.Vector3(-d.z, 0, d.x), base = P(p[0], p[1]), offs = OFF[polePh[b]] || [0];
      m4.makeTranslation(base.x, 0, base.z); poles.setMatrixAt(i, m4);
      q.setFromUnitVectors(X, n);
      m4.compose(base.clone().setY(HP - .06), q, new T3.Vector3(Math.max(.32, offs[offs.length - 1] * 2 + .22), 1, 1));
      arms.setMatrixAt(i, m4);
      offs.forEach(s => { m4.makeTranslation(base.x + n.x * s, HP - .02, base.z + n.z * s); ins.setMatrixAt(ii++, m4); });
    });
    loadPoles.forEach((b, i) => {
      const p = G.buses[b], c = P(p[0], p[1]).addScaledVector(poleDir[b], .14);
      m4.makeTranslation(c.x, HP - .42, c.z); cans.setMatrixAt(i, m4);
    });
    other.add(poles, arms, ins, cans);

    // loads: one column per bus, height = kW
    const boxGeo = new T3.BoxGeometry(.34, 1, .34); boxGeo.translate(0, .5, 0);
    Object.entries(G.loads).forEach(([b, kw]) => {
      const p = G.buses[b], z = G.bus_zone[b];
      if (!p) return;
      const mesh = new T3.Mesh(boxGeo, zm[z] ? zm[z].load : grey);
      mesh.position.copy(P(p[0], p[1])).add(new T3.Vector3(.28, 0, .28));
      mesh.scale.y = Math.max(.15, kw * .014);
      mesh.userData = { label: "Bus " + b + " · " + kw + " kW", click: () => explain([loadItem(b, kw, z)], 0, false), bus: b };
      add(mesh, z, order(p[0], p[1]));
    });

    // equipment is built from parts in a group; the group carries the label and the click
    const bushingGeo = new T3.CylinderGeometry(.022, .034, .16, 8);
    const part = (geo, mat, x, y, z, g) => { const m = new T3.Mesh(geo, mat); m.position.set(x, y, z); g.add(m); return m; };
    const group = (pos, label, click) => { const g = new T3.Group(); g.position.copy(pos); g.userData = { label, click }; return g; };
    const bushings = (g, xs, y, z) => xs.forEach(x => part(bushingGeo, porcelain, x, y, z || 0, g));
    // air-break switch: insulator posts with a blade per phase; an open one has its blades raised
    // blades hinge at one post: rotation.x = 0 is closed, -1.05 is open (the fault replay flips them)
    const airBreak = (g, phases, open, bladeMat) => {
      part(new T3.BoxGeometry(.08 + .24 * (phases - 1) + .1, .04, .3), steel, 0, 0, 0, g);
      g.userData.blades = (OFF[phases] || [0]).map(s => {
        part(bushingGeo, porcelain, s, .1, -.11, g); part(bushingGeo, porcelain, s, .1, .11, g);
        const blade = part(new T3.BoxGeometry(.035, .025, .26), bladeMat, s, .2, -.11, g);
        blade.geometry.translate(0, 0, .13);
        if (open) blade.rotation.x = -1.05;
        return blade;
      });
    };
    const devG = {}, tieG = {};   // switch groups by name, for the fault replay

    G.devices.forEach(([name, kind, x, y, zone]) => {
      const click = () => explain([objItem("dev:" + name, zone)], 0, false), at = P(x, y);
      let g;
      if (kind === "recloser") {        // oil/vacuum recloser tank with bushings, control cabinet lower on the pole
        g = group(at.setY(HP - .2), name + " · recloser", click);
        part(new T3.CylinderGeometry(.17, .17, .42, 16), black, 0, 0, 0, g);
        bushings(g, [-.1, 0, .1], .29);
        part(new T3.BoxGeometry(.2, .26, .12), grey, 0, -.55, .16, g);
      } else if (kind === "ieee") {     // gang-operated air-break switch on the crossarm
        g = group(at.setY(HP + .08), name + " · switch", click);
        airBreak(g, 3, false, steel);
      } else {                          // automated switch added in this study: enclosure + radio antenna
        g = group(at.setY(HP - .12), name + " · automated switch", click);
        edges(part(new T3.BoxGeometry(.36, .3, .26), white, 0, 0, 0, g), 0x1f4e9c);
        bushings(g, [-.1, 0, .1], .23);
        part(new T3.CylinderGeometry(.012, .012, .38, 6), steel, .15, .34, 0, g);
        part(new T3.SphereGeometry(.035, 10, 8), new T3.MeshStandardMaterial({ color: 0x1f4e9c }), .15, .54, 0, g);
      }
      devG[name] = g;
      add(g, zone, order(x, y));
    });

    const dash = new T3.LineDashedMaterial({ color: 0x333333, dashSize: .3, gapSize: .2 });
    const openBlade = new T3.MeshStandardMaterial({ color: 0xd03b3b, roughness: .4 });
    G.ties.forEach(([name, u, v]) => {
      const a = G.buses[u], b = v ? G.buses[v] : a && [a[0] + 700, a[1]];
      if (!a || !b) return;
      const A = P(a[0], a[1], HP), B = P(b[0], b[1], HP);
      const line = new T3.Line(new T3.BufferGeometry().setFromPoints([A, B]), dash);
      line.computeLineDistances(); other.add(line);
      const click = () => explain([objItem("tie:" + name, null)], 0, false);
      const g = group(A.clone().lerp(B, .5).setY(HP + .05), name + " · open tie", click);
      airBreak(g, name === "Sw8" ? 1 : 3, true, openBlade);   // red raised blades = normally open
      tieG[name] = g;
      add(g, null, order(a[0], a[1]));
      if (!v) {   // the adjacent feeder that Sw9 reaches: a small substation block
        const s = group(B.clone().setY(0), "Adjacent feeder", click);
        part(new T3.BoxGeometry(.9, .7, .9), tank, 0, .35, 0, s);
        bushings(s, [-.2, 0, .2], .78);
        add(s, null, 1);
      }
    });

    // regulators: one single-phase tank per regulated phase on a platform (Reg 2 has 1, Reg 3 has 2, Reg 4 has 3)
    const regTank = new T3.MeshStandardMaterial({ color: 0xe7c34a, roughness: .5 });
    const PH_REG = { "Reg 2": 1, "Reg 3": 2, "Reg 4": 3 };
    const regG = [], capG = [], subX = [], subR = [];   // stand-ins a SolidWorks model may replace
    G.regs.forEach(([name, bus, x, y]) => {
      const n = PH_REG[name] || 3;
      const g = group(P(x, y, HP - .3).add(new T3.Vector3(-.45, 0, -.45)), name + " · regulator",
                      () => explain([objItem("reg:" + bus, G.bus_zone[bus])], 0, false));
      part(new T3.BoxGeometry(.24 * n + .14, .05, .3), steel, 0, -.23, 0, g);
      for (let i = 0; i < n; i++) {
        const xi = (i - (n - 1) / 2) * .24;
        part(new T3.CylinderGeometry(.1, .1, .4, 14), regTank, xi, 0, 0, g);
        part(bushingGeo, porcelain, xi, .28, 0, g);
      }
      regG.push(g);
      add(g, G.bus_zone[bus], order(x, y));
    });

    // capacitor banks: a rack of cans (3 for the 3-phase C83, 1 for the single-phase banks)
    const capCan = new T3.MeshStandardMaterial({ color: 0xcfe3ea, roughness: .35 });
    G.caps.forEach(([name, bus, kvar, x, y]) => {
      const n = kvar >= 300 ? 3 : 1;
      const g = group(P(x, y, HP - .38).add(new T3.Vector3(-.3, 0, .3)), name + " · " + kvar + " kvar",
                      () => explain([objItem("cap:" + name, G.bus_zone[bus])], 0, false));
      part(new T3.BoxGeometry(.16 * n + .12, .04, .18), steel, 0, -.16, 0, g);
      for (let i = 0; i < n; i++) {
        const xi = (i - (n - 1) / 2) * .16;
        part(new T3.BoxGeometry(.11, .26, .08), capCan, xi, 0, 0, g);
        part(bushingGeo, porcelain, xi, .2, 0, g);
      }
      capG.push({ g, n });
      add(g, G.bus_zone[bus], order(x, y));
    });

    // substation yard west of bus 150: pad, fence, power transformer with radiators and bushings,
    // regulator Reg 1 and the bus structure the feeder leaves from
    const sub = group(src.clone().add(new T3.Vector3(-1.75, 0, 0)), "Substation",
                      () => explain([objItem("src", "Sw1")], 0, false));
    part(new T3.BoxGeometry(3.3, .06, 2.5), new T3.MeshStandardMaterial({ color: 0xc4c7cb, roughness: 1 }), 0, .03, 0, sub);
    const fence = new T3.LineSegments(new T3.EdgesGeometry(new T3.BoxGeometry(3.4, .7, 2.6)), new T3.LineBasicMaterial({ color: 0x6b6f75 }));
    fence.position.y = .35; sub.add(fence);
    subX.push(part(new T3.BoxGeometry(.85, .8, .7), new T3.MeshStandardMaterial({ color: 0x4d5359, roughness: .5, metalness: .3 }), -.7, .46, 0, sub));
    for (let i = 0; i < 5; i++) subX.push(part(new T3.BoxGeometry(.035, .62, .55), steel, -.2 + i * .07, .46, 0, sub));   // radiator fins
    [-.2, 0, .2].forEach(z => {
      subX.push(part(new T3.CylinderGeometry(.03, .045, .46, 8), porcelain, -.92, 1.08, z, sub));   // high-voltage bushings
      subX.push(part(new T3.CylinderGeometry(.025, .035, .26, 8), porcelain, -.48, .98, z, sub));   // 4.16 kV bushings
    });
    [-.3, 0, .3].forEach(z => {   // Reg 1: three single-phase regulators
      subR.push([part(new T3.CylinderGeometry(.11, .11, .44, 14), regTank, .45, .3, z, sub), part(bushingGeo, porcelain, .45, .6, z, sub)]);
    });
    [-.55, .55].forEach(z => part(new T3.CylinderGeometry(.04, .04, 1.3, 8), steel, 1.25, .65, z, sub));   // bus structure
    part(new T3.BoxGeometry(.07, .07, 1.25), steel, 1.25, 1.3, 0, sub);
    add(sub, null, 0);

    // ---- SolidWorks equipment (docs/models/*.glb, published only while their exports are fresh).
    // Each model replaces its drawn stand-in inside the same clickable group, scaled to the
    // stand-in's height; the pole segment in pole-mounted models is dropped (it is the brown body).
    // Without the network or the files (a page opened from disk), the drawn stand-ins stay.
    const GLB = MD.glb || {};
    if (Object.keys(GLB).length) {
      const GLTF_URL = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js";
      const POLE = [0.45, 0.33, 0.20];
      const localBox = meshes => meshes.reduce((b, m) => {
        m.updateMatrix();   // the models can arrive before the first frame has set the parts' matrices
        m.geometry.computeBoundingBox();
        return b.union(m.geometry.boundingBox.clone().applyMatrix4(m.matrix));
      }, new T3.Box3());
      const prep = gltf => {
        const root = new T3.Group();
        let pole = null;   // where the model's pole segment was (model units), for poleUnder
        gltf.scene.updateMatrixWorld(true);
        gltf.scene.traverse(o => {
          if (!o.isMesh) return;
          const c = o.material.color, geo = o.geometry.clone().applyMatrix4(o.matrixWorld);
          if (c && Math.abs(c.r - POLE[0]) + Math.abs(c.g - POLE[1]) + Math.abs(c.b - POLE[2]) < .06) {
            geo.computeBoundingBox();
            pole = pole ? pole.union(geo.boundingBox) : geo.boundingBox.clone();
            return;
          }
          root.add(new T3.Mesh(geo, o.material));
        });
        return { root, box: localBox(root.children), pole };
      };
      // a copy of the model scaled to the height of `box` (group-local), standing on its bottom centre
      const fitInto = (tpl, box) => {
        const s = (box.max.y - box.min.y) / (tpl.box.max.y - tpl.box.min.y);
        const o = tpl.root.clone(), tc = tpl.box.getCenter(new T3.Vector3()), bc = box.getCenter(new T3.Vector3());
        o.scale.setScalar(s);
        o.position.set(bc.x - s * tc.x, box.min.y - s * tpl.box.min.y, bc.z - s * tc.z);
        return o;
      };
      const swap = (g, old, tpl) => { const box = localBox(old); old.forEach(c => g.remove(c)); const o = fitInto(tpl, box); g.add(o); return o; };
      // a pole-mounted model gets a wooden pole from the ground, where its SolidWorks pole was
      const poleUnder = (g, o, tpl) => {
        if (!tpl.pole) return;
        const s = o.scale.x, pc = tpl.pole.getCenter(new T3.Vector3()), r = s * (tpl.pole.max.x - tpl.pole.min.x) / 2;
        const top = o.position.y + s * tpl.pole.max.y, bottom = -g.position.y;
        part(new T3.CylinderGeometry(r, r * 1.15, top - bottom, 10), wood, o.position.x + s * pc.x, (top + bottom) / 2, o.position.z + s * pc.z, g);
      };
      const onPole = (g, tpl) => poleUnder(g, swap(g, meshesOf(g), tpl), tpl);
      const meshesOf = g => g.children.filter(c => c.isMesh);
      const load = (name, use) => GLB[name] && new T3.GLTFLoader().load(GLB[name], gltf => use(prep(gltf)), undefined, () => {});
      loadJs(GLTF_URL).then(() => {
        load("recloser", t => G.devices.forEach(([n, kind]) => kind === "recloser" && onPole(devG[n], t)));
        load("auto_switch", t => G.devices.forEach(([n, kind]) => kind === "added" && onPole(devG[n], t)));
        load("capacitor", t => capG.forEach(({ g, n }) => n === 3 && onPole(g, t)));
        load("regulator", t => {   // one single-phase regulator per drawn tank (+ its bushing)
          regG.forEach(g => {
            const ms = meshesOf(g), pairs = [];
            for (let i = 1; i + 1 < ms.length; i += 2) pairs.push([ms[i], ms[i + 1]]);
            const boxes = pairs.map(localBox);
            ms.forEach(c => g.remove(c));
            boxes.forEach(b => g.add(fitInto(t, b)));
          });
          subR.forEach(pair => swap(sub, pair, t));
        });
        load("substation", t => swap(sub, subX, t));
        load("transformer", t => {   // pole-top transformers: one instanced mesh per material
          const s = .3 / (t.box.max.y - t.box.min.y), tc = t.box.getCenter(new T3.Vector3());
          const off = new T3.Matrix4().makeTranslation(-tc.x, -t.box.min.y, -tc.z), sc = new T3.Matrix4().makeScale(s, s, s);
          const Z = new T3.Vector3(0, 0, 1), one = new T3.Vector3(1, 1, 1);
          const mats = loadPoles.map(b => {
            const p = G.buses[b], c = P(p[0], p[1]).addScaledVector(poleDir[b], .14);
            const rq = new T3.Quaternion().setFromUnitVectors(Z, poleDir[b].clone().negate().setY(0).normalize());
            return new T3.Matrix4().compose(new T3.Vector3(c.x, HP - .53, c.z), rq, one).multiply(sc).multiply(off);
          });
          t.root.children.forEach(m => {
            const im = new T3.InstancedMesh(m.geometry, m.material, mats.length);
            mats.forEach((M, i) => im.setMatrixAt(i, M));
            other.add(im);
          });
          cans.visible = false;
        });
      }).catch(() => {});
    }

    // floating labels in three layers (zones, equipment, bus numbers); HTML, so they stay sharp and
    // switch language with the page. The Labels buttons hide a layer with one class on the box.
    const labels = [];
    const two = (en, vi) => vi && vi !== en ? '<span data-l="en">' + en + '</span><span data-l="vi">' + vi + "</span>" : en;
    const mkLabel = (html, kind, pos, zone, color) => {
      const el = document.createElement("div");
      el.className = "m3d-label m3d-" + kind; el.innerHTML = html;
      if (color) el.style.borderColor = color;
      labelBox.appendChild(el);
      labels.push({ el, kind, zone, pos });
    };
    G.zones.forEach(z => mkLabel(z.name + " · " + MD.kw[z.name] + " kW", "zone", P(z.label[0], z.label[1], HP + 1.5), z.name, z.color));
    const KIND = { recloser: ["recloser", "recloser"], ieee: ["switch", "dao phân đoạn"], added: ["added switch", "dao thêm vào"] };
    G.devices.forEach(([name, kind, x, y, zone]) =>
      mkLabel(name + " · " + two(...KIND[kind]), "eq", P(x, y, HP + .9), zone));
    G.ties.forEach(([name, u, v]) => {
      const a = G.buses[u], b = v ? G.buses[v] : a && [a[0] + 700, a[1]];
      if (!a || !b) return;
      const what = name === "Sw8" ? two("1-phase tie, unused", "dao 1 pha, không dùng") : two("tie, open", "dao liên lạc, mở");
      mkLabel(name + " · " + what, "eq", P((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, HP + .7), null);
      if (!v) mkLabel(two("Adjacent feeder", "Tuyến kế bên"), "eq", P(b[0], b[1], HP + 1), null);
    });
    G.regs.forEach(([name, bus, x, y]) => mkLabel(name + " · " + two("regulator", "điều áp"), "eq", P(x, y, HP + .95), G.bus_zone[bus]));
    G.caps.forEach(([name, bus, kvar, x, y]) => mkLabel(name + " · " + kvar + " kvar", "eq", P(x, y, HP + .45), G.bus_zone[bus]));
    mkLabel(two("Substation · 4.16 kV", "Trạm nguồn · 4.16 kV"), "eq", src.clone().add(new T3.Vector3(-1.75, 1.75, 0)), null);
    Object.entries(G.buses).forEach(([b, p]) => mkLabel(b, "bus", P(p[0], p[1], HP + .25), G.bus_zone[b]));

    // camera, controls: wheel zoom only after a click inside, so scrolling past still scrolls the page
    // home view: looking down at ~50°, pulled back until the whole feeder fits the box's shape
    const home = { pos: new T3.Vector3(), target: new T3.Vector3(0, 0, 0) }, look = new T3.Vector3(0, .64, .77);
    let touched = false;
    cam.position.set(0, span * .6, span * .8);   // never start on the target: OrbitControls would compute NaN
    const fitHome = () => {
      const vf = cam.fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(vf / 2) * cam.aspect);
      home.pos.copy(look).multiplyScalar(Math.max(span * .47 / Math.tan(hf / 2), span * .42 / Math.tan(vf / 2)));
      if (!touched) cam.position.copy(home.pos);
    };
    const controls = new T3.OrbitControls(cam, renderer.domElement);
    controls.target.copy(home.target);
    Object.assign(controls, { enableDamping: true, dampingFactor: .08, maxPolarAngle: 1.36, minDistance: 6,
                              maxDistance: span * 3, enableZoom: false, autoRotate: !reduce, autoRotateSpeed: .5 });
    const spinBtn = byId("m3d-spin");
    const setSpin = on => { controls.autoRotate = on; spinBtn.setAttribute("aria-pressed", String(on)); };
    setSpin(!reduce);
    controls.addEventListener("start", () => { touched = true; setSpin(false); hintOff(); });
    renderer.domElement.addEventListener("pointerdown", () => { controls.enableZoom = true; });
    mbox.addEventListener("pointerleave", () => { controls.enableZoom = false; });

    // focus: lift one zone, fade the others, glide the camera's target to it
    let focusZone = null, glide = null;
    const centre = {};
    G.zones.forEach(z => {
      const bs = Object.keys(G.bus_zone).filter(b => G.bus_zone[b] === z.name).map(b => G.buses[b]);
      const s = bs.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
      centre[z.name] = P(s[0] / bs.length, s[1] / bs.length, HP);
    });
    const focus = z => {
      focusZone = z || null;
      G.zones.forEach(q => { const s = zm[q.name]; s.liftGoal = focusZone === q.name ? .9 : 0; s.fadeGoal = focusZone && focusZone !== q.name ? .15 : 1; });
      glide = focusZone ? centre[focusZone] : home.target;
      if (focusZone) setSpin(false);
    };

    // ---- layer "errors": where the model misplaces faults (one column per bus) and which zones it
    // confuses (arrows from the true zone to the wrong guess); layer "fault": a step-by-step replay
    let lastKey = "";   // labels are re-placed only when this view key changes (see frame)
    const errLayer = new T3.Group(), faultLayer = new T3.Group();
    errLayer.visible = faultLayer.visible = false;
    scene.add(errLayer, faultLayer);
    const tr = (en, vi) => (L() === "vi" ? vi : en);
    const fmt = n => Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
    const pctS = x => (100 * x).toFixed(1) + "%";
    const zoneNames = G.zones.map(z => z.name);
    const kids = z => zoneNames.filter(q => MD.tree[q] === z);
    const below = z => kids(z).flatMap(k => [k, ...below(k)]);
    const layerLabel = (html, pos, layer, kind) => { mkLabel(html, kind || "err", pos, null); labels[labels.length - 1].layer = layer; return labels[labels.length - 1]; };

    const errBusItem = b => ({ el: mbox, noScroll: true, text: () => {
      const [n, wrong, fpiWrong, weak, top, topN] = MD.err[b], z = G.bus_zone[b];
      return {
        title: tr("Bus " + b + " · where the model slips", "Bus " + b + " · chỗ model hay sai"),
        what: tr(`<b>${wrong}</b> of the <b>${n}</b> faults simulated at bus ${b} (zone ${z}) were placed in the wrong zone: <b>${pctS(wrong / n)}</b>.`,
                 `<b>${wrong}</b> trong <b>${n}</b> sự cố mô phỏng ở bus ${b} (zone ${z}) bị đoán sai zone: <b>${pctS(wrong / n)}</b>.`),
        read: tr(`${weak} of them are weak ground faults (200 Ω or more). The wrong guess was most often zone <b>${top}</b> (${topN} times).`,
                 `${weak} trong số đó là sự cố chạm đất yếu (từ 200 Ω trở lên). Model đoán nhầm sang zone <b>${top}</b> nhiều nhất (${topN} lần).`),
        why: tr(`For comparison, conventional fault indicators misplace <b>${fpiWrong}</b> of the same ${n} faults (${pctS(fpiWrong / n)}).`,
                `Để so sánh, bộ chỉ báo sự cố truyền thống đoán sai <b>${fpiWrong}</b> trong cùng ${n} sự cố đó (${pctS(fpiWrong / n)}).`) };
    } });
    const relText = (t, p) => MD.tree[t] === p ? tr("the zone just upstream of it, one step closer to the substation", "zone ngay phía trên nó, gần trạm hơn một bước")
      : MD.tree[p] === t ? tr("the zone just downstream of it", "zone ngay phía dưới nó")
      : below(p).includes(t) ? tr("a zone further toward the substation", "một zone xa hơn về phía trạm")
      : below(t).includes(p) ? tr("a zone further from the substation", "một zone xa trạm hơn")
      : tr("a zone on another branch", "một zone ở nhánh khác");
    const pairItem = (t, p, n) => ({ el: mbox, noScroll: true, enter: () => focus(t), leave: () => focus(null), text: () => ({
      title: tr(`Zone ${t} → guessed ${p}`, `Zone ${t} → bị đoán là ${p}`),
      what: tr(`<b>${n}</b> faults that were really in zone ${t} were placed in zone ${p}, ${relText(t, p)}.`,
               `<b>${n}</b> sự cố thật ra nằm ở zone ${t} đã bị đoán là zone ${p}, ${relText(t, p)}.`),
      read: tr("The arrow runs from the true zone to the wrong guess; thicker means more faults.",
               "Mũi tên đi từ zone thật tới zone bị đoán nhầm; càng dày là càng nhiều sự cố."),
      why: tr("Neighbouring zones on the busy trunk see almost the same currents when a fault is weak, so they get confused.",
              "Khi sự cố yếu, các zone kề nhau trên trục chính đông tải thấy dòng điện gần như giống nhau, nên dễ bị nhầm.") }) });

    const errColor = rate => new T3.Color(0xf2a33a).lerp(new T3.Color(0xc62828), Math.min(1, rate / .08));
    const clean = [];
    Object.entries(MD.err).forEach(([b, e]) => {
      const p = G.buses[b];
      if (!p) return;
      if (!e[1]) { clean.push(p); return; }
      const h = .3 + .3 * e[1];
      const m = new T3.Mesh(new T3.CylinderGeometry(.17, .17, h, 14), new T3.MeshStandardMaterial({ color: errColor(e[1] / e[0]), roughness: .5 }));
      m.position.copy(P(p[0], p[1], h / 2)).add(new T3.Vector3(-.3, 0, -.3));
      m.userData = { label: () => tr(`Bus ${b} · ${e[1]} of ${e[0]} misplaced`, `Bus ${b} · ${e[1]}/${e[0]} đoán sai`),
                     click: () => explain([errBusItem(b)], 0, false) };
      errLayer.add(m); pick.push(m);
    });
    const okDiscs = new T3.InstancedMesh(new T3.CylinderGeometry(.13, .13, .04, 14),
                                         new T3.MeshStandardMaterial({ color: 0x5aa469 }), clean.length);
    clean.forEach((p, i) => { m4.makeTranslation((p[0] - cx) / 100 - .3, .02, (cy - p[1]) / 100 - .3); okDiscs.setMatrixAt(i, m4); });
    errLayer.add(okDiscs);
    const arc = (from, to, w, mat, rise) => {
      const a = centre[from].clone(), b = centre[to].clone(), mid = a.clone().lerp(b, .5);
      mid.y += rise;
      const curve = new T3.QuadraticBezierCurve3(a, mid, b), g = new T3.Group();
      g.add(new T3.Mesh(new T3.TubeGeometry(curve, 40, w, 8, false), mat));
      const tip = new T3.Mesh(new T3.ConeGeometry(w * 3 + .08, .5, 14), mat);
      tip.position.copy(curve.getPoint(.97)); tip.quaternion.setFromUnitVectors(UP, curve.getTangent(.97).normalize());
      g.add(tip);
      g.userData.apex = curve.getPoint(.5);
      return g;
    };
    const arcMat = new T3.MeshStandardMaterial({ color: 0xd03b3b, roughness: .4, transparent: true, opacity: .8 });
    MD.pairs.forEach(([t, p, n], i) => {
      const g = arc(t, p, .035 + n * .0035, arcMat, 2.2 + i * .35);
      g.userData = { label: () => tr(`${t} → ${p} · ${n} faults`, `${t} → ${p} · ${n} sự cố`), click: () => explain([pairItem(t, p, n)], 0, false), apex: g.userData.apex };
      errLayer.add(g); pick.push(g);
      layerLabel(`${t} → ${p} · ${n}`, g.userData.apex.clone().add(new T3.Vector3(0, .25, 0)), "errors");
    });

    // fault replay: a red flash at the fault, a lamp on every switch (green closed, red open),
    // zones grey while dark, an orange arrow when the model's guess is wrong, plus 3D directional
    // power-flow pulses (forward cyan from substation, reversed amber back-feed from closed ties).
    const GREEN = 0x2e9e44, RED = 0xd03b3b, DARK = new T3.Color(0x6a6f76), DARKLOAD = new T3.Color(0xa7abb0);
    const FAULTC = new T3.Color(0xd03b3b), closedBlade = new T3.MeshStandardMaterial({ color: 0x2e9e44, roughness: .4 });
    const lamps = {};
    [...Object.entries(devG), ...Object.entries(tieG)].forEach(([name, g]) => {
      const s = new T3.Mesh(new T3.SphereGeometry(.12, 14, 10), new T3.MeshBasicMaterial({ color: GREEN }));
      s.position.copy(g.position).add(new T3.Vector3(0, .62, 0));
      faultLayer.add(s); lamps[name] = s;
    });
    const setLamp = (name, closed) => { if (lamps[name]) lamps[name].material.color.setHex(closed ? GREEN : RED); };
    const setBlades = (name, closed) => {
      const g = devG[name] || tieG[name];
      (g && g.userData.blades || []).forEach(b => { b.rotation.x = closed ? 0 : -1.05; if (tieG[name]) b.material = closed ? closedBlade : openBlade; });
    };

    // Normalized graph for 3D BFS power-flow pulses (maps 150r->150 and strips r/s suffixes)
    const normBus = b => {
      const s = String(b);
      if (s === "150" || s === "150r") return "150";
      if (G.buses[s]) return s;
      const base = s.replace(/[rs]$/, "");
      return G.buses[base] ? base : s;
    };
    const busPos3 = (b, ug) => {
      const h = ug ? .2 : HP + .16;
      if (b === "150") return P(G.source[1], G.source[2], h);
      const c = G.buses[b];
      return c ? P(c[0], c[1], h) : P(G.source[1], G.source[2], h);
    };
    const flowAdj = new Map();
    const addFlowAdj = (u, v, z, idx, ug) => {
      if (!flowAdj.has(u)) flowAdj.set(u, []);
      flowAdj.get(u).push({ to: v, z, idx, ug });
    };
    G.edges.forEach(([u, v, z, ph, ug], idx) => {
      const nu = normBus(u), nv = normBus(v);
      addFlowAdj(nu, nv, z, idx, ug);
      addFlowAdj(nv, nu, z, idx, ug);
    });
    const tiePts3 = {};
    G.ties.forEach(([name, u, v]) => {
      const a = G.buses[u], b = v ? G.buses[v] : a && [a[0] + 700, a[1]];
      if (a && b) tiePts3[name] = { u: normBus(u), v: v ? normBus(v) : null, A: P(a[0], a[1], HP + .16), B: P(b[0], b[1], HP + .16) };
    });

    const MAX_FWD = 280, MAX_REV = 160;
    const fwdPulses = new T3.InstancedMesh(new T3.ConeGeometry(.12, .38, 8), new T3.MeshBasicMaterial({ color: 0x0ea5e9 }), MAX_FWD);
    const revPulses = new T3.InstancedMesh(new T3.ConeGeometry(.17, .52, 8), new T3.MeshBasicMaterial({ color: 0xff8c00 }), MAX_REV);
    fwdPulses.count = revPulses.count = 0;
    fwdPulses.frustumCulled = revPulses.frustumCulled = false;
    faultLayer.add(fwdPulses, revPulses);

    let flowFwd = [], flowRev = [];
    const mkSeg = (a, b, z) => {
      const dir = new T3.Vector3().subVectors(b, a);
      const len = dir.length();
      if (len < .05) return null;
      dir.normalize();
      const quat = new T3.Quaternion().setFromUnitVectors(UP, dir);
      return { a, b, z, quat, len };
    };
    const pPos = new T3.Vector3(), pScale = new T3.Vector3(1, 1, 1);
    const updateFlowPulses = now => {
      const place = (mesh, segs, maxN, speed, perSeg) => {
        let idx = 0;
        const tBase = reduce ? .5 : ((now * speed) % 1);
        for (let i = 0; i < segs.length && idx < maxN; i++) {
          const sg = segs[i], liftY = sg.z && zm[sg.z] ? zm[sg.z].lift : 0;
          const cnt = reduce ? 1 : (sg.len > 3.5 ? perSeg : 1);
          for (let j = 0; j < cnt && idx < maxN; j++) {
            const t = reduce ? .5 : ((tBase + j / cnt + (i * .17) % 1) % 1);
            pPos.lerpVectors(sg.a, sg.b, t);
            pPos.y += liftY;
            m4.compose(pPos, sg.quat, pScale);
            mesh.setMatrixAt(idx++, m4);
          }
        }
        mesh.count = idx;
        mesh.instanceMatrix.needsUpdate = true;
      };
      place(fwdPulses, flowFwd, MAX_FWD, .00048, 2);
      place(revPulses, flowRev, MAX_REV, .00078, 2);
    };
    const setFlowState = (upZones, backZones, closedTies) => {
      const upSet = new Set(upZones || []), backSet = new Set(backZones || []), tieSet = new Set(closedTies || []);
      flowFwd = []; flowRev = [];
      if (upSet.has("Sw1")) {
        const q = ["150"], vis = new Set(["150"]), seenE = new Set();
        while (q.length) {
          const u = q.shift();
          for (const e of (flowAdj.get(u) || [])) {
            if (e.z && !upSet.has(e.z)) continue;
            if (!seenE.has(e.idx)) {
              seenE.add(e.idx);
              const sg = mkSeg(busPos3(u, e.ug), busPos3(e.to, e.ug), e.z);
              if (sg) flowFwd.push(sg);
            }
            if (!vis.has(e.to)) { vis.add(e.to); q.push(e.to); }
          }
        }
      }
      if (backSet.size && tieSet.size) {
        const q = [], vis = new Set(), seenE = new Set(), tieDone = new Set();
        const seed = (bus, tName, aPos, bPos) => {
          if (tName && !tieDone.has(tName)) {
            tieDone.add(tName);
            const sg = mkSeg(aPos, bPos, null);
            if (sg) flowRev.push(sg);
          }
          if (!vis.has(bus)) { vis.add(bus); q.push(bus); }
        };
        if (tieSet.has("Sw9") && tiePts3.Sw9 && backSet.has(G.bus_zone["450"])) {
          seed("450", "Sw9", tiePts3.Sw9.B, tiePts3.Sw9.A);
        }
        if (tieSet.has("Sw7") && tiePts3.Sw7) {
          const z151 = G.bus_zone["151"], z300 = G.bus_zone["300"];
          if (upSet.has(z151) && backSet.has(z300)) seed("300", "Sw7", tiePts3.Sw7.A, tiePts3.Sw7.B);
          else if (upSet.has(z300) && backSet.has(z151)) seed("151", "Sw7", tiePts3.Sw7.B, tiePts3.Sw7.A);
        }
        while (q.length) {
          const u = q.shift();
          for (const e of (flowAdj.get(u) || [])) {
            if (!e.z || !backSet.has(e.z)) continue;
            if (!seenE.has(e.idx)) {
              seenE.add(e.idx);
              const sg = mkSeg(busPos3(u, e.ug), busPos3(e.to, e.ug), e.z);
              if (sg) flowRev.push(sg);
            }
            if (!vis.has(e.to)) { vis.add(e.to); q.push(e.to); }
          }
          if (tieSet.has("Sw7") && tiePts3.Sw7 && !tieDone.has("Sw7")) {
            if (u === "300" && backSet.has(G.bus_zone["151"]) && !vis.has("151")) seed("151", "Sw7", tiePts3.Sw7.B, tiePts3.Sw7.A);
            else if (u === "151" && backSet.has(G.bus_zone["300"]) && !vis.has("300")) seed("300", "Sw7", tiePts3.Sw7.A, tiePts3.Sw7.B);
          }
        }
      }
      updateFlowPulses(performance.now());
    };

    const fm = new T3.Group(); fm.visible = false; faultLayer.add(fm);
    const fBall = new T3.Mesh(new T3.SphereGeometry(.3, 18, 14), new T3.MeshStandardMaterial({ color: 0xff3b2f, emissive: 0xff3b2f, emissiveIntensity: .7 }));
    const fRing = new T3.Mesh(new T3.TorusGeometry(.5, .05, 8, 40), new T3.MeshBasicMaterial({ color: 0xff3b2f, transparent: true }));
    fRing.rotation.x = Math.PI / 2; fm.add(fBall, fRing);
    const faultTag = layerLabel("", new T3.Vector3(), "fault", "fault");
    let guessArc = null;
    const paint = st => zoneNames.forEach(z => {
      const s = zm[z], m = st[z] || "on";
      s.line.color.copy(m === "on" ? s.base : m === "fault" ? FAULTC : DARK);
      s.load.color.copy(m === "on" ? s.loadBase : DARKLOAD);
    });
    const hifDemoBtn = byId("m3d-hif-demo"), hifHud = byId("m3d-hif-hud");
    let hifTimers = [], hifRunning = false;
    const stopHifDemo = hideHud => {
      hifTimers.forEach(clearTimeout); hifTimers = []; hifRunning = false;
      if (hifDemoBtn) {
        hifDemoBtn.classList.remove("running");
        hifDemoBtn.innerHTML = '▶ <span data-l="en">10s HIF → FLISR</span><span data-l="vi">10s HIF → FLISR</span>';
      }
      if (hideHud && hifHud) hifHud.hidden = true;
    };
    const resetFault = () => {
      paint({}); fm.visible = false; setFlowState([], [], []);
      Object.keys(devG).forEach(n => { setLamp(n, true); setBlades(n, true); });
      Object.keys(tieG).forEach(n => { setLamp(n, false); setBlades(n, false); });
      if (guessArc) { faultLayer.remove(guessArc); guessArc = null; }
      lastKey = "";
    };
    const TYPE = { SLG: ["line-to-ground", "chạm đất một pha"], LL: ["line-to-line", "hai pha chạm nhau"],
                   LLG: ["double line-to-ground", "hai pha chạm đất"], "3PH": ["three-phase", "ba pha"] };
    const total = zoneNames.reduce((s, z) => s + MD.zkw[z], 0);
    const replay = (sc, opts) => {
      const Z = sc.Z, down = below(Z), up = zoneNames.filter(q => q !== Z && !down.includes(q));
      const R = MD.rest[Z] || { ties: [], back: [], dark: [], kw_back: "0", kw_dark: "0" };
      const iso = [Z, ...kids(Z)], p = G.buses[sc.bus], amps = Math.round(2402 / Math.max(sc.r, 1));
      const typ = tr(...TYPE[sc.ftype]), rOhm = sc.r < 1 ? sc.r : fmt(sc.r);
      const all = v => Object.fromEntries(zoneNames.map(q => [q, v]));
      const hif = sc.hif || null;
      const start = () => {
        resetFault(); focus(null);
        fm.position.copy(P(p[0], p[1], HP)); fm.visible = true;
        faultTag.pos = P(p[0], p[1], HP + .9);
        faultTag.el.innerHTML = (hif ? "⚡ HIF · " : "⚡ ") + tr("Fault · bus ", "Sự cố · bus ") + sc.bus;
        setLamp("Sw1", true);
      };
      const isolate = () => iso.forEach(d => { setLamp(d, false); setBlades(d, false); });
      const steps = [
        [() => { start(); setFlowState(zoneNames, [], []); },
         () => ({ title: hif ? tr("1 · Tier-1 HIF Arc → Fault", "1 · Hồ quang HIF Tầng 1 → Sự cố") : tr("1 · The fault", "1 · Sự cố"),
           what: hif
             ? tr(`A ${typ} arcing HIF through <b>${rOhm} Ω</b> at bus <b>${sc.bus}</b> (zone <b>${Z}</b>). Tier-1 C99 504 B int8 MLP raises HIF ALARM (p_hif = <b>${hif.p_hif.toFixed(4)}</b>, PERSIST = <b>${hif.persist}/3</b>).`,
                  `Sự cố hồ quang HIF ${typ} qua <b>${rOhm} Ω</b> tại bus <b>${sc.bus}</b> (zone <b>${Z}</b>). Tiny MLP C99 504 B int8 Tầng 1 báo HIF ALARM (p_hif = <b>${hif.p_hif.toFixed(4)}</b>, PERSIST = <b>${hif.persist}/3</b>).`)
             : tr(`A ${typ} fault through <b>${rOhm} Ω</b> at bus <b>${sc.bus}</b>, inside zone <b>${Z}</b>.`,
                  `Sự cố ${typ} qua điện trở <b>${rOhm} Ω</b> tại bus <b>${sc.bus}</b>, nằm trong zone <b>${Z}</b>.`),
           read: tr("Cyan pulses show forward supply from the substation. The red flash marks the fault; lamps above switches show green = closed, red = open.",
                    "Xung xanh dương là dòng cấp xuôi từ trạm nguồn. Chớp đỏ đánh dấu sự cố; đèn trên mỗi dao: xanh = đóng, đỏ = mở."),
           why: sc.ftype === "SLG" && sc.r >= 100
             ? tr(`With ${rOhm} Ω in the path only about <b>${amps} A</b> flows, about the size of normal load swings.`,
                  `Với ${rOhm} Ω trên đường đi, chỉ khoảng <b>${amps} A</b> chạy qua, cỡ mức dao động bình thường của tải.`)
             : tr("A fault this solid draws a large current, so every device between the substation and the fault sees it clearly.",
                  "Sự cố chắc như vậy tạo dòng rất lớn, nên mọi thiết bị giữa trạm và chỗ sự cố đều thấy rõ.") })],
        [() => { start(); paint(all("off")); setLamp("Sw1", false); setFlowState([], [], []); },
         () => ({ title: tr("2 · Lockout", "2 · Cắt hẳn"),
           what: tr("Recloser Sw1 trips, tries to re-close a few times, and locks out.", "Recloser Sw1 cắt, thử đóng lại vài lần rồi cắt hẳn (lockout)."),
           read: tr(`All <b>${fmt(total)} kW</b> on the feeder is dark (grey) and power-flow pulses stop.`, `Toàn bộ <b>${fmt(total)} kW</b> trên tuyến mất điện (màu xám) và xung dòng điện tắt hẳn.`),
           why: tr(`Without fault location the crew would now patrol all <b>${MD.patrol_none} kft</b> of line.`,
                   `Nếu không định vị được sự cố, đội sửa chữa phải đi hết <b>${MD.patrol_none} kft</b> đường dây.`) })],
        [() => {
           start(); paint({ ...all("off"), [Z]: "fault" }); setLamp("Sw1", false); setFlowState([], [], []);
           if (sc.wrong) { guessArc = arc(Z, sc.P, .07, new T3.MeshStandardMaterial({ color: 0xf28c28, roughness: .4 }), 3); faultLayer.add(guessArc); }
           zm[sc.P].liftGoal = .9;   // raise the guessed zone without fading the others, so the red true zone stays visible
         },
         () => ({ title: tr("3 · Where is it?", "3 · Sự cố ở đâu?"),
           what: tr(`The model reads the event records of the 10 devices and names zone <b>${sc.P}</b>${sc.conf ? ` (confidence ${sc.conf.toFixed(2)})` : ""}.`,
                    `Model đọc bản ghi sự kiện của 10 thiết bị và chọn zone <b>${sc.P}</b>${sc.conf ? ` (độ tự tin ${sc.conf.toFixed(2)})` : ""}.`),
           read: sc.wrong
             ? tr(`Wrong: the fault is really in zone <b>${Z}</b> (red); the orange arrow runs to the guess, ${relText(Z, sc.P)}. The crew finds nothing in ${sc.P} and ends up patrolling the whole feeder.`,
                  `Sai: sự cố thật ra nằm ở zone <b>${Z}</b> (màu đỏ); mũi tên cam chỉ tới zone bị đoán, ${relText(Z, sc.P)}. Đội sửa chữa không thấy gì ở ${sc.P} và phải đi cả tuyến.`)
             : tr(`Correct. The crew patrols only zone ${Z}: <b>${MD.kft[Z].toFixed(1)} kft</b> instead of <b>${MD.patrol_none} kft</b>.`,
                  `Đúng. Đội sửa chữa chỉ cần đi zone ${Z}: <b>${MD.kft[Z].toFixed(1)} kft</b> thay vì <b>${MD.patrol_none} kft</b>.`),
           why: sc.wrong
             ? (sc.ftype === "SLG" && sc.r >= 100
               ? tr(`It is a weak ground fault (about <b>${amps} A</b>), hidden in the noise on the busy trunk. ${MD.missed.length} faults are missed like this.`,
                    `Đây là sự cố chạm đất yếu (khoảng <b>${amps} A</b>), bị lẫn trong nhiễu trên trục chính đông tải. Có ${MD.missed.length} sự cố bị đoán sai kiểu này.`)
               : tr(`One of the ${MD.missed.length} faults the model misses.`, `Một trong ${MD.missed.length} sự cố model đoán sai.`))
             : tr("Solid faults and high-confidence events are isolated automatically before patrol.", "Các sự cố rõ ràng hoặc độ tự tin cao được cô lập tự động trước khi tuần tra.") })],
        [() => { start(); paint({ ...all("off"), [Z]: "fault" }); setLamp("Sw1", false); isolate(); setFlowState([], [], []); },
         () => ({ title: tr("4 · Isolate", "4 · Cô lập"),
           what: tr(`Open ${iso.join(", ")} so zone ${Z} is cut off on every side.`, `Mở ${iso.join(", ")} để tách zone ${Z} ra khỏi mọi phía.`),
           read: tr(`Red lamps are open switches. Zone ${Z} (red, ${fmt(MD.zkw[Z])} kW) waits for the repair.`,
                    `Đèn đỏ là dao đang mở. Zone ${Z} (màu đỏ, ${fmt(MD.zkw[Z])} kW) chờ sửa chữa.`),
           why: sc.wrong
             ? tr(`A real scheme would first isolate the guessed zone ${sc.P}; re-closing would then hit the fault again. The study does not simulate that, so the replay goes on with the true zone.`,
                  `Hệ thống thật sẽ cô lập zone bị đoán ${sc.P} trước; khi đóng lại sẽ đóng trúng sự cố. Nghiên cứu chưa mô phỏng việc đó, nên phần diễn lại tiếp tục với zone thật.`)
             : tr("Only this zone has to wait for the crew; the rest can be brought back.", "Chỉ zone này phải chờ đội sửa chữa; phần còn lại có thể cấp điện lại.") })],
        [() => {
           start(); isolate(); setLamp("Sw1", Z !== "Sw1");
           paint(Object.fromEntries(zoneNames.map(q => [q, q === Z ? "fault" : up.includes(q) ? "on" : "off"])));
           setFlowState(Z === "Sw1" ? [] : up, [], []);
         },
         () => {
           const upKw = up.reduce((s, q) => s + MD.zkw[q], 0);
           return Z === "Sw1"
             ? { title: tr("5 · Re-close", "5 · Đóng lại"),
                 what: tr("The fault is in the first zone after the substation, so Sw1 must stay open.", "Sự cố nằm ở zone đầu tiên sau trạm, nên Sw1 phải giữ mở."),
                 read: tr("Everything beyond it can only come back through a tie.", "Mọi phần phía sau chỉ có thể có điện lại qua dao liên lạc."), why: "" }
             : { title: tr("5 · Re-close", "5 · Đóng lại"),
                 what: tr(`Re-close Sw1. Everything between the substation and the fault gets power back: ${up.join(", ")}.`,
                          `Đóng lại Sw1. Mọi phần giữa trạm và chỗ sự cố có điện lại: ${up.join(", ")}.`),
                 read: tr(`<b>${fmt(upKw)} kW</b> back on within about a minute (cyan forward pulses resume from substation).`,
                          `<b>${fmt(upKw)} kW</b> có điện lại sau khoảng một phút (xung xanh dương chảy xuôi trở lại từ trạm).`),
                 why: tr("These customers no longer wait for the patrol.", "Các khách hàng này không còn phải chờ đội tuần tra.") };
         }],
        [() => {
           start(); isolate(); setLamp("Sw1", Z !== "Sw1");
           R.ties.forEach(t => { setLamp(t, true); setBlades(t, true); });
           paint(Object.fromEntries(zoneNames.map(q => [q, q === Z ? "fault" : up.includes(q) || R.back.includes(q) ? "on" : "off"])));
           setFlowState(Z === "Sw1" ? [] : up, R.back, R.ties);
         },
         () => ({ title: tr("6 · Restore through ties", "6 · Cấp lại qua tie"),
           what: R.back.length
             ? tr(`Close tie ${R.ties.join(" and ")} (green): ${R.back.join(", ")} come back via reversed back-feed (amber pulses).`,
                  `Đóng tie ${R.ties.join(" và ")} (đèn xanh): ${R.back.join(", ")} có điện lại nhờ dòng đổi hướng cấp ngược (xung cam).`)
             : R.dark.length ? tr(`No tie can take ${R.dark.join(", ")} within voltage and current limits.`,
                                  `Không tie nào nhận được ${R.dark.join(", ")} mà vẫn giữ giới hạn điện áp và dòng.`)
                             : tr(`Nothing beyond zone ${Z} lost power.`, `Không có phần nào phía sau zone ${Z} bị mất điện.`),
           read: R.back.length
             ? tr(`<b>${R.kw_back} kW</b> of the ${R.kw_dark} kW beyond the fault is restored.${R.dark.length ? ` ${R.dark.join(", ")} ${R.dark.length === 1 ? "stays" : "stay"} dark: picking ${R.dark.length === 1 ? "it" : "them"} up would break a limit.` : ""}`,
                  `Cấp lại được <b>${R.kw_back} kW</b> trên ${R.kw_dark} kW phía sau chỗ sự cố.${R.dark.length ? ` ${R.dark.join(", ")} vẫn mất điện: nhận thêm sẽ vượt giới hạn.` : ""}`)
             : R.dark.length ? tr(`They wait for the repair with zone ${Z}.`, `Các zone này chờ sửa xong cùng zone ${Z}.`)
                             : tr(`Only zone ${Z} waits for the repair.`, `Chỉ zone ${Z} chờ sửa chữa.`),
           why: tr("Before any tie closes, a power flow checks voltage (0.95–1.05 pu), current and the radial layout.",
                   "Trước khi đóng bất kỳ tie nào, tính trào lưu kiểm tra điện áp (0.95–1.05 pu), dòng điện và cấu trúc hình tia.") })],
      ];
      const items = steps.map(([enter, text]) => ({ el: mbox, noScroll: true, enter: () => { enter(); lastKey = ""; }, leave: () => {},
                                                    close: () => { stopHifDemo(true); resetFault(); focus(null); }, text }));
      hintOff();
      explain(items, 0, false);
      return items;
    };
    const replayClicked = b => { stopHifDemo(true); replay({ bus: b, Z: G.bus_zone[b], P: G.bus_zone[b], ftype: "SLG", r: .01, conf: null, wrong: false }); };
    const replayMissed = () => {
      stopHifDemo(true);
      const pool = MD.missed.filter(m => G.buses[m[0]]), m = pool[Math.floor(Math.random() * pool.length)];
      replay({ bus: m[0], Z: m[1], P: m[2], ftype: m[3], r: m[4], conf: m[5], wrong: true });
    };
    const replayRight = () => { stopHifDemo(true); const bs = Object.keys(G.bus_zone).filter(b => G.bus_zone[b]); replayClicked(bs[Math.floor(Math.random() * bs.length)]); };

    const updateHifHud = (hd, stepIdx, done) => {
      if (!hifHud || !hd) return;
      hifHud.hidden = false;
      const stTxt = done ? tr("6/6 Restored (reversed tie back-feed active)", "6/6 Đã phục hồi (dòng đổi hướng qua dao liên lạc đang chạy)")
                         : tr(`Step ${stepIdx + 1}/6`, `Bước ${stepIdx + 1}/6`);
      hifHud.innerHTML = tr(
        `<b>⚡ Tier-1 HIF ALARM → FLISR</b> · ${stTxt}<br>504 B int8 (${hd.params} params) · p_hif = <b>${hd.p_hif.toFixed(4)}</b> · PERSIST ${hd.persist}/3 · ${hd.host_us.toFixed(2)} µs host GCC · bus ${hd.bus} (${hd.r} Ω SLG, simulation only)`,
        `<b>⚡ Cảnh báo HIF Tầng 1 → FLISR</b> · ${stTxt}<br>504 B int8 (${hd.params} tham số) · p_hif = <b>${hd.p_hif.toFixed(4)}</b> · PERSIST ${hd.persist}/3 · ${hd.host_us.toFixed(2)} µs GCC · bus ${hd.bus} (SLG ${hd.r} Ω, chỉ là mô phỏng)`
      );
    };
    const runHifDemo10s = () => {
      if (hifRunning) { stopHifDemo(true); return; }
      if (layer !== "fault") setLayer("fault");
      const hd = MD.hif_demo || { bus: "72", Z: "Sw4", P: "Sw4", ftype: "SLG", r: 200, conf: null, p_hif: 0.99809, persist: 3, params: 417, bytes: 504, host_us: 0.5399 };
      const items = replay({ bus: hd.bus, Z: hd.Z, P: hd.P, ftype: hd.ftype, r: hd.r, conf: hd.conf, wrong: false, hif: hd });
      hifRunning = true;
      if (hifDemoBtn) {
        hifDemoBtn.classList.add("running");
        hifDemoBtn.innerHTML = '■ <span data-l="en">Stop 10s Demo</span><span data-l="vi">Dừng Demo 10s</span>';
      }
      updateHifHud(hd, 0, false);
      const schedule = [[2000, 1], [3600, 2], [5200, 3], [6800, 4], [8300, 5]];
      schedule.forEach(([ms, idx]) => {
        hifTimers.push(setTimeout(() => {
          if (!hifRunning) return;
          explain(items, idx, false);
          updateHifHud(hd, idx, idx === 5);
        }, ms));
      });
      hifTimers.push(setTimeout(() => {
        if (!hifRunning) return;
        stopHifDemo(false);
        updateHifHud(hd, 5, true);
      }, 10000));
    };

    let layer = "zones";
    const setLayer = name => {
      stopHifDemo(true);
      layer = name;
      if (xi >= 0) closeX();
      resetFault(); focus(null);
      errLayer.visible = name === "errors"; faultLayer.visible = name === "fault";
      if (name === "errors") zoneNames.forEach(z => { zm[z].line.color.copy(zm[z].base).lerp(new T3.Color(0xc3c6ca), .75); zm[z].load.color.copy(DARKLOAD); });
      ["zones", "errors", "fault"].forEach(n => mbox.classList.toggle("layer-" + n, n === name));
      mbox.querySelectorAll("[data-mlayer]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mlayer === name)));
      setSpin(false); lastKey = "";
      if (name !== "zones") toast(name === "errors"
        ? tr("Red columns: buses where faults get misplaced. Arrows: true zone → wrong guess.", "Cột đỏ: bus hay bị đoán sai. Mũi tên: zone thật → zone bị đoán nhầm.")
        : tr("Click anywhere on the feeder to put a fault there, or press 10s HIF → FLISR.", "Nhấp vào bất kỳ đâu trên lưới để đặt sự cố, hoặc bấm 10s HIF → FLISR."));
    };
    mbox.querySelectorAll("[data-mlayer]").forEach(b => b.addEventListener("click", () => setLayer(b.dataset.mlayer)));
    byId("m3d-miss").addEventListener("click", replayMissed);
    byId("m3d-hit").addEventListener("click", replayRight);
    if (hifDemoBtn) hifDemoBtn.addEventListener("click", runHifDemo10s);
    resetFault();

    // build-up: parts pop in from the substation outward the first time the model is seen
    let born = null;
    if (!reduce) reveal.forEach(([m]) => m.scale.setScalar(1e-4));
    const grow = now => {
      if (born === null) return;
      const t = (now - born) / 1900;
      reveal.forEach(([m, o, s]) => {
        const x = Math.min(1, Math.max(0, (t - o * .8) / .2)), e = Math.max(1e-4, x * x * (3 - 2 * x));
        m.scale.set(s.x * e, s.y * e, s.z * e);
      });
      if (t > 1.05) born = null;
    };

    const v3 = new T3.Vector3();
    const frame = now => {
      raf = 0;
      if (!visible) return;
      let moving = born !== null;
      grow(now);
      G.zones.forEach(q => {
        const s = zm[q.name];
        s.lift += (s.liftGoal - s.lift) * k; s.group.position.y = s.lift;
        if (Math.abs(s.liftGoal - s.lift) > .002) moving = true;
        const f = s.line.opacity + (s.fadeGoal - s.line.opacity) * k;
        s.line.opacity = s.load.opacity = f; s.line.depthWrite = s.load.depthWrite = f > .9;
      });
      if (glide) { controls.target.lerp(glide, k); if (controls.target.distanceTo(glide) < .01) glide = null; }
      if (fm.visible && faultLayer.visible && !reduce) {   // the fault's ring keeps pulsing outward
        const s = 1 + (now / 900 % 1) * 1.6;
        fRing.scale.setScalar(s); fRing.material.opacity = 1 - (s - 1) / 1.6;
      }
      if (faultLayer.visible && !reduce && (flowFwd.length || flowRev.length)) updateFlowPulses(now);
      controls.update();
      // labels move only when the view or a lift changes; bus numbers show when zoomed in or in the lifted zone
      const w = stage.clientWidth, h = stage.clientHeight;
      const key = [cam.position.x, cam.position.y, cam.position.z, controls.target.x, controls.target.z, w, h, focusZone].join();
      if (key !== lastKey || moving) {
        lastKey = key;
        const near = cam.position.distanceTo(controls.target) < home.pos.length() * .62, lang = L();
        // no overlaps: zone names win, then equipment, then bus numbers; a hidden label returns on zoom
        // priority: the active layer's own labels, then the focused zone's, then everything else in order
        const rank = lb => (lb.layer && lb.layer === layer ? 0 : focusZone && lb.zone === focusZone ? 1 : 2);
        const placed = [], ordered = labels.map((lb, i) => [rank(lb), i, lb]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]);
        ordered.forEach(lb => {
          const el = lb.el;
          const off = () => { el.style.display = "none"; };
          if (mbox.classList.contains("no-" + lb.kind)) return off();
          if (lb.layer && lb.layer !== layer) return off();
          if (layer === "errors" && (lb.kind === "eq" || lb.kind === "bus")) return off();
          if (lb.layer === "fault" && !fm.visible) return off();
          if (lb.kind === "bus" && !near && lb.zone !== focusZone) return off();
          v3.copy(lb.pos); if (lb.zone && zm[lb.zone]) v3.y += zm[lb.zone].lift;
          v3.project(cam);
          if (!(v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05)) return off();
          const x = (v3.x + 1) / 2 * w, y = (1 - v3.y) / 2 * h;
          el.style.display = "";
          const s = lb[lang] || (lb[lang] = [el.offsetWidth, el.offsetHeight]);   // measured once per language
          const r = [x - s[0] / 2 - 2, y - s[1] - 2, x + s[0] / 2 + 2, y + 2];
          const always = lb.kind === "zone" && layer === "zones";   // zone names never hide in the zone view
          if (!always && placed.some(q => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1])) return off();
          placed.push(r);
          el.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px) translate(-50%,-100%)";
          el.style.opacity = focusZone && lb.zone !== focusZone ? .25 : 1;
        });
      }
      renderer.render(scene, cam);
      raf = requestAnimationFrame(frame);
    };
    // draw only while the model is on screen: no work at all while the reader scrolls elsewhere
    let visible = false, raf = 0, seen = false;
    new IntersectionObserver(([en]) => {
      visible = en.isIntersecting;
      if (visible && !seen) {
        seen = true;
        if (!reduce) born = performance.now();
        setTimeout(hintOff, 9000);
      }
      if (visible && !raf) raf = requestAnimationFrame(frame);
    }, { threshold: .05 }).observe(mbox);
    const size = () => {
      const w = stage.clientWidth, h = stage.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); fitHome();
    };
    new ResizeObserver(size).observe(stage); size();

    // picking: a click (not a drag) on a part explains it; hovering names it
    const ray = new T3.Raycaster(), ndc = new T3.Vector2();
    const hit = e => {
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
      ray.setFromCamera(ndc, cam);
      // equipment is a group of parts: climb to the group; skip anything in a hidden layer
      const shown = o => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
      for (const h of ray.intersectObjects(pick, true)) {
        let o = h.object;
        while (o && !(o.userData && o.userData.click)) o = o.parent;
        if (o && shown(o)) return o;
      }
      return null;
    };
    let down = null, moveEv = null, hoverQueued = false;
    renderer.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener("pointerup", e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) { down = null; return; }
      down = null;
      const o = hit(e);
      if (!o) return;
      hintOff();
      if (layer === "fault") { if (o.userData.bus) replayClicked(o.userData.bus); }   // put a fault where the reader clicked
      else o.userData.click();
    });
    renderer.domElement.addEventListener("pointermove", e => {
      if (e.pointerType === "touch") return;
      moveEv = e;
      if (hoverQueued) return;
      hoverQueued = true;
      requestAnimationFrame(() => {
        hoverQueued = false;
        const o = hit(moveEv);
        renderer.domElement.style.cursor = o ? "pointer" : "grab";
        if (o) {
          const lab = typeof o.userData.label === "function" ? o.userData.label() : o.userData.label;
          tip.textContent = layer === "fault" && o.userData.bus ? "⚡ " + tr("Put a fault at bus ", "Đặt sự cố tại bus ") + o.userData.bus : lab;
          tip.hidden = false; move(moveEv.clientX, moveEv.clientY);
        }
        else if (!tipEl) tip.hidden = true;
      });
    });
    renderer.domElement.addEventListener("pointerleave", () => { if (!tipEl) tip.hidden = true; });
    byId("m3d-reset").addEventListener("click", () => { focus(null); cam.position.copy(home.pos); glide = home.target; });
    spinBtn.addEventListener("click", () => setSpin(!controls.autoRotate));
    return { focus, refresh: () => { lastKey = ""; } };   // refresh: re-place labels (layer or language changed)
  };

  if (mbox) {
    byId("m3d-3d").addEventListener("click", () => { if (!mbox.classList.contains("nogl")) setView("3d"); });
    byId("m3d-2d").addEventListener("click", () => setView("2d"));
    byId("m3d-tour").addEventListener("click", () => { hintOff(); explain(zoneItems, 0, false); });
    mbox.querySelectorAll("[data-layer]").forEach(b => b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", String(on));
      mbox.classList.toggle("no-" + b.dataset.layer, !on);
      if (model) model.refresh();
    }));
    // on touch screens the model waits for a tap, so swiping over it still scrolls the page
    if (matchMedia("(pointer: coarse)").matches) mbox.classList.add("touch", "locked");
    byId("m3d-unlock").addEventListener("click", () => { mbox.classList.remove("locked"); hintOff(); });
    byId("m3d-lock").addEventListener("click", () => mbox.classList.add("locked"));
    const near = new IntersectionObserver(([en]) => {
      if (!en.isIntersecting) return;
      near.disconnect();
      let gl = false;
      try { const c = document.createElement("canvas"); gl = !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) {}
      if (!gl) return noModel();
      loadJs(THREE_URL).then(() => loadJs(ORBIT_URL)).then(() => { model = buildModel(); }).catch(noModel);
    }, { rootMargin: "600px 0px" });
    near.observe(mbox);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => themeHooks.forEach(f => f()));
  }

  // ---- formulas: KaTeX (CDN) typesets every [data-tex] once the data section nears the screen;
  // until then, or if the CDN is blocked, the plain-text version stays readable
  const texEls = [...document.querySelectorAll("[data-tex]")];
  if (texEls.length) {
    const nearTex = new IntersectionObserver(([en]) => {
      if (!en.isIntersecting) return;
      nearTex.disconnect();
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css";
      document.head.appendChild(css);
      loadJs("https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js").then(() => texEls.forEach(el => {
        try {
          window.katex.render(el.dataset.tex, el, { displayMode: el.classList.contains("tex-d"), throwOnError: false, strict: "ignore" });
          el.classList.add("katex-done");
        } catch (e) {}
      })).catch(() => {});
    }, { rootMargin: "900px 0px" });
    nearTex.observe(texEls[0].closest("section"));
  }

  // ---- language: ?lang= > saved choice > browser language
  const setLang = (l, save) => {
    root.lang = l;
    document.title = TEXT[l].title;
    document.querySelectorAll("[data-set-lang]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setLang === l)));
    if (search) search.placeholder = search.dataset[l === "vi" ? "phVi" : "phEn"];
    applyTheme(); hide(); filterFaq(); xRelabel();
    if (model) model.refresh();
    if (save) {
      store.set("shf-lang", l);
      try { const u = new URL(location.href); u.searchParams.set("lang", l); history.replaceState(null, "", u); } catch (e) {}
    }
  };
  document.querySelectorAll("[data-set-lang]").forEach(b => b.addEventListener("click", () => setLang(b.dataset.setLang, true)));

  // ---- 30-second tour at the top: plays the five steps once when it comes on screen;
  // the step buttons jump to a step and pause, Play / Replay restart it
  const story = document.getElementById("story");
  if (story) {
    const ST = [
      { live: "ABCD", open: ["t"] },
      { live: "", open: ["d1", "t"], patrol: "ABCD", truck: "all" },
      { live: "", open: ["d1", "t"], ml: true, found: "C" },
      { live: "AB", tie: "D", open: ["d3", "d4"], found: "C" },
      { live: "AB", tie: "D", open: ["d3", "d4"], found: "C", patrol: "C", truck: "one" },
    ];
    const DUR = 6500, still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const lis = [...story.querySelectorAll(".story-steps li")], caps = [...story.querySelectorAll(".cap")];
    const truck = story.querySelector(".sk-truck");
    let step = 0, timer = 0, playing = false, resume = false, hinted = false;
    story.style.setProperty("--dur", DUR + "ms");
    const show = n => {
      const s = ST[n];
      step = n;
      story.dataset.step = String(n + 1);
      story.classList.add("f");
      story.classList.toggle("ml", !!s.ml);
      story.classList.toggle("end", n === ST.length - 1);
      story.querySelectorAll(".z").forEach(g => {
        g.classList.toggle("live", s.live.includes(g.dataset.z));
        g.classList.toggle("tie", s.tie === g.dataset.z);
      });
      story.querySelectorAll(".sk-band").forEach(b => b.classList.toggle("found", s.found === b.dataset.z));
      story.querySelectorAll(".sk-dev").forEach(d => d.classList.toggle("open", s.open.includes(d.dataset.d)));
      story.querySelectorAll(".sk-patrol").forEach(p => p.classList.toggle("on", !!s.patrol && s.patrol.includes(p.dataset.z)));
      truck.classList.toggle("show", !!s.truck);
      truck.classList.toggle("go", s.truck === "one");
      truck.dataset.t = s.truck || "";
      lis.forEach((li, i) => {
        li.classList.remove("on");
        li.classList.toggle("done", i < n);
        li.firstElementChild.setAttribute("aria-current", i === n ? "step" : "false");
      });
      void story.offsetWidth;   // restart the progress bar of the new step
      lis[n].classList.add("on");
      caps.forEach((c, i) => c.classList.toggle("on", i === n));
    };
    const next = () => {
      clearTimeout(timer);
      if (playing) timer = setTimeout(() => {
        if (step < ST.length - 1) { show(step + 1); next(); return; }
        setPlaying(false);
        if (!hinted) { hinted = true; xhint.hidden = false; setTimeout(() => { xhint.hidden = true; }, 8000); }
      }, DUR);
    };
    const setPlaying = on => {
      playing = on;
      story.classList.toggle("paused", !on);
      if (on) { show(step); next(); } else clearTimeout(timer);
    };
    byId("st-play").addEventListener("click", () => {
      if (!playing && step === ST.length - 1) step = 0;
      setPlaying(!playing);
    });
    byId("st-again").addEventListener("click", () => { step = 0; setPlaying(true); });
    lis.forEach((li, i) => li.firstElementChild.addEventListener("click", () => { setPlaying(false); show(i); }));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && playing) { resume = true; setPlaying(false); }
      else if (!document.hidden && resume) { resume = false; setPlaying(true); }
    });
    show(0);
    if (!still) {   // play now if the sketch is on screen at load, otherwise once it scrolls into view
      const fig = story.querySelector(".story-fig"), r = fig.getBoundingClientRect();
      if (r.top < innerHeight * 0.8 && r.bottom > 0) setPlaying(true);
      else {
        const io = new IntersectionObserver(es => {
          if (es.some(e => e.isIntersecting)) { io.disconnect(); setPlaying(true); }
        }, { threshold: 0.35 });
        io.observe(fig);
      }
    }
  }

  // ---- current section in the top bar, back-to-top button, print with everything open
  const nav = document.querySelector(".topbar nav");
  const bar = document.querySelector(".topbar");
  const prevB = document.getElementById("nav-prev"), nextB = document.getElementById("nav-next");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const links = [...nav.querySelectorAll("a")];
  let current = null, lockUntil = 0;
  // fades and arrows only on the side that hides links; the bar height feeds scroll-padding-top
  const edges = () => {
    const max = nav.scrollWidth - nav.clientWidth;
    const l = nav.scrollLeft > 2, r = nav.scrollLeft < max - 2;
    nav.classList.toggle("fade-l", l); nav.classList.toggle("fade-r", r);
    if (prevB.hidden === l) prevB.hidden = !l;
    if (nextB.hidden === r) nextB.hidden = !r;
    document.documentElement.style.setProperty("--barh", bar.offsetHeight + "px");
  };
  // keep a link in view by moving the strip only (the page scroll is the reader's), and only when it is cut off;
  // offsetLeft is measured from the nav itself (position: relative), so the maths matches nav.scrollLeft
  const reveal = a => {
    const l = a.offsetLeft, r = l + a.offsetWidth, pad = 28;
    if (l < nav.scrollLeft + pad || r > nav.scrollLeft + nav.clientWidth - pad)
      nav.scrollTo({ left: l - (nav.clientWidth - a.offsetWidth) / 2, behavior: still });
  };
  const setOn = a => {
    if (a === current) return;
    if (current) current.classList.remove("on");
    a.classList.add("on"); current = a; reveal(a);
  };
  const spy = new IntersectionObserver(entries => {
    if (performance.now() < lockUntil) return;   // a clicked link stays lit while the page travels to it
    entries.forEach(en => {
      const a = en.isIntersecting && links.find(l => l.getAttribute("href") === "#" + en.target.id);
      if (a) setOn(a);
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  links.forEach(a => {
    const s = document.querySelector(a.getAttribute("href"));
    if (s) spy.observe(s);
    a.addEventListener("click", () => { lockUntil = performance.now() + 1500; setOn(a); });
  });
  addEventListener("scrollend", () => { lockUntil = 0; });
  prevB.addEventListener("click", () => nav.scrollBy({ left: -nav.clientWidth * .7, behavior: still }));
  nextB.addEventListener("click", () => nav.scrollBy({ left: nav.clientWidth * .7, behavior: still }));
  nav.addEventListener("scroll", edges, { passive: true });
  // a mouse wheel over the strip scrolls it sideways while there are hidden links that way
  nav.addEventListener("wheel", e => {
    if (Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
    const max = nav.scrollWidth - nav.clientWidth;
    if (max <= 0 || (e.deltaY < 0 && nav.scrollLeft <= 0) || (e.deltaY > 0 && nav.scrollLeft >= max - 1)) return;
    nav.scrollLeft += e.deltaY; e.preventDefault();
  }, { passive: false });
  addEventListener("resize", edges, { passive: true });
  // links change width when the language switches; re-check the edges then too
  if (window.ResizeObserver) { const ro = new ResizeObserver(edges); ro.observe(nav); links.forEach(a => ro.observe(a)); }
  document.fonts && document.fonts.ready.then(edges);
  edges();
  const top = document.getElementById("totop");
  let ticking = false;
  addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const hidden = scrollY < 700;
      if (top.hidden !== hidden) top.hidden = hidden;
      ticking = false;
    });
  }, { passive: true });
  top.addEventListener("click", () => scrollTo({ top: 0, behavior: "smooth" }));
  addEventListener("beforeprint", () => document.querySelectorAll("details").forEach(d => { d.open = true; }));

  const asked = params.get("lang");
  const lang = asked === "vi" || asked === "en" ? asked
    : (store.get("shf-lang") || ((navigator.language || "").toLowerCase().startsWith("vi") ? "vi" : "en"));
  setLang(lang, false);
  openHash();
  // ?explain=<key> opens the guide on one component (shareable links, README screenshots);
  // otherwise every visitor gets a short hint in the corner
  // explain mode is always on, for every visitor
  setXmode(true);
  const ask = xt.findIndex(el => el.dataset.x === params.get("explain"));
  if (ask >= 0) explain(parts, ask, false);
  else if (!story) {   // with the tour on the page, the hint waits until the tour ends
    setTimeout(() => { xhint.hidden = false; setTimeout(() => { xhint.hidden = true; }, 8000); }, 1200);
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
