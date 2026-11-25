"""Automated privacy, PII, local-path, and secret leak audit for GitHub-published files.

Run before any git commit or push:
    python scripts/privacy_audit.py

Exits 0 only if zero personal info, local machine paths, private files, or secrets appear
in any Git-tracked or publishable project file.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATH_PREFIXES = (
    ".env",
    ".kaggle/",
    "ops/",
    "HANDOFF.md",
    "CLAUDE.local.md",
    "inputs/private/",
    "docs/RESUME_BULLETS.md",
    ".venv/",
)

FORBIDDEN_PATH_SUFFIXES = (
    "kaggle.json",
    ".env",
    ".env.local",
)

TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".html", ".css", ".js",
    ".c", ".h", ".ino", ".cir", ".csv", ".ini", ".cfg", ".sh", ".ps1", ".ipynb",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_EMAIL_DOMAINS = (
    "users.noreply.github.com",
    "example.com",
    "example.org",
    "localhost",
)

CONTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("local_windows_user_path", re.compile(r"(?i)[A-Z]:[/\\]Users[/\\][A-Za-z0-9._-]+")),
    ("local_drive_project_path", re.compile(r"(?i)[A-Z]:[/\\]Local[/\\]Projects")),
    ("windows_username_leak", re.compile(r"(?i)(?:^|[/\\:\s'\"`])choit(?:[/\\:\s'\"`]|$)")),
    ("personal_school_mention", re.compile(r"(?i)\bvol\s*state\b")),
    ("github_token", re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("api_key_token", re.compile(r"(?:AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|KGAT_[A-Za-z0-9]{12,})")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


def candidate_files() -> list[Path]:
    """All Git-tracked files plus non-ignored publishable files in hif_sensor/, docs/, .github/."""
    files: set[Path] = set()
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
        for line in out.splitlines():
            p = ROOT / line.strip()
            if p.is_file():
                files.add(p)
    except Exception:
        pass

    # Also check newly added files that are not git-ignored
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
        )
        for line in out.splitlines():
            p = ROOT / line.strip()
            if p.is_file():
                files.add(p)
    except Exception:
        pass
    return sorted(files)


def audit() -> list[str]:
    findings: list[str] = []
    self_rel = Path("scripts/privacy_audit.py").as_posix()

    for path in candidate_files():
        rel = path.relative_to(ROOT).as_posix()
        for pref in FORBIDDEN_PATH_PREFIXES:
            if pref == ".env" and rel == ".env.example":
                continue
            if rel == pref.rstrip("/") or rel.startswith(pref):
                findings.append(f"{rel}: forbidden_private_file ({pref})")
        for suf in FORBIDDEN_PATH_SUFFIXES:
            if rel == suf or rel.endswith("/" + suf):
                findings.append(f"{rel}: forbidden_secret_file ({suf})")
        if rel.startswith("hif_sensor/circuit/") and path.suffix.lower() in (".raw", ".db", ".log"):
            findings.append(f"{rel}: forbidden_binary_sim_artifact")

        if rel == self_rel or path.suffix.lower() not in TEXT_EXTS:
            continue
        if path.stat().st_size > 15_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            for rule_name, pat in CONTENT_RULES:
                if rule_name == "local_windows_user_path" and rel == "tests/test_provenance.py" and r"C:\Users\alice" in line:
                    continue
                if pat.search(line):
                    findings.append(f"{rel}:{lineno}: {rule_name}")
            for m in EMAIL_RE.finditer(line):
                email = m.group(0).lower()
                # Skip CSS @media/@keyframes or JS @version false hits (already filtered by regex)
                domain = email.split("@", 1)[1]
                if not any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
                    # Ignore npm CDN version tags like katex@0.16.11/dist/... if matched
                    if "/" in line[m.start():m.end() + 1] or domain.replace(".", "").isdigit():
                        continue
                    findings.append(f"{rel}:{lineno}: personal_email ({email})")
    return findings


def main() -> int:
    findings = audit()
    if findings:
        print(f"PRIVACY AUDIT FAILED: {len(findings)} finding(s)")
        for item in findings[:50]:
            print("  -", item)
        if len(findings) > 50:
            print(f"  ... and {len(findings) - 50} more")
        return 1
    print("PRIVACY AUDIT PASS: 0 personal info / local path / secret leaks found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
