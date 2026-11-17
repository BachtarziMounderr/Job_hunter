"""A factual completion message, including searches with no suitable opportunities."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.matching.service import RankedMatch
from app.notifications.service import DeliveryReport, select_opportunities, select_reviews
from app.pipeline import PipelineReport
from app.profiles import load_profiles


def format_run_report(
    settings: Settings,
    collection: PipelineReport,
    matches: list[RankedMatch],
    delivery: DeliveryReport,
    reviews: DeliveryReport | None = None,
    summary: str | None = None,
) -> str:
    profiles = load_profiles(settings)
    opportunities = select_opportunities(matches, settings)
    now = datetime.now(UTC).astimezone(ZoneInfo(settings.notification_timezone))
    state = "terminée" if collection.exit_code == 0 else "partielle"
    review_groups = select_reviews(matches, settings)
    lines = [
        f"Job Hunter — recherche {state} — Algérie"
        if settings.search_scope == "algeria"
        else f"Job Hunter — recherche {state}",
        now.strftime("%d/%m/%Y à %H:%M") + f" ({settings.notification_timezone})",
        "",
        "Mode : test limité à 25 offres"
        if settings.run_mode == "smoke-test"
        else "Mode : veille quotidienne"
        if settings.run_mode == "daily"
        else "Mode : recherche manuelle",
        f"Annonces reçues : {collection.records_received}.",
        f"Offres distinctes analysées : {len({m.job_id for m in matches})}.",
        f"Profils : {len(profiles)} ; comparaisons : {len(matches)}.",
        f"Offres retenues (seuil {settings.minimum_match_score:g}/100) : {len(opportunities)}.",
        f"Alertes envoyées : {delivery.sent} ; déjà traitées : {delivery.skipped}.",
        f"Pistes à vérifier : {len(review_groups)} ; "
        f"nouvelles pistes envoyées : {reviews.sent if reviews else 0}.",
        "",
    ]
    for profile in profiles:
        count = sum(
            m.profile_name == profile.name
            and m.result.eligible_for_notification
            and m.result.total_score >= settings.minimum_match_score
            for m in matches
        )
        lines.append(f"• {profile.name[:120]} : {count} offre(s) retenue(s).")
    if not opportunities:
        lines.extend(
            [
                "",
                "Aucune recommandation ferme dans les données analysées. Les pistes incertaines "
                "sont présentées séparément ; ce résultat ne couvre pas tout le marché.",
            ]
        )
    if collection.sources_failed or collection.invalid_records:
        lines.append(
            f"Sources en échec : {collection.sources_failed} ; "
            f"annonces invalides : {collection.invalid_records}."
        )
        if settings.search_scope == "algeria" and collection.sources_failed:
            lines.append(
                "Des offres déjà connues peuvent être analysées ; "
                "leur source n'a pas forcément pu être revérifiée aujourd'hui."
            )
    if collection.limited_sources:
        lines.append("Collecte plafonnée pour : " + ", ".join(collection.limited_sources))
    if settings.search_scope == "algeria":
        lines.append(
            f"Écartées avant analyse : {collection.out_of_scope_records} "
            f"hors périmètre/localisation non confirmée, "
            f"{collection.irrelevant_records} hors métiers cibles."
        )
        reasons = {"role": "métier", "experience": "expérience", "geography": "géographie"}
        for code, label in reasons.items():
            count = sum(code in m.result.exclusion_codes for m in matches)
            lines.append(
                f"Comparaisons exclues pour {label} : {count} (motifs pouvant se cumuler)."
            )
        for source, detail in collection.source_details.items():
            lines.append(
                f"Source {source} : {detail['accepted']} annonce(s) ciblée(s) ; "
                + ("indisponible/partielle" if detail["error"] else "accessible")
            )
        if not settings.gmail_enabled:
            lines.append("LinkedIn/Emploitic et autres alertes : connexion Gmail à configurer.")
        elif not settings.gmail_oauth_json:
            lines.append("Alertes email indisponibles : GMAIL_OAUTH_JSON manquant.")
    if delivery.failed or delivery.uncertain:
        lines.append(
            f"Alertes en échec : {delivery.failed} ; envoi incertain : {delivery.uncertain}."
        )
    if summary:
        lines.extend(["", "Résumé : " + summary])
    return "\n".join(lines)
