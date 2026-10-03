"""Is it worth applying? Step 0, before the profile and the plan.

A model extracts the posting's requirements once; Python gives the verdict, always the
same, against the fact base. No automatic "skip": an uncovered requirement is a reason to
read, not a sentence. Pluses do not count against.

    py -m jobsearch.evaluate prepare postings/example.md   # prompt to extract the requirements
    py -m jobsearch.evaluate postings/example.md           # verdict, and a line in the log

The model writes `postings/<name>.requirements.json`. The verdict goes into
`applications.yaml`, where you note by hand how it went: after a few outcomes, that is the
data that tells whether the thresholds predict anything.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from jobsearch import config
from jobsearch.ats import LEXICON, _found
from jobsearch.facts import ROOT, load

THRESHOLDS = {"apply": 0.75, "maybe": 0.5}
CENTRAL_WEIGHT = 2

INSTRUCTIONS = """\
Extract the requirements of the job posting below into one JSON file, {output}, with this
shape and nothing else:

{{"requirements": [
  {{"text": "<the requirement, short, in the posting's words>",
    "kind": "required" | "plus",
    "central": true | false,
    "terms": ["<searchable words: tools, skills, platforms, as the posting writes them>"],
    "years": <integer if the posting asks for N+ years, else null>,
    "area": "<what the years are of, e.g. SEO, else null>",
    "language": "<a language the posting asks for, else null>",
    "equivalents": [["<one list per term, same order: the forms a {facts_language} text uses>"]]}}
]}}

Rules:
- Take the requirements: the section that says what the candidate must have (requirements,
  qualifications, what you bring, nice to have). The duties of the role are not
  requirements: skip them unless the posting has no requirements section.
- One item per requirement line. Do not split a line into one item per tool: a line that
  lists tools is one item with several terms.
- `kind` is "plus" for nice-to-have, preferred, ideally, a plus, bonus; else "required".
- `central` is true for what the role is about: what its title names and what the first
  responsibilities ask. A specific tool, a side duty or a soft skill is not central.
- `terms` are concrete names a CV would literally contain: tools, platforms,
  techniques with a name ("canonical tags", "Ahrefs", "GA4"). Never qualities or
  outcomes ("data-driven", "measurable results", "strong understanding", "strategy"):
  no fact proves those by a word. A requirement with no concrete name has empty
  `terms`, and the reader judges it.
- The candidate's fact base is written in {facts_language}. `equivalents` has one list per
  term, in the same order: every form a {facts_language} professional text may use for it,
  the translation and the English term used as a loanword, singular and plural
  ("crawlability" -> ["scansionabilità", "crawling", "scansione"]). An empty list when the
  term is the same. For a language requirement, one list: the language's name in
  {facts_language}.
- Copy and translate, do not judge: you do not know the candidate.

The posting:

{posting}
"""


def prepare(posting: Path) -> int:
    output = posting.with_suffix(".requirements.json")
    prompt = posting.with_suffix(".requirements.prompt.md")
    text = INSTRUCTIONS.format(
        output=output,
        posting=posting.read_text(encoding="utf-8"),
        facts_language=config.config().get("facts_language", "English"),
    )
    prompt.write_text(text, encoding="utf-8")
    print(f"[ok] {prompt.relative_to(ROOT)}: give it to a model, it writes {output.name}")
    return 0


def proven(term: str, facts: str) -> bool:
    """A term is proven if the fact base says it, in its own form or a known synonym."""
    forms = [term]
    for key, variants in LEXICON.items():
        if term.lower() in (v.lower() for v in [key, *variants]):
            forms = [key, *variants]
    return bool(_found(facts, forms))


def years_in(area: str | None) -> float | None:
    """The years in an area, from the start dates declared in `cv.yaml` (`career:`)."""
    career = {str(k).lower(): v for k, v in config.config().get("career", {}).items()}
    start = career.get(str(area or "").lower())
    if not start:
        return None
    year, month = (int(x) for x in str(start).split("-")[:2])
    today = date.today()
    return (today.year - year) + (today.month - month) / 12


def judge(req: dict, facts: str, languages: str) -> tuple[float | None, str]:
    """How far the fact base proves a requirement (0-1, None if no word can prove it)."""
    # One list of forms per term; a single string counts as a list of one form.
    equivalents = [[e] if isinstance(e, str) else list(e) for e in req.get("equivalents") or []]
    if req.get("language"):
        names = [req["language"], *(f for forms in equivalents for f in forms)]
        ok = any(x.lower() in languages for x in names if x)
        return (1.0 if ok else 0.0), f"language {'' if ok else 'not '}in the facts"
    if req.get("years"):
        years = years_in(req.get("area"))
        if years is None:
            return None, f"years of {req.get('area')}: start date not in cv.yaml"
        ok = years >= req["years"]
        return (1.0 if ok else 0.0), f"{years:.1f} years against {req['years']}"
    terms = req.get("terms") or []
    if not terms:
        return None, "no word proves it: the reader judges it"
    # A term is proven in the posting's form or in the form of the fact base's language.
    paired = equivalents + [[]] * len(terms)
    taken = [t for t, forms in zip(terms, paired)
             if proven(t, facts) or any(f and proven(f, facts) for f in forms)]
    missing = [t for t in terms if t not in taken]
    note = "all in the facts" if not missing else f"missing: {', '.join(missing)}"
    return len(taken) / len(terms), note


def verdict(score: float | None) -> str:
    thresholds = {**THRESHOLDS, **config.config().get("evaluate", {})}
    if score is None:
        return "maybe"
    if score >= thresholds["apply"]:
        return "apply"
    return "maybe" if score >= thresholds["maybe"] else "weak"


def log(posting: Path, result: str, score: float | None) -> None:
    registry = ROOT / "applications.yaml"
    entries = yaml.safe_load(registry.read_text(encoding="utf-8")) if registry.exists() else []
    entries = entries or []
    name = posting.relative_to(ROOT).as_posix()
    entry = next((e for e in entries if e.get("posting") == name), None)
    if entry is None:
        entry = {"posting": name, "status": "evaluated"}
        entries.append(entry)
    entry.update(evaluated_on=date.today().isoformat(), verdict=result,
                 score=None if score is None else round(score, 2))
    registry.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")


def evaluate(posting: Path) -> int:
    requirements = posting.with_suffix(".requirements.json")
    if not requirements.exists():
        print(f"[not evaluated] {requirements.name} is missing: "
              f"py -m jobsearch.evaluate prepare {posting}")
        return 1
    reqs = json.loads(requirements.read_text(encoding="utf-8"))["requirements"]
    facts = load()
    base = " ".join(f"{f.body} {f.meta}" for f in facts.values() if f.citable)
    languages = " ".join(f.body for s, f in facts.items() if "languages" in s).lower()
    languages += " " + " ".join(
        re.findall(r"\w+", str(config.config().get("languages", "")))
    ).lower()

    weights = []
    for kind in ("required", "plus"):
        group = [r for r in reqs if r.get("kind", "required") == kind]
        if not group:
            continue
        print(f"\n{kind.upper()}")
        for r in group:
            how_much, note = judge(r, base, languages)
            sign = {None: "?", 1.0: "+", 0.0: "-"}.get(how_much, "~")
            star = "*" if r.get("central") else " "
            print(f"  [{sign}]{star}{r['text'][:70]:<70}  {note}")
            if kind == "required" and how_much is not None:
                weights.append((how_much, CENTRAL_WEIGHT if r.get("central") else 1))
    # A central requirement counts double: the heart of the role weighs more than a tool.
    total = sum(weight for _, weight in weights)
    score = sum(q * weight for q, weight in weights) / total if weights else None
    result = verdict(score)
    share = "n/a" if score is None else f"{score:.0%}"
    print(f"\nrequired proven by the facts, central (*) double: {share} of {len(weights)} "
          f"checkable -> {result}")
    log(posting, result, score)
    print("logged in applications.yaml: note there how it goes (sent, interview, rejected)")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "prepare" and len(argv) > 1:
        return prepare(Path(argv[1]).resolve())
    return evaluate(Path(argv[0]).resolve())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
