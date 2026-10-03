"""The same plan in every layout, to choose by looking.

    py -m jobsearch.preview plans/example.json

Writes `cv/preview/<plan>.<layout>.pdf` and, for each layout, says how an ATS reads it:
pages, extractable contacts, experience in the right order. A good-looking layout that an
ATS reads scrambled is fine only for CVs handed over in person.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jobsearch.facts import ROOT
from jobsearch.render import available_layouts, html, pdf

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def reading(printed: Path, plan: dict) -> str:
    """An ATS's verdict in one line: what it extracts, and in which order."""
    from pypdf import PdfReader

    pages = PdfReader(str(printed)).pages
    text = " ".join(" ".join(p.extract_text().split()) for p in pages)
    notes = [f"{len(pages)} p."]
    if not EMAIL.search(text):
        notes.append("email not extracted")
    # Each role is searched after the previous one: two roles can have the same title.
    pos = 0
    for v in plan.get("experience", []):
        role = " ".join(v["role"].split())
        found = text.find(role, pos)
        if found == -1:
            notes.append(f"«{role}» does not read where it should" if role in text
                         else f"«{role}» does not extract")
            break
        pos = found + len(role)
    else:
        notes.append("order ok")
    return ", ".join(notes)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    plan = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    folder = ROOT / "cv" / "preview"
    folder.mkdir(parents=True, exist_ok=True)
    for name in available_layouts():
        page = folder / f"{plan['profile']}.{name}.html"
        page.write_text(html(plan, name), encoding="utf-8")
        printed = pdf(page)
        result = reading(printed, plan) if printed else "PDF not generated"
        print(f"  {name:<12} {result}  -> {page.with_suffix('.pdf').relative_to(ROOT)}")
    print("\nchoose with `layout:` in cv.yaml, or in the plan for one CV only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
