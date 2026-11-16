# ruff: noqa: E501  (prompt text: long lines are intentional)
"""Benchmark prompts: JD extraction (Task A) and candidate judging (Task C).

The few-shot examples are fictional and written for this benchmark; none is taken from or
paraphrases a benchmark JD or a real profile.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------- Task A: JD extraction
JD_SCHEMA_V2: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "role_family": {"type": "string"},
        "must_have_skills": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "nice_to_have_skills": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "min_years": {"type": ["number", "null"]},
        "max_years": {"type": ["number", "null"]},
        "locations": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "domains": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "summary": {"type": "string"},
    },
    "required": [
        "title",
        "role_family",
        "must_have_skills",
        "nice_to_have_skills",
        "min_years",
        "max_years",
        "locations",
        "domains",
        "summary",
    ],
}

JD_SYSTEM_V2 = """You extract structured hiring requirements from a job description for a recruiter. Return ONLY JSON matching the schema.

Rules:
- title: the job title exactly as the JD states it.
- role_family: what the job really is in a few words, judged from the responsibilities, not the title (a title like "Champion" or "Architect" can hide a different job).
- must_have_skills: up to 12 concrete skills, tools, technologies or competencies the JD makes mandatory, most important first. Keep concrete names exactly (e.g. "Playwright", "TypeScript", "Rest Assured", "Terraform", "ISO 8583"); never replace a named tool with a vague category.
- nice_to_have_skills: up to 10 items the JD marks as preferred, a plus, good to have, or desirable.
- min_years: the minimum total years of experience the JD states. A range "8 to 12 years" gives 8. null if no number is stated.
- max_years: ONLY when the JD states an upper limit (a range like "3 to 5 years" or "no more than 7 years"). Otherwise null. Never guess one.
- locations: cities (or countries if no city) where the job is based, as stated. [] if not stated.
- domains: up to 3 industries the JD names or clearly targets (e.g. "Banking & Financial Services", "Insurance"). [] if none. Never add an industry the JD does not mention.
- summary: one sentence describing the ideal candidate, max 35 words.
Everything must be supported by the JD text. Do not invent requirements."""

# app's current prompt/schema is imported from talentlens.jd for the "as shipped" baseline


def jd_user(text: str, max_chars: int = 12000) -> str:
    return f"Job description:\n<<<\n{text[:max_chars]}\n>>>"


# ---------------------------------------------------------------- Task C: candidate judging
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grade": {"type": "integer", "minimum": 0, "maximum": 3},
        "reason": {"type": "string"},
    },
    "required": ["grade", "reason"],
}
JUDGE_SCHEMA_COT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "job_role_family": {"type": "string"},
        "candidate_role_family": {"type": "string"},
        "seniority_fit": {"type": "string"},
        "constraints_met": {"type": "string"},
        "grade": {"type": "integer", "minimum": 0, "maximum": 3},
        "reason": {"type": "string"},
    },
    "required": [
        "job_role_family",
        "candidate_role_family",
        "seniority_fit",
        "constraints_met",
        "grade",
        "reason",
    ],
}

RUBRIC_SHORT = """Grade how well the candidate fits the job, judging their actual career (job titles held, what they did, for how long) against the real role family, seniority and hard constraints first, and the skill list second. Keywords in a skills list are weak evidence; held roles are strong evidence.
3 = strong fit: right role family in recent roles, right seniority, meets every stated hard constraint (minimum years, required location / right to work when the JD says it is strict), most must-haves evidenced in their experience.
2 = good fit: right role family and seniority but notable gaps (several must-haves missing, domain missing, slightly short on years, or near but not exact location).
1 = partial: adjacent role family (e.g. test manager for a hands-on automation role, developer for a tester role, project manager for a program director role), clearly too junior or too senior, or badly missing a soft constraint.
0 = not relevant: different role family, or fails a hard constraint the JD calls strict (e.g. "firm minimum", "only candidates based in", "not over N years"), or too little information.
If the JD title looks misleading, grade against what the job really does."""

JUDGE_SYSTEM = (
    "You are an expert technical recruiter screening candidates for a job. "
    "Return ONLY JSON matching the schema.\n\n"
    + RUBRIC_SHORT
    + "\n\nreason: one short line (max 25 words) citing the decisive evidence or gap."
)

JUDGE_SYSTEM_COT = (
    "You are an expert technical recruiter screening candidates for a job. "
    "Return ONLY JSON matching the schema. Fill the fields in order: first state the job's real role "
    "family, then the candidate's role family from their recent titles, then whether their years and "
    "seniority fit, then whether they meet the hard constraints, and only then the grade.\n\n"
    + RUBRIC_SHORT
    + "\n\nreason: one short line (max 25 words)."
)

FEWSHOT = [
    {
        "job": "Senior Payroll Manager (UK), 10+ years, must be UK-based; leads a payroll team of 12; "
        "ADP, multi-country payroll, statutory reporting; nice: Workday.",
        "candidate": "Title: Payroll Lead | Years: 13 | Location: Manchester, United Kingdom\n"
        "Payroll Lead at a retail group (5 yrs) managing 9 payroll specialists across UK and "
        "Ireland on ADP; before that Payroll Analyst (8 yrs).",
        "out": {
            "grade": 3,
            "reason": "UK payroll lead, 13 yrs, runs a team on ADP across two countries; matches family, seniority, location.",
        },
    },
    {
        "job": "Senior Payroll Manager (UK), 10+ years, must be UK-based; leads a payroll team of 12; "
        "ADP, multi-country payroll, statutory reporting; nice: Workday.",
        "candidate": "Title: HR Business Partner | Years: 15 | Location: London, United Kingdom\n"
        "HRBP for a bank's technology division; employee relations, workforce planning; "
        "skills list includes Payroll, ADP, Workday.",
        "out": {
            "grade": 1,
            "reason": "HR business partner, not a payroll role; payroll appears only as a listed skill.",
        },
    },
    {
        "job": "Junior Mobile Developer (Flutter), 1-3 years, Singapore only.",
        "candidate": "Title: Principal Mobile Architect | Years: 16 | Location: Austin, United States\n"
        "Leads mobile architecture for a fintech; Flutter, Kotlin, Swift; manages 20 engineers.",
        "out": {
            "grade": 0,
            "reason": "Far too senior for a 1-3 year junior role and outside Singapore (strict).",
        },
    },
]


def fewshot_block() -> str:
    parts = ["Examples (fictional, for calibration):"]
    for ex in FEWSHOT:
        parts.append(
            f"JOB: {ex['job']}\nCANDIDATE:\n{ex['candidate']}\nANSWER: {json.dumps(ex['out'])}"
        )
    return "\n\n".join(parts)


def judge_user(
    jd_text: str, card_text: str, jd_chars: int = 5000, with_fewshot: bool = False
) -> str:
    head = (fewshot_block() + "\n\nNow grade this one.\n\n") if with_fewshot else ""
    return f"{head}JOB DESCRIPTION:\n<<<\n{jd_text[:jd_chars]}\n>>>\n\nCANDIDATE PROFILE:\n<<<\n{card_text}\n>>>"


LISTWISE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "grade": {"type": "integer", "minimum": 0, "maximum": 3},
                    "reason": {"type": "string"},
                },
                "required": ["id", "grade", "reason"],
            },
        }
    },
    "required": ["grades"],
}


def listwise_user(jd_text: str, cards: list[tuple[int, str]], jd_chars: int = 5000) -> str:
    body = "\n\n".join(f"CANDIDATE id={cid}:\n<<<\n{txt}\n>>>" for cid, txt in cards)
    return (
        f"JOB DESCRIPTION:\n<<<\n{jd_text[:jd_chars]}\n>>>\n\n"
        f"Grade each of these {len(cards)} candidates independently (do not grade on a curve).\n\n{body}"
    )
