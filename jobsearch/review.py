"""The review: a blind reader reads the PDF and fixes the CV. The candidate approves the diff.

The reader does not see the fact base, the preferences or the plan's reasons: it sees what
a recruiter sees, the PDF and the posting. That is why it finds what the plan's author does
not see. It may cut, reorder, reword; it may not add a fact.

    py -m jobsearch.review prepare plans/example.json   # prompt for the reader
    py -m jobsearch.review diff plans/example.json      # checks + diff, proposed PDF
    py -m jobsearch.review apply plans/example.json [--skip 2,5]
    py -m jobsearch.review sign plans/example.json "why"   # a change by the candidate

`prepare` writes `plans/<slug>.review.prompt.md`; the reader, a session without context,
writes `plans/<slug>.review.json`. `diff` lays out the proposal as a draft, passes it to
the gate and prints the numbered changes. `apply` writes the approved ones into the plan
and signs it: `jobsearch.deliver` delivers only a plan that is signed and untouched since.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from jobsearch.facts import ROOT, numbers
from jobsearch.gate import check, plan_text
from jobsearch.render import main as render

# The words that raise a claim: if they appear where they were not, the candidate must see
# them. Italian forms too: the CV may be in Italian.
RAISES = re.compile(
    r"\b(led|lead|leading|managed|managing|headed|owned|owner|ownership|built|launched|"
    r"drove|grew|scaled|senior|expert|guidat\w*|diretto|gestit\w*|responsabile|"
    r"lanciat\w*|costruit\w*|team)\b",
    re.I,
)
# What the reader does not touch: dates, places, links and institutions are facts, not form.
FIXED = ("period", "location", "url", "institution")

INSTRUCTIONS = """\
You are a senior recruiter and CV expert with 15 years of screening for tech and marketing
roles in Italy, the UK and remote European companies. You will review one CV and fix it.

Read, with the Read tool and nothing else:
- the CV as the reader sees it: {pdf}
- the job posting it answers: {posting}
Do not open any other file. The CV text is also below as JSON: it is what you edit.

First read it the way a recruiter does: the 7-second scan, then a careful read. Then edit
the JSON so the CV reads well to a recruiter and a hiring manager for this posting.

You may: cut a line, cut a project, reorder lines and projects, merge lines, reword a line,
reword the title and the summary, remove skills, reword a role or company line.
You may not: add a fact, a number, a skill, a tool, a project or an experience that is not
already in the JSON; change any `period`, `location`, `url` or `institution`; remove an
experience (empty its `lines` instead, it stays as one line); change an `id`; remove a
skill, tool or term that the posting names, even if it looks like filler: an automated
matcher screens the CV for the posting's exact words before any human reads it.
Rewording must not raise a claim: "presented to" does not become "led", "worked on"
does not become "owned". If the right fix needs a fact you do not have, do not write it:
put it in `remaining`.

Write one file, {output}, with this shape and nothing else:

{{
  "cv": <the edited JSON, same shape and ids>,
  "changes": [{{"where": "<title|summary|e1|p2|skills|education|languages>",
                "reason": "<one sentence: why a recruiter reads the old version badly>",
                "layer": "<writing|facts|template|strategy>"}}],
  "remaining": [{{"finding": "<what still hurts>", "layer": "<facts|template|strategy>"}}]
}}

`layer` says where the problem comes from: `writing` the wording, `facts` a missing or
weak fact, `template` the layout, `strategy` a choice of what to apply for or how to
present the candidate. If the CV needs no change, return it unchanged with empty
`changes`.

The CV, as JSON:

{cv}
"""


def visible(plan: dict) -> dict:
    """The CV as the reader sees it: no facts, no coverage, no exclusions."""
    def entry(prefix: str, i: int, v: dict) -> dict:
        keep = {k: v[k] for k in v if k not in ("fact",)}
        return {"id": f"{prefix}{i + 1}", **keep}

    return {
        "title": plan.get("title", ""),
        "summary": plan.get("summary", ""),
        "experience": [entry("e", i, v) for i, v in enumerate(plan.get("experience", []))],
        "projects": [entry("p", i, v) for i, v in enumerate(plan.get("projects", []))],
        "skills": plan.get("skills", []),
        "education": plan.get("education", []),
        "languages": plan.get("languages", []),
    }


def signature(plan: dict) -> str:
    return hashlib.sha256(plan_text(plan).encode()).hexdigest()[:12]


def paths(plan_path: Path) -> tuple[Path, Path]:
    stem = plan_path.with_suffix("")
    return stem.with_name(stem.name + ".review.prompt.md"), stem.with_name(
        stem.name + ".review.json"
    )


def prepare(plan_path: Path, plan: dict) -> int:
    from jobsearch.ats import posting_of

    prompt, output = paths(plan_path)
    posting = posting_of(plan)
    pdf = ROOT / "cv" / f"{plan['profile']}.pdf"
    if not pdf.exists():
        print(f"[not prepared] {pdf.name} does not exist: rerun render")
        return 1
    text = INSTRUCTIONS.format(
        pdf=pdf,
        posting=posting if posting else "(no posting: a general CV for the role in the title)",
        output=output,
        cv=json.dumps(visible(plan), ensure_ascii=False, indent=2),
    )
    prompt.write_text(text, encoding="utf-8")
    print(f"[ok] {prompt.relative_to(ROOT)}: give it to a session without context")
    return 0


def units(plan: dict) -> dict[str, object]:
    """The parts of the CV that are approved one by one."""
    vis = visible(plan)
    parts: dict[str, object] = {"title": vis["title"], "summary": vis["summary"]}
    for v in vis["experience"] + vis["projects"]:
        parts[v["id"]] = v
    for key in ("skills", "education", "languages"):
        parts[key] = vis[key]
    return parts


def text_of(part: object) -> str:
    return json.dumps(part, ensure_ascii=False)


def without_id(part: object) -> str:
    """The text of a part without its id: "e3" is not a number in the CV."""
    if isinstance(part, dict):
        part = {k: v for k, v in part.items() if k != "id"}
    return text_of(part)


def checks(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """Blocks (the reader added a fact) and signals (the candidate should look here)."""
    blocks, signals = [], []
    old, new = units(before), after
    for key in new:
        if key not in old:
            blocks.append(f"{key}: new part, the reader cannot add")
    for key in old:
        if key.startswith("e") and key[1:].isdigit() and new.get(key) is None:
            blocks.append(f"{key}: experience removed, it leaves a gap: empty its lines")
    everything_before = " ".join(without_id(p) for p in old.values())
    for key, part in new.items():
        if part is None or key not in old:
            continue
        if added := numbers(without_id(part)) - numbers(everything_before):
            blocks.append(f"{key}: new numbers {sorted(added)}")
        if isinstance(part, dict):
            for field in FIXED:
                if part.get(field) != old[key].get(field):  # type: ignore[union-attr]
                    blocks.append(f"{key}: «{field}» changed, it is a fact")
        words_before = {m.lower() for m in RAISES.findall(text_of(old[key]))}
        if raised := {m.lower() for m in RAISES.findall(text_of(part))} - words_before:
            signals.append(f"{key}: raises the claim? {sorted(raised)}")
    items_before = {v.lower() for g in before.get("skills", []) for v in g["items"]}
    for g in new.get("skills", []) or []:
        for v in g["items"]:
            if v.lower() not in items_before:
                blocks.append(f"skills: «{v}» is new, the reader cannot add")
    return blocks, signals


def proposal(plan: dict, cv: dict) -> dict[str, object]:
    """The parts of the proposal, with None for a project that was cut."""
    parts: dict[str, object] = {"title": cv["title"], "summary": cv["summary"]}
    for v in cv.get("experience", []) + cv.get("projects", []):
        parts[v["id"]] = v
    for key in ("skills", "education", "languages"):
        parts[key] = cv.get(key, [])
    for key in units(plan):
        parts.setdefault(key, None)
    return parts


def changed(plan: dict, parts: dict[str, object]) -> list[str]:
    old = units(plan)
    return [k for k in parts if text_of(parts[k]) != text_of(old.get(k))]


def merge(plan: dict, parts: dict[str, object], taken: list[str], cv: dict) -> dict:
    """The plan with the approved parts. Projects follow the proposal's order."""
    new = json.loads(json.dumps(plan))
    for k in ("title", "summary", "skills", "education", "languages"):
        if k in taken:
            new[k] = parts[k]
    for section, prefix in (("experience", "e"), ("projects", "p")):
        originals = {f"{prefix}{i + 1}": v for i, v in enumerate(plan[section])}
        sequence = list(originals)
        if section == "projects" and any(k.startswith("p") for k in taken):
            proposed = [v["id"] for v in cv.get("projects", [])]
            sequence = proposed + [k for k in originals if k not in proposed]
        entries = []
        for k in sequence:
            if k in taken:
                if parts[k] is None:
                    continue
                entry = {c: x for c, x in parts[k].items() if c != "id"}  # type: ignore[union-attr]
                entries.append({"fact": originals[k]["fact"], **entry})
            else:
                entries.append(originals[k])
        new[section] = entries
    return new


def show(plan: dict, parts: dict[str, object], names: list[str], reasons: dict) -> None:
    old = units(plan)
    for n, k in enumerate(names, 1):
        print(f"\n[{n}] {k}  ({reasons.get(k, 'no reason given')})")
        for line in lines_of(old.get(k)):
            print(f"  - {line}")
        for line in lines_of(parts[k]):
            print(f"  + {line}")


def lines_of(part: object) -> list[str]:
    if part is None:
        return ["(removed)"]
    if isinstance(part, str):
        return [part]
    if isinstance(part, dict):
        head = " | ".join(str(part.get(c, "")) for c in ("role", "name", "org") if part.get(c))
        return [head] + [f"  {r}" for r in part.get("lines", [])]
    return [text_of(x) for x in part]  # type: ignore[union-attr]


def diff(plan_path: Path, plan: dict, skip: set[int] | None = None) -> tuple[int, dict]:
    _, output = paths(plan_path)
    if not output.exists():
        print(f"[unverified] {output.name} is not there: the reader has not written yet")
        return 1, {}
    answer = json.loads(output.read_text(encoding="utf-8"))
    parts = proposal(plan, answer["cv"])
    blocks, signals = checks(plan, parts)
    names = changed(plan, parts)
    reasons = {}
    for m in answer.get("changes", []):
        reasons[m["where"]] = f"{m.get('layer', '?')}: {m.get('reason', '')}"
    taken = [k for n, k in enumerate(names, 1) if n not in (skip or set())]
    new = merge(plan, parts, taken, answer["cv"])
    return (1 if blocks else 0), {
        "parts": parts, "names": names, "reasons": reasons, "blocks": blocks,
        "signals": signals, "new": new, "remaining": answer.get("remaining", []),
    }


def print_diff(plan_path: Path, plan: dict) -> int:
    result, d = diff(plan_path, plan)
    if not d:
        return result
    show(plan, d["parts"], d["names"], d["reasons"])
    for r in d["remaining"]:
        print(f"\n[remaining, {r.get('layer', '?')}] {r.get('finding', '')}")
    print()
    for s in d["signals"]:
        print(f"[to check]       {s}")
    for b in d["blocks"]:
        print(f"[blocked]        {b}")
    # The proposal is laid out as a draft: the candidate looks at it in the PDF, not only
    # in the diff.
    draft = ROOT / "plans" / f".{plan['profile']}.proposal.json"
    draft.write_text(json.dumps(d["new"], ensure_ascii=False, indent=2), encoding="utf-8")
    render([str(draft)])
    draft.unlink()
    gate_blocks, _ = check(d["new"])
    for b in gate_blocks:
        print(f"[blocked, gate]  {b}")
    if not d["names"]:
        print("[ok] no changes proposed")
    print(f"\nproposal laid out in cv/{plan['profile']}.pdf; the plan has not changed")
    return 1 if d["blocks"] or gate_blocks else 0


def apply(plan_path: Path, plan: dict, skip: set[int]) -> int:
    result, d = diff(plan_path, plan, skip)
    if not d:
        return result
    if d["blocks"]:
        print("[not applied] the proposal adds facts: run the review again")
        return 1
    new = d["new"]
    new["review"] = {
        "date": date.today().isoformat(),
        "skipped": sorted(skip),
        "signature": signature(new),
    }
    plan_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] {plan_path.relative_to(ROOT)} signed; now render and deliver")
    return render([str(plan_path)])


def resign(plan_path: Path, plan: dict, reason: str) -> int:
    """A change by the candidate after the review: signed without another round, and logged.

    Only on a plan already reviewed: the blind review is not skipped, it is updated.
    """
    rev = plan.get("review")
    if not rev:
        print("[not signed] the plan has never been reviewed: review first")
        return 1
    if not reason.strip():
        print("[not signed] the reason for the change is needed")
        return 1
    if rev.get("signature") == signature(plan):
        print("[ok] nothing to sign: the plan has not changed since the review")
        return 0
    rev.setdefault("candidate_changes", []).append(
        {"date": date.today().isoformat(), "reason": reason,
         "previous_signature": rev["signature"]}
    )
    rev["signature"] = signature(plan)
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    plan_path.write_text(text, encoding="utf-8")
    print(f"[ok] {plan_path.relative_to(ROOT)} re-signed: {reason}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("prepare", "diff", "apply", "sign"):
        print(__doc__)
        return 1
    plan_path = Path(argv[1]).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if argv[0] == "prepare":
        return prepare(plan_path, plan)
    if argv[0] == "diff":
        return print_diff(plan_path, plan)
    if argv[0] == "sign":
        return resign(plan_path, plan, " ".join(argv[2:]))
    skip = set()
    if "--skip" in argv:
        skip = {int(n) for n in argv[argv.index("--skip") + 1].split(",")}
    return apply(plan_path, plan, skip)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
