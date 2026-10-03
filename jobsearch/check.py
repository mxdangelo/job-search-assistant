"""What makes each fact weak: the questions to ask before a CV relies on it.

    py -m jobsearch.check

Deterministic. It reads the fact base and lists, fact by fact, what is missing: a status,
a source, a period, a description; numbers nobody can trace; time between jobs that no
fact covers. The interview (`jobsearch.intake interview`) starts from this list.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date

from jobsearch.facts import STATUSES, load

PERIOD = re.compile(r"(\d{2})/(\d{4})")
# A period may also be ISO (2026-07-21) or a bare year: readable, just less precise.
ISO = re.compile(r"(\d{4})-(\d{2})")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# A metric, not a year or a level: years and "C1" are not numbers anyone must source.
METRIC = re.compile(r"\b\d[\d.,]*%?")
ONGOING = re.compile(r"in corso|oggi|present|ongoing|current", re.I)
MONTHS = (r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|"
          r"novembre|dicembre|january|february|march|april|may|june|july|august|september|"
          r"october|november|december")
DATE = re.compile(rf"\d{{4}}-\d{{2}}(?:-\d{{2}})?|\d{{1,2}}/\d{{4}}|\d{{1,2}}\s+(?:{MONTHS})"
                  rf"(?:\s+\d{{4}})?|(?:{MONTHS})\s+\d{{1,2}}(?:,?\s+\d{{4}})?", re.I)
OLD_CV = re.compile(r"\b(?:old|previous|vecchio|precedente)?\s*CV\b", re.I)
THIN = 120         # characters: below this a fact says what, not what changed
GAP_MONTHS = 4      # time between two jobs worth asking about


@dataclass
class Span:
    slug: str
    start: date
    end: date
    ongoing: bool


def span(slug: str, period: str) -> Span | None:
    found = PERIOD.findall(period) or [(m, y) for y, m in ISO.findall(period)]
    if not found:
        return None
    start = date(int(found[0][1]), int(found[0][0]), 1)
    ongoing = bool(ONGOING.search(period))
    end = date.today() if ongoing or len(found) < 2 else date(int(found[-1][1]), int(found[-1][0]), 1)
    return Span(slug, start, end, ongoing)


def weaknesses(meta: dict, body: str, kind: str) -> list[str]:
    found = []
    status = str(meta.get("status", ""))
    if not any(s in status for s in STATUSES):
        found.append("no status: measured, stated or unconfirmed?")
    elif "unconfirmed" in status:
        found.append("unconfirmed: confirm it, or it never reaches a CV")
    if not meta.get("evidence"):
        found.append("no evidence: where does this come from?")
    if kind in ("experience", "project") and not meta.get("period"):
        found.append("no period")
    elif meta.get("period") and not YEAR.search(str(meta["period"])):
        found.append(f"period «{meta['period']}» has no date")
    if kind == "experience":
        for key in ("company", "role"):
            if not meta.get(key):
                found.append(f"no {key}")
    if kind in ("experience", "project") and len(body) < THIN:
        found.append("thin: what changed because of this work? a number, and its source?")
    # Dates are not metrics: they go before the numbers are counted.
    metrics = [m for m in METRIC.findall(DATE.sub(" ", body))
               if not YEAR.fullmatch(m) and (len(m.strip(".,")) > 1 or m.endswith("%"))]
    # An old CV is a claim, not a source: its numbers still need one. Only when every
    # source listed in `evidence` is a CV; a screenshot or a repo next to it is a source.
    evidence = str(meta.get("evidence", ""))
    sources = [s for s in evidence.split(";") if s.strip()]
    from_cv = bool(sources) and all(OLD_CV.search(s) for s in sources)
    if kind in ("experience", "project") and metrics and (not evidence or from_cv):
        where = "only the old CV says so" if from_cv else "no source"
        found.append(f"numbers, {where} ({', '.join(metrics[:3])}): how were they counted?")
    return found


def gaps(spans: list[Span]) -> list[str]:
    """Months between the end of one job and the start of the next that no job covers."""
    found, covered = [], None
    for s in sorted(spans, key=lambda s: s.start):
        if covered and (s.start.year - covered.year) * 12 + s.start.month - covered.month > GAP_MONTHS:
            found.append(f"{covered:%m/%Y} – {s.start:%m/%Y}: no fact covers this time")
        covered = max(covered or s.end, s.end)
    return found


def report() -> tuple[dict[str, list[str]], list[str], date | None]:
    """Weak points per fact, gaps between jobs, and the latest date the base covers."""
    facts = load()
    weak, spans = {}, []
    for slug, fact in facts.items():
        kind = str(fact.meta.get("type", slug.split("/")[0])).rstrip("s")
        if found := weaknesses(fact.meta, fact.body, kind):
            weak[slug] = found
        if kind == "experience" and (s := span(slug, str(fact.meta.get("period", "")))):
            spans.append(s)
    latest = max((s.end for s in spans), default=None)
    if spans and any(s.ongoing for s in spans):
        latest = date.today()
    return weak, gaps(spans), latest


def main(argv: list[str]) -> int:
    if not load():
        print("the fact base is empty: `py -m jobsearch.intake cv <file>` or `intake interview`")
        return 0
    weak, holes, latest = report()
    if not weak and not holes:
        print("[ok] no weak facts, no gaps")
    for slug, found in weak.items():
        print(f"\n{slug}")
        for item in found:
            print(f"  - {item}")
    if holes:
        print("\ntime between jobs")
        for item in holes:
            print(f"  - {item}")
    if latest and (latest.year, latest.month) == (date.today().year, date.today().month):
        print("\na job is ongoing: anything new not yet in the fact base?")
    elif latest:
        print(f"\nthe fact base reaches {latest:%m/%Y}: anything since then?")
    print(f"\n{len(weak)} facts to strengthen, {len(holes)} gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
