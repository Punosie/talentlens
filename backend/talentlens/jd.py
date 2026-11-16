"""Job-description understanding: rules produce instant requirements; the LLM refines them."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .ai import rules, taxonomy
from .ai.extract import _s, _str_list
from .ai.llm import LLM

MAX_JD_CHARS = 8000

_NICE_HDR = re.compile(
    r"(nice[\s\-]to[\s\-]have|good[\s\-]to[\s\-]have|preferred|desirable|desired|bonus|"
    r"plus|advantage|optional|would be great)",
    re.I,
)
_MUST_HDR = re.compile(
    r"(must[\s\-]have|must|required|requirements?|mandatory|essential|qualifications?|"
    r"key skills|what you('|’)ll need|you have|skills)",
    re.I,
)
_RANGE_YEARS = re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I)
_MIN_YEARS = re.compile(
    r"(?:minimum|min\.?|at least|over|more than)?\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I
)


@dataclass
class Requirements:
    title: str | None = None
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    min_years: float | None = None
    max_years: float | None = None
    locations: list[str] = field(default_factory=list)  # canonical cities and/or countries
    domains: list[str] = field(default_factory=list)
    summary: str | None = None
    source: str = "rules"  # rules | llm
    role_family: str | None = None  # what the job really is (can differ from a misleading title)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Requirements:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    def query_text(self) -> str:
        """Compact text used for embedding / reranking against resumes."""
        parts = [
            self.role_family or "",
            self.title or "",
            f"{self.min_years:g}+ years experience" if self.min_years else "",
            ("Required: " + ", ".join(self.must_have_skills)) if self.must_have_skills else "",
            ("Nice to have: " + ", ".join(self.nice_to_have_skills))
            if self.nice_to_have_skills
            else "",
            ("Industry: " + ", ".join(self.domains)) if self.domains else "",
            ("Location: " + ", ".join(self.locations)) if self.locations else "",
            self.summary or "",
        ]
        return ". ".join(p for p in parts if p)


def _split_sections(text: str) -> tuple[str, str]:
    """Return (must-ish text, nice-to-have text) based on headings / line cues."""
    must: list[str] = []
    nice: list[str] = []
    mode = "must"
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        short = len(s) < 60
        if short and _NICE_HDR.search(s):
            mode = "nice"
        elif short and _MUST_HDR.search(s):
            mode = "must"
        (nice if mode == "nice" or (not short and _NICE_HDR.search(s)) else must).append(s)
    return "\n".join(must), "\n".join(nice)


def _years(text: str) -> tuple[float | None, float | None]:
    head = text[:MAX_JD_CHARS]
    m = _RANGE_YEARS.search(head)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if 0 < lo <= hi <= 45:
            return lo, hi
    vals = [float(x) for x in _MIN_YEARS.findall(head) if 0 < float(x) <= 40]
    return (min(vals), None) if vals else (None, None)


def _locations(text: str) -> list[str]:
    gz = taxonomy.gazetteer()
    cities = gz.find_cities(text[:3000])
    if cities:
        seen: list[str] = []
        for _, c in sorted(cities):
            if c not in seen:
                seen.append(c)
        return seen[:3]
    countries = gz.find_countries(text[:3000])
    out: list[str] = []
    for _, c in countries:
        if c not in out:
            out.append(c)
    return out[:2]


def parse_rules(text: str) -> Requirements:
    text = text[:MAX_JD_CHARS]
    must_txt, nice_txt = _split_sections(text)
    must = rules.extract_skills(must_txt or text, limit=15)
    nice = [s for s in rules.extract_skills(nice_txt, limit=10) if s not in must]
    lo, hi = _years(text)
    title = rules.extract_title(text, None)
    return Requirements(
        title=title,
        must_have_skills=must[:12],
        nice_to_have_skills=nice[:10],
        min_years=lo,
        max_years=hi,
        locations=_locations(text),
        domains=rules.extract_domains(text, title, limit=2),
        summary=None,
        source="rules",
    )


JD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "must_have_skills": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "nice_to_have_skills": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "min_years": {"type": "number"},
        "max_years": {"type": "number"},
        "city": {"type": "string"},
        "country": {"type": "string"},
        "domains": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "summary": {"type": "string"},
    },
    "required": [
        "title",
        "must_have_skills",
        "nice_to_have_skills",
        "min_years",
        "max_years",
        "city",
        "country",
        "domains",
        "summary",
    ],
}

JD_SYSTEM = (
    "You read a job description for a recruiter and return ONLY JSON matching the schema.\n"
    "- title: the role title.\n"
    "- must_have_skills: up to 12 essential hard skills / competencies, short canonical names.\n"
    "- nice_to_have_skills: up to 10 preferred but optional skills.\n"
    "- min_years / max_years: required experience range in years; 0 when not stated.\n"
    "- city / country: job location; '' if not stated or fully remote.\n"
    "- domains: up to 3 industries the role is in (e.g. 'Telecommunications', 'Retail').\n"
    "- summary: one sentence describing the ideal candidate, max 35 words.\n"
    "Do not invent requirements that are not in the text."
)


_UPPER_YEARS = re.compile(
    r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)"
    r"|(?:not|no)\s+(?:more|over)\s+(?:than\s+)?(\d{1,2})\s*(?:years?|yrs?)"
    r"|(?:up to|maximum(?: of)?|max\.?|at most)\s*(\d{1,2})\s*(?:years?|yrs?)"
    r"|more than\s+(\d{1,2})\s*(?:years?|yrs?)\s+of\s+experience\s+(?:will not|won't)",
    re.I,
)


def stated_max_years(text: str) -> float | None:
    """An upper experience bound the JD actually states, or None."""
    for m in _UPPER_YEARS.finditer(text[:MAX_JD_CHARS]):
        if m.group(1) and m.group(2):
            lo, hi = float(m.group(1)), float(m.group(2))
            if 0 < lo <= hi <= 45:
                return hi
        for g in (m.group(3), m.group(4), m.group(5)):
            if g and 0 < float(g) <= 45:
                return float(g)
    return None


def normalize_location(raw: str) -> str | None:
    """Free text ("Pune, India", "UAE", "New York metro area") -> canonical city, else country.
    Unknown places are kept as written; 'remote' / 'anywhere' are dropped."""
    s = raw.strip()
    if not s or re.search(r"\b(remote|anywhere|global|worldwide)\b", s, re.I):
        return None
    gz = taxonomy.gazetteer()
    cities = gz.find_cities(s)
    if cities:
        return cities[0][1]
    country = gz.country_alias.get(re.sub(r"\s+", " ", s.lower()).strip(" ."))
    if country:
        return country
    countries = gz.find_countries(s)
    if countries:
        return countries[0][1]
    return s.split(",")[0].strip().title() or None


def parse_llm(
    llm: LLM,
    text: str,
    fallback: Requirements | None = None,
    *,
    max_tokens: int = 400,
    system: str | None = None,
    schema: dict[str, Any] | None = None,
    max_years_only_if_stated: bool = False,
) -> Requirements:
    base = fallback or parse_rules(text)
    data = llm.json_chat(
        system or JD_SYSTEM,
        f"Job description:\n<<<\n{text[:MAX_JD_CHARS]}\n>>>",
        schema or JD_SCHEMA,
        max_tokens=max_tokens,
    )
    return requirements_from_llm(
        data, text, base, max_years_only_if_stated=max_years_only_if_stated
    )


def requirements_from_llm(
    data: dict[str, Any],
    text: str,
    base: Requirements,
    *,
    max_years_only_if_stated: bool = False,
) -> Requirements:
    """Normalise an LLM's JSON (old city/country schema or the newer locations list) into
    canonical Requirements."""
    tax = taxonomy.skills()
    dm = taxonomy.domains()
    gz = taxonomy.gazetteer()

    def canon_list(values: list[str], limit: int) -> list[str]:
        out: list[str] = []
        for raw in values:
            c = tax.canonicalize(raw) or (raw if 2 <= len(raw) <= 32 else None)
            if c and c.lower() not in {x.lower() for x in out}:
                out.append(c)
        return out[:limit]

    must = canon_list(_str_list(data.get("must_have_skills")), 12) or base.must_have_skills
    nice = [
        s
        for s in canon_list(_str_list(data.get("nice_to_have_skills")), 10)
        if s.lower() not in {m.lower() for m in must}
    ]

    def num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if 0 < f <= 45 else None

    lo, hi = num(data.get("min_years")), num(data.get("max_years"))
    if lo is None:
        lo, hi = base.min_years, base.max_years if hi is None else hi
    if max_years_only_if_stated:
        hi = stated_max_years(text)  # an upper bound only when the JD actually states one
    if lo is not None and hi is not None and hi < lo:
        hi = None

    if isinstance(data.get("locations"), list):
        locations = []
        for raw in _str_list(data.get("locations")):
            val = normalize_location(raw)
            if val and val not in locations:
                locations.append(val)
        locations = locations or base.locations
    else:
        city, country = gz.normalize(_s(data.get("city")), _s(data.get("country")))
        locations = [x for x in (city,) if x] or ([country] if country else []) or base.locations

    domains: list[str] = []
    for raw in _str_list(data.get("domains")):
        d = dm.canonicalize(raw)
        if d and d not in domains:
            domains.append(d)

    return Requirements(
        title=_s(data.get("title")) or base.title,
        must_have_skills=must,
        nice_to_have_skills=nice,
        min_years=lo,
        max_years=hi,
        locations=locations,
        domains=domains or base.domains,
        summary=_s(data.get("summary")),
        source="llm",
        role_family=_s(data.get("role_family")) or None,
    )
