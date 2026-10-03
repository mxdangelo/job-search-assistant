"""The posting's words against the PDF text, the way an ATS searches them.

An ATS does not read the CV: it extracts the text and searches it for the posting's terms,
and a recruiter querying the database does the same. This simulates that common step, not
any product's proprietary score.

For each lexicon term that appears in the posting, four outcomes:

- **present** — the PDF contains the same word the posting uses;
- **synonym** — the PDF says it with another word ("GA4" where the posting says
  "Google Analytics"): whoever searches for the posting's word does not find it. A warning,
  not a block, because between a posting in Italian and a CV in English the synonym is the
  translation;
- **missing** — the PDF does not say it in any form but the fact base proves it: the gate
  blocks;
- **uncovered** — neither the PDF nor the fact base: it is not written, it is known.

    py -m jobsearch.ats plans/example.json
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from jobsearch import config
from jobsearch.facts import ROOT, load

# Canonical term -> the forms in which a posting or a CV writes it. Only terms an ATS really
# searches for: tools, techniques, platforms. The first form is the one to use. The lexicon
# is bilingual on purpose: it serves Italian CVs and postings too.
LEXICON: dict[str, list[str]] = {
    "Google Search Console": ["Search Console", "GSC"],
    "GA4": ["GA4", "Google Analytics", "Analytics 4"],
    "Looker Studio": ["Looker Studio", "Data Studio"],
    "Looker": ["Looker"],
    "Adobe Analytics": ["Adobe Analytics"],
    "Google Tag Manager": ["Tag Manager", "GTM"],
    "Semrush": ["Semrush"],
    "Ahrefs": ["Ahrefs"],
    "SeoZoom": ["SeoZoom"],
    "Screaming Frog": ["Screaming Frog"],
    "Majestic": ["Majestic"],
    "Lumar": ["Lumar"],
    "AWR": ["AWR"],
    "Tableau": ["Tableau"],
    "Power BI": ["Power BI"],
    "Omni": ["Omni"],
    "Excel": ["Excel", "Google Sheets", "xlsx"],
    "PowerPoint": ["PowerPoint"],
    "Jira": ["Jira"],
    "Asana": ["Asana"],
    "Trello": ["Trello"],
    "ClickUp": ["ClickUp"],
    "CRM": ["CRM"],
    "WordPress": ["WordPress"],
    "Shopify": ["Shopify"],
    "Webflow": ["Webflow"],
    "HTML": ["HTML"],
    "CSS": ["CSS"],
    "JavaScript": ["JavaScript"],
    "JSON-LD": ["JSON-LD"],
    "Python": ["Python"],
    "SQL": ["SQL"],
    "Apps Script": ["Apps Script"],
    "Core Web Vitals": ["Core Web Vitals"],
    "hreflang": ["hreflang"],
    "dati strutturati": ["dati strutturati", "structured data", "schema markup", "Schema.org"],
    "crawling": ["crawling"],
    "indicizzazione": ["indicizzazione", "indexation", "indexing"],
    "rendering": ["rendering"],
    "keyword research": ["keyword research"],
    "link building": ["link building"],
    "digital PR": ["digital PR"],
    "link interni": ["link interni", "internal link", "internal linking", "internal links"],
    "E-E-A-T": ["E-E-A-T", "EEAT"],
    "content audit": ["content audit", "content audits", "audit dei contenuti"],
    "editorial calendar": ["editorial calendar", "content calendar", "calendario editoriale"],
    "CMS": ["CMS"],
    "search intent": ["search intent", "intento di ricerca"],
    "keyword mapping": ["keyword mapping"],
    "on-page": ["on-page"],
    "technical SEO": ["technical SEO", "SEO tecnica"],
    "canonical": ["canonical"],
    "redirect": ["redirect", "redirects"],
    "XML sitemap": ["XML sitemap", "XML sitemaps", "sitemap"],
    "migrazioni": ["migration", "migrations", "migrazione"],
    "fact-checking": ["fact-checking", "fact checking", "source verification", "verifica delle fonti"],
    "localizzazione": ["localization", "localisation", "localizzazione"],
    "conversione": ["conversion", "conversions", "conversione", "conversioni", "CRO"],
    "B2B": ["B2B"],
    "healthcare": ["healthcare", "sanità", "clinical"],
    "cannibalizzazione": ["cannibalizzazione", "cannibalisation", "cannibalization"],
    "e-commerce": ["e-commerce", "ecommerce", "marketplace"],
    "llms.txt": ["llms.txt"],
    "GEO": ["GEO"],
    "AEO": ["AEO"],
    "AI Overview": ["AI Overview"],
    "ChatGPT": ["ChatGPT"],
    "Gemini": ["Gemini"],
    "Perplexity": ["Perplexity"],
    "MCP": ["MCP"],
    "Google Ads": ["Google Ads"],
    "Meta Ads": ["Meta Ads", "Meta e Google Ads"],
    "SEA": ["SEA", "SEM"],
    # AI builder: agents, orchestration, automation, assisted development tools.
    # "Make" stays out: as a common word it would match any English text.
    "agenti": ["agenti", "agents", "agentic", "agentiche"],
    "orchestrazione": ["orchestrazione", "orchestration"],
    "LangGraph": ["LangGraph"],
    "LangChain": ["LangChain"],
    "CrewAI": ["CrewAI"],
    "AutoGen": ["AutoGen"],
    "function calling": ["function calling", "tool use", "tool-calling", "tool calling"],
    "Docker": ["Docker", "containerise", "containerize", "container"],
    "uv": ["uv"],
    "idempotenza": ["idempotent", "idempotency", "idempotenti", "idempotente"],
    "rate limit": ["rate limit", "rate limits", "rate-limit", "rate-limits"],
    "state machine": ["state machine", "state-machine"],
    "webhook": ["webhook"],
    "LLM-as-judge": ["LLM-as-judge"],
    "evals": ["evals"],
    "provenance": ["provenance", "provenienza"],
    "calibration": ["calibration", "calibrazione"],
    "machine learning": ["machine learning", "ML"],
    "statistica": ["statistics", "statistica", "applied statistics"],
    "PromptOps": ["PromptOps"],
    "email marketing": ["email marketing", "newsletter"],
    "marketing automation": ["marketing automation"],
    "customer journey": ["customer journey", "customer journeys"],
    "customer experience": ["customer experience"],
    "digital adoption": ["digital adoption"],
    "dashboard": ["dashboard", "dashboards"],
    "KPI": ["KPI"],
    "retention": ["retention"],
    "UX": ["UX"],
    "data-driven": ["data-driven"],
    "stakeholder": ["stakeholder", "stakeholders"],
    "SEO locale": ["SEO locale", "local SEO"],
    "Salesforce": ["Salesforce"],
    "HubSpot": ["HubSpot"],
    "Splio": ["Splio"],
    "loyalty": ["loyalty"],
    "segmentazione": ["segmentazione", "segmentare", "segmentation", "segmenting"],
    "redemption": ["redemption"],
    "customer lifetime value": ["customer lifetime value", "CLV"],
    "multicanale": ["multicanale", "multichannel", "omnichannel"],
    "data quality": ["data quality", "qualità dei dati", "qualità del dato"],
    "report": ["report", "reportistica", "reporting"],
    "Office": ["pacchetto Office", "Microsoft Office"],
    "retail": ["retail"],
    "product marketing": ["product marketing"],
    "SaaS": ["SaaS"],
    "automazione": ["automation", "automations", "automazione", "automazioni"],
    "workflow": ["workflow", "workflows"],
    "integrazioni": ["integration", "integrations", "integrazioni"],
    "RAG": ["RAG"],
    "n8n": ["n8n"],
    "Zapier": ["Zapier"],
    "Cursor": ["Cursor"],
    "Windsurf": ["Windsurf"],
    "Replit": ["Replit"],
    "Lovable": ["Lovable"],
    "Claude Code": ["Claude Code"],
    "prototipi": ["prototipi", "prototipo", "prototype", "MVP"],
    "GitHub": ["GitHub"],
    "YMYL": ["YMYL"],
    "SEO": ["SEO"],
    "piano editoriale": ["piano editoriale", "piani editoriali", "editorial plan"],
}

def _rule(form: str) -> re.Pattern:
    """A form as a whole word: "SQL" must not be found inside "NoSQL"."""
    return re.compile(r"(?<![\w-])" + re.escape(form) + r"(?![\w-])", re.I)


def _found(text: str, forms: list[str]) -> list[str]:
    return [f for f in forms if _rule(f).search(text)]


@dataclass
class Result:
    present: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)    # the fact base proves them
    uncovered: list[str] = field(default_factory=list)  # the fact base does not


def posting_of(plan: dict) -> Path | None:
    """The posting the plan's profile answers, from the profile's front matter."""
    profile = ROOT / "profiles" / f"{plan['profile']}.md"
    if not profile.exists():
        return None
    text = profile.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}
    path = (meta or {}).get("posting")
    return ROOT / path if path and (ROOT / path).exists() else None


def compare(posting: str, cv: str, facts: str, ignore: frozenset[str] = frozenset()) -> Result:
    result = Result()
    for term, forms in LEXICON.items():
        # A term the posting names in order to exclude it: the plan declares it.
        if term in ignore:
            continue
        used = _found(posting, forms)
        if not used:
            continue
        # The CV must say the posting's word, not a synonym: that is the one searched for.
        if _found(cv, used):
            result.present.append(term)
        elif others := _found(cv, forms):
            result.synonyms.append(f"the posting says «{used[0]}», the CV «{others[0]}»")
        elif _found(facts, forms):
            result.missing.append(f"{term} (the posting says «{used[0]}»)")
        else:
            result.uncovered.append(term)
    return result


# Names really written with a capital in the middle: they are not glued words.
INNER_CAPITAL = {
    "B2B", "SaaS", "WordPress", "SeoZoom", "ClickUp", "GitHub", "JavaScript", "PowerPoint",
    "LinkedIn", "SQLite", "MongoDB", "NoSQL", "RoBERTa", "YouTube", "GPTBot", "OpenAI",
    "TikTok", "DeepL", "ChatGPT", "LangGraph", "LangChain", "CrewAI", "AutoGen", "PyPI",
}
GLUED = re.compile(r"\b\S*[a-zà-ù0-9][A-Z]\S*")
# A figure with its multiplier: "13.9M", "820K". Not a glued word.
SHORT_FIGURE = re.compile(r"^\d[\d.,]*[KMB][,.;:]?$")
BROKEN = re.compile(r"\b\w+- \w+")


def extraction_faults(text: str) -> list[str]:
    """The words the PDF delivers broken: "xlsxSkills", "e- commerce".

    They are the ones a parser reads as words that do not exist. The first case comes from
    two blocks side by side with no space, the second from a line break at the hyphen.
    """
    glued = {
        w
        for w in GLUED.findall(text)
        if not any(n in w for n in INNER_CAPITAL | config.proper_nouns())
        and not SHORT_FIGURE.match(w)
    }
    broken = set(BROKEN.findall(text))
    return [f"broken word in the PDF: «{w}»" for w in sorted(glued | broken)]


def pdf_text(plan: dict) -> str | None:
    pdf = ROOT / "cv" / f"{plan['profile']}.pdf"
    if not pdf.exists():
        return None
    from pypdf import PdfReader
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(str(pdf)).pages)


def check(plan: dict) -> tuple[Result | None, str]:
    """The result, or None and the reason it could not look."""
    posting = posting_of(plan)
    if posting is None:
        return None, "no posting in the profile: nothing to compare"
    cv = pdf_text(plan)
    if cv is None:
        return None, "the PDF does not exist"
    # Only citable facts prove anything: an unconfirmed one does not enter a CV.
    facts = " ".join(f"{f.body} {f.meta}" for f in load().values() if f.citable)
    ignore = frozenset(v["term"] for v in plan.get("ats_ignore", []))
    return compare(posting.read_text(encoding="utf-8"), cv, facts, ignore), ""


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    plan = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    result, reason = check(plan)
    if result is None:
        print(f"[unverified] {reason}")
        return 0
    print(f"present ({len(result.present)}): {', '.join(result.present)}")
    print(f"synonyms ({len(result.synonyms)}): {'; '.join(result.synonyms) or '-'}")
    print(f"missing ({len(result.missing)}): {', '.join(result.missing) or '-'}")
    print(f"uncovered ({len(result.uncovered)}): {', '.join(result.uncovered) or '-'}")
    return 1 if result.missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
