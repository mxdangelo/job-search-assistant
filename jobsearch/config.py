"""Where the data lives, and what it says about itself.

The engine holds no person. The data lives in a separate folder: the one named by
`JOBSEARCH_DATA`, otherwise the folder the command runs from. It holds `facts/`,
`postings/`, `profiles/`, `plans/`, `preferences.md` and `cv.yaml`.
"""
from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("JOBSEARCH_DATA") or Path.cwd()).resolve()
FACTS = ROOT / "facts"

USUAL_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


@cache
def config() -> dict:
    """The data folder's `cv.yaml`. Without `facts/` there is nothing to work on."""
    if not FACTS.is_dir():
        sys.exit(f"no facts/ folder in {ROOT}: run from the data folder or set JOBSEARCH_DATA")
    file = ROOT / "cv.yaml"
    return (yaml.safe_load(file.read_text(encoding="utf-8")) or {}) if file.exists() else {}


def header() -> dict:
    return config().get("header", {"name": "", "contacts": []})


def dev() -> Path:
    """The folder of the repos that measured facts take their numbers from."""
    return (ROOT / config().get("dev", "..")).resolve()


def chrome() -> Path | None:
    for candidate in [config().get("chrome"), *USUAL_CHROME]:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def jargon() -> list[str]:
    return [str(p) for p in config().get("jargon", [])]


def proper_nouns() -> set[str]:
    return {str(n) for n in config().get("proper_nouns", [])}


def expected_words() -> list[dict]:
    return list(config().get("expected_words", []))
