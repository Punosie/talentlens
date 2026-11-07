from talentlens.ai.extract import merge
from talentlens.enrich import CVFields


def _rule() -> CVFields:
    return CVFields(
        name="Rule Name",
        email="r@example.com",
        city="Pune",
        country="India",
        location="Pune, India",
        years_exp=4.0,
        title="Engineer",
        skills=["Python", "SQL"],
        domains=["Retail"],
        extractor="rules",
    )


def test_llm_values_win_but_are_normalised() -> None:
    f = merge(
        _rule(),
        {
            "name": "Priya Sharma",
            "current_title": "Lead Data Engineer",
            "city": "Bangalore",
            "country": "",
            "total_years_experience": 8.04,
            "skills": [
                "k8s",
                "python",
                "Some Niche Tool",
                "a",
                "this is far too long to be a skill name",
            ],
            "domains": ["banking"],
            "education": ["B.Tech"],
            "summary": "Data engineer.",
        },
    )
    assert f.name == "Priya Sharma"
    assert (f.city, f.country, f.location) == ("Bengaluru", "India", "Bengaluru, India")
    assert f.years_exp == 8.0
    assert f.skills[:3] == ["Kubernetes", "Python", "Some Niche Tool"]
    assert "SQL" in f.skills  # rule skills are kept
    assert f.domains == ["Banking & Financial Services", "Retail"]
    assert f.email == "r@example.com"
    assert f.extractor == "llm"


def test_bad_llm_values_fall_back_to_rules() -> None:
    f = merge(
        _rule(),
        {
            "name": "Curriculum Vitae 2024 of the candidate",
            "current_title": "",
            "city": "",
            "country": "",
            "total_years_experience": 99,
            "skills": [],
            "domains": [],
            "education": [],
            "summary": "",
        },
    )
    assert f.name == "Rule Name"
    assert f.title == "Engineer"
    assert (f.city, f.country) == ("Pune", "India")
    assert f.years_exp == 4.0


def test_no_llm_json_returns_rules() -> None:
    r = _rule()
    assert merge(r, None) is r
