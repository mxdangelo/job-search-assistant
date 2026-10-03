"""Reads the fact base: one file per unit, front matter plus prose.

No other module opens the files in `facts/`. Whoever needs a fact asks here.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date

import yaml

from jobsearch.config import FACTS, ROOT, dev  # noqa: F401  (ROOT: for those importing it here)

# A number as a CV writes it: 1.090, 2.752, 30, 8/10, 300.000.
NUMBER = re.compile(r"\d[\d.,/]*")

STATUSES = {"measured", "stated", "unconfirmed"}


@dataclass
class Fact:
    slug: str          # "experience/acme"
    meta: dict
    body: str

    @property
    def status(self) -> str:
        return str(self.meta.get("status", "unconfirmed"))

    @property
    def confidential(self) -> list[str]:
        """True things this fact does not let a CV print. See `preferences.md`."""
        return [str(x) for x in (self.meta.get("confidential") or [])]

    @property
    def excluded(self) -> bool:
        """`cv: no` — true, but the candidate wants it in no CV."""
        return self.meta.get("cv") is False or str(self.meta.get("cv", "")).lower() == "no"

    @property
    def citable(self) -> bool:
        """A fact that is only inferred does not enter a CV until someone confirms it."""
        return "unconfirmed" not in self.status and not self.excluded


def split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body.strip()


def load() -> dict[str, Fact]:
    facts = {}
    for path in sorted(FACTS.rglob("*.md")):
        slug = path.relative_to(FACTS).with_suffix("").as_posix()
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        facts[slug] = Fact(slug=slug, meta=meta, body=body)
    return facts


def numbers(text: str) -> set[str]:
    """The numbers in a text, normalised for comparison (separators removed)."""
    raw = NUMBER.findall(text)
    return {n.strip(".,/").replace(".", "").replace(",", "") for n in raw if n.strip(".,/")}


def fact_base_numbers(facts: dict[str, Fact] | None = None) -> set[str]:
    facts = facts or load()
    everything = " ".join(f"{f.body} {f.meta}" for f in facts.values())
    return numbers(everything)


def last_commit(repo: str) -> date | None:
    """The date of a repo's last commit in cv.yaml's `dev` folder, or None if it cannot look."""
    folder = dev() / repo
    if not (folder / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(folder), "log", "-1", "--format=%cs"],
        capture_output=True, text=True,
    )
    return date.fromisoformat(result.stdout.strip()) if result.returncode == 0 else None


def stale(facts: dict[str, Fact] | None = None) -> tuple[list[str], list[str]]:
    """The facts written from a repo that has moved on since.

    The fact base ages silently: a fact still says "33 articles" while the repo records a
    full audit. A fact that names a `repo:` also declares `updated:`, and if the repo has
    newer commits the fact must be reread before writing a CV.
    """
    facts = facts or load()
    old, blind = [], []
    for slug, fact in facts.items():
        repo = fact.meta.get("repo")
        if not repo:
            continue
        updated = fact.meta.get("updated")
        commit = last_commit(str(repo))
        if updated is None or commit is None:
            blind.append(f"{slug}: could not look (updated={updated}, repo={repo})")
        elif commit > date.fromisoformat(str(updated)):
            old.append(f"{slug}: updated {updated}, last commit of {repo} {commit}")
    return old, blind


def size() -> str:
    facts = load()
    total = sum(len(f.body.encode()) for f in facts.values())
    return f"{len(facts)} facts, {total / 1024:.1f} KB"


if __name__ == "__main__":
    print(size())
    for slug, f in load().items():
        print(f"  {f.status:28} {slug}")
    old, blind = stale()
    for line in old:
        print(f"[stale]           {line}")
    for line in blind:
        print(f"[unverified]      {line}")
