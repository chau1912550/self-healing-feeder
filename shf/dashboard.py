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

from . import config
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
def line_chart(xlabels: list[str], series: list[tuple[str, str, int, list[float]]], title: str) -> str:
    W, H, L, R, T_, B = 680, 300, 46, 150, 14, 42
    pw, ph = W - L - R, H - T_ - B
    step = pw / (len(xlabels) - 1)
    X = [L + i * step for i in range(len(xlabels))]
    Y = lambda v: T_ + ph * (1 - v)  # noqa: E731
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    for v in (0, .25, .5, .75, 1):
        g.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 + svg_text(L - 8, Y(v) + 4, f"{v:.0%}", anchor="end"))
    for x, lab in zip(X, xlabels):
        g.append(svg_text(x, T_ + ph + 18, lab, anchor="middle"))
    g.append(svg_text(L + pw / 2, H - 4, "fault resistance (Ω), line-to-ground faults",
                      "điện trở sự cố (Ω), sự cố chạm đất một pha", anchor="middle"))
    gid = "guide-" + "".join(c for c in title.lower() if c.isalnum())   # stable id, no diff noise
    g.append(f'<line id="{gid}" class="guide-line" x1="0" x2="0" y1="{T_}" y2="{T_ + ph}"/>')
    for _, _, slot, vals in series:
        pts = " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(X, vals))
        g.append(f'<polyline class="ln" style="stroke:var(--s{slot})" points="{pts}"/>')
        for x, v in zip(X, vals):
            g.append(f'<circle class="dot" style="fill:var(--s{slot})" cx="{x:.1f}" cy="{Y(v):.1f}" r="4"/>')
    # direct labels at the line ends, nudged apart so they never overlap
    placed, last = [], -1e9
    for y, en, vi, slot in sorted((Y(vals[-1]), en, vi, slot) for en, vi, slot, vals in series):
        y = max(y, last + 15)
        placed.append((y, en, vi, slot))
        last = y
    for y, en, vi, slot in placed:
        g.append(f'<line style="stroke:var(--s{slot})" class="key" x1="{L + pw + 10}" x2="{L + pw + 22}" '
                 f'y1="{y:.1f}" y2="{y:.1f}"/>' + svg_text(L + pw + 27, y + 4, en, vi, "lab"))
    for i, (x, lab) in enumerate(zip(X, xlabels)):  # hover columns, wider than the marks
        en = "".join(f"<br>{esc(n)}: <b>{pct(v[i])}</b>" for n, _, _, v in series)
        vi = "".join(f"<br>{esc(n)}: <b>{pct(v[i])}</b>" for _, n, _, v in series)
        g.append(f'<rect class="hit" x="{x - step / 2:.1f}" y="{T_}" width="{step:.1f}" height="{ph}" '
                 f'data-guide="{gid}:{x:.1f}" {tip(f"<b>{lab} Ω</b>{en}", f"<b>{lab} Ω</b>{vi}")}/>')
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


def explanations(d: dict, v: dict) -> str:
    """EXPLAIN filled with this run's numbers, as JSON for the page script."""
    out = {k: {lang: bubble_text({f: e[f][i].format(**v) for f in ("title", "what", "read", "why")})
               for i, lang in enumerate(("en", "vi"))}
           for k, e in EXPLAIN.items() if d["ea"] or not e.get("needs_ea")}
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
    out = {"geo": geo, "kw": {z: num(float(zrow[z]["kW"])) for z in zrow},
           "text": {"zone": zones, "obj": obj, "load": load}}
    return json.dumps(out, ensure_ascii=False).replace("</", "<\\/")


DATA_DIR = config.ROOT / "docs" / "data"   # files published with the page (GitHub Pages serves docs/)
PUBLISHED = [  # (published name, source, English, Vietnamese)
    ("fault_dataset.csv.gz", config.GENERATED / "dataset.csv.gz",
     "All simulated faults, one row each: the true zone, fault type, resistance, load level and 150 measurements.",
     "Toàn bộ sự cố mô phỏng, mỗi sự cố một dòng: zone thật, loại sự cố, điện trở, mức tải và 150 số đo."),
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
    ("feeder_geometry.json", config.RESULTS / "feeder_geometry.json",
     "Bus coordinates, lines and equipment used by the 3D model.", "Tọa độ bus, đường dây và thiết bị dùng cho mô hình 3D."),
]


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
    ("r", "Fault resistance", "Điện trở sự cố", "Ω"),
    ("scenario, load_mult", "Loading scenario and feeder-wide load level (0.3–1.1 × peak)",
     "Kịch bản tải và mức tải toàn tuyến (0.3–1.1 × đỉnh)", "–"),
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
     "rows": [("Fault current", "Dòng sự cố", r"I_f \approx \dfrac{V_{LN}}{\lvert Z_{th}\rvert + R_f}",
               "I_f ≈ V_LN / (|Z_th| + R_f)")],
     "where": [(r"V_{LN}", "V_LN", "phase-to-ground voltage: 4.16 kV ÷ √3 ≈ 2,402 V on this feeder",
                "điện áp pha – đất: 4.16 kV ÷ √3 ≈ 2,402 V trên tuyến này"),
               (r"Z_{th}", "Z_th", "impedance of the network up to the fault, small near the substation",
                "tổng trở của lưới tính tới chỗ sự cố, nhỏ khi ở gần trạm"),
               (r"R_f", "R_f", "fault resistance: a tree branch, dry soil, an arc",
                "điện trở sự cố: cành cây, đất khô, hồ quang")],
     "example": ("At R<sub>f</sub> = 400 Ω the fault draws about 2,402 V ÷ 400 Ω ≈ 6 A, roughly 1% of the hundreds of amps "
                 "on the trunk. That is why weak ground faults hide in the noise.",
                 "Với R<sub>f</sub> = 400 Ω, dòng sự cố chỉ khoảng 2,402 V ÷ 400 Ω ≈ 6 A, cỡ 1% so với hàng trăm ampe trên trục "
                 "chính. Vì vậy sự cố chạm đất yếu bị lẫn vào nhiễu.")},
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
     "example": ("Subtracting the pre-fault reading removes the load current, so what is left is mostly the fault "
                 "itself. Adding these columns lifts accuracy from {acc_mag} to {acc}.",
                 "Trừ đi số đo trước sự cố là loại bỏ dòng tải, phần còn lại chủ yếu do chính sự cố gây ra. Thêm các cột "
                 "này nâng accuracy từ {acc_mag} lên {acc}.")},
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
     "Simulate every fault type at every bus, 9 ground-fault resistances, random load and 1% sensor noise: "
     "{faults} labeled faults.",
     "Model cần bằng chứng gì?",
     "Mô phỏng mọi loại sự cố ở mọi bus, 9 mức điện trở chạm đất, tải ngẫu nhiên và nhiễu cảm biến 1%: {faults} sự cố "
     "có nhãn."),
    ("What is the bar to beat?",
     "Replay the conventional fault-indicator rule on the same faults: {acc_fpi} correct.",
     "Mốc cần vượt qua là gì?",
     "Chạy lại quy tắc bộ chỉ báo sự cố truyền thống trên cùng các sự cố: đúng {acc_fpi}."),
    ("Which signals carry the answer?",
     "Use what a recloser's event record already holds, plus the before/after change that strips out load.",
     "Tín hiệu nào chứa đáp án?",
     "Dùng đúng những gì bản ghi sự kiện của recloser có sẵn, cộng thêm phần thay đổi trước/sau để loại dòng tải."),
    ("Is the model really learning, not memorizing?",
     "Gradient-boosted trees, tested only on buses never seen in training; an early 99.9% exposed a data leak "
     "that randomized load fixed. Result: {acc}.",
     "Model có thật sự học, hay chỉ học thuộc?",
     "Cây tăng cường gradient, chỉ kiểm tra trên bus chưa thấy khi huấn luyện; lần đầu đạt 99.9% đã lộ ra rò rỉ dữ "
     "liệu, và việc ngẫu nhiên hóa tải đã sửa. Kết quả: {acc}."),
    ("Where and why does it fail?",
     "Per-zone FNR/FPR and the confusion matrix point to weak ground faults on the busy trunk; the fault-current "
     "formula explains why (about 6 A).",
     "Model sai ở đâu, vì sao?",
     "FNR/FPR theo zone và ma trận nhầm lẫn chỉ ra sự cố chạm đất yếu trên trục chính đông tải; công thức dòng sự cố "
     "giải thích lý do (khoảng 6 A)."),
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
        f'<h3>{T("How the reasoning goes", "Cách tư duy để ra kết quả")}</h3><ol class="steps">{steps}</ol>'
        f'<h3>{T("The formulas behind the numbers", "Các công thức đằng sau con số")}</h3>'
        + TB("Each card shows the equation, what every symbol means, and an example with this study's numbers.",
             "Mỗi thẻ gồm công thức, ý nghĩa từng ký hiệu, và một ví dụ dùng số liệu của nghiên cứu này.", "p", "note")
        + f'<div class="fxs">{formulas}</div>'
        f'<h3>{T("Download the data", "Tải dữ liệu")}</h3>{downloads}'
        f'<h3>{T("What a row of the dataset means", "Một dòng dữ liệu nghĩa là gì")}</h3>'
        + TB("‹dev› is one of the 10 measuring devices (Sw1 … L77), so each fault has 10 × 15 = 150 measurement columns.",
             "‹dev› là một trong 10 thiết bị đo (Sw1 … L77), nên mỗi sự cố có 10 × 15 = 150 cột số đo.", "p", "note")
        + cols)


def model_section(d: dict) -> str:
    if not d["geo"]:
        return ""
    bar = ('<div class="m3d-bar"><div class="seg" role="group" aria-label="View">'
           '<button type="button" id="m3d-3d" aria-pressed="true">3D</button>'
           f'<button type="button" id="m3d-2d" aria-pressed="false">{T("2D map", "Bản đồ 2D")}</button></div>'
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
    legend = TB("Column = load kW · one wire per phase · grey can = pole-top transformer · black tank = recloser · "
                "white box with antenna = added switch · red raised blades = open tie · yellow tanks = regulators · "
                "pale cans = capacitors · fenced yard = substation",
                "Cột = tải kW · mỗi pha một dây · bình xám = máy biến áp trên trụ · thùng đen = recloser · "
                "hộp trắng có ăng-ten = dao thêm vào · lưỡi đỏ dựng lên = dao liên lạc mở · thùng vàng = điều áp · "
                "bình nhạt = tụ bù · sân có rào = trạm nguồn", "div", "m3d-legend")
    unlock = (f'<button type="button" class="m3d-unlock" id="m3d-unlock">'
              f'{T("Tap to explore the 3D model", "Chạm để khám phá mô hình 3D")}</button>')
    img = ('<div class="m3d-map"><img data-src="images/feeder-map.png" '
           'alt="One-line map of the IEEE 123-bus feeder with zones, switches, ties, regulators, capacitors and loads"></div>')
    box = (f'<div class="m3d" id="m3d" data-x="map3d">{bar}<div class="m3d-stage"></div><div class="m3d-labels"></div>'
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
    out.append(status("warning" if r400 < .9 else "good",
                      ("High-impedance ground faults", "Sự cố chạm đất trở kháng cao"),
                      (f"only {pct(r400)} correct at 400 Ω, the known weak spot (fault current ≈ 6 A)",
                       f"chỉ đúng {pct(r400)} ở 400 Ω, điểm yếu đã biết (dòng sự cố ≈ 6 A)")))
    dev, acc = min(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1])
    out.append(status("warning" if acc < .9 else "good", ("One sensor offline", "Mất một cảm biến"),
                      (f"worst case is {dev} offline: {pct(acc)} correct", f"tệ nhất khi mất {dev}: đúng {pct(acc)}")))
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
    return out


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
        "r100_mag": pct(mag["slg_by_resistance"]["100.0"]), "r100_fpi": pct(fpi["slg_by_resistance"]["100.0"]),
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
    return v


def faq_section(d: dict, v: dict) -> str:
    items = [f for f in FAQ if d["ea"] or not f.get("needs_ea")]
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
                   f'<dl class="gls">{cards}</dl>')


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
    s_loc = section(
        "location", ("2 · Fault location", "2 · Định vị sự cố"),
        ("After the feeder-head recloser locks out, <b>which of the 10 zones holds the fault?</b> Accuracy is "
         "measured on <b>buses the model never saw in training</b>. The chart shows where each method breaks down: "
         "<b>as the ground-fault resistance rises, the fault current shrinks</b> toward the size of normal load swings.",
         "Sau khi recloser đầu tuyến cắt hẳn, <b>sự cố nằm ở zone nào trong 10 zone?</b> Độ chính xác được đo trên "
         "<b>các bus mà model chưa từng thấy khi huấn luyện</b>. Biểu đồ cho thấy mỗi phương pháp bắt đầu sai ở đâu: "
         "<b>điện trở chạm đất càng lớn, dòng sự cố càng nhỏ</b>, tiến dần tới mức dao động bình thường của phụ tải."),
        xbox("chart-res", f'<div class="legend">{legend}</div>'
                          f'<div class="chart">{line_chart(xl, series, "Accuracy vs fault resistance")}</div>')
        + f'<details><summary>{T("Show as table", "Xem dạng bảng")}</summary>{res_table}</details>'
        f'<h3>{T("By fault type", "Theo loại sự cố")} ({term("types", "SLG, LL, LLG, 3PH")})</h3>'
        + xbox("table-type", loc_table)
        + f'<h3>{T("If one sensor stops reporting (ML, full features)", "Khi một cảm biến ngừng gửi số liệu (ML, đủ đặc trưng)")}</h3>'
        + xbox("chart-sensor", f'<div class="chart">{miss_chart}</div>'),
        (f'ML puts {v["acc"]} of faults in the right zone, against {v["acc_fpi"]} for fault indicators, and keeps '
         f'working as faults get weaker: {v["r100"]} vs {v["r100_fpi"]} at 100 Ω.',
         f'ML xác định đúng zone cho {v["acc"]} số sự cố, so với {v["acc_fpi"]} của bộ chỉ báo sự cố, và vẫn hoạt động '
         f'khi sự cố yếu dần: {v["r100"]} so với {v["r100_fpi"]} ở 100 Ω.'))

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
            (f"<b>{tot} of {n_all} faults ({sh}) went to the wrong zone.</b> {v['slg_hi']} of them ({v['slg_hi_share']}) "
             f"are <b>ground faults at 200 Ω or more</b>, and <b>errors rise with load</b> ({lo_l} in the lightest third "
             f"of scenarios, {hi_l} in the heaviest). Because the model always names a zone, misses and false blames "
             "are <b>counted per zone</b> (one zone vs the rest).",
             f"<b>{tot} trên {n_all} sự cố ({sh}) bị đoán sai zone.</b> {v['slg_hi']} trong số đó ({v['slg_hi_share']}) "
             f"là <b>sự cố chạm đất từ 200 Ω trở lên</b>, và <b>lỗi tăng theo mức tải</b> ({lo_l} ở 1/3 kịch bản nhẹ nhất, "
             f"{hi_l} ở 1/3 nặng nhất). Vì model luôn chọn một zone, bỏ sót và báo nhầm được <b>tính theo từng zone</b> "
             "(một zone so với phần còn lại)."),
            f"<h3>{T('Per zone', 'Theo từng zone')}</h3>" + xbox("table-zone", pz)
            + f'<h3>{term("confusion")}</h3>'
            + TB("Rows are the true zone, columns the predicted zone, in feeder order from the substation. Gray "
                 "diagonal = correct. Blue cells are errors; darker means more.",
                 "Hàng là zone thật, cột là zone dự đoán, xếp theo thứ tự từ trạm ra. Đường chéo màu xám = đoán đúng. "
                 "Ô xanh là lỗi; càng đậm càng nhiều.", "p", "note")
            + xbox("heat", f'<div class="chart heatwrap">{confusion_heatmap(d["confusion"], order)}</div>', "heatbox")
            + f'<h3>{T("Where the wrong answers point", "Câu trả lời sai rơi vào đâu")}</h3>'
            + xbox("chart-dir", f'<div class="chart">{dir_chart}</div>')
            + f'<h3>{T("Let the model say “not sure”", "Cho model nói “không chắc”")}</h3>'
            + TB(f'Predictions below the {term("confidence", "confidence")} cutoff go to a manual patrol instead. '
                 f'Median confidence: {v["conf_right"]} when right, {v["conf_wrong"]} when wrong.',
                 f'Các dự đoán có {term("confidence", "độ tự tin", "độ tự tin")} dưới ngưỡng được chuyển sang tuần tra '
                 f'thủ công. Độ tự tin trung vị: {v["conf_right"]} khi đúng, {v["conf_wrong"]} khi sai.', "p", "note")
            + xbox("table-defer", defer),
            (f'Most mistakes ({v["slg_hi_share"]}) are <b>very weak ground faults</b>, mostly on the <b>busy trunk near '
             f'the substation</b>, and {v["off1"]} of them land <b>just one zone away</b>.',
             f'Phần lớn lỗi ({v["slg_hi_share"]}) là <b>sự cố chạm đất rất yếu</b>, chủ yếu trên <b>trục chính đông tải '
             f'gần trạm</b>, và {v["off1"]} số lỗi <b>chỉ lệch sang zone ngay bên cạnh</b>.'))
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
                                  T("Power flows checked", "Số lần tính trào lưu")], rows, {3, 5, 6, 7})),
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
                       "10 zone đóng cắt của tuyến IEEE 123-bus dùng trong toàn bộ báo cáo."), xbox("table-zones", zt))

    body = (model_section(d) + s_loc + s_err + s_rest + s_zones + faq_section(d, v) + glossary_section()
            + data_section(v, publish_data()))
    runtime = f'{m["runtime_s"]:.0f}'
    repo_link = f'<a href="{REPO}">{T("source on GitHub", "mã nguồn trên GitHub")}</a>'
    header = (
        f'<h1>{T("Self-Healing Feeder · Run Report", "Self-Healing Feeder · Báo cáo kết quả")}</h1>'
        + TB(f'Machine-learning fault location and automated restoration ({term("flisr")}) on the IEEE 123-bus '
             f'distribution feeder, simulated in {term("opendss")}. Every number on this page is read from the latest '
             f'<code>python run.py</code>.',
             f'Định vị sự cố bằng machine learning và tự động khôi phục cấp điện ({term("flisr")}) trên lưới phân phối '
             f'IEEE 123-bus, mô phỏng bằng {term("opendss")}. Mọi con số trên trang được đọc từ lần chạy '
             f'<code>python run.py</code> gần nhất.', "p")
        + '<div class="meta">'
        + T(f"{v['faults']} simulated faults · run time {runtime} s · simulation only, not field data",
            f"{v['faults']} sự cố mô phỏng · thời gian chạy {runtime} giây · chỉ là mô phỏng, không phải dữ liệu thực địa")
        + f" · {repo_link}</div>")
    guide = TB('<b>New here?</b> Click the <b>?</b> on any card, chart or table (or turn on <b>Explain</b> at the '
               'bottom left and click anything): the guide flies there, circles it and explains it. Words with a '
               '<span class="term-demo">dotted underline</span> have a short definition, and every chart shows exact '
               'numbers on hover. Questions are answered in the <a href="#faq">Q&amp;A</a>.',
               '<b>Lần đầu xem?</b> Nhấp nút <b>?</b> ở góc bất kỳ thẻ, biểu đồ hay bảng nào (hoặc bật <b>Giải thích</b> '
               'ở góc trái dưới rồi nhấp vào bất cứ đâu): nhân vật hướng dẫn sẽ bay tới, khoanh lại và giải thích. Từ '
               'có <span class="term-demo">gạch chân chấm chấm</span> có định nghĩa ngắn, và mọi biểu đồ đều hiện số '
               'chính xác khi rê chuột. Các câu hỏi thường gặp nằm ở mục <a href="#faq">Hỏi đáp</a>.', "p", "guide")
    nav = "".join(f'<a href="#{i}">{T(en, vi)}</a>' for i, en, vi in [
        ("health", "Checks", "Kiểm tra"), ("model", "3D model", "Mô hình 3D"), ("location", "Location", "Định vị"),
        ("errors", "Errors", "Lỗi"),
        ("restoration", "Restoration", "Khôi phục"), ("zones", "Zones", "Zone"), ("faq", "Q&amp;A", "Hỏi đáp"),
        ("glossary", "Glossary", "Thuật ngữ"), ("data", "Data", "Dữ liệu")])
    health = (f'<div class="panel" id="health" data-x="health"><h2>{T("Run checks", "Kiểm tra lần chạy")}<a class="anchor" href="#health" '
              f'aria-label="Link to this section">#</a></h2>'
              + TB("<b>Pass</b> = the result meets its limit. <b>Watch</b> = a known weak spot to keep an eye on. "
                   "<b>Fail</b> = something to fix before trusting the numbers.",
                   "<b>Đạt</b> = kết quả nằm trong giới hạn. <b>Lưu ý</b> = điểm yếu đã biết, cần theo dõi. <b>Lỗi</b> "
                   "= phải sửa trước khi tin vào số liệu.", "p", "how")
              + f'<ul class="checks">{"".join(checks(d))}</ul></div>')
    footer = TB(f"Assumptions behind the outage numbers: automated switching {t['automated']} min, manual switching "
                f"{t['manual']} min, repair {t['repair']} min. Every device beyond the IEEE test case is marked "
                "<code>ASSUMPTION</code> in <code>shf/config.py</code>. Rebuild this page with "
                "<code>python -m shf.dashboard</code>.",
                f"Giả định đằng sau các con số mất điện: đóng cắt tự động {t['automated']} phút, đóng cắt thủ công "
                f"{t['manual']} phút, sửa chữa {t['repair']} phút. Mọi thiết bị ngoài lưới thử nghiệm IEEE đều được "
                "đánh dấu <code>ASSUMPTION</code> trong <code>shf/config.py</code>. Dựng lại trang bằng "
                "<code>python -m shf.dashboard</code>.", "p")

    page = TEMPLATE
    for key, val in {"NAV": nav, "HEADER": header, "GUIDE": guide, "TILES": tiles, "HEALTH": health,
                     "BODY": body, "FOOTER": footer, "XDATA": explanations(d, v), "MDATA": model_data(d)}.items():
        page = page.replace(f"@@{key}@@", val)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    feeder_png = config.FIGURES / "feeder_zones.png"   # the 2D view of the model section (Pages serves docs/ only)
    if feeder_png.exists():
        (OUT.parent / "images").mkdir(exist_ok=True)
        shutil.copyfile(feeder_png, OUT.parent / "images" / "feeder-map.png")
    OUT.write_text(page, encoding="utf-8")
    print("wrote", OUT)


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
.topbar-in { max-width: 1040px; margin: 0 auto; padding: 8px 16px; display: flex; gap: 10px; align-items: center; }
.brand { font-weight: 650; white-space: nowrap; font-size: 14px; }
.topbar nav { display: flex; gap: 2px; overflow-x: auto; flex: 1; min-width: 0; scrollbar-width: none; }
.topbar nav::-webkit-scrollbar { display: none; }
.topbar nav a { padding: 4px 10px; border-radius: 999px; text-decoration: none; color: var(--ink2);
  white-space: nowrap; font-size: 13.5px; }
.topbar nav a:hover { background: var(--soft); }
.topbar nav a.on { background: var(--ink); color: var(--page); }
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

.chart { overflow-x: auto; }
.chart svg { width: 100%; min-width: 560px; height: auto; display: block; }  /* legible on phones: the chart scrolls, not the page */
.heatwrap { max-width: 520px; }
.heatwrap svg { min-width: 440px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink2); margin-bottom: 4px; }
.legend i { display: inline-block; width: 12px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }
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
.xdock { position: fixed; left: 16px; bottom: 16px; z-index: 7; display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 14px 4px 4px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface);
  color: var(--ink); font: inherit; font-size: 13.5px; font-weight: 600; cursor: pointer; box-shadow: 0 2px 12px rgb(0 0 0 / .14); }
.xdock[aria-pressed="true"] { background: var(--ink); color: var(--page); border-color: var(--ink); }
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
.m3d.view2d .m3d-stage, .m3d.view2d .m3d-labels, .m3d.view2d .m3d-hint, .m3d.view2d .m3d-legend,
.m3d.view2d #m3d-spin, .m3d.view2d #m3d-reset, .m3d.nogl #m3d-3d { display: none; }
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
  .xdock-l { display: none; } .xdock { padding: 4px; }
  body.xopen .xdock { display: none; }
}
@media print {
  .topbar, .totop, .faq-tools, .copy, #tip, .anchor, header .guide { display: none !important; }
  .xq, .xdock, .xhint, .buddy, .xring, .xscribble, .xbubble, .m3d-bar, .m3d-hint, .m3d-unlock { display: none !important; }
  body { background: #fff; } main { padding-top: 0; }
  section, .panel, .tile, .faq-item { break-inside: avoid; }
}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-in">
  <span class="brand">Self-Healing Feeder</span>
  <nav aria-label="Sections">@@NAV@@</nav>
  <div class="ctrls">
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
<button type="button" class="xdock" id="xdock" aria-pressed="false"><span class="face" aria-hidden="true"><i></i><i></i></span><span class="xdock-l"><span data-l="en">Explain</span><span data-l="vi">Giải thích</span></span></button>
<div class="xhint" id="xhint" hidden><span data-l="en">Hi! Explain mode is on: click any card, chart, table or the 3D model and I will explain it. Click me to turn it off.</span><span data-l="vi">Chào bạn! Chế độ giải thích đang bật: nhấp vào bất kỳ thẻ, biểu đồ, bảng hay mô hình 3D nào, mình sẽ giải thích. Nhấp vào mình để tắt.</span></div>
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
    en: { title: "Self-Healing Feeder Report", copied: "Link copied", theme: { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" } },
    vi: { title: "Báo cáo Self-Healing Feeder", copied: "Đã sao chép link", theme: { auto: "◐ Tự động", light: "☀ Sáng", dark: "☾ Tối" } },
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
  const openHash = () => {
    const el = location.hash && document.getElementById(location.hash.slice(1));
    if (el && el.tagName === "DETAILS") { el.open = true; el.scrollIntoView(); }
  };
  addEventListener("hashchange", openHash);

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
    const it = xlist[xi], el = it.el, r = el.getBoundingClientRect();
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
    xi = -1;
    bub.hidden = true; ring.hidden = true; scrib.hidden = true;
    document.body.classList.remove("xopen");
    const dk = dockBtn.getBoundingClientRect();   // fly home, then disappear
    buddy.style.left = dk.left + scrollX + "px"; buddy.style.top = dk.top + scrollY + "px";
    setTimeout(() => { if (xi < 0) buddy.hidden = true; }, reduce ? 0 : 600);
  };
  byId("xb-close").addEventListener("click", closeX);
  byId("xb-prev").addEventListener("click", () => explain(xlist, xi - 1, true));
  byId("xb-next").addEventListener("click", () => explain(xlist, xi + 1, true));
  const setXmode = (on, save) => {
    xmode = on;
    dockBtn.setAttribute("aria-pressed", String(on));
    document.body.classList.toggle("xmode", on);
    if (save) store.set("shf-xmode", on ? "on" : "off");
  };
  dockBtn.addEventListener("click", () => {
    setXmode(!xmode, true);
    xhint.hidden = true;
    toast(XL[L()][xmode ? "on" : "off"]);
    if (!xmode) closeX();
  });
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
      zm[z.name] = { group, lift: 0, liftGoal: 0, fadeGoal: 1,
        line: new T3.MeshStandardMaterial({ color: c, roughness: .45, transparent: true }),
        load: new T3.MeshStandardMaterial({ color: c.clone().lerp(new T3.Color(0xffffff), .35), roughness: .6, transparent: true }) };
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
      twin.userData = { label: "Zone " + z, click: zoneClick(z) };
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
      mesh.userData = { label: "Bus " + b + " · " + kw + " kW", click: () => explain([loadItem(b, kw, z)], 0, false) };
      add(mesh, z, order(p[0], p[1]));
    });

    // equipment is built from parts in a group; the group carries the label and the click
    const bushingGeo = new T3.CylinderGeometry(.022, .034, .16, 8);
    const part = (geo, mat, x, y, z, g) => { const m = new T3.Mesh(geo, mat); m.position.set(x, y, z); g.add(m); return m; };
    const group = (pos, label, click) => { const g = new T3.Group(); g.position.copy(pos); g.userData = { label, click }; return g; };
    const bushings = (g, xs, y, z) => xs.forEach(x => part(bushingGeo, porcelain, x, y, z || 0, g));
    // air-break switch: insulator posts with a blade per phase; an open one has its blades raised
    const airBreak = (g, phases, open, bladeMat) => {
      part(new T3.BoxGeometry(.08 + .24 * (phases - 1) + .1, .04, .3), steel, 0, 0, 0, g);
      (OFF[phases] || [0]).forEach(s => {
        part(bushingGeo, porcelain, s, .1, -.11, g); part(bushingGeo, porcelain, s, .1, .11, g);
        const blade = part(new T3.BoxGeometry(.035, .025, .26), bladeMat, s, .2, open ? -.02 : 0, g);
        if (open) { blade.geometry.translate(0, 0, .13); blade.position.z = -.11; blade.rotation.x = -1.05; }
      });
    };

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
      add(g, G.bus_zone[bus], order(x, y));
    });

    // substation yard west of bus 150: pad, fence, power transformer with radiators and bushings,
    // regulator Reg 1 and the bus structure the feeder leaves from
    const sub = group(src.clone().add(new T3.Vector3(-1.75, 0, 0)), "Substation",
                      () => explain([objItem("src", "Sw1")], 0, false));
    part(new T3.BoxGeometry(3.3, .06, 2.5), new T3.MeshStandardMaterial({ color: 0xc4c7cb, roughness: 1 }), 0, .03, 0, sub);
    const fence = new T3.LineSegments(new T3.EdgesGeometry(new T3.BoxGeometry(3.4, .7, 2.6)), new T3.LineBasicMaterial({ color: 0x6b6f75 }));
    fence.position.y = .35; sub.add(fence);
    part(new T3.BoxGeometry(.85, .8, .7), new T3.MeshStandardMaterial({ color: 0x4d5359, roughness: .5, metalness: .3 }), -.7, .46, 0, sub);
    for (let i = 0; i < 5; i++) part(new T3.BoxGeometry(.035, .62, .55), steel, -.2 + i * .07, .46, 0, sub);   // radiator fins
    [-.2, 0, .2].forEach(z => {
      part(new T3.CylinderGeometry(.03, .045, .46, 8), porcelain, -.92, 1.08, z, sub);   // high-voltage bushings
      part(new T3.CylinderGeometry(.025, .035, .26, 8), porcelain, -.48, .98, z, sub);   // 4.16 kV bushings
    });
    [-.3, 0, .3].forEach(z => {   // Reg 1: three single-phase regulators
      part(new T3.CylinderGeometry(.11, .11, .44, 14), regTank, .45, .3, z, sub);
      part(bushingGeo, porcelain, .45, .6, z, sub);
    });
    [-.55, .55].forEach(z => part(new T3.CylinderGeometry(.04, .04, 1.3, 8), steel, 1.25, .65, z, sub));   // bus structure
    part(new T3.BoxGeometry(.07, .07, 1.25), steel, 1.25, 1.3, 0, sub);
    add(sub, null, 0);

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
    let lastKey = "";
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
      controls.update();
      // labels move only when the view or a lift changes; bus numbers show when zoomed in or in the lifted zone
      const w = stage.clientWidth, h = stage.clientHeight;
      const key = [cam.position.x, cam.position.y, cam.position.z, controls.target.x, controls.target.z, w, h, focusZone].join();
      if (key !== lastKey || moving) {
        lastKey = key;
        const near = cam.position.distanceTo(controls.target) < home.pos.length() * .62, lang = L();
        // no overlaps: zone names win, then equipment, then bus numbers; a hidden label returns on zoom
        const placed = [], ordered = focusZone ? labels.filter(lb => lb.zone === focusZone).concat(labels.filter(lb => lb.zone !== focusZone)) : labels;
        ordered.forEach(lb => {
          const el = lb.el;
          const off = () => { el.style.display = "none"; };
          if (mbox.classList.contains("no-" + lb.kind)) return off();
          if (lb.kind === "bus" && !near && lb.zone !== focusZone) return off();
          v3.copy(lb.pos); if (lb.zone && zm[lb.zone]) v3.y += zm[lb.zone].lift;
          v3.project(cam);
          if (!(v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05)) return off();
          const x = (v3.x + 1) / 2 * w, y = (1 - v3.y) / 2 * h;
          el.style.display = "";
          const s = lb[lang] || (lb[lang] = [el.offsetWidth, el.offsetHeight]);   // measured once per language
          const r = [x - s[0] / 2 - 2, y - s[1] - 2, x + s[0] / 2 + 2, y + 2];
          if (lb.kind !== "zone" && placed.some(q => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1])) return off();
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
      const h = ray.intersectObjects(pick, true)[0];   // equipment is a group of parts: climb to the group
      let o = h && h.object;
      while (o && !(o.userData && o.userData.click)) o = o.parent;
      return o;
    };
    let down = null, moveEv = null, hoverQueued = false;
    renderer.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener("pointerup", e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) { down = null; return; }
      down = null;
      const o = hit(e);
      if (o) { hintOff(); o.userData.click(); }
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
        if (o) { tip.textContent = o.userData.label; tip.hidden = false; move(moveEv.clientX, moveEv.clientY); }
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

  // ---- current section in the top bar, back-to-top button, print with everything open
  const nav = document.querySelector(".topbar nav");
  const links = [...nav.querySelectorAll("a")];
  let current = null;
  const spy = new IntersectionObserver(entries => {
    entries.forEach(en => {
      const a = en.isIntersecting && links.find(l => l.getAttribute("href") === "#" + en.target.id);
      if (!a || a === current) return;
      if (current) current.classList.remove("on");
      a.classList.add("on"); current = a;
      // keep the link visible by scrolling the menu strip only; scrollIntoView would also
      // touch the page scroll and cut short the reader's smooth wheel scrolling
      const l = a.offsetLeft, r = l + a.offsetWidth;
      if (l < nav.scrollLeft || r > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = l - (nav.clientWidth - a.offsetWidth) / 2;
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  links.forEach(a => { const s = document.querySelector(a.getAttribute("href")); if (s) spy.observe(s); });
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
  // otherwise first-time visitors get a short hint next to the guide button
  // explain mode starts on for every visitor unless they switched it off before
  setXmode(store.get("shf-xmode") !== "off", false);
  const ask = xt.findIndex(el => el.dataset.x === params.get("explain"));
  if (ask >= 0) explain(parts, ask, false);
  else if (!store.get("shf-xhint")) {
    store.set("shf-xhint", "1");
    setTimeout(() => { xhint.hidden = false; setTimeout(() => { xhint.hidden = true; }, 8000); }, 1200);
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
