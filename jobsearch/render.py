"""Approved plan -> HTML -> PDF. No model: this step only lays out the page.

The PDF in `cv/` is a draft: `jobsearch.deliver` copies it to `cv/delivered/`, after the
checks.

    py -m jobsearch.render plans/example.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from jobsearch import config
from jobsearch.facts import ROOT

HERE = Path(__file__).resolve().parent
# A hyphenated word: "e-commerce", "JSON-LD", "obsidian-claude-pkm".
COMPOUND = re.compile(r"(\w+(?:-\w+)+)")
# In a file name the brand is enough: "Acme", not "Acme Italia S.p.A.".
SUFFIXES = re.compile(r"\s+(?:S\.p\.A\.|S\.r\.l\.|Group|Italia)(?=\s|$)", re.I)


def whole(text: str) -> Markup:
    """Hyphenated words stay on one line: broken at "e-commerce", the ATS reads
    "e- commerce", and the word the posting searches for is gone."""
    return Markup(COMPOUND.sub(r'<span class="whole">\1</span>', str(escape(text))))


def folders(name: str) -> list[Path]:
    """Where to look for a layout: first in the data (a layout of one's own), then in the
    engine. `classic` always closes the list: a layout that only changes the style inherits
    the template, and its style is added to the classic one instead of redoing it."""
    candidates = [ROOT / "layout" / name, HERE / "layout" / name, HERE / "layout" / "classic"]
    return [c for c in dict.fromkeys(candidates) if c.is_dir()]


def layout_of(plan: dict) -> str:
    return plan.get("layout") or config.config().get("layout") or "classic"


def available_layouts() -> list[str]:
    names = {c.name for base in (HERE / "layout", ROOT / "layout") if base.is_dir()
             for c in base.iterdir() if c.is_dir()}
    return sorted(names, key=lambda n: (n != "classic", n))


def html(plan: dict, layout: str | None = None) -> str:
    dirs = folders(layout or layout_of(plan))
    if not dirs or (dirs[0].name != (layout or layout_of(plan))):
        raise SystemExit(f"layout «{layout or layout_of(plan)}» not found")
    env = Environment(loader=FileSystemLoader(dirs), autoescape=select_autoescape(["html"]))
    env.filters["whole"] = whole
    # Styles from the most general to the most specific: classic, then the layout's fixes.
    sheets = [d / "style.css" for d in reversed(dirs) if (d / "style.css").exists()]
    style = "\n".join(f.read_text(encoding="utf-8") for f in dict.fromkeys(sheets))
    # The PDF title is what the viewer shows on the tab: the same as the file.
    title = delivery_name(plan).removesuffix(".pdf")
    return env.get_template("cv.html.j2").render(
        p=plan, person=config.header(), style=style, page_title=title
    )


def pdf(source: Path) -> Path | None:
    """Prints in A4. If Chrome is missing, it says so: not a CV without a PDF, a PDF not made."""
    out = source.with_suffix(".pdf")
    if (browser := config.chrome()) is None:
        print("[unverified] Chrome not found: set it in cv.yaml (chrome:)")
        return None
    before = out.stat().st_mtime if out.exists() else 0
    subprocess.run(
        [str(browser), "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out}", source.as_uri()],
        check=True, capture_output=True,
    )
    # On Windows a PDF open in a viewer is locked and Chrome fails silently:
    # the old PDF stays, and the gate would check that one.
    if not out.exists() or out.stat().st_mtime <= before:
        print(f"[not generated] {out.name} was not rewritten: close it in the viewer and rerun")
        return None
    if not complete(out):
        print(f"[not generated] {out.name} is still incomplete after waiting: rerun")
        return None
    return out


def complete(out: Path, attempts: int = 20) -> bool:
    """Chrome can exit before it has finished writing: whoever reads at once finds half a
    PDF. Wait until the size stops changing and the PDF opens."""
    from pypdf import PdfReader

    size = -1
    for _ in range(attempts):
        now = out.stat().st_size
        if now == size:
            try:
                PdfReader(str(out)).pages[0].extract_text()
                return True
            except Exception:  # half a PDF fails in different ways: try again
                pass
        size = now
        time.sleep(0.25)
    return False


def company(plan: dict) -> str:
    """The company of the posting the profile answers, if there is one."""
    profile = ROOT / "profiles" / f"{plan['profile']}.md"
    posting = _front_matter(profile).get("posting") if profile.exists() else None
    if not posting or not (ROOT / posting).exists():
        return ""
    name = str(_front_matter(ROOT / posting).get("company", "")).split("(")[0]
    return SUFFIXES.sub("", name).strip()


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def delivery_name(plan: dict) -> str:
    """The file name is the first thing a recruiter reads, before the CV.

    It carries the company when the CV answers a posting: two CVs with the same title
    must not overwrite each other in `delivered/`.
    """
    role = re.split(r"—|–| - ", plan.get("title", plan["profile"]))[0]
    if who := company(plan):
        role = f"{role.strip()} ({who})"
    clean = " ".join(re.sub(r'[\/:*?"<>|]', " ", role).split())
    return f"CV {config.header()['name']} - {clean}.pdf"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    plan = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    folder = ROOT / "cv"
    folder.mkdir(exist_ok=True)
    page = folder / f"{plan['profile']}.html"
    page.write_text(html(plan), encoding="utf-8")
    print(f"[ok] {page.relative_to(ROOT)}")
    if (printed := pdf(page)) is None:
        return 1
    print(f"[ok] {printed.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
