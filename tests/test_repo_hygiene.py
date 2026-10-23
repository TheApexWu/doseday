"""Tracked files must not carry private material or machine-specific paths."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Built by concatenation so this file does not match its own scan.
FORBIDDEN = [
    "/" + "Users/",
    "doseday" + "-draft",
    "~" + "/",
    "Desk" + "top",
    "St" + "udy",
    "viam" + "-flowers",
]
REQUIRED_IGNORES = ["poses.json", "calib.json", "pills.json", ".env.*", ".DS_Store"]


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def test_no_forbidden_strings_in_tracked_text():
    offenders = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in FORBIDDEN:
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {needle!r}")
    assert not offenders, "\n".join(offenders)


def test_gitignore_covers_site_and_secret_files():
    lines = {ln.strip() for ln in (ROOT / ".gitignore").read_text().splitlines()}
    missing = [p for p in REQUIRED_IGNORES if p not in lines]
    assert not missing, f"missing from .gitignore: {missing}"
