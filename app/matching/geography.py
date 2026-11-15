"""Conservative geographic decisions based on explicit scope, never semantic inference."""

import re
from dataclasses import dataclass
from typing import Literal

from app.matching.skills import fold_text
from app.schemas.job import Job, RemoteType
from app.schemas.profile import CandidateProfile

COUNTRIES = {
    "DZ": ("algeria", "algerie", "algiers", "alger", "constantine", "annaba", "oran", "الجزائر"),
    "FR": ("france", "french residents"),
    "US": ("united states", "usa", "u.s.", "us only"),
    "CA": ("canada",),
    "DE": ("germany", "deutschland", "allemagne"),
    "GB": ("united kingdom", "uk", "great britain"),
    "ES": ("spain", "espagne"),
    "IT": ("italy", "italie"),
    "NL": ("netherlands", "nederland", "pays-bas"),
    "BE": ("belgium", "belgique"),
    "PT": ("portugal",),
    "PL": ("poland", "pologne"),
    "IE": ("ireland",),
    "CH": ("switzerland", "suisse"),
    "AT": ("austria",),
    "IN": ("india", "inde"),
    "AU": ("australia",),
    "BR": ("brazil",),
    "TN": ("tunisia", "tunisie"),
    "MA": ("morocco", "maroc"),
    "EG": ("egypt", "egypte"),
}
REGIONS = {
    "EMEA": {
        "DZ",
        "FR",
        "DE",
        "GB",
        "ES",
        "IT",
        "NL",
        "BE",
        "PT",
        "PL",
        "IE",
        "CH",
        "AT",
        "TN",
        "MA",
        "EG",
    },
    "EU": {"FR", "DE", "ES", "IT", "NL", "BE", "PT", "PL", "IE", "AT"},
    "Europe": {"FR", "DE", "GB", "ES", "IT", "NL", "BE", "PT", "PL", "IE", "CH", "AT"},
    "Africa": {"DZ", "TN", "MA", "EG"},
    "North America": {"US", "CA"},
    "LATAM": {"BR"},
    "APAC": {"IN", "AU"},
    "MENA": {"DZ", "TN", "MA", "EG"},
}
REGION_ALIASES = {
    "EMEA": ("emea",),
    "EU": ("eu", "european union", "union europeenne", "eea", "eee"),
    "Europe": ("europe",),
    "Africa": ("africa", "afrique"),
    "North America": ("north america", "amerique du nord"),
    "LATAM": ("latam", "latin america"),
    "APAC": ("apac", "asia pacific"),
    "MENA": ("mena", "north africa", "afrique du nord"),
}


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)


@dataclass(frozen=True)
class GeographyDecision:
    status: Literal["eligible", "ineligible", "unknown"]
    score: float
    reason: str


def _scope_decision(text: str, country: str) -> GeographyDecision:
    value = fold_text(text)
    if "worldwide" in value and re.search(r"\bonly\b|uniquement|restricted to", value):
        narrowed = re.sub(r"\bworldwide\b", "", value)
        decision = _scope_decision(narrowed, country)
        if decision.status != "eligible":
            return decision
    # Explicit exclusion takes precedence over broader regional/worldwide claims.
    for match in re.finditer(
        r"(?:except|excluding|exclude|hors|sauf|not open to)\s+([^.;\n]+)", value
    ):
        excluded = match.group(1)
        if _contains(excluded, COUNTRIES.get(country, (country.casefold(),))):
            return GeographyDecision(
                "ineligible", 0, "Le pays de résidence est explicitement exclu"
            )
        if any(
            _contains(excluded, aliases) and country in REGIONS[region]
            for region, aliases in REGION_ALIASES.items()
        ):
            return GeographyDecision(
                "ineligible", 0, "La région du candidat est explicitement exclue"
            )
    # Remove excluded scopes before reading the positive list.
    positive = re.split(r"\b(?:except|excluding|hors|sauf)\b", value)[0]
    if _contains(
        positive,
        (
            "worldwide",
            "anywhere in the world",
            "anywhere",
            "globally",
            "global",
            "monde entier",
            "partout dans le monde",
        ),
    ):
        return GeographyDecision("eligible", 100, "Périmètre remote mondial explicitement indiqué")
    detected = {code for code, aliases in COUNTRIES.items() if _contains(positive, aliases)}
    if re.search(r"\bus\b", positive):
        detected.add("US")
    regions = [region for region, aliases in REGION_ALIASES.items() if _contains(positive, aliases)]
    if country in detected or any(country in REGIONS[region] for region in regions):
        return GeographyDecision(
            "eligible", 100, "Pays ou région de résidence inclus explicitement"
        )
    if detected or regions:
        return GeographyDecision(
            "ineligible", 0, "Périmètre indiqué limité à d'autres pays ou régions"
        )
    return GeographyDecision(
        "unknown", 50, "Périmètre géographique non déterminable ; vérification requise"
    )


def geographic_eligibility(job: Job, profile: CandidateProfile) -> GeographyDecision:
    """Require explicit remote scope; office location alone is not a remote restriction."""
    country = profile.residence_country
    scope = job.remote_eligibility
    description = fold_text(job.description)
    # Only explicit residence/work-location statements are read from free text.
    restrictions = re.findall(
        r"(?:must (?:reside|be (?:based|located)) in|candidates? (?:must be|based) in|"
        r"remote (?:only )?(?:within|from)|residence obligatoire en|"
        r"(?:only|uniquement) (?:open|available|ouvert) (?:to|aux?) (?:candidates? in )?)"
        r"\s*([^.;\n]{2,120})",
        description,
    )
    restrictions += re.findall(
        r"\b(usa|united states|canada|eu|europe|france|germany|uk)\s+only\b",
        description,
    )
    for restriction in restrictions:
        decision = _scope_decision(restriction, country)
        if decision.status == "ineligible":
            return decision
        if decision.status == "unknown":
            return decision
    # Work authorization is a separate constraint, never inferred from residence.
    auth = re.findall(
        r"(?:authorized|authorised|right|authorization) to work in\s+([^.;\n]{2,80})", description
    )
    for requirement in auth:
        codes = {code for code, aliases in COUNTRIES.items() if _contains(requirement, aliases)}
        if codes and not (codes & set(profile.work_authorization_countries)):
            return GeographyDecision(
                "unknown", 50, "Autorisation de travail exigée non confirmée dans le profil"
            )
    if job.remote_type == RemoteType.REMOTE:
        if scope and scope != "unknown":
            decision = _scope_decision(scope, country)
        else:
            explicit = re.search(
                r"(?:remote|teletravail)[^.;\n]{0,40}(worldwide|anywhere|monde entier|emea)",
                description,
            )
            decision = (
                _scope_decision(explicit.group(0), country)
                if explicit
                else GeographyDecision(
                    "unknown",
                    50,
                    "Remote indiqué sans liste de pays éligibles",
                )
            )
        # Description exclusions override a positive structured worldwide/region label.
        exclusion = re.search(r"(?:except|excluding|hors|sauf)\s+([^.;\n]+)", description)
        if (
            exclusion
            and _scope_decision("worldwide " + exclusion.group(0), country).status == "ineligible"
        ):
            return GeographyDecision("ineligible", 0, "Exclusion explicite du pays ou de la région")
        return decision
    local = " ".join(filter(None, [job.country, job.location]))
    if job.country == country:
        return GeographyDecision("eligible", 100, "Pays de l'offre égal au pays de résidence")
    local_decision = _scope_decision(local, country)
    if local_decision.status == "eligible":
        return GeographyDecision("eligible", 100, "Offre située dans le pays de résidence")
    if local_decision.status == "ineligible":
        return GeographyDecision(
            "ineligible", 0, "Offre locale dans un autre pays ; mobilité non configurée"
        )
    return GeographyDecision("unknown", 50, "Lieu ou conditions de travail inconnus")
