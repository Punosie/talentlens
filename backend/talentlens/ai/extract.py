"""Resume field extraction: rules always; the LLM's JSON (when present) is merged on top."""

from __future__ import annotations

import re
from typing import Any

from ..enrich import CVFields
from . import rules, taxonomy
from .llm import LLM

MAX_LLM_CHARS = 7000
_FLUFF = re.compile(
    r"\b(expert|expertise|skills?|abilit(y|ies)|excellent|strong|proven|knowledge|"
    r"experience|oriented|driven|player|thinker|passionate)\b",
    re.I,
)

CV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "current_title": {"type": "string"},
        "city": {"type": "string"},
        "country": {"type": "string"},
        "total_years_experience": {"type": "number"},
        "skills": {"type": "array", "items": {"type": "string"}, "maxItems": 25},
        "domains": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "education": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "summary": {"type": "string"},
    },
    "required": [
        "name",
        "current_title",
        "city",
        "country",
        "total_years_experience",
        "skills",
        "domains",
        "education",
        "summary",
    ],
}

CV_SYSTEM = (
    "You extract facts from a candidate's resume for a recruiter. Return ONLY JSON that matches "
    "the schema. Rules:\n"
    "- name: the candidate's full name, not a company.\n"
    "- current_title: most recent job title.\n"
    "- city/country: where the candidate currently lives or works (most recent), '' if unknown.\n"
    "- total_years_experience: total professional experience in years (number). Use an explicit "
    "statement if present, otherwise compute from job dates up to today; 0 if unknown.\n"
    "- skills: up to 25 concrete hard skills, tools, technologies or functional competencies, "
    "most important first; short canonical names (e.g. 'Python', 'SAP FICO', 'Key Account "
    "Management'). No soft-skill fluff.\n"
    "- domains: up to 4 industries the candidate has actually worked in, only when the resume "
    "names them (an employer's sector, or the products and clients described); [] if unclear.\n"
    "- education: up to 3 highest degrees, short.\n"
    "- summary: a neutral 1-2 sentence professional summary, max 40 words.\n"
    "Never invent facts that are not in the resume."
)


def llm_extract_full(llm: LLM, text: str, filename: str) -> dict[str, Any]:
    """v0.1 prompt (whole resume, also asks for skills). Kept for benchmarking."""
    body = text[:MAX_LLM_CHARS]
    user = f"Resume file name: {filename}\n\nResume text:\n<<<\n{body}\n>>>"
    return llm.json_chat(CV_SYSTEM, user, CV_SCHEMA, max_tokens=450)


# --- compact prompt: ask only for what the rules are weak at --------------------------
HEADER_CHARS = 2500
DATE_LINES_CHARS = 2500

CV_SCHEMA_COMPACT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "current_title": {"type": "string"},
        "city": {"type": "string"},
        "country": {"type": "string"},
        "total_years_experience": {"type": "number"},
        "domains": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "summary": {"type": "string"},
    },
    "required": [
        "name",
        "current_title",
        "city",
        "country",
        "total_years_experience",
        "domains",
        "summary",
    ],
}

CV_SYSTEM_COMPACT = (
    "You read the top of a resume and its job-date lines. Return ONLY JSON:\n"
    "- name: the candidate's full name (a person, not a company or heading).\n"
    "- current_title: the job title of the most recent role (e.g. 'Head of Sales'), never a "
    "section heading, skill list or summary sentence; max 8 words.\n"
    "- city, country: where the candidate lives/works now; '' if unknown.\n"
    "- total_years_experience: number. If the resume states a total ('15+ years of experience') "
    "use it. Otherwise count from the earliest job start date to the latest end date (or today). "
    "Ignore education dates. 0 if unknown.\n"
    "- domains: up to 3 industries the candidate worked in, only when the text names them "
    "(an employer's sector, or the products and clients described); [] if unclear.\n"
    "- summary: one neutral sentence, max 25 words.\n"
    "Never invent facts."
)


def compact_input(text: str) -> str:
    """Resume header (name, title, contact, location live here) + lines with job dates."""
    header = text[:HEADER_CHARS]
    dated: list[str] = []
    used = 0
    for line in text[HEADER_CHARS:].splitlines():
        s = line.strip()
        if not s or len(s) > 200:
            continue
        if rules._RANGE_RX.search(s) or rules._EXPLICIT_YEARS.search(s):
            dated.append(s)
            used += len(s) + 1
            if used > DATE_LINES_CHARS:
                break
    if dated:
        return f"{header}\n…\n[job date lines]\n" + "\n".join(dated)
    return header


def llm_extract(llm: LLM, text: str, filename: str) -> dict[str, Any]:
    user = f"File: {filename}\n<<<\n{compact_input(text)}\n>>>"
    return llm.json_chat(CV_SYSTEM_COMPACT, user, CV_SCHEMA_COMPACT, max_tokens=220)


def _s(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = re.sub(r"\s+", " ", v).strip(" ,;.-")
    return v or None


def _str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [s for s in (_s(x) for x in v) if s]


def grounded_domains(raw: list[str], text: str | None, limit: int) -> list[str]:
    """Canonical industries from an LLM answer, keeping only those the text supports.

    Small models copy industries from a prompt's examples or guess them from a job title, so an
    LLM industry is kept only when at least one of that industry's keywords appears in the text.
    Without a text nothing can be checked, and every recognised industry is kept."""
    dm = taxonomy.domains()
    support = dm.score(text) if text else None
    out: list[str] = []
    for r in raw:
        d = dm.canonicalize(r)
        if d and d not in out and (support is None or d in support):
            out.append(d)
    return out[:limit]


def merge(rule: CVFields, llm_json: dict[str, Any] | None, text: str | None = None) -> CVFields:
    """Combine rule-based fields with the LLM's JSON. Deterministic, so it is safe to re-run.
    Given the resume `text`, LLM industries that the text doesn't support are dropped."""
    if not llm_json:
        return rule
    tax = taxonomy.skills()
    gz = taxonomy.gazetteer()

    name = _s(llm_json.get("name"))
    if not name or len(name.split()) > 5 or any(ch.isdigit() for ch in name) or "@" in name:
        name = rule.name

    title = _s(llm_json.get("current_title")) or rule.title
    if title and len(title) > 90:
        title = title[:90]

    city, country = gz.normalize(_s(llm_json.get("city")), _s(llm_json.get("country")))
    if not city and not country:
        city, country = rule.city, rule.country

    years = llm_json.get("total_years_experience")
    try:
        years_f = float(years) if years is not None else None
    except (TypeError, ValueError):
        years_f = None
    if years_f is None or not (0 < years_f <= 50):
        years_f = rule.years_exp
    else:
        years_f = round(years_f, 1)

    skills: list[str] = []
    seen: set[str] = set()
    for raw in _str_list(llm_json.get("skills")):
        canon = tax.canonicalize(raw)
        if canon is None:
            # keep unknown-but-concrete tools ("Veeva Vault", "Kisssoft"); drop wordy fluff
            if not (2 <= len(raw) <= 32) or len(raw.split()) > 3 or _FLUFF.search(raw):
                continue
            canon = raw if not raw.islower() else raw.title()
        if canon.lower() not in seen:
            seen.add(canon.lower())
            skills.append(canon)
    for s in rule.skills:
        if s.lower() not in seen:
            seen.add(s.lower())
            skills.append(s)

    domains = grounded_domains(_str_list(llm_json.get("domains")), text, 4)
    for d in rule.domains:
        if d not in domains:
            domains.append(d)

    education = _str_list(llm_json.get("education"))[:3] or rule.education
    summary = _s(llm_json.get("summary")) or rule.summary

    return CVFields(
        name=name,
        email=rule.email,
        phone=rule.phone,
        city=city,
        country=country,
        location=rules.format_location(city, country),
        years_exp=years_f,
        title=title,
        skills=skills[:60],
        domains=domains[:4],
        education=education,
        summary=summary,
        extractor="llm",
    )
