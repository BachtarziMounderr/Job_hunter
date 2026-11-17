"""Conservative country evidence for offers situated in Algeria, not worldwide remote jobs."""

import re

from app.matching.skills import fold_text
from app.schemas.job import Job

# Algerian cities/wilayas are evidence only in the location field, never a company biography.
ALGERIAN_LOCATIONS = (
    "algeria",
    "algerie",
    "algiers",
    "alger",
    "oran",
    "constantine",
    "annaba",
    "blida",
    "boumerdes",
    "bejaia",
    "setif",
    "tizi ouzou",
    "tlemcen",
    "batna",
    "biskra",
    "chlef",
    "tipaza",
    "bouira",
    "bordj bou arreridj",
    "mostaganem",
    "sidi bel abbes",
    "skikda",
    "jijel",
    "guelma",
    "tebessa",
    "ouargla",
    "ghardaia",
    "laghouat",
    "djelfa",
    "adrar",
    "bechar",
    "tamanrasset",
    "tindouf",
    "illizi",
    "el oued",
    "el taref",
    "el bayadh",
    "el meniaa",
    "el mghair",
    "el oued",
    "ouled djellal",
    "timimoun",
    "bordj badji mokhtar",
    "beni abbes",
    "in salah",
    "in guezzam",
    "touggourt",
    "djanet",
    "tissemsilt",
    "tiaret",
    "saida",
    "mascara",
    "relizane",
    "ain defla",
    "ain temouchent",
    "ain salah",
    "ain guezzam",
    "naama",
    "khenchela",
    "souk ahras",
    "mila",
    "oum el bouaghi",
    "msila",
    "m'sila",
    "medea",
    "tissemsilt",
    "bab ezzouar",
    "cheraga",
    "hydra",
    "oued smar",
    "الجزائر",
    "وهران",
    "قسنطينة",
    "عنابة",
    "سطيف",
    "بجاية",
    "البليدة",
)
FOREIGN_LOCATIONS = {
    "FR": ("france", "paris", "lyon", "marseille"),
    "TN": ("tunisia", "tunisie", "tunis", "sousse"),
    "MA": ("morocco", "maroc", "casablanca", "rabat"),
    "EG": ("egypt", "egypte", "cairo", "alexandria"),
    "DE": ("germany", "allemagne", "berlin", "munich"),
    "GB": ("united kingdom", "london", "uk"),
    "US": ("united states", "usa", "new york"),
    "CA": ("canada", "montreal", "toronto"),
}


def contains_term(text: str, terms) -> bool:
    value = fold_text(text)
    return any(
        re.search(r"(?<!\w)" + re.escape(fold_text(term)) + r"(?!\w)", value) for term in terms
    )


def location_country(location: str | None) -> str | None:
    if not location:
        return None
    if re.search(
        r"except|excluding|sauf|hors|worldwide|anywhere|monde entier", fold_text(location)
    ):
        return None
    if contains_term(location, ALGERIAN_LOCATIONS):
        return "DZ"
    for code, terms in FOREIGN_LOCATIONS.items():
        if contains_term(location, terms):
            return code
    return None


def locality_key(location: str | None) -> str:
    value = fold_text(location or "")
    aliases = {
        "algiers": "alger",
        "الجزائر": "alger",
        "وهران": "oran",
        "قسنطينة": "constantine",
        "عنابة": "annaba",
        "بجاية": "bejaia",
        "سطيف": "setif",
    }
    for term in sorted(ALGERIAN_LOCATIONS, key=len, reverse=True):
        if term not in {"algeria", "algerie"} and contains_term(value, [term]):
            return aliases.get(term, fold_text(term))
    return re.sub(r"\W+", " ", value).strip() or "DZ"


def algeria_status(job: Job) -> str:
    country = job.country or location_country(job.location)
    if country == "DZ":
        return "eligible"
    if country:
        return "ineligible"
    return "unknown"
