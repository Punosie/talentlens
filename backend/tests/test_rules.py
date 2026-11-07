from datetime import date

import pytest

from talentlens.ai import rules, taxonomy

from .conftest import ALICE, BOB, CAROL


def test_alice_fields() -> None:
    f = rules.extract(ALICE, "Alice_Example_Resume.pdf")
    assert f.name == "Alice Example"
    assert f.email == "alice@example.com"
    assert f.phone and f.phone.replace(" ", "").endswith("9876543210")
    assert (f.city, f.country) == ("Bengaluru", "India")
    assert f.years_exp == 7
    assert f.title == "Senior Data Engineer"
    for s in (
        "Python",
        "Apache Spark",
        "Apache Airflow",
        "SQL",
        "Amazon Web Services",
        "Kubernetes",
    ):
        assert s in f.skills
    assert "Banking & Financial Services" in f.domains


def test_bob_and_carol() -> None:
    b = rules.extract(BOB, "Bob Sample CV.docx")
    assert b.name == "Bob Sample"
    assert (b.city, b.country) == ("Dubai", "United Arab Emirates")
    assert b.years_exp == 12
    assert "Retail" in b.domains
    assert "SAP Retail" in b.skills and "Excel" in b.skills

    c = rules.extract(CAROL, "Carol_Placeholder.pdf")
    assert (c.city, c.country) == ("Riyadh", "Saudi Arabia")
    assert c.years_exp == 5
    assert "Telecommunications" in c.domains
    assert {"5G", "4G/LTE", "RAN", "Ericsson", "Nokia"} <= set(c.skills)


@pytest.mark.parametrize(
    ("text", "absent"),
    [
        ("He ran the spring campaign and helped people excel at work.", {"RAN", "Spring", "Excel"}),
        ("A lean team with a safe culture; I like to go fast.", {"Lean", "SAFe", "Go"}),
        ("We sketch ideas and segment users by amplitude.", set()),
    ],
)
def test_ambiguous_words_do_not_become_skills(text: str, absent: set[str]) -> None:
    assert absent.isdisjoint(rules.extract_skills(text))


def test_special_token_skills() -> None:
    skills = rules.extract_skills(
        "Worked with C++, C#, .NET Core, CI/CD, Node.js and P&L ownership"
    )
    assert {"C++", "C#", ".NET", "CI/CD", "Node.js", "P&L Management"} <= set(skills)


def test_years_from_date_ranges() -> None:
    this_year = date.today().year
    text = "Analyst, X Corp  Jan 2015 - Dec 2017\nManager, Y Ltd  Mar 2018 - Present"
    y = rules.years_from_ranges(text)
    assert y is not None
    expected = this_year + (date.today().month - 1) / 12 - 2015
    assert abs(y - expected) < 0.5


def test_overlapping_ranges_merge() -> None:
    y = rules.years_from_ranges("2010 - 2015\n2013 - 2016")
    assert y == pytest.approx(6.1, abs=0.1)


def test_name_from_filename_fallback() -> None:
    assert rules.name_from_filename("Ajit_Patwardhan_CV_Updated.pdf") == "Ajit Patwardhan"
    assert rules.name_from_filename("2024 04 27 CV Resume Doug Lucas (1).pdf") == "Doug Lucas"
    assert rules.extract_name("RESUME\n\nPRIYA SHARMA\nBangalore", "x.pdf") == "Priya Sharma"


def test_taxonomy_canonicalize() -> None:
    tax = taxonomy.skills()
    assert tax.canonicalize("k8s") == "Kubernetes"
    assert tax.canonicalize("Rust") == "Rust"
    assert tax.canonicalize("aws") == "Amazon Web Services"
    assert tax.canonicalize("Quantum Basket Weaving") is None


def test_gazetteer_normalize() -> None:
    gz = taxonomy.gazetteer()
    assert gz.normalize("Bangalore", None) == ("Bengaluru", "India")
    assert gz.normalize("gurgaon", "india") == ("Gurugram", "India")
    assert gz.normalize(None, "UAE") == (None, "United Arab Emirates")


def test_domain_canonicalize() -> None:
    dm = taxonomy.domains()
    assert dm.canonicalize("banking") == "Banking & Financial Services"
    assert dm.canonicalize("Telecom") == "Telecommunications"
    assert dm.canonicalize("Financial Services") == "Banking & Financial Services"
    assert dm.canonicalize("IT Services") == "Information Technology & Software"
    assert dm.canonicalize("IT outsourcing") == "IT Consulting & Outsourcing"
    assert dm.canonicalize("Card payments / Fintech") == "Banking & Financial Services"
    assert dm.canonicalize("Gearbox design") is None


def test_wordy_llm_skills_map_to_longest_alias() -> None:
    tax = taxonomy.skills()
    assert tax.canonicalize("Project Management Professional (PMP)") == "PMP"
    assert tax.canonicalize("AWS cloud") == "Amazon Web Services"
    assert tax.canonicalize("Agile SCRUM Master") in {"Scrum", "Agile"}
