"""Filling the fact base: from an old CV, and by interview.

    py -m jobsearch.intake cv old-cv.pdf     # prompt: split an old CV into fact files
    py -m jobsearch.intake interview         # prompt: a chat that asks, one question at a time

The engine calls no model. Each command writes a prompt to the data folder; run it with any
model that can write files, or paste it in a chat and save the files it returns. Facts
from an old CV enter as `stated`, never `measured`: the CV is a claim, not a source. The
interview starts from what `jobsearch.check` finds weak, and from what came after the
latest job in the fact base.
"""
from __future__ import annotations

import re
import sys
import zipfile
from datetime import date
from pathlib import Path

from jobsearch import config
from jobsearch.check import report
from jobsearch.facts import ROOT, load

OPEN = "intake.open.md"   # what the old CV leaves open, written by the import

SCHEMA = """\
Each fact is one Markdown file under `facts/`, with YAML front matter and prose:

- `facts/experience/<slug>.md` — one job or client:
  type: experience, company, role, location, period ("MM/YYYY → MM/YYYY" or
  "MM/YYYY → present"), evidence, status, confidential (optional list).
- `facts/projects/<slug>.md` — one project: type: project, name, period, role,
  technologies (list), url (optional), evidence, status.
- `facts/education/<slug>.md` — degrees, courses, languages (`languages.md`): type:
  education, evidence, status.
- `facts/tools.md` — tools and techniques in current use: type: tools, evidence, status.

`status` is one of:
- `measured` — the candidate counted it from a file and says how; the command or the
  file is in `evidence`.
- `stated` — the candidate says it (or an old CV does). True until they say otherwise.
- `unconfirmed` — inferred, never confirmed. It never reaches a CV.

`confidential` lists strings that are true but must never be printed: salary, fees,
client names under NDA.

The prose says what the work was, for whom (what the company does), what changed because
of it, and with which number, if there is one. Write the facts in {language}.
"""

FROM_CV = """\
Split the old CV below into fact files for a fact base. Do not write a CV.

{schema}
Rules:
- Everything the CV says enters as `status: stated`, with `evidence: old CV, <file name>`.
  Never `measured`: a CV is a claim, not a source.
- Anything you infer that the CV does not say (a company's sector, an overlap, a
  promotion) enters as `status: unconfirmed`, in its own sentence, so it can be confirmed
  or dropped.
- Keep every number exactly as written. Do not round, do not add one.
- Self-ratings ("8/10", "excellent knowledge") and adjectives about the candidate are not
  facts: leave them out, and list them at the end.
- Write the files under {facts}. Then write {open_file}: a list of what the CV leaves
  open, one question per line, each starting with the fact file it is about: jobs with no
  result, numbers with no source, unexplained gaps, unclear company descriptions,
  confidential items never declared. The interview starts from that file.

The old CV ({name}):

{text}
"""

INTERVIEW = """\
You are interviewing a candidate to build and strengthen their fact base: the verified
material every CV of theirs will be written from. Ask one question at a time, in
{language}, wait for the answer, and write or update the fact files as you go.

{schema}
Where to start, in this order:
{start}

For each job, ask until you have:
1. Company, what it does and for whom (one line a stranger understands).
2. Role, and whether in-house or freelance.
3. Period, month and year, start and end.
4. What the candidate did, in their words.
5. What changed because of it — and a number if there is one. Then: where does that
   number come from? A file, a dashboard, an export? That decides `measured` or `stated`.
6. Whom they presented results to, who decided on them.
7. What is true but must never be printed (salary, fees, NDA names): `confidential`.

Rules:
- Never invent or round a number. If the candidate is unsure, write it as `unconfirmed`.
- Keep the candidate's words for what they did; do not upgrade a verb ("helped" stays
  "helped").
- After each job, show the fact file you wrote and ask if it is right.
- Stop when the list above is done, and say what is still `unconfirmed`.

The fact base today:
{facts}
"""


def text_of(path: Path) -> str:
    """The text of an old CV: PDF, Word or plain text. No dependency for Word."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(p.extract_text() for p in PdfReader(str(path)).pages)
    if suffix == ".docx":
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return path.read_text(encoding="utf-8")


def language() -> str:
    return str(config.config().get("facts_language", "English"))


def schema() -> str:
    return SCHEMA.format(language=language())


def from_cv(path: Path) -> int:
    if not path.exists():
        print(f"[not prepared] {path} does not exist")
        return 1
    out = ROOT / "intake.cv.prompt.md"
    out.write_text(FROM_CV.format(schema=schema(), facts=ROOT / "facts", name=path.name,
                                  open_file=ROOT / OPEN, text=text_of(path)), encoding="utf-8")
    print(f"[ok] {out.relative_to(ROOT)}: give it to a model that can write files,")
    print("     then run `py -m jobsearch.check` and `py -m jobsearch.intake interview`")
    return 0


def interview() -> int:
    facts = load()
    weak, holes, latest = report()
    start = []
    if not facts:
        start.append("- The fact base is empty: start from the most recent job, then go back.")
    else:
        ongoing = latest and latest.year == date.today().year and latest.month == date.today().month
        if ongoing:
            start.append("- What is new and not yet in the fact base? An old CV is always behind:"
                         " new jobs, clients, projects, courses, results in the current job.")
        elif latest:
            start.append(f"- What happened after {latest:%m/%Y}, the latest date the fact base"
                         " covers? New jobs, clients, projects, courses.")
        if (ROOT / OPEN).exists():
            questions = (ROOT / OPEN).read_text(encoding="utf-8").strip().splitlines()
            # Only the questions: a note the model added ("none found") is not a starting point.
            start += [f"- {q.lstrip('-* ').strip()}" for q in questions if "?" in q]
        start += [f"- The time {h}" for h in holes]
        for slug, found in weak.items():
            start.append(f"- `{slug}`: " + "; ".join(found))
    listing = "\n".join(
        f"- {slug}: {f.meta.get('role') or f.meta.get('name') or f.meta.get('type', '')}"
        f" {f.meta.get('period', '')} [{f.status}]"
        for slug, f in facts.items()
    ) or "(empty)"
    out = ROOT / "intake.interview.prompt.md"
    out.write_text(INTERVIEW.format(language=language(), schema=schema(),
                                    start="\n".join(start), facts=listing), encoding="utf-8")
    print(f"[ok] {out.relative_to(ROOT)}: {len(start)} starting points."
          " Use it in a chat with a model that can write files.")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["cv"] and len(argv) > 1:
        return from_cv(Path(argv[1]).resolve())
    if argv[:1] == ["interview"]:
        return interview()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
