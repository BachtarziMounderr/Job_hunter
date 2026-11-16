"""A factual completion message, including searches with no suitable opportunities."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.matching.service import RankedMatch
from app.notifications.service import DeliveryReport, select_opportunities
from app.pipeline import PipelineReport
from app.profiles import load_profiles


def format_run_report(
    settings: Settings,
    collection: PipelineReport,
    matches: list[RankedMatch],
    delivery: DeliveryReport,
) -> str:
    profiles = load_profiles(settings)
    opportunities = select_opportunities(matches, settings)
    now = datetime.now(UTC).astimezone(ZoneInfo(settings.notification_timezone))
    state = "terminée" if collection.exit_code == 0 else "partielle"
    lines = [
        f"Job Hunter — recherche {state}",
        now.strftime("%d/%m/%Y à %H:%M") + f" ({settings.notification_timezone})",
        "",
        f"Annonces reçues : {collection.records_received}.",
        f"Offres distinctes analysées : {len({m.job_id for m in matches})}.",
        f"Profils : {len(profiles)} ; comparaisons : {len(matches)}.",
        f"Offres retenues (seuil {settings.minimum_match_score:g}/100) : "
        f"{len(opportunities)}.",
        f"Alertes envoyées : {delivery.sent} ; déjà traitées : {delivery.skipped}.",
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
                "Aucune offre ne satisfait tous les critères actuels : métier, niveau, "
                "éligibilité géographique et score minimum.",
            ]
        )
    if collection.sources_failed or collection.invalid_records:
        lines.append(
            f"Sources en échec : {collection.sources_failed} ; "
            f"annonces invalides : {collection.invalid_records}."
        )
    if collection.limited_sources:
        lines.append("Collecte plafonnée pour : " + ", ".join(collection.limited_sources))
    if delivery.failed or delivery.uncertain:
        lines.append(
            f"Alertes en échec : {delivery.failed} ; envoi incertain : {delivery.uncertain}."
        )
    return "\n".join(lines)
