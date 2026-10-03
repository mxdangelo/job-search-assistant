"""Prepares the selection step: builds the reading list and prints it with sizes.

The cost of a step is decided here, not in the prompt. Usage:

    py -m jobsearch.plan profiles/example.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from jobsearch.facts import FACTS, ROOT, load, stale

POSTING = re.compile(r"^posting:\s*(\S+)", re.M)

INSTRUCTIONS = """\
Write the plan of a CV. Do not write the CV.

Read the fact base (`facts/`), the preferences and the target profile, and produce a single
JSON file with this shape:

{
  "profile": "<profile slug>",
  "language": "it" | "en",
  "max_pages": <integer>,
  "title": "<the role under the name>",
  "summary": "<two lines: who, what they can do, for this posting>",
  "experience": [
    {"fact": "<slug>", "role": "...", "org": "...", "location": "...",
     "period": "...", "lines": ["...", "..."]}
  ],
  "projects": [{"fact": "<slug>", "name": "...", "url": "...", "lines": ["..."]}],
  "skills": [{"group": "...", "items": ["...", "..."]}],
  "education": [{"title": "...", "institution": "...", "period": "..."}],
  "coverage": [{"requirement": "<from the posting>", "evidence": "<slug, or 'uncovered: why'>"}],
  "excluded": [{"fact": "<slug>", "reason": "<one line>"}]
}

Before choosing, the coverage:

- List the posting's requirements, from the posting's text and not from the profile that
  summarises it, and for each one the fact that proves it. What the fact base does not
  prove stays `uncovered`, stated: it is not covered with a paraphrase.
- The posting's central question (what the profile calls "who they want") gets the
  strongest evidence, with two full lines. Never squeezed into a role line.
- The tools the posting names and the fact base confirms go into skills, with the name the
  posting uses: it is the word the ATS searches for.

The provenance rules:

- Every line comes from a fact in the fact base. No number that is not already there.
- A fact with `status: unconfirmed` does not enter, nor does one with `cv: no`.
- Nothing a fact declares `confidential:`, in any form and in any paraphrase. These are
  true things: that is why they are in the fact base and not in the CV.

The writing rules (in full in `preferences.md`):

- The result leads the line, the method follows. Two lines for recent roles, one for old
  ones.
- Never the commercial relationship: fees, rates, renewals, confirmed batches, quotes
  pending. Never belittle one's own work. Never self-ratings or adjectives about oneself.
- A volume (words, articles, commits) enters only with the reason beside it.
- Every role carries its nature: (in-house) or (freelance).
- The voice is the reader's, not the fact base's. The fact base is written for whoever
  keeps it: its maxims and its internal names do not pass into the CV. At most one sentence
  of opinion per CV; the rest are facts.
- Years are counted on the dates the CV shows: a trade begun in 2021 does not become
  "eight years" by adding the one before.
- At most one antithesis ("X, not Y") per CV; at most one colon per line.
  No first person. In English the quotation marks are “ ”.
- The posting's words (tools, skills) are reused; its sentences are not.
- A number states an outcome or a scale, never a count of activity (findings, documents,
  files, lines of code). Null results and rejections do not open an entry.
- Every sequence ("then", "since") must match the dates; a year in progress is not closed;
  a translated title does not go up a grade; every little-known organisation carries a
  description, the same in every CV.
- No asides between subject and verb. A number without a starting point goes at the end
  of the line. A tool is named for its purpose. Products keep their capitalisation.
- Skills in groups that prove something: a tool the posting names stays, in the group
  where it is a working tool (an AI assistant with the LLM pipelines, not with the SEO
  tools); an item the posting does not ask for and the experience does not use goes.

The form rules:

- Reverse chronology by start date; with equal starts, the one that ended later first.
- No gaps: if the page limit cannot hold an experience, compress it by leaving `lines`
  empty — a line with role, company and period remains. An uncovered year between the
  first and the last role blocks the gate.
- The page limit is binding: `excluded` cannot be empty if you left something out, and it
  must say why. What goes in is a choice, so is what stays out.
- The plan is one file. Write nothing else.
"""


def build(profile: Path) -> Path:
    pieces, index_lines = [], []

    def add(name: str, text: str) -> None:
        pieces.append(f"\n\n===== {name} =====\n{text}")
        index_lines.append(f"  {len(text.encode()) / 1024:5.1f} KB  {name}")

    profile_text = profile.read_text(encoding="utf-8")
    add(f"profile: {profile.name}", profile_text)
    # The profile summarises the posting, and the summary loses the tool names:
    # coverage is done on the original text.
    if found := POSTING.search(profile_text):
        posting = ROOT / found.group(1).strip()
        add(f"posting: {posting.name}", posting.read_text(encoding="utf-8"))
    add("preferences.md", (ROOT / "preferences.md").read_text(encoding="utf-8"))
    for slug in load():
        add(f"facts/{slug}.md", (FACTS / f"{slug}.md").read_text(encoding="utf-8"))

    text = INSTRUCTIONS + "".join(pieces)
    out = ROOT / "plans" / f"{profile.stem}.prompt.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")

    print("reading list:")
    print("\n".join(index_lines))
    print(f"  {'-' * 40}")
    print(f"  {len(text.encode()) / 1024:5.1f} KB  total -> {out.relative_to(ROOT)}")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    # A fact base behind its repos writes last month's CVs: update the facts first.
    old, blind = stale()
    for line in blind:
        print(f"[unverified] {line}")
    if old:
        for line in old:
            print(f"[stale]      {line}")
        print("the fact base is behind its repos: update those facts, then run again")
        return 1
    build(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
