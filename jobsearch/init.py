"""A new data folder, ready to fill.

    py -m jobsearch.init <folder>

Creates the folders, a `cv.yaml` from a few questions, a starting `preferences.md` and an
empty applications log. Then: `intake cv` to start from an old CV, or `intake interview`
to start from nothing. It never overwrites a folder that already has facts.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

FOLDERS = ["facts/experience", "facts/projects", "facts/education", "postings", "profiles",
           "plans", "cv"]
TEMPLATES = Path(__file__).resolve().parent / "templates"


def ask(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{hint}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def career() -> dict:
    """Start dates per field, to count the years a posting asks for: «SEO=2021-08»."""
    found = {}
    raw = ask("Career start per field, e.g. SEO=2021-08, content=2018-09 (optional)")
    for part in filter(None, (p.strip() for p in raw.split(","))):
        if "=" in part:
            field, start = (x.strip() for x in part.split("=", 1))
            found[field] = start
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    root = Path(argv[0]).resolve()
    if (root / "cv.yaml").exists() or (
        (root / "facts").is_dir() and any((root / "facts").rglob("*.md"))
    ):
        print(f"[not created] {root} is already a data folder: nothing overwritten")
        return 1
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)

    name = ask("Your name, as it goes on the CV")
    contacts = [c.strip() for c in ask("Contacts, comma separated (email, phone, site, city)")
                .split(",") if c.strip()]
    settings = {
        "header": {"name": name, "contacts": contacts},
        "layout": "classic",
        "facts_language": ask("Language you will write your facts in", "English"),
        "career": career(),
        "jargon": [],
        "proper_nouns": [],
        "expected_words": [],
    }
    (root / "cv.yaml").write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False),
                                  encoding="utf-8")
    if not (root / "preferences.md").exists():
        shutil.copyfile(TEMPLATES / "preferences.md", root / "preferences.md")
    if not (root / "applications.yaml").exists():
        (root / "applications.yaml").write_text("[]\n", encoding="utf-8")

    print(f"\n[ok] {root}")
    print("next, from that folder:")
    print("  py -m jobsearch.intake cv <old-cv.pdf>   # start from an old CV")
    print("  py -m jobsearch.intake interview         # or from nothing")
    print("  py -m jobsearch.check                    # what is still weak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
