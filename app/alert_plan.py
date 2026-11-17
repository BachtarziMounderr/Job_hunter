"""Initial saved-search links derived from the candidate orientations; no account automation."""

import html
from pathlib import Path
from urllib.parse import quote, urlencode

from app.config import Settings
from app.matching.classifiers import classify_role
from app.profiles import load_profiles

ROLE_QUERIES = {
    "ai_ml": ["intelligence artificielle", "machine learning", "ingénieur IA"],
    "data": ["data analyst", "data scientist", "ingénieur données", "business intelligence"],
    "backend": ["développeur Python", "développeur backend"],
    "full_stack": ["développeur full stack"],
    "frontend": ["développeur React", "développeur frontend"],
}


def alert_plan(settings: Settings) -> list[dict]:
    groups = {}
    for profile in load_profiles(settings):
        for title in profile.target_roles:
            for query in ROLE_QUERIES.get(classify_role(title), []):
                groups.setdefault(query, set()).add(profile.name)
    return [
        {
            "query": query,
            "profiles": sorted(profiles),
            "linkedin": "https://www.linkedin.com/jobs/search/?"
            + urlencode({"keywords": query, "location": "Algeria", "f_TPR": "r86400"}),
            "emploitic": "https://emploitic.com/offres-d-emploi/q-"
            + quote(query.replace(" ", "-")),
        }
        for query, profiles in groups.items()
    ][:20]


def write_alert_plan(settings: Settings, path: Path) -> None:
    rows = []
    for item in alert_plan(settings):
        rows.append(
            f"<tr><td>{html.escape(item['query'])}</td>"
            f"<td>{html.escape(', '.join(item['profiles']))}</td>"
            f"<td><a href='{html.escape(item['linkedin'], quote=True)}'>LinkedIn</a></td>"
            f"<td><a href='{html.escape(item['emploitic'], quote=True)}'>Emploitic</a></td></tr>"
        )
    template = Path(__file__).resolve().parent.parent / "config" / "alert_plan.html"
    text = template.read_text(encoding="utf-8").replace("<!--ROWS-->", "".join(rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
