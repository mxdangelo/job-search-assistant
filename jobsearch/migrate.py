"""Moves a data folder from the old Italian schema (cvpipeline) to the English one.

    py -m jobsearch.migrate <data dir>

Renames folders and files, and translates the keys and enum values of front matter, plans,
requirements, reviews, `cv.yaml` and the applications log. The prose you wrote (facts,
preferences, postings, your notes) is left as it is. Idempotent: a second run finds nothing
to do. Every file keeps its modification time, so the gate's freshness check still holds.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

# --- names -------------------------------------------------------------------------------

TOP_LEVEL = {
    "fatti": "facts", "annunci": "postings", "profili": "profiles", "piani": "plans",
    "preferenze.md": "preferences.md", "candidature.yaml": "applications.yaml",
}
CV_FOLDERS = {"consegna": "delivered", "anteprima": "preview"}
FACT_FOLDERS = {"esperienze": "experience", "progetti": "projects", "formazione": "education"}
FACT_SLUGS = {"profilo": "profile", "education/lingue": "education/languages"}
SUFFIXES = {
    ".requisiti.json": ".requirements.json",
    ".requisiti.prompt.md": ".requirements.prompt.md",
    ".revisione.json": ".review.json",
    ".revisione.prompt.md": ".review.prompt.md",
}
LAYOUTS = {"classico": "classic", "compatto": "compact", "moderno": "modern",
           "due-colonne": "two-column"}

# --- keys --------------------------------------------------------------------------------

FACT_KEYS = {
    "tipo": "type", "azienda": "company", "ruolo": "role", "luogo": "location",
    "periodo": "period", "prova": "evidence", "stato": "status", "riservato": "confidential",
    "aggiornato": "updated", "nome": "name", "titolo": "title", "tecnologie": "technologies",
    "contatti": "contacts", "istituto": "institution",
}
FACT_TYPES = {
    "esperienza": "experience", "progetto": "project", "formazione": "education",
    "lingue": "languages", "profilo": "profile", "strumenti": "tools", "posizione": "position",
}
STATUSES = {"misurato": "measured", "dichiarato": "stated", "da_confermare": "unconfirmed"}

PROFILE_KEYS = {
    "profilo": "profile", "mercato": "market", "tetto_pagine": "max_pages",
    "lingua": "language", "annuncio": "posting",
}
POSTING_KEYS = {
    "azienda": "company", "ruolo": "role", "sede": "location", "contratto": "contract",
    "raccolto": "collected", "lingua_annuncio": "posting_language",
    "lingua_candidatura": "posting_language", "selezione": "screening", "ral": "salary",
    "richiesta_extra": "extra_request",
}
PLAN_KEYS = {
    "profilo": "profile", "lingua": "language", "tetto_pagine": "max_pages",
    "titolo": "title", "apertura": "summary", "esperienze": "experience", "fatto": "fact",
    "ruolo": "role", "luogo": "location", "periodo": "period", "righe": "lines",
    "progetti": "projects", "nome": "name", "competenze": "skills", "gruppo": "group",
    "voci": "items", "formazione": "education", "istituto": "institution",
    "lingue": "languages", "copertura": "coverage", "requisito": "requirement",
    "prova": "evidence", "escluse": "excluded", "perche": "reason",
    "ats_ignora": "ats_ignore", "termine": "term", "competenze_in_alto": "skills_first",
    "progetti_prima": "projects_first", "revisione": "review", "data": "date",
    "saltate": "skipped", "firma": "signature", "modifiche_candidato": "candidate_changes",
    "motivo": "reason", "firma_prima": "previous_signature",
}
REVIEW_KEYS = {
    **PLAN_KEYS, "modifiche": "changes", "dove": "where", "livello": "layer",
    "restanti": "remaining", "rilievo": "finding",
}
REVIEW_WHERE = {"titolo": "title", "apertura": "summary", "competenze": "skills",
                "formazione": "education", "lingue": "languages"}
REVIEW_LAYERS = {"scrittura": "writing", "fondo": "facts", "strategia": "strategy"}
REQUIREMENT_KEYS = {
    "requisiti": "requirements", "testo": "text", "tipo": "kind", "centrale": "central",
    "termini": "terms", "anni": "years", "lingua": "language", "equivalenti": "equivalents",
}
REQUIREMENT_KINDS = {"richiesto": "required"}
CONFIG_KEYS = {
    "intestazione": "header", "nome": "name", "contatti": "contacts", "gergo": "jargon",
    "nomi_propri": "proper_nouns", "parole_attese": "expected_words", "se_titolo": "if_title",
    "parola": "word", "perche": "reason", "carriera": "career", "lingua_fondo": "facts_language",
    "valuta": "evaluate", "candidati": "apply", "dubbio": "maybe", "lingue": "languages",
}
APPLICATION_KEYS = {
    "annuncio": "posting", "stato": "status", "valutato": "evaluated_on",
    "verdetto": "verdict", "punteggio": "score", "esito": "outcome", "nota": "note",
}
APPLICATION_STATUSES = {"valutato": "evaluated", "da mandare": "to send",
                        "mandato": "sent", "colloquio": "interview", "rifiutato": "rejected"}
VERDICTS = {"candidati": "apply", "dubbio": "maybe", "debole": "weak"}

FOLDER_PREFIX = re.compile(r"\b(esperienze|progetti|formazione)/")
PATH_PREFIX = re.compile(r"^(['\"]?)(annunci|cv/consegna)/")
PATHS = {"annunci": "postings", "cv/consegna": "cv/delivered"}
KEY_LINE = re.compile(r"^(?P<lead>[ ]*(?:-[ ]+)?)(?P<key>[A-Za-z_][\w-]*)(?P<colon>[ ]*:)"
                      r"(?P<rest>(?:[ ].*)?)$")

done: list[str] = []


# --- helpers -----------------------------------------------------------------------------

def slug(old: str) -> str:
    """A fact slug in the new folders: "esperienze/acme" -> "experience/acme"."""
    head, _, tail = old.partition("/")
    new = f"{FACT_FOLDERS.get(head, head)}/{tail}" if tail else head
    return FACT_SLUGS.get(new, new)


def evidence(text: str) -> str:
    """Fact paths inside a free-text evidence line."""
    text = FOLDER_PREFIX.sub(lambda m: FACT_FOLDERS[m.group(1)] + "/", text)
    return text.replace("education/lingue", "education/languages")


def data_path(value: str) -> str:
    """A data-folder path in a YAML value: "annunci/x.md" -> "postings/x.md"."""
    return PATH_PREFIX.sub(lambda m: m.group(1) + PATHS[m.group(2)] + "/", value)


def path_value(value: str) -> str:
    return f" {data_path(value.strip())}" if value.strip() else value


def rename(old: Path, new: Path, root: Path) -> None:
    if not old.exists():
        return
    if new.exists():
        if old.is_dir() and new.is_dir():
            for child in sorted(old.iterdir()):
                rename(child, new / child.name, root)
            if not any(old.iterdir()):
                old.rmdir()
        else:
            print(f"[conflict] {old.relative_to(root)} and {new.relative_to(root)} both exist: "
                  "left as is")
        return
    times = os.stat(old)
    new.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new)
    os.utime(new, ns=(times.st_atime_ns, times.st_mtime_ns))
    done.append(f"renamed  {old.relative_to(root)} -> {new.relative_to(root)}")


def rewrite(path: Path, root: Path, change: Callable[[str], str]) -> None:
    """Applies `change` to a file's text, keeping its bytes' newlines and its mtime."""
    if not path.is_file():
        return
    old = path.read_bytes().decode("utf-8")
    new = change(old)
    if new == old:
        return
    times = os.stat(path)
    path.write_bytes(new.encode("utf-8"))
    os.utime(path, ns=(times.st_atime_ns, times.st_mtime_ns))
    done.append(f"rewrote  {path.relative_to(root)}")


def exact(mapping: dict[str, str]) -> Callable[[str], str]:
    """A value transform that maps a whole scalar, quoted or not."""
    def change(value: str) -> str:
        v = value.strip()
        quote = v[0] if v[:1] in ("'", '"') and len(v) > 1 and v[-1] == v[0] else ""
        inner = v[1:-1] if quote else v
        return f" {quote}{mapping[inner]}{quote}" if inner in mapping else value
    return change


def words(mapping: dict[str, str]) -> Callable[[str], str]:
    """A value transform that maps whole words anywhere in the value."""
    rule = re.compile(r"\b(" + "|".join(map(re.escape, mapping)) + r")\b")
    return lambda value: rule.sub(lambda m: mapping[m.group(1)], value)


def yaml_lines(text: str, keys: dict[str, str], values: dict[str, Callable[[str], str]],
               top_only: bool) -> str:
    """Renames keys line by line: comments, quoting and layout stay as they are."""
    out = []
    for line in text.split("\n"):
        body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        m = KEY_LINE.match(body)
        if m and not (top_only and m["lead"]):
            key = keys.get(m["key"], m["key"])
            rest = values[key](m["rest"]) if key in values else m["rest"]
            body = f"{m['lead']}{key}{m['colon']}{rest}"
        out.append(body + cr)
    return "\n".join(out)


def front_matter(keys: dict[str, str], values: dict[str, Callable[[str], str]]
                 ) -> Callable[[str], str]:
    def change(text: str) -> str:
        if not text.startswith("---"):
            return text
        end = text.find("\n---", 3)
        if end < 0:
            return text
        return yaml_lines(text[:end], keys, values, top_only=True) + text[end:]
    return change


def json_file(keys: dict[str, str], values: dict[str, Callable[[str], str]]
              ) -> Callable[[str], str]:
    def walk(node: object) -> object:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                key = keys.get(k, k)
                v = walk(v)
                out[key] = values[key](v) if key in values and isinstance(v, str) else v
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    def change(text: str) -> str:
        data = json.loads(text)
        new = walk(data)
        if new == data and list(_keys(new)) == list(_keys(data)):
            return text
        indent = re.search(r"\n( +)\S", text)
        dumped = json.dumps(new, ensure_ascii=False, indent=len(indent.group(1)) if indent else 2)
        return dumped + ("\n" if text.endswith("\n") else "")
    return change


def _keys(node: object):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for x in node:
            yield from _keys(x)


# --- the migration -----------------------------------------------------------------------

def rename_all(root: Path) -> None:
    for old, new in TOP_LEVEL.items():
        rename(root / old, root / new, root)
    for old, new in CV_FOLDERS.items():
        rename(root / "cv" / old, root / "cv" / new, root)
    facts = root / "facts"
    for old, new in FACT_FOLDERS.items():
        rename(facts / old, facts / new, root)
    for old, new in FACT_SLUGS.items():
        rename(facts / f"{old}.md", facts / f"{new}.md", root)
    for folder in (root / "postings", root / "plans"):
        for path in sorted(folder.glob("*")) if folder.is_dir() else []:
            for old, new in SUFFIXES.items():
                if path.name.endswith(old):
                    rename(path, path.with_name(path.name[: -len(old)] + new), root)
    preview = root / "cv" / "preview"
    for path in sorted(preview.glob("*.*.*")) if preview.is_dir() else []:
        stem, layout, ext = path.name.rsplit(".", 2)
        if layout in LAYOUTS:
            rename(path, path.with_name(f"{stem}.{LAYOUTS[layout]}.{ext}"), root)
    for css in sorted((root / "layout").glob("*/stile.css")):
        rename(css, css.with_name("style.css"), root)
        print(f"[check]  {css.parent.relative_to(root)}: a layout of your own uses the old class "
              "names and plan keys: compare it with the engine's classic layout")


def rewrite_all(root: Path) -> None:
    fact = front_matter(FACT_KEYS, {"type": exact(FACT_TYPES), "status": words(STATUSES)})
    for path in sorted((root / "facts").rglob("*.md")):
        rewrite(path, root, fact)

    profile = front_matter(PROFILE_KEYS, {"posting": path_value})
    for path in sorted((root / "profiles").glob("*.md")):
        rewrite(path, root, profile)

    posting = front_matter(POSTING_KEYS, {})
    requirements = json_file(REQUIREMENT_KEYS,
                             {"kind": lambda v: REQUIREMENT_KINDS.get(v, v)})
    for path in sorted((root / "postings").glob("*")):
        if path.suffix == ".md" and not path.name.endswith(".prompt.md"):
            rewrite(path, root, posting)
        elif path.name.endswith(".requirements.json"):
            rewrite(path, root, requirements)

    plan_values = {"fact": slug, "evidence": evidence,
                   "layout": lambda v: LAYOUTS.get(v, v)}
    plan = json_file(PLAN_KEYS, plan_values)
    review = json_file(REVIEW_KEYS, {**plan_values,
                                     "where": lambda v: REVIEW_WHERE.get(v, v),
                                     "layer": lambda v: REVIEW_LAYERS.get(v, v)})
    for path in sorted((root / "plans").glob("*.json")):
        rewrite(path, root, review if path.name.endswith(".review.json") else plan)

    rewrite(root / "cv.yaml", root, lambda t: yaml_lines(
        t, CONFIG_KEYS, {"layout": exact(LAYOUTS)}, top_only=False))
    rewrite(root / "applications.yaml", root, lambda t: yaml_lines(
        t, APPLICATION_KEYS,
        {"posting": path_value, "cv": path_value,
         "status": exact(APPLICATION_STATUSES), "verdict": exact(VERDICTS)},
        top_only=False))


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print(__doc__)
        return 1
    root = Path(argv[0]).resolve()
    if not (root / "fatti").is_dir() and not (root / "facts").is_dir():
        print(f"[not migrated] {root} has neither fatti/ nor facts/: not a data folder")
        return 1
    rename_all(root)
    rewrite_all(root)
    for line in done:
        print(line)
    if not done:
        print("[ok] nothing to migrate: the folder already uses the English schema")
        return 0
    print(f"[ok] {len(done)} changes. Your own prose (README, preferences, facts, notes) is "
          "untouched: paths it mentions may still use the old names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
