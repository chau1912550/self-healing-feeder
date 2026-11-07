"""Project health check: is every stated number still true, is every page fresh, is nothing secret in git?

    python harness/check.py           # all checks (about 1 s)
    python harness/check.py --tests   # also run the pytest suite

Run it after every change and before every commit. It exits with code 1 if anything fails,
and each failure says which file to fix and how. What it checks:

  facts      every number in harness/facts.toml appears, as computed from results/, in its files
  forbidden  no claim or stale wording listed in harness/facts.toml
  fresh      published copies (docs/data, docs/monitor, error analysis) match the latest run
  links      every relative link in the Markdown files points to a file that exists
  secrets    no API key or .env file is tracked by git
  apis       config/apis.md, .env.example and the code agree on which APIs exist
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RES = ROOT / "results"
PROSE = ["README.md", *sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "docs").rglob("*.md"))]
results: list[tuple[str, str, str]] = []   # (status, check, detail)


def report(ok: bool, check: str, detail: str, warn: bool = False) -> None:
    results.append(("PASS" if ok else ("WARN" if warn else "FAIL"), check, detail))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def num(v: str):
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


def namespace() -> dict:
    from shf.dashboard_text import FAQ
    m = json.loads(read("results/metrics.json"))
    e = json.loads(read("results/error_analysis/error_analysis.json"))
    with open(RES / "restoration.csv", encoding="utf-8") as f:
        r = [{k: num(v) for k, v in row.items()} for row in csv.DictReader(f)]
    mon = json.loads(read("docs/monitor/data.json"))
    return {
        "m": m, "e": e, "r": r, "mon": mon, "faq": len(FAQ),
        "defer": {t["threshold"]: t for t in e["defer_low_confidence"]},
        "pct": lambda x, d=1: f"{100 * x:.{d}f}%",
        "comma": lambda n: f"{round(n):,}",
        "f1": lambda x: f"{x:.1f}",
        "round": round, "min": min, "max": max, "sum": sum, "len": len, "str": str, "list": list,
    }


def check_facts(spec: dict, ns: dict) -> None:
    for fact in spec.get("fact", []):
        try:
            val = eval(fact["expr"], {"__builtins__": {}, **ns})   # expressions come from our own facts.toml
        except Exception as ex:  # noqa: BLE001
            report(False, "facts", f"{fact['id']}: expression failed ({ex})")
            continue
        if val is None:
            report(False, "facts", f"{fact['id']}: not in results yet; re-run python run.py", warn=True)
            continue
        texts = val if isinstance(val, list) else [val]
        for rel in fact["in"]:
            body = read(rel)
            missing = [t for t in texts if t not in body]
            report(not missing, "facts",
                   f"{fact['id']} in {rel}" + (f": expected {missing} ({fact['what']}); update the text to the latest run"
                                               if missing else f" = {', '.join(texts)}"))


def check_forbidden(spec: dict) -> None:
    for rule in spec.get("forbidden", []):
        hits = [f"{rel}:{i}" for rel in rule.get("files", PROSE)
                for i, line in enumerate(read(rel).splitlines(), 1) if rule["text"].lower() in line.lower()]
        report(not hits, "forbidden", f"'{rule['text']}'" + (f" found at {', '.join(hits)}. {rule['why']}" if hits else ""))


def check_fresh(ns: dict) -> None:
    m, e = ns["m"], ns["e"]
    acc = m["fault_location"]["ml_full"]["accuracy"]
    same = e["faults"] == m["dataset"]["rows"] and abs(e["ml_accuracy"] - acc) < 1e-3
    report(same, "fresh", "error analysis matches the latest run" if same else
           "results/error_analysis is from an older run: python scripts/error_analysis.py")
    mon_ok = abs(ns["mon"]["metrics"]["ml_acc"] - acc) < 1e-9
    report(mon_ok, "fresh", "docs/monitor/data.json matches the latest run" if mon_ok else
           "docs/monitor/data.json is stale: python scripts/export_control_room.py")
    stale = []
    for pub in (ROOT / "docs" / "data").iterdir():
        for src in (RES / pub.name, RES / "error_analysis" / pub.name):
            if src.exists() and src.read_bytes() != pub.read_bytes():
                stale.append(pub.name)
    report(not stale, "fresh", "docs/data copies match results/" if not stale else
           f"docs/data/{', '.join(stale)} differ from results/: python -m shf.dashboard")


def check_links() -> None:
    bad = []
    for rel in PROSE:
        base = (ROOT / rel).parent
        for target in re.findall(r"\]\(([^)\s]+)\)", read(rel)):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#")[0]
            if path and not (base / path).exists():
                bad.append(f"{rel} -> {target}")
    report(not bad, "links", "all relative links resolve" if not bad else "broken: " + "; ".join(bad))


SECRET = re.compile(r"(sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}"
                    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


def check_secrets() -> None:
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        report(False, "secrets", "git not available; cannot list tracked files", warn=True)
        return
    report(".env" not in files, "secrets", ".env is not tracked" if ".env" not in files else ".env is tracked: git rm --cached .env")
    hits = []
    for rel in files:
        p = ROOT / rel
        if p.suffix in {".gz", ".png", ".jpg", ".pkl", ".ipynb"} or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            if SECRET.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(rel)
        except OSError:
            pass
    report(not hits, "secrets", "no key-like strings in tracked files" if not hits else f"possible key in {', '.join(hits)}")


def check_apis() -> None:
    from shf import apis
    try:
        rows = apis.registry()
    except Exception as ex:  # noqa: BLE001
        report(False, "apis", f"config/apis.md: {ex}")
        return
    bad_status = [r["Name"] for r in rows if r["Status"] not in apis.STATUSES]
    report(not bad_status, "apis", f"{len(rows)} registered" + (f"; bad status in {bad_status} (use planned/active/off)" if bad_status else ""))
    example = set(re.findall(r"^([A-Z0-9_]+)=", read(".env.example"), re.M))
    reg_vars = {r["Env var"] for r in rows}
    report(reg_vars == example, "apis", ".env.example matches the registry" if reg_vars == example else
           f".env.example and config/apis.md differ: only in registry {sorted(reg_vars - example)}, only in .env.example {sorted(example - reg_vars)}")
    names = {r["Name"].lower(): r for r in rows}
    code = [p for p in ROOT.rglob("*.py") if not {".venv", "harness", "tests"} & set(p.parts)]
    unknown, raw = [], []
    for p in code:
        text = p.read_text(encoding="utf-8", errors="ignore")
        unknown += [f"{p.name}: {n}" for n in re.findall(r"apis\.key\(\s*[\"']([^\"']+)", text) if n.lower() not in names]
        if p.name != "apis.py" and re.search(r"(environ|getenv)\W+[\"'][A-Z_]*(KEY|TOKEN|SECRET)", text):
            raw.append(p.name)
    report(not unknown, "apis", "code only uses registered APIs" if not unknown else f"not in config/apis.md: {unknown}")
    report(not raw, "apis", "keys are read only through shf.apis" if not raw else
           f"{raw} read a key straight from the environment; use shf.apis.key()", warn=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", action="store_true", help="also run pytest")
    ap.add_argument("-v", "--verbose", action="store_true", help="list passing checks too")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    spec = tomllib.loads(read("harness/facts.toml"))
    ns = namespace()
    check_facts(spec, ns)
    check_forbidden(spec)
    check_fresh(ns)
    check_links()
    check_secrets()
    check_apis()
    if args.tests:
        t = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True)
        report(t.returncode == 0, "tests", (t.stdout.strip().splitlines() or ["no output"])[-1])
    for st, check, detail in results:
        if st != "PASS" or args.verbose:
            print(f"{st}  {check:<9} {detail}")
    n = {s: sum(r[0] == s for r in results) for s in ("PASS", "WARN", "FAIL")}
    print(f"\n{n['PASS']} passed, {n['WARN']} warnings, {n['FAIL']} failed"
          + ("" if args.verbose else "  (add -v to list the passing checks)"))
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
