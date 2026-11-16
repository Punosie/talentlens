# Gold-standard rubric (Opus 5.5)

This rubric is used for every judgement in the TalentLens benchmark: the Opus gold rankings, the local-model judging task (Task C) and the distillation labels. The gold files themselves contain real names and are kept outside git (`%LOCALAPPDATA%\TalentLens\benchmarks\gold\JDxx\`). Only this rubric and anonymised metrics are committed.

## 1. Gold requirements (`gold_requirements.json`)
Same shape as TalentLens `Requirements`, plus `education` and `role_family`:

| Field | Rule |
|---|---|
| `title` | The title as written in the JD (cleaned of codes such as "L10" only if they are noise). |
| `role_family` | What the job really is, in a few words (e.g. "QE transformation / test-automation architecture leadership"). This can differ from the title. |
| `must_have_skills` | Concrete skills/competencies the JD makes mandatory, max 12, most important first. Canonical taxonomy names where one exists (`taxonomy.skills().canonicalize`); otherwise the JD's own short wording. Never broaden a concrete tool into a vague phrase. |
| `nice_to_have_skills` | Stated as preferred / plus / good-to-have, max 10. |
| `min_years` | The stated minimum total experience. A range "8 to 12" gives 8. Null if not stated. Domain-specific minimums ("8+ in cards") are noted in `summary`, not here. |
| `max_years` | Only when the JD states an upper bound ("3 to 5 years", "no one over 7"). Otherwise null. |
| `locations` | Canonical cities, else countries, only when the JD states where the job is. |
| `domains` | Industries named or clearly implied by the JD, using `domains.txt` names. |
| `education` | Degree requirement if stated. |
| `summary` | One sentence describing the ideal candidate. |

## 2. Candidate grades (0–3)
Judge the **person's actual career** (titles held, what they did, for how long) against the **role family, seniority and hard constraints** first, and the skill list second. A profile that lists the right keywords but has held the wrong kind of job is not a fit.

| Grade | Meaning | Typical evidence |
|---|---|---|
| **3 – strong fit** | Would be put forward to the client today. | Right role family in recent roles (last ~5 years); seniority matches; meets every stated hard constraint (min years, location/right-to-work when the JD says it is strict); covers most must-haves, with evidence in their experience, not only in the skills list; domain matches when the JD stresses it. |
| **2 – good fit** | Worth a recruiter call. | Right role family and seniority, but with notable gaps: several must-haves missing, domain missing, slightly short on years (within ~2 years of a soft minimum), or a location that is near but not exact when the JD allows it. |
| **1 – partial / adjacent** | Long-shot; only if the pool is thin. | Adjacent family (e.g. test manager for a hands-on SDET role, developer for an SDET role, project manager for a program director role), or right family but clearly too junior or senior, or failing a soft constraint badly. |
| **0 – not relevant** | Not worth a call. | Different role family; or fails a **hard** constraint (JD says "firm", "will not be considered", "only candidates based in…", "no one over N years"); or the profile has too little information to judge. |

### Hard constraints (cap the grade)
- **Strict minimum years** (the JD says firm/strict/"will not be considered"): below the minimum → max grade 0 if more than 2 years short, max 1 otherwise.
- **Soft minimum years** ("12+ years"): 1–3 years short → at most 2. More than 3 years short → at most 1.
- **Stated maximum years** ("3 to 5", "not over 7"): more than 2 years above the stated maximum → at most 1. Beyond an explicit cut-off → 0.
- **Location stated as strict** ("only candidates based in the UAE/GCC", "must have right to work in the UK"): outside it → at most 1 (0 if the role is onsite-only and the person is on another continent with no link to the region).
- **Location stated but not strict**: being elsewhere lowers the grade by at most one step, and only when the JD expects onsite presence.
- Years of experience come from the profile's career dates (`years_exp` is a computed estimate; check it against the experience list when close to a threshold).

### Role family over title
The JD title can mislead (JD01 "Enterprise Architect" is really QE-transformation leadership; JD05 "Digital Champion" is really a cloud solution architect). Always grade against the `role_family` in the gold requirements.

### Consistency rules
- Judge each candidate independently against the rubric. Do not grade on a curve within a batch.
- Evidence must quote or paraphrase the profile (title, company type, years, concrete skills). Gaps name the missing must-haves or failed constraints.
- When the profile is sparse (only a title), grade on the title and years alone, and never above 2.
- Ties in the final ranking are broken by (a) how many must-haves have experience evidence, (b) recency of the role-family match, (c) seniority fit.

## 3. Ranking output (`gold_ranking.json`)
- `top20`: the 20 best judged candidates in order (grade first, then the tie-break rules above).
- `judged`: every judged candidate, as `{id, grade, evidence, gaps}`. `id` is the TalentLens snapshot row id; names are attached only in the private copy.
- `pool`: how the candidate pool was built (queries and system runs) and its size.
- `timing`: Opus wall-clock minutes for this JD.

## 4. Metrics derived from the gold
- nDCG@10 uses gain `2^grade − 1` over the system's top 10. Candidates the gold has not judged are judged later with this same rubric (pooling top-up), so no system is scored against unjudged people.
- P@10 is the share of the top 10 with grade ≥ 2.
- Recall@25 is the share of all grade-≥2 gold candidates that appear in the top 25.
- MRR is the reciprocal rank of the first grade-3 candidate (grade 2 if the JD has no grade 3).
