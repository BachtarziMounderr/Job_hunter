"""One portable results document: useful links and explanations, without candidate CVs."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.config import Settings
from app.matching.service import RankedMatch
from app.notifications.service import _job_key
from app.pipeline import PipelineReport

LABELS = {"recommended": "Recommandée", "review": "À vérifier", "excluded": "Écartée"}


@dataclass(frozen=True)
class ResultEntry:
    best: RankedMatch
    profiles: tuple[RankedMatch, ...]
    category: str
    url: str | None


def application_link(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
    except ValueError:
        pass
    return None


def category(match: RankedMatch, settings: Settings) -> str:
    result = match.result
    if result.eligible_for_notification and result.total_score >= settings.minimum_match_score:
        return "recommended"
    if (
        settings.search_scope == "algeria"
        and match.job.country == "DZ"
        and result.geographic_status == "eligible"
        and not result.exclusion_codes
        and result.total_score >= settings.review_minimum_score
    ):
        return "review"
    return "excluded"


def result_entries(matches: list[RankedMatch], settings: Settings) -> list[ResultEntry]:
    groups = defaultdict(list)
    for match in matches:
        groups[_job_key(match, local_only=settings.search_scope == "algeria")].append(match)
    entries = []
    for group in groups.values():
        group.sort(
            key=lambda m: (
                {"recommended": 0, "review": 1, "excluded": 2}[category(m, settings)],
                -m.result.total_score,
            )
        )
        best = group[0]
        profiles = {}
        for match in group:
            profiles.setdefault(match.profile_name, match)
        entries.append(
            ResultEntry(
                best,
                tuple(profiles.values()),
                category(best, settings),
                application_link(str(best.job.application_url)),
            )
        )
    return sorted(
        entries,
        key=lambda e: (
            {"recommended": 0, "review": 1, "excluded": 2}[e.category],
            -e.best.result.total_score,
        ),
    )


def _list(values: list[str], empty: str) -> str:
    return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in (values or [empty])) + "</ul>"


def _profile_details(match: RankedMatch, settings: Settings) -> str:
    result = match.result
    parts = [
        f'<section class="profile-analysis"><h4>{escape(match.profile_name)}'
        f" <span>{result.total_score:.1f}/100 · {LABELS[category(match, settings)]}</span></h4>",
        '<div class="explanation-grid"><div><h5>Compétences communes</h5>',
        _list(
            result.matched_skills, "Aucune compétence commune détectée dans le texte disponible."
        ),
        "</div><div><h5>Compétences à confirmer dans ton CV</h5>",
        _list(result.missing_skills, "Aucun écart de compétence détecté par l'algorithme."),
        "</div></div><h5>Points à examiner</h5>",
        _list(
            result.review_reasons + result.incompatibility_reasons,
            "Pas de réserve détectée ; lis la fiche avant de candidater.",
        ),
        '<dl class="components">',
    ]
    for label, score in [
        ("Proximité du texte", result.semantic_score),
        ("Compétences", result.skills_score),
        ("Expérience", result.experience_score),
        ("Formation", result.education_score),
        ("Localisation", result.location_score),
    ]:
        parts.append(f"<div><dt>{label}</dt><dd>{score:.0f}/100</dd></div>")
    return "".join(parts) + "</dl></section>"


def _card(entry: ResultEntry, settings: Settings, names: list[str]) -> str:
    match, job = entry.best, entry.best.job
    profiles = [
        m.profile_name
        for m in entry.profiles
        if entry.category == "excluded" or category(m, settings) != "excluded"
    ]
    search = " ".join([job.title, job.company or "", job.location or "", *profiles])
    reasons = match.result.review_reasons or match.result.incompatibility_reasons
    if entry.category == "review" and not reasons:
        reasons = ["Score inférieur au seuil de recommandation ferme."]
    preview = reasons[0] if reasons else "Les critères configurés sont satisfaits."
    button = (
        f'<a class="apply" href="{escape(entry.url, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Voir l’offre et postuler</a>'
        if entry.url
        else '<span class="muted">Lien HTTPS indisponible</span>'
    )
    profile_attrs = " ".join(
        f'data-profile-{i}="1"' for i, name in enumerate(names) if name in profiles
    )
    # Every dynamic value is HTML-escaped; source data is never inserted as JavaScript.
    return "".join(
        [
            f'<article class="job" data-status="{entry.category}" {profile_attrs} '
            f'data-search="{escape(search, quote=True)}" data-score="{match.result.total_score}">',
            '<div class="job-main"><div class="job-copy">',
            f'<div class="company">{escape(job.company or "Entreprise non précisée")}</div>',
            f"<h3>{escape(job.title)}</h3>",
            f'<p class="location">{escape(job.location or "Localisation non précisée")}</p>',
            f'<p class="profile">CV conseillé : <strong>{escape(match.profile_name)}</strong></p>',
            '</div><div class="decision">',
            f'<span class="badge {entry.category}">{LABELS[entry.category]}</span>',
            f'<div class="score">{match.result.total_score:.1f}<small>/100</small></div>',
            "<small>Compatibilité indicative</small></div></div>",
            f'<p class="reason">{escape(preview)}</p>',
            f'<div class="job-actions">{button}',
            f'<span class="source">{escape(job.source_name)}</span></div>',
            "<details><summary>Pourquoi ce résultat ? Voir les profils</summary>",
            "".join(
                _profile_details(m, settings)
                for m in sorted(entry.profiles, key=lambda m: -m.result.total_score)
            ),
            f'<p class="dates">Publication : '
            f"{job.published_at.strftime('%d/%m/%Y') if job.published_at else 'non précisée'}. "
            f"Dernière présence dans la source : {job.last_seen_at.strftime('%d/%m/%Y')}.</p>",
            "</details></article>",
        ]
    )


def write_results(
    settings: Settings,
    matches: list[RankedMatch],
    output: Path,
    collection: PipelineReport | None = None,
    summary: str | None = None,
) -> list[ResultEntry]:
    entries = result_entries(matches, settings)
    now = datetime.now(UTC).astimezone(ZoneInfo(settings.notification_timezone))
    names = sorted({m.profile_name for m in matches})
    recommended = sum(e.category == "recommended" for e in entries)
    reviews = sum(e.category == "review" for e in entries)
    state = "Collecte partielle" if collection and collection.exit_code else "Résultats disponibles"
    if collection is None:
        state = "Depuis les annonces enregistrées · aucune nouvelle collecte"
    alerts = (
        "Alertes email connectées"
        if settings.gmail_enabled and settings.gmail_oauth_json
        else ("LinkedIn / Emploitic : connexion Gmail à configurer")
    )
    coverage = [f"<p>{escape(alerts)}. Ces résultats ne couvrent pas tout le marché.</p>"]
    if collection:
        for source, detail in collection.source_details.items():
            label = "indisponible ou partielle" if detail["error"] else "accessible"
            coverage.append(
                f"<p>{escape(source)} : {detail['received']} annonce(s) reçue(s), "
                f"{detail['accepted']} ciblée(s) ; {label}.</p>"
            )
        if collection.sources_failed:
            coverage.append(
                "<p>Des offres conservées peuvent apparaître même si leur source "
                "n’a pas pu être revérifiée pendant cette recherche.</p>"
            )
        if collection.limited_sources:
            coverage.append(
                "<p>Collecte plafonnée : " + escape(", ".join(collection.limited_sources)) + ".</p>"
            )
    replacements = {
        "DATE": now.strftime("%d %m %Y · %H:%M"),
        "TIMEZONE": escape(settings.notification_timezone),
        "STATE": escape(state),
        "TOTAL": str(len(entries)),
        "RECOMMENDED": str(recommended),
        "REVIEWS": str(reviews),
        "EXCLUDED": str(len(entries) - recommended - reviews),
        "PROFILE_OPTIONS": "".join(
            f'<option value="{i}">{escape(name)}</option>' for i, name in enumerate(names)
        ),
        "JOBS": "".join(_card(e, settings, names) for e in entries),
        "COVERAGE": "".join(coverage),
        "SUMMARY": f"<p>{escape(summary)}</p>" if summary else "",
        "COLLECTION": (
            f"{collection.records_received} annonces reçues ; "
            f"{collection.irrelevant_records} hors métiers cibles avant analyse."
            if collection
            else "Données enregistrées, sans nouvelle recherche."
        ),
        "MINIMUM": f"{settings.minimum_match_score:g}",
        "REVIEW_MINIMUM": f"{settings.review_minimum_score:g}",
        "WEIGHTS": ", ".join(
            f"{label} ({getattr(settings.score_weights, key) * 100:g} %)"
            for key, label in [
                ("semantic", "la proximité du texte"),
                ("skills", "les compétences"),
                ("experience", "l’expérience"),
                ("education", "la formation"),
                ("location", "la localisation"),
            ]
        ),
    }
    template = (Path(__file__).resolve().parent.parent / "config/results.html").read_text(
        encoding="utf-8"
    )
    for key, value in replacements.items():
        template = template.replace("<!--" + key + "-->", value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding="utf-8")
    return entries


def digest_caption(settings: Settings, entries: list[ResultEntry], collection=None) -> str:
    day = (
        datetime.now(UTC).astimezone(ZoneInfo(settings.notification_timezone)).strftime("%d/%m/%Y")
    )
    firm = sum(e.category == "recommended" for e in entries)
    review = sum(e.category == "review" for e in entries)
    lines = [
        f"Job Hunter · Algérie · {day}",
        f"{firm} recommandation(s) · {review} piste(s) à vérifier",
        f"{len(entries)} offres analysées · liens et profils dans le rapport joint.",
    ]
    if collection and collection.exit_code:
        lines.append("Collecte partielle : certaines sources sont indisponibles.")
    if collection is None:
        lines.append("Offres enregistrées : aucune nouvelle collecte pour cet envoi.")
    if settings.run_mode == "smoke-test":
        lines.append("Essai limité à 25 offres.")
    lines.extend(
        [
            "",
            "Télécharge le fichier HTML et ouvre-le dans ton navigateur.",
            "Filtre par CV, consulte les réserves et clique sur « Voir l’offre et postuler ».",
        ]
    )
    if not firm and review:
        lines.append(
            "À vérifier ne signifie pas refusé : lis les points signalés avant de candidater."
        )
    return "\n".join(lines)[:1000]


def digest_buttons(entries: list[ResultEntry]) -> list[list[dict]]:
    return [
        [
            {
                "text": f"{entry.best.job.company or 'Offre'} · {entry.best.job.title}"[:60],
                "url": entry.url,
            }
        ]
        for entry in entries
        if entry.url and entry.category != "excluded"
    ][:8]
