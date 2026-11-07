"""Deterministic, fast field extraction (no LLM). Runs for every resume.

The LLM refines these fields later. If Ollama is unavailable, these are the final values.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path

from ..enrich import CVFields
from . import taxonomy

EMAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RX = re.compile(r"(?<![\w/])(\+?\d[\d\s().\-]{7,17}\d)(?![\w/])")

_NAME_STOP = re.compile(
    r"\b(resume|résumé|curriculum|vitae|cv|profile|email|e-mail|phone|mobile|tel|address|"
    r"summary|objective|page|linkedin|contact|career|professional|experience|skills|"
    r"education|personal|details|declaration|references?|about|engagement|services|"
    r"consultancy|consulting|limited|ltd|pvt|inc|llc|technologies|solutions|systems|bank|"
    r"group|company|university|college|institute|school|management|customer|sales|"
    r"business|marketing|operations|technology|digital|global|international|private|"
    r"confidential|core|key|highlights|achievements|competencies|expertise)\b",
    re.I,
)
_FILENAME_NOISE = re.compile(
    r"\b(resume|résumé|cv|curriculum|vitae|updated|update|latest|new|final|profile|copy|"
    r"version|v\d+|draft|doc|docx|pdf|naukri|linkedin|\d+)\b",
    re.I,
)
_FILE_ROLE = re.compile(
    r"\b(jd|job|description|supply|chain|cvm|crm|noc|role|position|opening|vacancy|"
    r"candidate|profiles?|consultant|au|uk|us|uae|ksa|india)\b",
    re.I,
)
_TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|director|head|lead|leader|analyst|consultant|architect|"
    r"officer|specialist|executive|president|vp|vice president|administrator|scientist|"
    r"designer|coordinator|supervisor|associate|advisor|adviser|strategist|accountant|"
    r"controller|auditor|recruiter|planner|expert|owner|founder|partner|cxo|ceo|cfo|cto|coo|"
    r"cmo|cio|chief|tester|programmer|technician|representative|agent)\b",
    re.I,
)
_SECTION = re.compile(
    r"^\s*(professional\s+)?(summary|profile|objective|career objective|about me|"
    r"professional profile|executive summary|career summary)\s*:?\s*$",
    re.I,
)
_DEGREE = re.compile(
    r"\b(b\.?\s?tech|m\.?\s?tech|b\.?\s?e\b|m\.?\s?e\b|b\.?\s?sc|m\.?\s?sc|bca|mca|mba|pgdm|"
    r"pgdba|b\.?\s?com|m\.?\s?com|b\.?\s?a\b|m\.?\s?a\b|bba|ph\.?\s?d|doctorate|bachelor'?s?|"
    r"master'?s?|diploma|ca\b|cfa|acca|llb|llm|md\b|mbbs)\b",
    re.I,
)

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"  # noqa: E501
_DATE = rf"(?:{_MON}[\s.,'’\-]*(\d{{2,4}})|(\d{{1,2}})[/\-.](\d{{4}})|(\d{{4}}))"
_PRESENT = r"(present|current|currently|till\s+date|to\s+date|date|now|ongoing|today)"
_RANGE_RX = re.compile(rf"{_DATE}\s*(?:-|–|—|to|till|until)\s*(?:{_DATE}|{_PRESENT})", re.I)
_EXPLICIT_YEARS = re.compile(
    r"(\d{1,2}(?:\.\d{1,2})?)\s*\+?\s*(?:years?|yrs?)\.?\s*(?:\+\s*)?"
    r"(?:of\s+)?(?:\w+\s+){0,4}?(?:experience|exp\b|expertise)",
    re.I,
)
_EXPLICIT_YEARS_2 = re.compile(
    r"(?:experience|exp)\s*(?:of|:)?\s*(?:over|more than|about|around|nearly)?\s*"
    r"(\d{1,2}(?:\.\d{1,2})?)\s*\+?\s*(?:years?|yrs?)",
    re.I,
)
_OVER_YEARS = re.compile(
    r"(?:over|more than|nearly|around|almost)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I
)


# ---------------------------------------------------------------------------
def _clean_lines(text: str, n: int | None = None) -> list[str]:
    lines = [ln.strip(" \t•·|-–—*:") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return lines[:n] if n else lines


def _looks_like_name(line: str) -> bool:
    if len(line) > 40 or any(ch.isdigit() for ch in line) or "@" in line:
        return False
    if _NAME_STOP.search(line) or _TITLE_WORDS.search(line):
        return False
    words = [w for w in re.split(r"\s+", line) if w]
    if not 2 <= len(words) <= 4:
        return False
    for w in words:
        core = w.strip(".,")
        if not core:
            return False
        if not (core[0].isupper() or core.isupper()):
            return False
        if not re.fullmatch(r"[A-Za-zÀ-ÿ'.\-]+", core):
            return False
    return True


def _smart_title(s: str) -> str:
    return " ".join(w if (len(w) <= 3 and w.endswith(".")) else w.capitalize() for w in s.split())


def name_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    stem = re.sub(r"[_\-+.()\[\]]+", " ", stem)
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)  # JohnSmith -> John Smith
    stem = _FILENAME_NOISE.sub(" ", stem)
    words = [w for w in stem.split() if w.isalpha() and len(w) > 1]
    if not 1 <= len(words) <= 4:
        return None
    joined = " ".join(words)
    if _NAME_STOP.search(joined) or _TITLE_WORDS.search(joined) or _FILE_ROLE.search(joined):
        return None  # "Supply_Chain_Head.pdf", "JD CVM Head.docx" are roles, not people
    return _smart_title(joined)


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{2,}", s.lower())}


def extract_name(text: str, filename: str) -> str | None:
    """Prefer a name line from the top of the resume that agrees with the filename.

    Filenames are usually "<Name>_Resume.pdf", so a text candidate that shares no token
    with a two-or-more-word filename name is probably a heading or company, not the person.
    """
    from_file = name_from_filename(filename)
    file_tokens = _tokens(from_file or "")
    first_plausible: str | None = None
    for line in _clean_lines(text, 10):
        cand = line.split("|")[0].split(",")[0].strip()
        if not _looks_like_name(cand):
            continue
        cand = _smart_title(cand) if cand.isupper() else cand
        if not file_tokens or _tokens(cand) & file_tokens:
            return cand
        # filename tokens glued together ("DeepaGaneshKumar") still count as agreement
        glued = re.sub(r"[^a-z]", "", (from_file or "").lower())
        if any(len(t) >= 4 and (t in glued or glued in t) for t in _tokens(cand)):
            return from_file  # same name, but the filename version has proper spacing
        first_plausible = first_plausible or cand
    if from_file and len(from_file.split()) >= 2:
        return from_file
    return first_plausible or from_file


def extract_title(text: str, name: str | None) -> str | None:
    for line in _clean_lines(text, 15):
        for seg in re.split(r"\s*[|•·]\s*|\s{3,}", line):
            seg = seg.strip(" ,;")
            if not seg or (name and seg.lower() == name.lower()):
                continue
            if len(seg) > 70 or "@" in seg or _SECTION.match(seg):
                continue
            if _TITLE_WORDS.search(seg) and not re.search(r"\d{4}", seg):
                return seg[0].upper() + seg[1:]
    return None


def _year(y: str) -> int | None:
    v = int(y)
    if v < 100:
        v += 2000 if v <= (date.today().year % 100) + 1 else 1900
    return v if 1960 <= v <= date.today().year + 1 else None


def _parse_date(groups: tuple[str | None, ...]) -> float | None:
    mon, y1, num_m, y2, y3 = groups
    if mon and y1:
        y = _year(y1)
        m = _MONTHS.get(mon.lower()[:4].rstrip(".")) or _MONTHS.get(mon.lower()[:3], 1)
        return y + (m - 1) / 12 if y else None
    if num_m and y2:
        y = _year(y2)
        m = int(num_m)
        return y + (min(max(m, 1), 12) - 1) / 12 if y else None
    if y3:
        y = _year(y3)
        return float(y) if y else None
    return None


def years_from_ranges(text: str) -> float | None:
    today = date.today()
    now = today.year + (today.month - 1) / 12
    intervals: list[tuple[float, float]] = []
    for m in _RANGE_RX.finditer(text):
        g = m.groups()
        start = _parse_date(g[0:5])
        end = now if g[10] else _parse_date(g[5:10])
        if start is None or end is None:
            continue
        if g[4] and g[9] and not g[10]:  # bare "2014 - 2016": count whole years
            end += 1 / 12
        if not (0 < end - start <= 45) or end > now + 0.1:
            continue
        intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total = sum(e - s for s, e in merged)
    return round(total, 1) if total >= 0.25 else None


def explicit_years(text: str) -> float | None:
    vals: list[float] = []
    for rx in (_EXPLICIT_YEARS, _EXPLICIT_YEARS_2, _OVER_YEARS):
        for m in rx.finditer(text[:6000]):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if 0.5 <= v <= 45:
                vals.append(v)
    return max(vals) if vals else None


def extract_years(text: str) -> float | None:
    exp = explicit_years(text)
    if exp is not None:
        return exp
    return years_from_ranges(text)


def extract_location(text: str) -> tuple[str | None, str | None]:
    gz = taxonomy.gazetteer()
    head = text[:1500]
    cities = gz.find_cities(head)
    if cities:
        city = min(cities)[1]
        return city, gz.city_country.get(city)
    cities = gz.find_cities(text)
    if cities:
        city = Counter(c for _, c in cities).most_common(1)[0][0]
        return city, gz.city_country.get(city)
    countries = gz.find_countries(head) or gz.find_countries(text)
    if countries:
        return None, Counter(c for _, c in countries).most_common(1)[0][0]
    return None, None


def extract_skills(text: str, limit: int = 60) -> list[str]:
    tax = taxonomy.skills()
    counts = tax.find(text)
    first = tax.first_positions(text)
    ranked = sorted(counts, key=lambda s: (-counts[s], first.get(s, 1 << 30)))
    return ranked[:limit]


def extract_domains(text: str, title: str | None = None, limit: int = 3) -> list[str]:
    scores = taxonomy.domains().score(text)
    title_hits = taxonomy.domains().score(title) if title else {}
    picked = []
    for name, (distinct, total) in scores.items():
        if (distinct >= 2 and total >= 4) or name in title_hits:
            picked.append((total + 5 * (name in title_hits), name))
    picked.sort(reverse=True)
    return [n for _, n in picked[:limit]]


def extract_summary(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines[:60]):
        if _SECTION.match(line):
            body = []
            for nxt in lines[i + 1 : i + 12]:
                s = nxt.strip()
                if not s:
                    if body:
                        break
                    continue
                if s.isupper() and len(s) < 40:  # the next section heading
                    break
                body.append(s)
            summary = " ".join(body)
            if len(summary) > 40:
                return summary[:400].rsplit(" ", 1)[0] + ("…" if len(summary) > 400 else "")
    return None


def extract_education(text: str, limit: int = 4) -> list[str]:
    out: list[str] = []
    for line in _clean_lines(text):
        if len(line) <= 160 and _DEGREE.search(line) and line not in out:
            out.append(line)
            if len(out) >= limit:
                break
    return out


def extract_contacts(text: str) -> tuple[str | None, str | None]:
    em = EMAIL_RX.search(text)
    phone = None
    for m in PHONE_RX.finditer(text[:3000]):
        digits = re.sub(r"\D", "", m.group(1))
        if 9 <= len(digits) <= 15 and not re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
            phone = re.sub(r"\s+", " ", m.group(1)).strip()
            break
    return (em.group(0).lower() if em else None), phone


def format_location(city: str | None, country: str | None) -> str | None:
    if city and country and city != country:
        return f"{city}, {country}"
    return city or country


def extract(text: str, filename: str) -> CVFields:
    name = extract_name(text, filename)
    title = extract_title(text, name)
    city, country = extract_location(text)
    email, phone = extract_contacts(text)
    return CVFields(
        name=name,
        email=email,
        phone=phone,
        city=city,
        country=country,
        location=format_location(city, country),
        years_exp=extract_years(text),
        title=title,
        skills=extract_skills(text),
        domains=extract_domains(text, title),
        education=extract_education(text),
        summary=extract_summary(text),
        extractor="rules",
    )
