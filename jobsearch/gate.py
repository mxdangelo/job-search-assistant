"""The deterministic check on the finished CV. Arithmetic outside the model, afterwards.

Three outcomes, never two: `ok`, `blocked`, `unverified`. The third is not the second.

The questions, in this order:

1. **Provenance** — every number in the CV is in the fact base, every fact cited exists and
   is citable.
2. **Confidentiality** — nothing the fact base declares `confidential:`, and none of the
   forms a CV cannot carry anyway (see `preferences.md`, "What never goes in").
3. **Chronology** — no uncovered year between the first and the last role listed, the
   experience in reverse order, and no "eight years of" the dates do not support.
4. **Readability** — the text re-extracted from the PDF, as an ATS would: contacts,
   canonical headings, every role with its company and its period, in the right order.
5. **Page limit** — the PDF's pages.
6. **Freshness** — a plan written before the last change to the facts it cites.

    py -m jobsearch.gate plans/example.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from jobsearch import ats, config
from jobsearch.facts import ROOT, fact_base_numbers, load, numbers

PLACEHOLDER = re.compile(r"\[(?:nome|xxx|todo|tbd)[^\]]*\]|\bTODO\b|\bXXX\b", re.I)
# Years and page numbers have no source in the fact base: they are not claims.
EXEMPT = {str(a) for a in range(1990, 2036)} | {"", "1", "2", "3", "4", "5"}

# Forms no fact base declares and no CV can carry. The reasons are in `preferences.md`.
# The patterns are Italian on purpose: they check Italian CVs.
FORBIDDEN = [
    (re.compile(r"\b(?:compens\w+|tariff\w+|onorari\w+|retribuzion\w+|RAL)\b", re.I),
     "own money: the cost of a machine is written, one's own price is not"),
    (re.compile(r"\b(?:confermat\w+ dal cliente|rinnov\w+|in attesa|in trattativa|"
                r"da confermare|lotto confermato)\b", re.I),
     "state of the commercial relationship, not a result"),
    (re.compile(r"\b(?:esercitazion\w+|homework|compito|per hobby|tempo libero|"
                r"progetto personale)\b", re.I),
     "belittles one's own work"),
    (re.compile(r"\b\d\s*/\s*10\b"),
     "numeric self-rating: it is not a measure"),
    (re.compile(r"\b(?:appassionat\w+|proattiv\w+|dinamic\w+|volenteros\w+|team player|"
                r"problem solver|orientat\w+ al risultato)\b", re.I),
     "CV adjective: takes a line and says nothing"),
]


def jargon() -> list[tuple[re.Pattern, str]]:
    """The fact base's internal jargon, declared in `cv.yaml`: the reader does not know it."""
    words = config.jargon()
    if not words:
        return []
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in words) + r")\b", re.I)
    return [(pattern, "internal jargon: the reader does not know it")]

# "otto anni", "five years": figures in words escape the number check.
NUMBER_WORDS = {
    "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7,
    "otto": 8, "nove": 9, "dieci": 10, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
CLAIMED_YEARS = re.compile(
    r"\b(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")\+?\s+(?:anni|years)\b(?=(.{0,30}))", re.I
)
MONTH_YEAR = re.compile(r"(\d{2})/(\d{4})")

YEAR = re.compile(r"(?:19|20)\d{2}")
# Below this share of the first page's lines, the last page reads as a leftover.
MIN_FILL = 0.5
ONGOING = re.compile(r"in corso|oggi|presente|attual|ongoing|present", re.I)


def plan_text(plan: dict) -> str:
    pieces = [plan.get("summary", ""), plan.get("title", "")]
    for entry in plan.get("experience", []) + plan.get("projects", []):
        pieces += [entry.get("role", ""), entry.get("org", ""), entry.get("name", "")]
        pieces += entry.get("lines", [])
    for group in plan.get("skills", []):
        pieces += group.get("items", [])
    for degree in plan.get("education", []):
        pieces += [degree.get("title", ""), degree.get("institution", "")]
    pieces += plan.get("languages", [])
    return " ".join(pieces)


def years(period: str) -> set[int]:
    """The years a period line covers. "ongoing" runs to today."""
    found = [int(a) for a in YEAR.findall(period)]
    if not found:
        return set()
    end = date.today().year if ONGOING.search(period) else max(found)
    return set(range(min(found), max(end, max(found)) + 1))


def confidentiality(text: str, facts: dict) -> list[str]:
    """True things a CV does not print: those declared in the fact base, and the others."""
    low = text.lower()
    findings = [
        f"confidential in {slug}: «{term}»"
        for slug, fact in facts.items()
        for term in fact.confidential
        if term.lower() in low
    ]
    for rule, reason in FORBIDDEN + jargon():
        for found in dict.fromkeys(m.group(0) for m in rule.finditer(text)):
            findings.append(f"«{found}» — {reason}")
    return findings


def chronology(plan: dict, facts: dict) -> tuple[list[str], list[str]]:
    """A removed experience leaves a gap. The gap is closed by compressing it, not ignoring it."""
    covered: set[int] = set()
    for entry in plan.get("experience", []):
        covered |= years(str(entry.get("period", "")))
    if not covered:
        return [], ["chronology: could not look, no readable period in the plan"]

    blocks, open_ = [], []
    for year in sorted(set(range(min(covered), max(covered) + 1)) - covered):
        who = [
            slug for slug, fact in facts.items()
            if fact.meta.get("type") == "experience"
            and year in years(str(fact.meta.get("period", "")))
        ]
        if who:
            blocks.append(f"chronology gap in {year}: in the fact base {', '.join(who)} covers it")
        else:
            open_.append(f"chronology gap in {year}: nothing in the fact base covers it")
    return blocks, open_


def bounds(period: str) -> tuple[date, date] | None:
    """Start and end of a period "MM/YYYY — MM/YYYY | today", on the first of the month."""
    found = [date(int(a), int(m), 1) for m, a in MONTH_YEAR.findall(period)]
    if not found:
        return None
    today = date.today().replace(day=1)
    end = today if ONGOING.search(period) else max(found)
    return min(found), end


def order(plan: dict) -> list[str]:
    """Reverse chronology by start; with equal starts, the one that ended later first."""
    keys = [(v["fact"], bounds(str(v.get("period", "")))) for v in plan.get("experience", [])]
    keys = [(slug, b) for slug, b in keys if b]
    expected = sorted(keys, key=lambda k: (k[1][0], k[1][1]), reverse=True)
    if [s for s, _ in keys] == [s for s, _ in expected]:
        return []
    return [f"experience order: expected {', '.join(s.split('/')[-1] for s, _ in expected)}"]


def months(plan: dict, seo_only: bool) -> int:
    """The span in months from the first start to the last end, as whoever counts dates reads it.

    The span and not the sum: a role titled "marketing" between two SEO roles does not
    break the career in the reader's eyes.
    """
    periods = []
    for entry in plan.get("experience", []):
        # The title, not the notes after "·": "Journalist · SEO editing" is not an SEO role.
        title = str(entry.get("role", "")).split("·")[0]
        if seo_only and "seo" not in title.lower():
            continue
        if b := bounds(str(entry.get("period", ""))):
            periods.append(b)
    if not periods:
        return 0
    start, end = min(p[0] for p in periods), max(p[1] for p in periods)
    return (end.year - start.year) * 12 + end.month - start.month + 1


def claimed_years(plan: dict, text: str) -> list[str]:
    """"Eight years of SEO" against the dates: the reader counts, and the count must add up."""
    findings = []
    for figure, after in CLAIMED_YEARS.findall(text):
        said = int(figure) if figure.isdigit() else NUMBER_WORDS[figure.lower()]
        # "eight years of SEO" is measured on SEO roles; "eight years between journalism
        # and SEO" is not.
        seo = re.match(r"\s*(?:di|of|in)\s+SEO\b", after, re.I) is not None
        covered = months(plan, seo_only=seo)
        if said * 12 > covered + 6:
            scope = "of SEO" if seo else "in all"
            findings.append(f"«{figure} anni/years» but the experience covers "
                            f"{covered / 12:.1f} {scope}")
    return findings


def freshness(path: Path, plan: dict) -> list[str]:
    """A plan older than the facts it cites is written on a fact base that is gone."""
    written = path.stat().st_mtime
    used = [v["fact"] for v in plan.get("experience", []) + plan.get("projects", [])]
    changed = [
        slug for slug in used
        if (fact := ROOT / "facts" / f"{slug}.md").exists() and fact.stat().st_mtime > written
    ]
    if not changed:
        return []
    return [f"the fact base changed after the plan: {', '.join(changed)} — reread them"]


# How an ATS reads: canonical headings, plain contacts, reading order.
HEADINGS = {
    "it": ("Esperienza professionale", "Competenze", "Formazione"),
    "en": ("Professional experience", "Skills", "Education"),
}
CONTACTS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "phone": re.compile(r"\+?\d[\d\s.]{7,}\d"),
}
MARKS = (("—", "-"), ("–", "-"), ("−", "-"), ("→", "-"),
         ("’", "'"), ("·", " "), (" ", " "))


def flatten(text: str) -> str:
    """The text as it reaches a parser: dashes unified, spaces collapsed, lower case."""
    for mark, replacement in MARKS:
        text = text.replace(mark, replacement)
    return " ".join(text.split()).casefold()


def readability(plan: dict) -> tuple[list[str], list[str]]:
    """The CV reread from the PDF, not from the plan. If a piece does not extract, an ATS
    does not see it."""
    pdf = ROOT / "cv" / f"{plan['profile']}.pdf"
    if not pdf.exists():
        return [], [f"readability: could not look, {pdf.name} does not exist"]
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], ["readability: could not look, pypdf not installed"]

    pages = [page.extract_text() for page in PdfReader(str(pdf)).pages]
    flat = flatten(" ".join(pages))
    blocks = []
    for name, rule in CONTACTS.items():
        if not rule.search(flat):
            blocks.append(f"{name} not extractable from the PDF")
    for expected in HEADINGS[plan.get("language", "it")]:
        if flatten(expected) not in flat:
            blocks.append(f"heading «{expected}» not extracted: the section is not recognised")

    # The cursor moves on: every entry must be found after the previous one, or the order
    # does not hold.
    cursor = 0
    for entry in plan.get("experience", []):
        for field in ("role", "org", "period"):
            value = flatten(str(entry.get(field, "")))
            if not value:
                continue
            if value not in flat:
                blocks.append(f"{entry['fact']}: «{entry[field]}» does not extract from the PDF")
            elif field == "role":
                found = flat.find(value, cursor)
                if found < 0:
                    blocks.append(f"{entry['fact']}: out of sequence, an ATS reads it in the "
                                  "wrong place")
                else:
                    cursor = found
    return blocks, []


# The voice rules that can be checked without judgement (preferences.md, "The voice").
# Antitheses no: a crude check flags legitimate lines too, they are left to the reviewer.
FIRST_PERSON = {
    "en": re.compile(r"\b(I|I'm|I've|I'd|my|me|mine|myself)\b"),
    "it": re.compile(r"\b(io|mio|mia|miei|mie|ho)\b", re.I),
}
SENTENCE = re.compile(r"(?<=[.;!?])\s+")


def written_lines(plan: dict) -> list[str]:
    """The sentences the plan writes in full: summary and lines, not the names."""
    lines = [plan.get("summary", "")]
    for entry in plan.get("experience", []) + plan.get("projects", []):
        lines += entry.get("lines", [])
    return [r for r in lines if r]


def voice(plan: dict) -> list[str]:
    blocks = []
    language = plan.get("language", "it")
    lines = written_lines(plan)
    if person := FIRST_PERSON.get(language):
        found = sorted({m for r in lines for m in person.findall(r)})
        if found:
            blocks.append(f"first person: {found}")
    if language == "en" and "«" in plan_text(plan):
        blocks.append("« » quotation marks in an English CV: write “ ”")
    for line in lines:
        for sentence in SENTENCE.split(line):
            if sentence.count(":") > 1:
                blocks.append(f"chained colons: «{sentence[:70]}…»")
    seen: dict[str, str] = {}
    for group in plan.get("skills", []):
        for v in group.get("items", []):
            key = v.lower()
            if key in seen:
                blocks.append(f"repeated skill: «{v}» in {seen[key]} and {group['group']}")
            seen[key] = group["group"]
            if key.startswith(group["group"].lower() + " "):
                blocks.append(f"skill that repeats its group: «{group['group']} {v}»")
    return blocks


def check(plan: dict, path: Path | None = None) -> tuple[list[str], list[str]]:
    blocks, open_ = [], []
    facts = load()
    text = plan_text(plan)

    invented = numbers(text) - fact_base_numbers(facts) - EXEMPT
    if invented:
        blocks.append(f"numbers not in the fact base: {sorted(invented)}")

    used = [v["fact"] for v in plan.get("experience", []) + plan.get("projects", [])]
    for slug in used:
        if slug not in facts:
            blocks.append(f"fact does not exist: {slug}")
        elif facts[slug].excluded:
            blocks.append(f"fact excluded from CVs (cv: no in the fact base): {slug}")
        elif not facts[slug].citable:
            blocks.append(f"fact still unconfirmed, not citable: {slug}")

    if found := PLACEHOLDER.findall(text):
        blocks.append(f"placeholders left: {found}")

    blocks += confidentiality(text, facts)
    blocks += voice(plan)

    gaps, unsure = chronology(plan, facts)
    blocks += gaps
    open_ += unsure
    blocks += order(plan)
    blocks += claimed_years(plan, text)
    if path is not None:
        blocks += freshness(path, plan)

    if not plan.get("coverage"):
        open_.append("`coverage` is empty: the plan does not say which line proves which "
                     "requirement")

    unreadable, unsure = readability(plan)
    blocks += unreadable
    open_ += unsure

    if not plan.get("excluded"):
        open_.append("`excluded` is empty: the plan does not declare what it left out")

    # The ATS: the text as a parser extracts it, and the posting's words searched there.
    if (extracted := ats.pdf_text(plan)) is not None:
        blocks += ats.extraction_faults(extracted)
    result, reason = ats.check(plan)
    if result is None:
        open_.append(f"ATS: could not look, {reason}")
    else:
        blocks += [f"ATS: the posting asks for it, the fact base proves it, the CV does not "
                   f"say it: {m}" for m in result.missing]
        open_ += [f"ATS: {s}" for s in result.synonyms]

    # The words the candidate always wants in a certain kind of CV (`cv.yaml`).
    for rule in config.expected_words():
        if_title, word = str(rule["if_title"]).lower(), str(rule["word"])
        if if_title in plan.get("title", "").lower() and word.lower() not in text.lower():
            open_.append(f"{word} does not appear: {rule.get('reason', '')}")

    pdf = ROOT / "cv" / f"{plan['profile']}.pdf"
    limit = plan.get("max_pages", 1)
    if not pdf.exists():
        open_.append(f"pages: could not look, {pdf.name} does not exist")
    else:
        try:
            from pypdf import PdfReader
            pages = PdfReader(str(pdf)).pages
            lines = [p.extract_text().splitlines() for p in pages]
            problem = []
            if len(pages) > limit:
                leftover = sum(len(r) for r in lines[limit:])
                problem = [f"{len(pages)} pages against a limit of {limit}: "
                           f"about {leftover} lines left over"]
            elif len(pages) > 1:
                problem = half_page(lines)
            blocks += problem
            # With a page problem, the cheapest cuts: the lines that wrap for one or two
            # words. Shorten the line, do not narrow the margins.
            if problem:
                open_ += [f"cut: {v}" for v in widows(lines)]
        except ImportError:
            open_.append("pages: could not look, pypdf not installed")
    return blocks, open_


def half_page(lines: list[list[str]]) -> list[str]:
    """The last page full or nothing: half a page looks worse than one full page."""
    full, last = len(lines[0]), len(lines[-1])
    fill = last / max(full, 1)
    if fill >= MIN_FILL:
        return []
    short = int(full * MIN_FILL) - last + 1
    return [f"the last page is {fill:.0%} full: {short} lines short of filling it, or "
            f"{last} to remove to go back to {len(lines) - 1}"]


def widows(lines: list[list[str]]) -> list[str]:
    """The PDF lines that hold only the tail of a sentence: one or two words."""
    found = []
    for page in lines:
        for before, line in zip(page, page[1:]):
            if len(line.split()) <= 2 and len(before) > 60 and line.rstrip().endswith((".", ")")):
                found.append(f"«…{before[-35:]} / {line.strip()}»")
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    path = Path(argv[0])
    plan = json.loads(path.read_text(encoding="utf-8"))
    blocks, open_ = check(plan, path)
    for line in blocks:
        print(f"[blocked]       {line}")
    for line in open_:
        print(f"[unverified]    {line}")
    if not blocks and not open_:
        print("[ok] no findings")
    return 1 if blocks else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
