"""Build docs/index.html: a one-page report of the latest run that a reader can scan.

    python -m shf.dashboard      # rebuild from results/ (run.py and scripts/error_analysis.py call this)

Reads only the files in results/, so it takes about a second and runs no simulation.
The page is a single self-contained file (inline SVG, no external scripts), so it
opens straight from disk and is served as-is by GitHub Pages from docs/.
"""
from __future__ import annotations

import csv
import html
import json
import math

from . import config

OUT = config.ROOT / "docs" / "index.html"
REPO = "https://github.com/chau1912550/self-healing-feeder"
V_TOL = config.V_TOL

METHODS = [  # (metrics key, label, categorical slot)
    ("fpi_baseline", "Conventional FPI", 1),
    ("ml_magnitude_only", "ML, magnitudes only", 2),
    ("ml_full", "ML, full features", 3),
]


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


def tip(s: str) -> str:
    """Attribute value for the hover tooltip (HTML allowed, built from our own data)."""
    return f'data-tip="{esc(s, quote=True)}" tabindex="0"'


def bar_path(x0: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Horizontal bar, square at the baseline, 4px rounded data end."""
    r = min(r, w, h / 2)
    return (f"M{x0:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 -{r},{r}h-{w - r:.1f}z")


# ---------------------------------------------------------------- charts
def line_chart(xlabels: list[str], series: list[tuple[str, int, list[float]]], title: str) -> str:
    W, H, L, R, T, B = 680, 300, 46, 150, 14, 42
    pw, ph = W - L - R, H - T - B
    step = pw / (len(xlabels) - 1)
    X = [L + i * step for i in range(len(xlabels))]
    Y = lambda v: T + ph * (1 - v)  # noqa: E731
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    for v in (0, .25, .5, .75, 1):
        g.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                 f'<text class="tick" x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.0%}</text>')
    for x, lab in zip(X, xlabels):
        g.append(f'<text class="tick" x="{x:.1f}" y="{T + ph + 18}" text-anchor="middle">{esc(lab)}</text>')
    g.append(f'<text class="tick" x="{L + pw / 2:.1f}" y="{H - 4}" text-anchor="middle">'
             f'fault resistance (Ω), line-to-ground faults</text>')
    gid = "guide-" + "".join(c for c in title.lower() if c.isalnum())   # stable id, no diff noise
    g.append(f'<line id="{gid}" class="guide" x1="0" x2="0" y1="{T}" y2="{T + ph}"/>')
    for name, slot, vals in series:
        pts = " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(X, vals))
        g.append(f'<polyline class="ln" style="stroke:var(--s{slot})" points="{pts}"/>')
        for x, v in zip(X, vals):
            g.append(f'<circle class="dot" style="fill:var(--s{slot})" cx="{x:.1f}" cy="{Y(v):.1f}" r="4"/>')
    # direct labels at the line ends, nudged apart so they never overlap
    ends = sorted(((Y(vals[-1]), name, slot) for name, slot, vals in series))
    placed, last = [], -1e9
    for y, name, slot in ends:
        y = max(y, last + 15)
        placed.append((y, name, slot))
        last = y
    for y, name, slot in placed:
        g.append(f'<line style="stroke:var(--s{slot})" class="key" x1="{L + pw + 10}" x2="{L + pw + 22}" '
                 f'y1="{y:.1f}" y2="{y:.1f}"/><text class="lab" x="{L + pw + 27}" y="{y + 4:.1f}">{esc(name)}</text>')
    for i, (x, lab) in enumerate(zip(X, xlabels)):  # hover columns, wider than the marks
        lines = "".join(f'<br>{esc(n)}: <b>{pct(v[i])}</b>' for n, _, v in series)
        g.append(f'<rect class="hit" x="{x - step / 2:.1f}" y="{T}" width="{step:.1f}" height="{ph}" '
                 f'data-guide="{gid}:{x:.1f}" {tip(f"<b>{esc(lab)} Ω</b>{lines}")}/>')
    g.append("</svg>")
    return "".join(g)


def hbar_chart(items: list[tuple[str, float, str]], vmax: float, fmt, title: str,
               ref: tuple[float, str] | None = None) -> str:
    W, L, R, rowh, bh = 680, 150, 70, 26, 16
    pw = W - L - R
    H = len(items) * rowh + 30
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">']
    g.append(f'<line class="axis" x1="{L}" x2="{L}" y1="4" y2="{len(items) * rowh + 4}"/>')
    for i, (lab, v, t) in enumerate(items):
        y = 4 + i * rowh + (rowh - bh) / 2
        w = max(pw * v / vmax, 1)
        g.append(f'<text class="lab" x="{L - 10}" y="{y + bh - 3:.1f}" text-anchor="end">{esc(lab)}</text>'
                 f'<path class="bar" d="{bar_path(L, y, w, bh)}"/>'
                 f'<text class="val" x="{L + w + 6:.1f}" y="{y + bh - 3:.1f}">{fmt(v)}</text>'
                 f'<rect class="hit" x="0" y="{4 + i * rowh}" width="{W}" height="{rowh}" {tip(t)}/>')
    if ref:
        x = L + pw * ref[0] / vmax
        g.append(f'<line class="ref" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{len(items) * rowh + 8}"/>'
                 f'<text class="tick" x="{x:.1f}" y="{H - 6}" text-anchor="middle">{esc(ref[1])}</text>')
    g.append("</svg>")
    return "".join(g)


def confusion_heatmap(rows: list[dict], order: list[str]) -> str:
    cell, L, T = 44, 64, 56
    n = len(order)
    W, H = L + n * cell + 4, T + n * cell + 4
    m = {r["true"]: r for r in rows}
    off = [int(m[t][p]) for t in order for p in order if t != p]
    top = max(off) or 1
    g = [f'<svg viewBox="0 0 {W} {H}" class="heat" role="img" aria-label="Confusion matrix, true vs predicted zone">']
    g.append(f'<text class="tick" x="{L + n * cell / 2}" y="12" text-anchor="middle">predicted zone →</text>')
    for j, p in enumerate(order):
        g.append(f'<text class="tick" x="{L + j * cell + cell / 2}" y="{T - 10}" text-anchor="middle">{p}</text>')
    for i, t in enumerate(order):
        y = T + i * cell
        g.append(f'<text class="tick" x="{L - 8}" y="{y + cell / 2 + 4}" text-anchor="end">{t}</text>')
        for j, p in enumerate(order):
            x, c = L + j * cell, int(m[t][p])
            if t == p:
                cls, label = "diag", f"{c:,}"
                msg = f"<b>{t}</b> correctly placed: <b>{c:,}</b> faults"
            elif c == 0:
                cls, label, msg = "q0", "", f"True {t} → predicted {p}: 0"
            else:
                q = 1 + min(4, int(4 * math.sqrt(c / top)))   # 5 sequential steps, sqrt scale
                cls, label = f"q{q}", str(c)
                msg = f"True <b>{t}</b> → predicted <b>{p}</b>: <b>{c}</b> faults"
            g.append(f'<g {tip(msg)}><rect class="cell {cls}" x="{x + 1}" y="{y + 1}" width="{cell - 2}" '
                     f'height="{cell - 2}" rx="3"/><text class="ct {cls}" x="{x + cell / 2}" y="{y + cell / 2 + 4}" '
                     f'text-anchor="middle">{label}</text></g>')
    g.append("</svg>")
    return "".join(g)


# ---------------------------------------------------------------- page pieces
def status(kind: str, text: str, detail: str) -> str:
    icon = {"good": "✓", "warning": "!", "critical": "✕"}[kind]
    word = {"good": "Pass", "warning": "Watch", "critical": "Fail"}[kind]
    return (f'<li class="check"><span class="chip {kind}"><span aria-hidden="true">{icon}</span> {word}</span>'
            f'<div><b>{esc(text)}</b><span class="muted">{detail}</span></div></li>')


def tile(label: str, value: str, sub: str) -> str:
    return f'<div class="tile"><div class="tl">{esc(label)}</div><div class="tv">{value}</div><div class="ts">{sub}</div></div>'


def table(head: list[str], rows: list[list[str]], num_cols: set[int] = frozenset()) -> str:
    th = "".join(f'<th{" class=n" if i in num_cols else ""}>{h}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td{" class=n" if i in num_cols else ""}>{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def section(id_: str, title: str, how: str, body: str) -> str:
    return f'<section id="{id_}"><h2>{title}</h2><p class="how">{how}</p>{body}</section>'


def checks(d: dict) -> list[str]:
    m, fl, rs = d["m"], d["m"]["fault_location"], d["m"]["restoration"]
    full, fpi = fl["ml_full"]["accuracy"], fl["fpi_baseline"]["accuracy"]
    out = [
        status("good" if m["dataset"]["converged_share"] == 1 else "critical", "Every fault simulation converged",
               f'{pct(m["dataset"]["converged_share"])} of {num(m["dataset"]["rows"])} power-flow solutions'),
        status("good" if rs["all_final_states_within_limits"] else "critical", "Every restored feeder stays within limits",
               "0.95–1.05 pu at every energized node and no line above its emergency rating, for all 10 fault zones"),
        status("good" if rs["all_radial"] else "critical", "Every switching plan keeps the feeder radial",
               "no loops after the ties close"),
        status("good" if full > fpi else "critical", "ML beats the conventional method",
               f"{pct(full)} vs {pct(fpi)} of faults placed in the right zone"),
    ]
    worst_r = fl["ml_full"]["slg_by_resistance"]["400.0"]
    out.append(status("warning" if worst_r < .9 else "good", "High-impedance ground faults",
                      f"only {pct(worst_r)} correct at 400 Ω, the known weak spot (fault current ≈ 6 A)"))
    dev, acc = min(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1])
    out.append(status("warning" if acc < .9 else "good", "One sensor offline",
                      f"worst case is {dev} offline: {pct(acc)} correct"))
    ea = d["ea"]
    if ea is None:
        out.append(status("warning", "Error analysis missing", "run <code>python scripts/error_analysis.py</code>"))
    elif round(ea["ml_accuracy"], 4) != round(full, 4):
        out.append(status("warning", "Error analysis is out of date",
                          "it was built from a different run; re-run <code>python scripts/error_analysis.py</code>"))
    else:
        out.append(status("good", "Error analysis matches this run",
                          f'same out-of-fold accuracy ({pct(ea["ml_accuracy"], 2)})'))
    return out


def build() -> None:
    d = load()
    m, fl, rs = d["m"], d["m"]["fault_location"], d["m"]["restoration"]
    order = [z["zone"] for z in d["zones"]]
    pk = m["patrol_kft"]
    t = rs["timing_assumption_min"]
    by_type = m["dataset"]["by_type"]

    tiles = "".join([
        tile("Fault zone found", pct(fl["ml_full"]["accuracy"]), f'vs {pct(fl["fpi_baseline"]["accuracy"])} with conventional fault indicators'),
        tile("Average crew patrol", f'{pk["ml_full"]:.1f} kft', f'vs {pk["no_location"]:.1f} kft with no fault location ({pk["ml_full"] / pk["no_location"] - 1:+.0%})'),
        tile("Healthy load restored by ties", f'{num(rs["kW_restored_by_tie_total"])} kW',
             f'of {num(rs["kW_downstream_healthy_total"])} kW left dark ({rs["kW_restored_by_tie_total"] / rs["kW_downstream_healthy_total"]:.0%}), summed over 10 cases'),
        tile("Customer outage (kW·min)", f'−{rs["kWmin_reduction_pct_weighted_by_line_length"]:.1f}%',
             f'vs manual switching; assumes {t["automated"]} / {t["manual"]} / {t["repair"]} min'),
        tile("Faults simulated", num(m["dataset"]["rows"]), " · ".join(f"{k} {num(v)}" for k, v in by_type.items())),
    ])

    # fault location
    rkeys = list(fl["ml_full"]["slg_by_resistance"])
    xl = [f"{float(k):g}" for k in rkeys]
    series = [(lab, s, [fl[k]["slg_by_resistance"][r] for r in rkeys]) for k, lab, s in METHODS]
    types = ["3PH", "LL", "LLG", "SLG"]
    loc_table = table(["Method", "All faults", *types],
                      [[lab, f"<b>{pct(fl[k]['accuracy'])}</b>", *[pct(fl[k]["by_fault_type"][ty]) for ty in types]]
                       for k, lab, _ in METHODS], {1, 2, 3, 4, 5})
    res_table = table(["Ω", *[lab for _, lab, _ in METHODS]],
                      [[x, *[pct(v[i]) for _, _, v in series]] for i, x in enumerate(xl)], {1, 2, 3})
    miss = sorted(fl["ml_full"]["missing_sensor_accuracy"].items(), key=lambda kv: kv[1])
    miss_chart = hbar_chart([(f"{k} offline", v, f"<b>{k} offline</b><br>{pct(v)} of faults placed correctly")
                             for k, v in miss], 1, pct, "Accuracy with one sensor offline",
                            ref=(fl["ml_full"]["accuracy"], f'all online {pct(fl["ml_full"]["accuracy"])}'))
    s_loc = section("location", "1 · Fault location",
                    "After the feeder-head recloser locks out, which of the 10 zones holds the fault? Accuracy is measured on "
                    "buses the model never saw in training. The chart shows where each method breaks down: as the ground-fault "
                    "resistance rises, the fault current shrinks toward the size of normal load swings.",
                    f'<div class="legend"><span><i style="background:var(--s1)"></i>Conventional FPI</span>'
                    f'<span><i style="background:var(--s2)"></i>ML, magnitudes only</span>'
                    f'<span><i style="background:var(--s3)"></i>ML, full features</span></div>'
                    f'<div class="chart">{line_chart(xl, series, "Accuracy vs fault resistance")}</div>'
                    f'<details><summary>Show as table</summary>{res_table}</details>'
                    f'<h3>By fault type</h3>{loc_table}'
                    f'<h3>If one sensor stops reporting (ML, full features)</h3><div class="chart">{miss_chart}</div>')

    # error analysis
    ea = d["ea"]
    if ea:
        pz = table(["Zone", "Faults", "Missed (FNR)", "Wrongly blamed (FPR)", "Precision"],
                   [[r["zone"], num(int(r["n"])), pct(float(r["FNR"])), pct(float(r["FPR"]), 2), pct(float(r["precision"]))]
                    for r in d["per_zone"]], {1, 2, 3, 4})
        dirs = sorted(ea["ml_error_direction"].items(), key=lambda kv: -kv[1])
        tot = ea["ml_errors"]
        dir_chart = hbar_chart([(k.split(" (")[0], v, f"<b>{esc(k)}</b><br>{v} of {tot} errors ({v / tot:.0%})")
                                for k, v in dirs], max(v for _, v in dirs), lambda v: f"{v:.0f}", "Where wrong answers point")
        defer = table(["Defer below", "Faults kept", "Accuracy on kept", "Errors left"],
                      [[f'{r["threshold"]:.2f}', pct(r["coverage"]), pct(r["accuracy_on_kept"]), num(r["errors_kept"])]
                       for r in ea["defer_low_confidence"]], {0, 1, 2, 3})
        hi = ea["ml_errors_slg_200_ohm_or_more"]
        load_t = ea["ml_error_rate_by_load_tercile"]
        s_err = section("errors", "2 · Error analysis",
                        f"{tot} of {num(ea['faults'])} faults ({tot / ea['faults']:.1%}) went to the wrong zone. "
                        f"{hi} of them ({hi / tot:.0%}) are ground faults at 200 Ω or more, and errors rise with load "
                        f"({pct(load_t['low'])} in the lightest third of scenarios, {pct(load_t['high'])} in the heaviest). "
                        "Because the model always names a zone, misses and false blames are counted per zone (one zone vs the rest).",
                        f"<h3>Per zone</h3>{pz}"
                        f'<h3>Confusion matrix</h3><p class="note">Rows are the true zone, columns the predicted zone, in feeder '
                        f'order from the substation. Gray diagonal = correct. Blue cells are errors; darker means more.</p>'
                        f'<div class="chart heatwrap">{confusion_heatmap(d["confusion"], order)}</div>'
                        f'<h3>Where the wrong answers point</h3><div class="chart">{dir_chart}</div>'
                        f'<h3>Let the model say “not sure”</h3><p class="note">Predictions below the confidence cutoff go to a '
                        f'manual patrol instead. Median confidence: {ea["ml_median_confidence"]["correct"]:.2f} when right, '
                        f'{ea["ml_median_confidence"]["wrong"]:.2f} when wrong.</p>{defer}')
    else:
        s_err = section("errors", "2 · Error analysis", "Not built yet.",
                        "<p>Run <code>python scripts/error_analysis.py</code> to add per-zone misses, the confusion matrix "
                        "and the confidence trade-off.</p>")

    # restoration
    rows = []
    for r in d["rest"]:
        ok = (r["radial"] == "True" and int(r["final_overloads"]) == 0
              and float(r["final_vmin_pu"]) >= config.V_MIN_PU - V_TOL and float(r["final_vmax_pu"]) <= config.V_MAX_PU + V_TOL)
        chip = '<span class="chip good">✓ Within limits</span>' if ok else '<span class="chip critical">✕ Violation</span>'
        out_kw, back = float(r["kW_downstream_healthy"]), float(r["kW_restored_by_tie"])
        dash = lambda v: "–" if v == "-" else v  # noqa: E731
        rows.append([f'<b>{r["fault_zone"]}</b>', chip, dash(r["ties_closed"]),
                     f"{num(back)} / {num(out_kw)}" if out_kw else "–", dash(r["unserved_healthy"]),
                     f'{float(r["final_vmin_pu"]):.3f}–{float(r["final_vmax_pu"]):.3f}',
                     f'{float(r["kWmin_reduction_pct"]):.1f}%', r["power_flow_checks"]])
    s_rest = section("restoration", "3 · Isolation and restoration",
                     "Each zone is faulted in turn. The fault is isolated, the upstream part re-closed, and a tie switch is closed only "
                     "if a power flow shows every voltage, current and the radial layout stay within limits.",
                     table(["Fault zone", "Status", "Ties closed", "kW back / dark", "Still dark", "Voltage (pu)",
                            "kW·min saved", "Power flows checked"], rows, {3, 5, 6, 7}))

    zt = table(["Zone", "Fed by", "Upstream zone", "Load kW", "Load points", "Line kft"],
               [[z["zone"], esc(z["fed_by"]), z["parent_zone"] or "substation", num(float(z["kW"])), z["load_points"],
                 f'{float(z["line_kft"]):.2f}'] for z in d["zones"]], {3, 4, 5})
    s_zones = section("zones", "4 · Feeder zones", "The 10 switching zones of the IEEE 123-bus feeder used throughout this report.", zt)

    page = TEMPLATE.format(
        runtime=f'{m["runtime_s"]:.0f}', rows=num(m["dataset"]["rows"]), repo=REPO,
        checks="".join(checks(d)), tiles=tiles, body=s_loc + s_err + s_rest + s_zones,
        t_auto=t["automated"], t_man=t["manual"], t_rep=t["repair"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print("wrote", OUT)


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Self-Healing Feeder Report</title>
<meta name="description" content="Run report for the self-healing feeder study: fault location accuracy, error analysis and restoration checks on the IEEE 123-bus feeder.">
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: #e1e0d9;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --bar: #2a78d6;
  --good: #0ca30c; --good-ink: #006300; --warning: #fab219; --critical: #d03b3b;
  --q1: #cde2fb; --q2: #9ec5f4; --q3: #5598e7; --q4: #2a78d6; --q5: #1c5cab;
  --qi-lo: #0b0b0b; --qi-hi: #ffffff; --diag: #f0efec;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --border: #2c2c2a;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --bar: #3987e5;
    --good-ink: #0ca30c;
    --q1: #184f95; --q2: #1c5cab; --q3: #256abf; --q4: #3987e5; --q5: #6da7ec;
    --qi-lo: #f0efec; --qi-hi: #0b0b0b; --diag: #2c2c2a;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #9a988f;
  --grid: #2c2c2a; --axis: #383835; --border: #2c2c2a;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --bar: #3987e5;
  --good-ink: #0ca30c;
  --q1: #184f95; --q2: #1c5cab; --q3: #256abf; --q4: #3987e5; --q5: #6da7ec;
  --qi-lo: #f0efec; --qi-hi: #0b0b0b; --diag: #2c2c2a;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 28px 16px 64px; }}
header h1 {{ font-size: 28px; line-height: 1.2; margin: 0 0 6px; letter-spacing: -0.01em; }}
header p {{ margin: 0; color: var(--ink2); max-width: 760px; }}
.meta {{ margin-top: 10px; font-size: 13px; color: var(--muted); }}
a {{ color: var(--s1); }}
nav {{ display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 18px 0 8px; font-size: 14px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }}
.tile, section, .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }}
.tile {{ padding: 14px 16px; }}
.tl {{ font-size: 13px; color: var(--ink2); }}
.tv {{ font-size: 30px; font-weight: 650; line-height: 1.2; margin: 4px 0; font-variant-numeric: tabular-nums; }}
.ts {{ font-size: 12.5px; color: var(--muted); }}
.panel {{ padding: 16px 18px; }}
.panel h2, section h2 {{ font-size: 19px; margin: 0 0 6px; }}
section {{ padding: 18px; margin-top: 18px; }}
h3 {{ font-size: 15px; margin: 22px 0 8px; }}
.how {{ color: var(--ink2); margin: 0 0 12px; max-width: 800px; }}
.note {{ color: var(--muted); font-size: 13px; margin: 0 0 8px; }}
.checks {{ list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 10px; }}
.check {{ display: flex; gap: 12px; align-items: flex-start; }}
.check b {{ display: block; font-weight: 600; }}
.muted {{ color: var(--muted); font-size: 13.5px; }}
.chip {{ flex: none; display: inline-flex; gap: 4px; align-items: center; font-size: 12px; font-weight: 600;
  padding: 2px 9px; border-radius: 999px; white-space: nowrap; border: 1px solid;
  min-width: 74px; justify-content: center; }}
.chip.good {{ color: var(--good-ink); border-color: var(--good); }}
.chip.warning {{ color: var(--ink); border-color: var(--warning); background: color-mix(in srgb, var(--warning) 22%, transparent); }}
.chip.critical {{ color: var(--critical); border-color: var(--critical); }}
.chart {{ overflow-x: auto; }}
.chart svg {{ width: 100%; min-width: 560px; height: auto; display: block; }}   /* keep text legible on phones; the chart scrolls, not the page */
.heatwrap svg {{ min-width: 440px; }}
.heatwrap {{ max-width: 520px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--ink2); margin-bottom: 4px; }}
.legend i {{ display: inline-block; width: 12px; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: 6px; }}
svg text {{ font-family: inherit; }}
.tick {{ font-size: 12px; fill: var(--muted); }}
.lab {{ font-size: 13px; fill: var(--ink2); }}
.val {{ font-size: 12.5px; fill: var(--ink); font-variant-numeric: tabular-nums;
  paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ stroke: var(--axis); stroke-width: 1; }}
.ref {{ stroke: var(--ink2); stroke-width: 1; stroke-dasharray: 3 3; }}
.guide {{ stroke: var(--axis); stroke-width: 1; opacity: 0; }}
.ln {{ fill: none; stroke-width: 2; stroke-linejoin: round; }}
.key {{ stroke-width: 3; stroke-linecap: round; }}
.dot {{ stroke: var(--surface); stroke-width: 2; }}
.bar {{ fill: var(--bar); }}
.hit {{ fill: transparent; outline: none; }}
.hit:focus {{ fill: color-mix(in srgb, var(--ink) 5%, transparent); }}
.cell {{ stroke: none; }} .cell.q0 {{ fill: transparent; stroke: var(--grid); }} .cell.diag {{ fill: var(--diag); }}
.cell.q1 {{ fill: var(--q1); }} .cell.q2 {{ fill: var(--q2); }} .cell.q3 {{ fill: var(--q3); }}
.cell.q4 {{ fill: var(--q4); }} .cell.q5 {{ fill: var(--q5); }}
.ct {{ font-size: 12px; font-variant-numeric: tabular-nums; pointer-events: none; }}
.ct.diag {{ fill: var(--ink2); font-size: 10.5px; }} .ct.q1, .ct.q2 {{ fill: var(--qi-lo); }}
.ct.q3, .ct.q4, .ct.q5 {{ fill: var(--qi-hi); }}
.heat g:hover rect, .heat g:focus rect {{ stroke: var(--ink); stroke-width: 1.5; }}
.heat g {{ outline: none; }}
.tw {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
th {{ font-weight: 600; color: var(--ink2); white-space: nowrap; }}
td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
details {{ margin: 6px 0 4px; font-size: 14px; }} summary {{ cursor: pointer; color: var(--s1); }}
code {{ font-size: 0.92em; background: var(--diag); padding: 1px 5px; border-radius: 4px; }}
footer {{ margin-top: 24px; font-size: 13px; color: var(--muted); }}
#tip {{ position: fixed; z-index: 9; pointer-events: none; max-width: 260px; padding: 8px 10px; border-radius: 8px;
  font-size: 13px; line-height: 1.45; background: var(--ink); color: var(--page); box-shadow: 0 4px 16px rgb(0 0 0 / .18); }}
@media (max-width: 560px) {{ header h1 {{ font-size: 23px; }} .tv {{ font-size: 26px; }} section {{ padding: 14px; }} }}
</style>
</head>
<body>
<main>
<header>
  <h1>Self-Healing Feeder · Run Report</h1>
  <p>Machine-learning fault location and automated restoration (FLISR) on the IEEE 123-bus distribution feeder,
  simulated in OpenDSS. Every number on this page is read from the latest <code>python run.py</code>.</p>
  <div class="meta">{rows} simulated faults · run time {runtime} s · simulation only, not field data ·
  <a href="{repo}">source on GitHub</a></div>
</header>
<nav aria-label="Sections"><a href="#health">Run checks</a><a href="#location">Fault location</a>
<a href="#errors">Error analysis</a><a href="#restoration">Restoration</a><a href="#zones">Zones</a></nav>
<div class="tiles">{tiles}</div>
<div class="panel" id="health"><h2>Run checks</h2>
<p class="how">Pass = the result meets its limit. Watch = a known weak spot to keep an eye on. Fail = something to fix before trusting the numbers.</p>
<ul class="checks">{checks}</ul></div>
{body}
<footer>Assumptions behind the outage numbers: automated switching {t_auto} min, manual switching {t_man} min, repair {t_rep} min.
All devices beyond the IEEE test case are marked <code>ASSUMPTION</code> in <code>shf/config.py</code>.
Rebuild this page with <code>python -m shf.dashboard</code>.</footer>
</main>
<div id="tip" role="tooltip" hidden></div>
<script>
(() => {{
  const tip = document.getElementById("tip");
  let guide = null;
  const show = (el, x, y) => {{
    tip.innerHTML = el.dataset.tip; tip.hidden = false;
    if (el.dataset.guide) {{
      const [id, gx] = el.dataset.guide.split(":");
      guide = document.getElementById(id);
      guide.setAttribute("x1", gx); guide.setAttribute("x2", gx); guide.style.opacity = 1;
    }}
    move(x, y);
  }};
  const move = (x, y) => {{
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
    tip.style.top = (y + h + 22 > innerHeight ? y - h - 14 : y + 16) + "px";
  }};
  const hide = () => {{ tip.hidden = true; if (guide) guide.style.opacity = 0; guide = null; }};
  document.addEventListener("pointerover", e => {{ const el = e.target.closest("[data-tip]"); if (el) show(el, e.clientX, e.clientY); }});
  document.addEventListener("pointermove", e => {{ if (!tip.hidden) move(e.clientX, e.clientY); }});
  document.addEventListener("pointerout", e => {{ if (e.target.closest("[data-tip]")) hide(); }});
  document.addEventListener("focusin", e => {{ const el = e.target.closest("[data-tip]");
    if (el) {{ const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); }} }});
  document.addEventListener("focusout", hide);
  addEventListener("scroll", hide, {{ passive: true }});
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
