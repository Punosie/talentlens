"""Skills, domain and location dictionaries, plus fast regex matchers built from them."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"

# Tokens may contain + # . / & - (C++, C#, .NET, CI/CD, P&L, Wi-Fi), so boundaries are custom.
_LEFT = r"(?<![\w+#&])"
_RIGHT = r"(?![\w+#&]|\.\w)"


def _alias_pattern(alias: str) -> str:
    parts = [re.escape(p) for p in alias.split()]
    return r"[\s\-]+".join(parts)


def _compile(aliases: list[str], flags: int) -> re.Pattern[str] | None:
    if not aliases:
        return None
    alts = "|".join(_alias_pattern(a) for a in sorted(set(aliases), key=len, reverse=True))
    return re.compile(f"{_LEFT}(?:{alts}){_RIGHT}", flags)


def _norm_key(s: str) -> str:
    return re.sub(r"[\s\-]+", " ", s.strip().lower())


_SPACES = re.compile(r"[\s\-]+")


def _space_key(s: str) -> str:
    return _SPACES.sub(" ", s)


@dataclass(frozen=True)
class Taxonomy:
    canonical: tuple[str, ...]
    alias_ci: dict[str, str]  # normalised lower alias -> canonical
    alias_cs: dict[str, str]  # exact alias -> canonical (case-sensitive)
    rx_ci: re.Pattern[str] | None
    rx_cs: re.Pattern[str] | None

    def find(self, text: str) -> Counter[str]:
        """Count canonical matches in text."""
        counts: Counter[str] = Counter()
        if self.rx_ci:
            for m in self.rx_ci.finditer(text):
                c = self.alias_ci.get(_norm_key(m.group(0)))
                if c:
                    counts[c] += 1
        if self.rx_cs:
            for m in self.rx_cs.finditer(text):
                c = self.alias_cs.get(re.sub(r"[\s\-]+", " ", m.group(0)))
                if c:
                    counts[c] += 1
        return counts

    def find_with_positions(self, text: str) -> tuple[Counter[str], dict[str, int]]:
        """Counts and first position of each canonical skill in ONE pass over the text
        (find() + first_positions() scanned it twice with the large alternation regexes)."""
        counts: Counter[str] = Counter()
        pos: dict[str, int] = {}
        for rx, table, key in (
            (self.rx_ci, self.alias_ci, _norm_key),
            (self.rx_cs, self.alias_cs, _space_key),
        ):
            if rx is None:
                continue
            for m in rx.finditer(text):
                c = table.get(key(m.group(0)))
                if c:
                    counts[c] += 1
                    if c not in pos or m.start() < pos[c]:
                        pos[c] = m.start()
        return counts, pos

    def first_positions(self, text: str) -> dict[str, int]:
        pos: dict[str, int] = {}
        for rx, table, key in (
            (self.rx_ci, self.alias_ci, _norm_key),
            (self.rx_cs, self.alias_cs, lambda s: re.sub(r"[\s\-]+", " ", s)),
        ):
            if rx is None:
                continue
            for m in rx.finditer(text):
                c = table.get(key(m.group(0)))
                if c and c not in pos:
                    pos[c] = m.start()
        return pos

    def canonicalize(self, term: str) -> str | None:
        """Map a free-text term (e.g. from the LLM) onto a canonical name, if known. Cached."""
        cache = self.__dict__.setdefault("_canon_cache", {})
        if term in cache:
            return cache[term]
        out = self._canonicalize(term)
        if len(cache) < 50_000:
            cache[term] = out
        return out

    def _canonicalize(self, term: str) -> str | None:
        t = term.strip()
        if not t:
            return None
        if t in self.alias_cs:
            return self.alias_cs[t]
        k = _norm_key(t)
        if k in self.alias_ci:
            return self.alias_ci[k]
        # Otherwise use the longest alias inside the term:
        # "Project Management Professional (PMP)" -> "PMP", "AWS cloud" -> "Amazon Web Services"
        best: tuple[int, str] | None = None
        for rx, table, key in (
            (self.rx_ci, self.alias_ci, _norm_key),
            (self.rx_cs, self.alias_cs, lambda s: re.sub(r"[\s\-]+", " ", s)),
        ):
            if rx is None:
                continue
            for m in rx.finditer(t):
                c = table.get(key(m.group(0)))
                if c and (best is None or len(m.group(0)) > best[0]):
                    best = (len(m.group(0)), c)
        if best and best[0] >= 0.3 * len(t):
            return best[1]
        return None


def _load_taxonomy(path: Path) -> Taxonomy:
    canonical: list[str] = []
    alias_ci: dict[str, str] = {}
    alias_cs: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        head = parts[0]
        name = head.lstrip("=!")
        canonical.append(name)
        if head.startswith("!"):  # lookup-only canonical name
            parts = parts[1:]
        for alias in parts:
            if alias.startswith("="):
                alias_cs[re.sub(r"\s+", " ", alias[1:])] = name
            else:
                alias_ci.setdefault(_norm_key(alias), name)
    rx_ci = _compile(list(alias_ci), re.IGNORECASE)
    rx_cs = _compile(list(alias_cs), 0)
    # canonicalize() is lenient: any alias, any case, plus every canonical name
    # ("rust" -> "Rust", "aws" -> "Amazon Web Services", "go" -> "Go"), because LLM output
    # is already a skill name and not prose.
    lookup = dict(alias_ci)
    for a, c in alias_cs.items():
        lookup.setdefault(_norm_key(a), c)
    for c in canonical:
        lookup.setdefault(_norm_key(c), c)
    return Taxonomy(tuple(canonical), lookup, alias_cs, rx_ci, rx_cs)


@lru_cache
def skills() -> Taxonomy:
    return _load_taxonomy(DATA / "skills.txt")


# --- domains ----------------------------------------------------------------
_GENERIC_DOMAIN_WORDS = {
    "services",
    "service",
    "management",
    "technology",
    "technologies",
    "goods",
    "sector",
    "public",
    "professional",
    "industry",
    "industrial",
    "products",
    "solutions",
}


@dataclass(frozen=True)
class DomainMatcher:
    names: tuple[str, ...]
    rx: dict[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]]

    def score(self, text: str) -> dict[str, tuple[int, int]]:
        """domain -> (distinct keyword hits, capped total hits)"""
        out: dict[str, tuple[int, int]] = {}
        for name, (ci, cs) in self.rx.items():
            per_kw: Counter[str] = Counter()
            for rx in (ci, cs):
                if rx is None:
                    continue
                for m in rx.finditer(text):
                    per_kw[m.group(0).lower()] += 1
            if per_kw:
                out[name] = (len(per_kw), sum(min(v, 3) for v in per_kw.values()))
        return out

    def canonicalize(self, term: str) -> str | None:
        """Map a free-text industry ("Fintech", "telecom operator") onto a known domain."""
        t = term.strip().lower()
        if not t:
            return None
        for name in self.names:
            if t == name.lower():
                return name
        scores = self.score(term)
        # whole-word overlap with a domain's own name ("banking" -> "Banking & Financial ...")
        words = set(re.findall(r"[a-z]{4,}", t)) - _GENERIC_DOMAIN_WORDS
        best_name, best_key = None, (0, (0, 0))
        for name in self.names:
            overlap = len(
                words & (set(re.findall(r"[a-z]{4,}", name.lower())) - _GENERIC_DOMAIN_WORDS)
            )
            key = (overlap, scores.get(name, (0, 0)))
            if key > best_key:
                best_name, best_key = name, key
        return best_name


@lru_cache
def domains() -> DomainMatcher:
    names: list[str] = []
    rx: dict[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]] = {}
    for raw in (DATA / "domains.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        name, kws = parts[0], parts[1:]
        long_kw = [k for k in kws if len(k) > 3]
        short_kw = sorted({v for k in kws if len(k) <= 3 for v in (k, k.upper())})
        names.append(name)
        rx[name] = (_compile(long_kw, re.IGNORECASE), _compile(short_kw, 0))
    return DomainMatcher(tuple(names), rx)


# --- locations ----------------------------------------------------------------
@dataclass(frozen=True)
class Gazetteer:
    city_country: dict[str, str]  # canonical city -> country
    city_alias: dict[str, str]  # lower alias -> canonical city
    country_alias: dict[str, str]  # lower alias -> canonical country
    rx_city: re.Pattern[str]
    rx_country_ci: re.Pattern[str]
    rx_country_cs: re.Pattern[str] | None
    countries: tuple[str, ...]

    def find_cities(self, text: str) -> list[tuple[int, str]]:
        out = []
        for m in self.rx_city.finditer(text):
            c = self.city_alias.get(_norm_key(m.group(0)))
            if c:
                out.append((m.start(), c))
        return out

    def find_countries(self, text: str) -> list[tuple[int, str]]:
        out = []
        for rx in (self.rx_country_ci, self.rx_country_cs):
            if rx is None:
                continue
            for m in rx.finditer(text):
                c = self.country_alias.get(_norm_key(m.group(0)))
                if c:
                    out.append((m.start(), c))
        out.sort()
        return out

    def normalize(self, city: str | None, country: str | None) -> tuple[str | None, str | None]:
        """Canonicalise free-text city/country (e.g. from the LLM)."""
        c_city = None
        if city:
            c_city = self.city_alias.get(_norm_key(city))
            if c_city is None:
                hits = self.find_cities(city)
                c_city = hits[0][1] if hits else city.strip().title()
        c_country = None
        if country:
            c_country = self.country_alias.get(_norm_key(country))
            if c_country is None:
                hits = self.find_countries(country)
                c_country = hits[0][1] if hits else country.strip().title()
        if c_city and c_city in self.city_country:
            c_country = self.city_country[c_city]
        return c_city, c_country


@lru_cache
def gazetteer() -> Gazetteer:
    city_country: dict[str, str] = {}
    city_alias: dict[str, str] = {}
    country_alias: dict[str, str] = {}
    short_country: list[str] = []
    countries: list[str] = []
    for raw in (DATA / "locations.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "::" not in line:
            continue
        left, right = line.split("::", 1)
        c_parts = [p.strip() for p in left.split("|") if p.strip()]
        country = c_parts[0]
        countries.append(country)
        for a in c_parts:
            if len(a.replace(".", "")) <= 3:
                short_country.append(a)
            country_alias[_norm_key(a)] = country
        for group in right.split(";"):
            names = [p.strip() for p in group.split("|") if p.strip()]
            if not names:
                continue
            city = names[0]
            city_country[city] = country
            for a in names:
                city_alias[_norm_key(a)] = city
    long_country = [a for a in country_alias if a not in {s.lower() for s in short_country}]
    # Short city aliases (KL, NCR, RAK) are matched case-insensitively but need to be upper-case
    rx_city = _compile([a for a in city_alias if len(a) > 3], re.IGNORECASE)
    short_city = [a.upper() for a in city_alias if len(a) <= 3]
    if short_city:
        alts = "|".join(map(re.escape, short_city))
        rx_city = re.compile(f"{rx_city.pattern}|{_LEFT}(?-i:{alts}){_RIGHT}", re.IGNORECASE)
    return Gazetteer(
        city_country,
        city_alias,
        country_alias,
        rx_city,
        _compile(long_country, re.IGNORECASE),  # type: ignore[arg-type]
        _compile(short_country, 0),
        tuple(countries),
    )


# --- free-text location filters ("New Jersey", "NJ", "Bay Area", "Karnataka") ---------------
US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}


@dataclass(frozen=True)
class LocationTerm:
    """How one location filter value matches a CV: exact city/country names, or text patterns
    (SQL LIKE, case-insensitive) on the full written location, which keeps the state/region."""

    exact: tuple[str, ...]
    patterns: tuple[str, ...]


def location_term(value: str) -> LocationTerm:
    raw = " ".join(value.split()).strip(" ,.")
    if not raw:
        return LocationTerm((), ())
    gz = gazetteer()
    exact = {raw}
    key = _norm_key(raw)
    if key in gz.city_alias:
        exact.add(gz.city_alias[key])
    if key in gz.country_alias:
        exact.add(gz.country_alias[key])
    patterns: set[str] = set()
    abbr = raw.upper() if raw.upper() in US_STATES else _STATE_BY_NAME.get(raw.lower())
    if abbr:  # "NJ" or "New Jersey": the state's name or its abbreviation in a written location
        name = US_STATES[abbr]
        patterns |= {f"%{name}%", f"%, {abbr},%", f"%, {abbr}"}
    if len(raw) >= 3:
        patterns.add(f"%{raw}%")
    return LocationTerm(tuple(sorted(exact)), tuple(sorted(patterns)))


def location_matches(value: str, city: str | None, country: str | None, full: str | None) -> bool:
    """Python twin of the SQL filter (search.Filters), used for match scoring."""
    t = location_term(value)
    lower_exact = {e.lower() for e in t.exact}
    if (city and city.lower() in lower_exact) or (country and country.lower() in lower_exact):
        return True
    text = (full or "").lower()
    for p in t.patterns:
        core = p.strip("%").lower()
        if p.endswith("%") and core in text:
            return True
        if not p.endswith("%") and text.endswith(core):
            return True
    return False
