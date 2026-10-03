# job-search-assistant

A job posting goes in, a CV tailored to it comes out. An LLM chooses what to say from a
verified fact base, and deterministic Python checks block anything it cannot trace back
to a fact.

No RAG. The fact base fits in one context window, and retrieval adds the one failure a CV
cannot afford: the fact that matters is not retrieved, and nobody notices.

## How it works

| Step | Who | What |
|---|---|---|
| 0. `evaluate` | model + Python | Should you apply? A model extracts the posting's requirements once; Python scores them against the fact base and logs the verdict. |
| 1. Profile | you | A short note on what this posting wants and which gaps to state. |
| 2. `plan` | model | Reads every fact, the preferences and the posting, and writes a *plan*: what goes in, in which order, and what stays out. |
| 3. `render` | Python | Plan → HTML → PDF, through a layout. No model. |
| 4. `gate` | Python | Every number and date must exist in the fact base. Also checks confidential data, chronology, ATS readability, page count and voice rules. |
| 5. `review` | blind model + you | A reviewer that sees only the PDF and the posting edits the CV. Python blocks any added fact; you approve the diff line by line. |
| 6. `deliver` | Python | Copies the PDF to `cv/delivered/` only if the plan is signed by the review and still passes the gate. |

The model steps write a prompt file and expect a JSON file back. The engine makes no API
calls: run the prompt with whatever model you use. The rest is plain Python.

## Facts have three states

Each fact is a Markdown file with front matter. `status` is one of:

- `measured` — counted from files; the command or source is in `evidence`.
- `stated` — stated by the candidate, not verified.
- `unconfirmed` — inferred, never confirmed. It cannot enter a CV, and it does not
  count as evidence in any check.

A fact can also list `confidential:` strings: true, but never printed (salary, client
fees). The gate blocks a CV that contains one; avoiding a paraphrase is the plan step's job.

## Try it

Requires Python 3.11+ and Chrome (or Chromium).

```
pip install -e .
cd example
py -m jobsearch.evaluate postings/acme-seo.md   # should Alex apply?
py -m jobsearch.render plans/acme-seo.json      # the CV, as PDF
py -m jobsearch.gate plans/acme-seo.json        # the checks
py -m jobsearch.preview plans/acme-seo.json     # the same CV in every layout
```

On Linux and macOS use `python` instead of `py`. Then change "96,000" to "120,000" in
`plans/acme-seo.json` and run `gate` again: the invented number is blocked.

`example/` holds one fictional candidate, Alex Moretti. Their backlink project is
`unconfirmed`, so the posting's backlink requirement stays uncovered even though a file
mentions it.

## Start your own

```
py -m jobsearch.init ~/my-jobsearch        # folders, cv.yaml from a few questions
cd ~/my-jobsearch
py -m jobsearch.intake cv old-cv.pdf       # prompt: split an old CV into fact files
py -m jobsearch.check                      # what each fact still lacks
py -m jobsearch.intake interview           # prompt: a chat that fills the gaps
```

`intake cv` reads PDF, Word or text. Everything an old CV says enters as `stated`: a CV
is a claim, not a source. What the model infers enters as `unconfirmed` and stays out of
every CV until you confirm it.

`intake interview` writes a prompt for a chat that asks one question at a time and writes
the fact files as you answer. It starts from what `check` finds weak, from the time
between jobs no fact covers, and from what came after the latest job in the base: an old
CV is always out of date. With an empty base it starts from your most recent job. The
questions are fixed by the engine: company and what it does, role, period, what changed,
the number and where it comes from, whom you reported to, what must never be printed.

## Your data

The engine holds no person. Commands run from a data folder, or from anywhere with
`JOBSEARCH_DATA` pointing to it:

```
facts/             experience/, projects/, education/, profile.md
postings/          postings, and their extracted requirements
profiles/          one note per posting
plans/             the plans, one JSON per CV
preferences.md     how to write: read by the plan step
cv.yaml            name and contacts, layout, jargon to block, career start dates
applications.yaml  the evaluation log, with your notes on each outcome
```

Keep the data folder private. It holds what you would not print.

The fact base and the CVs can be in Italian or English. Postings can be in another
language: `facts_language` in `cv.yaml` tells the requirements step which language to
translate the posting's terms into, and a plan's `language` picks the CV headings.

A data folder written for the earlier Italian schema (`fatti/`, `piani/`, …) moves to
this one with `py -m jobsearch.migrate <data dir>`. It keeps file times, so plans do not
turn stale, and a second run changes nothing.

## Layouts

`classic`, `compact`, `modern` (single column, ATS-safe) and `two-column` (sidebar,
riskier for ATS parsers). Choose one with `layout:` in `cv.yaml`, or per CV in the plan.
A layout of your own goes in `<data>/layout/<name>/`: a `style.css` that overrides the
classic one, and a `cv.html.j2` only if the structure changes. `preview` reports for each
layout whether the contacts extract and the experience reads in order.

## License

MIT.
