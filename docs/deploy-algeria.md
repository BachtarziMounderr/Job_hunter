# Déploiement personnel : Algérie, midi, Telegram

Le programme s'exécute sur GitHub Actions et s'arrête après le traitement. Neon
conserve les données et historiques. Aucun serveur web permanent n'est nécessaire.
La programmation est `0 11 * * *` : midi en Algérie (`Africa/Algiers`, UTC+1).
GitHub peut retarder le démarrage ; Telegram reçoit le bilan après le traitement.

## Secrets du dépôt

| Nom | Contenu |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL poolée, préfixe `postgresql+psycopg://` |
| `MIGRATION_DATABASE_URL` | URL PostgreSQL directe pour les migrations |
| `PROFILES_JSON` | Tableau JSON exporté depuis les trois CV |
| `TELEGRAM_BOT_TOKEN` | Jeton BotFather |
| `TELEGRAM_CHAT_ID` | Chat de destination |
| `GROQ_API_KEY` | Clé Groq, si les reformulations sont activées |
| `GMAIL_OAUTH_JSON` | Autorisation Gmail locale, après [configuration initiale](gmail-setup.md) |

Copier uniquement les valeurs, sans préfixe `NOM=` ni guillemets d'un fichier dotenv.
Ne pas mettre les secrets dans les Repository variables.

## Variables du dépôt

```text
SCHEDULER_BACKEND=github
NOTIFICATIONS_ENABLED=true
LLM_ENABLED=true
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GMAIL_ENABLED=false
GMAIL_LABEL=JobHunter/Alerts
```

Passer `GMAIL_ENABLED=true` après avoir ajouté `GMAIL_OAUTH_JSON` et configuré les
alertes. Tant que Gmail n'est pas activé, seuls les sites d'entreprises sont
interrogés et le bilan signale clairement l'absence des alertes LinkedIn/Emploitic.

## Vérification et activation

1. La CI vérifie tests, format, migrations PostgreSQL et démarrage du conteneur.
2. Actions → Daily discovery → Run workflow → `smoke-test` limite l'analyse à 25
   offres algériennes. Ce mode est affiché dans Telegram et ne consomme pas le jour
   de veille normal.
3. Le mode `daily` analyse jusqu'à 1 000 offres locales ciblées. Une seule recherche
   quotidienne confirmée est exécutée par date algérienne, même après une relance.
4. Les recommandations et pistes à vérifier ont un historique d'envoi durable.
   Un passage d'une piste à une recommandation peut produire une nouvelle alerte.
5. Les résultats CI et les échecs de la recherche sont envoyés par un job Telegram
   indépendant de l'application, y compris si le build du conteneur échoue.

Les offres historiques Arbeitnow/Jobicy sont conservées pour audit mais exclues de
la sélection et des nouvelles notifications. L'évaluation synthétique hors réseau
reste disponible avec les anciennes fixtures ; elle ne représente pas le marché réel.

## Reprise après erreur

Les embeddings sont sauvegardés par petits lots. Une interruption avant le bilan
permet une reprise sans réenvoyer les offres déjà confirmées. Une réponse Telegram
perdue conserve un statut incertain : vérifier le chat avant de réinitialiser cet état.
Les alertes Gmail ne sont jamais marquées comme lues, déplacées ou supprimées.
