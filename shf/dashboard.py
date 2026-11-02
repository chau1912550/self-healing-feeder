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
    return section("faq", ("5 · Questions & answers", "5 · Hỏi đáp"),
                   ("Questions a reviewer or interviewer is likely to ask, answered with this run's numbers. Search "
                    "(Vietnamese works with or without accents), filter by topic, or open them all.",
                    "Những câu người xét duyệt hoặc phỏng vấn hay hỏi, trả lời bằng số liệu của lần chạy này. Có thể "
                    "tìm kiếm (gõ có dấu hay không dấu đều được), lọc theo chủ đề, hoặc mở tất cả."),
                   tools + '<div class="faq-list">' + "".join(rows) + "</div>" + empty)


def glossary_section() -> str:
    cards = "".join(f'<div class="gl" id="term-{k}"><dt>{T(ten, tvi)}</dt><dd>{T(den, dvi)}</dd></div>'
                    for k, (ten, den, tvi, dvi) in GLOSSARY.items())
    return section("glossary", ("6 · Glossary", "6 · Thuật ngữ"),
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
    cut = f'{pk["ml_full"] / pk["no_location"] - 1:+.0%}'
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
        "location", ("1 · Fault location", "1 · Định vị sự cố"),
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
            "errors", ("2 · Error analysis", "2 · Phân tích lỗi"),
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
        s_err = section("errors", ("2 · Error analysis", "2 · Phân tích lỗi"), ("Not built yet.", "Chưa được tạo."),
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
        "restoration", ("3 · Isolation and restoration", "3 · Cô lập và khôi phục"),
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
    s_zones = section("zones", ("4 · Feeder zones", "4 · Các zone của tuyến"),
                      ("The 10 switching zones of the IEEE 123-bus feeder used throughout this report.",
                       "10 zone đóng cắt của tuyến IEEE 123-bus dùng trong toàn bộ báo cáo."), xbox("table-zones", zt))

    body = s_loc + s_err + s_rest + s_zones + faq_section(d, v) + glossary_section()
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
        ("health", "Checks", "Kiểm tra"), ("location", "Location", "Định vị"), ("errors", "Errors", "Lỗi"),
        ("restoration", "Restoration", "Khôi phục"), ("zones", "Zones", "Zone"), ("faq", "Q&amp;A", "Hỏi đáp"),
        ("glossary", "Glossary", "Thuật ngữ")])
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
                     "BODY": body, "FOOTER": footer, "XDATA": explanations(d, v)}.items():
        page = page.replace(f"@@{key}@@", val)
    OUT.parent.mkdir(parents=True, exist_ok=True)
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
.check b { display: block; font-weight: 600; }
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
  .xq, .xdock, .xhint, .buddy, .xring, .xscribble, .xbubble { display: none !important; }
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
<button type="button" class="xdock" id="xdock" aria-pressed="false"><span class="face" aria-hidden="true"><i></i><i></i></span><span class="xdock-l"><span data-l="en">Explain</span><span data-l="vi">Giải thích</span></span></button>
<div class="xhint" id="xhint" hidden><span data-l="en">Hi! Click me, then click any card, chart or table and I will explain it.</span><span data-l="vi">Chào bạn! Nhấp vào mình, rồi nhấp vào bất kỳ thẻ, biểu đồ hay bảng nào, mình sẽ giải thích.</span></div>
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
  const applyTheme = () => {
    if (theme === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = theme;
    themeBtn.textContent = TEXT[L()].theme[theme];
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
  let xmode = false, xi = -1;
  xt.forEach((el, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "xq"; b.textContent = "?";
    b.addEventListener("click", e => { e.stopPropagation(); explain(i, true); });
    el.appendChild(b);
  });
  const xRelabel = () => {
    const t = XL[L()];
    document.querySelectorAll(".xq").forEach(b => { b.title = t.ask; b.setAttribute("aria-label", t.ask); });
    byId("xb-close").setAttribute("aria-label", t.close);
    if (xi >= 0) render();
  };
  const render = () => {
    const t = XL[L()], d = XD[xt[xi].dataset.x][L()];
    byId("xb-title").textContent = d.title;
    ["what", "read", "why"].forEach(k => { byId("xk-" + k).textContent = t[k]; byId("xb-" + k).textContent = d[k]; });
    byId("xb-prev").textContent = t.prev; byId("xb-next").textContent = t.next;
    byId("xb-count").textContent = (xi + 1) + " / " + xt.length;
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
  const explain = (i, smooth) => {
    xi = (i + xt.length) % xt.length;
    const el = xt[xi], r = el.getBoundingClientRect();
    hide(); xhint.hidden = true;
    if (r.top < 100 || r.top > innerHeight * 0.4)   // bring it under the top bar, keeping room for the buddy
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
    if (bub.hidden) { bub.hidden = false; bub.focus({ preventScroll: true }); }
    document.body.classList.add("xopen");
  };
  const closeX = () => {
    if (xi < 0) return;
    xi = -1;
    bub.hidden = true; ring.hidden = true; scrib.hidden = true;
    document.body.classList.remove("xopen");
    const dk = dockBtn.getBoundingClientRect();   // fly home, then disappear
    buddy.style.left = dk.left + scrollX + "px"; buddy.style.top = dk.top + scrollY + "px";
    setTimeout(() => { if (xi < 0) buddy.hidden = true; }, reduce ? 0 : 600);
  };
  byId("xb-close").addEventListener("click", closeX);
  byId("xb-prev").addEventListener("click", () => explain(xi - 1, true));
  byId("xb-next").addEventListener("click", () => explain(xi + 1, true));
  dockBtn.addEventListener("click", () => {
    xmode = !xmode;
    dockBtn.setAttribute("aria-pressed", String(xmode));
    document.body.classList.toggle("xmode", xmode);
    xhint.hidden = true;
    toast(XL[L()][xmode ? "on" : "off"]);
    if (!xmode) closeX();
  });
  document.addEventListener("click", e => {   // capture phase: in explain mode a click explains instead
    if (!xmode || e.target.closest(".xq, .xbubble, .xdock, a, button, summary, input, .term")) return;
    const el = e.target.closest("[data-x]");
    if (!el || xt.indexOf(el) < 0) return;
    e.stopPropagation(); e.preventDefault();
    explain(xt.indexOf(el), true);
  }, true);
  document.addEventListener("keydown", e => {
    if (xi < 0 || (e.target.matches && e.target.matches("input, textarea"))) return;
    if (e.key === "Escape") closeX();
    else if (e.key === "ArrowRight") explain(xi + 1, true);
    else if (e.key === "ArrowLeft") explain(xi - 1, true);
  });
  let reflow = false;
  const repositionSoon = () => {
    if (xi < 0 || reflow) return;
    reflow = true;
    requestAnimationFrame(() => { reflow = false; if (xi >= 0) place(xt[xi]); });
  };
  addEventListener("resize", repositionSoon);
  // the language switch, an opened table or answer can move things: keep the circle on its target
  new ResizeObserver(repositionSoon).observe(document.querySelector("main"));

  // ---- language: ?lang= > saved choice > browser language
  const setLang = (l, save) => {
    root.lang = l;
    document.title = TEXT[l].title;
    document.querySelectorAll("[data-set-lang]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setLang === l)));
    if (search) search.placeholder = search.dataset[l === "vi" ? "phVi" : "phEn"];
    applyTheme(); hide(); filterFaq(); xRelabel();
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
  const ask = xt.findIndex(el => el.dataset.x === params.get("explain"));
  if (ask >= 0) explain(ask, false);
  else if (!store.get("shf-xhint")) {
    store.set("shf-xhint", "1");
    setTimeout(() => { xhint.hidden = false; setTimeout(() => { xhint.hidden = true; }, 7000); }, 1200);
  }
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
