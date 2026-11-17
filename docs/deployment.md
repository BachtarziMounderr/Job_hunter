# Archive : ancien hébergement Render + Neon

> Le déploiement actuel est décrit dans [Algérie + GitHub Actions](deploy-algeria.md).
> Les horaires et procédures Render ci-dessous sont historiques, pas la configuration active.

## État préparé

Le dépôt contient un Dockerfile avec le modèle multilingue mis en cache au build,
un Blueprint Render pour une tâche quotidienne, les migrations PostgreSQL et des
workflows GitHub Actions pour les tests et, en alternative, la planification.
Les CV, profils privés, bases locales et fichiers `.env` sont exclus de Git et du
contexte Docker.

Le travail consiste en un processus ponctuel qui sort après exécution. Aucun service
web, domaine public ou polling Telegram permanent n'est nécessaire. La base Neon
conserve les offres, scores et historiques entre deux exécutions.

Le CLI Render est désormais authentifié. La validation authentifiée du Blueprint
retourne cependant `need_payment_info` : les informations de paiement du workspace
doivent être complétées pour ce cron payant. Aucun service Job Hunter n'a été créé.
Le plugin Render demande encore une reconnexion indépendante, mais le CLI peut
effectuer le déploiement dès que ce blocage de facturation est résolu. Le schéma JSON
public du Blueprint a été validé, ainsi que le conteneur dans la CI GitHub.

## Déployer le Blueprint

Le fichier `render.yaml` doit d'abord être présent dans la branche `main` du dépôt.

[Ouvrir le Blueprint du projet](https://dashboard.render.com/blueprint/new?repo=https://github.com/BachtarziMounderr/Job_hunter)

Le service prévu est un cron Docker à `07:17 UTC` chaque jour, soit `08:17` à Alger.
À Paris, ce sera `08:17` en hiver et `09:17` en été. Le compteur journalier des
notifications utilise `Africa/Algiers`, indépendamment du fuseau du planificateur.

Le modèle a dépassé 1 Go de mémoire lors de l'exécution CPU locale ; le Blueprint
prévoit donc le plan `1c-2g`, au lieu d'un plan 512 Mo insuffisant pour cette exécution.
Ce n'est pas un service gratuit : les cron jobs ont une facturation liée à leur durée,
avec un minimum mensuel documenté. Vérifie le prix actuel au moment de l'activation.

## Secrets à renseigner

| Clé | Source |
|---|---|
| `DATABASE_URL` | URL PostgreSQL poolée de `.env.neon` |
| `MIGRATION_DATABASE_URL` | URL PostgreSQL directe de `.env.neon` |
| `PROFILES_JSON` | Contenu complet de `private/profiles.json` |
| `TELEGRAM_BOT_TOKEN` | Ton jeton BotFather |
| `TELEGRAM_CHAT_ID` | Le chat de destination |
| `GROQ_API_KEY` | Clé créée sur console.groq.com |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` |

Les URL SQLAlchemy doivent commencer par `postgresql+psycopg://`. Les secrets sont
injectés à l'exécution, jamais par `ARG`, dans le Dockerfile ou dans le Blueprint.
`GROQ_MODEL` reste configurable et `LLM_PROVIDER=groq` sélectionne ce fournisseur.
Pour un compte Qwen direct, sélectionner `LLM_PROVIDER=qwen` et ajouter les variables
`QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL` au service. Aucun LLM n'est nécessaire
pour les embeddings, qui sont calculés indépendamment en Python.

Le Blueprint démarre avec `PIPELINE_ENABLED=false`, `NOTIFICATIONS_ENABLED=false`
et `LLM_ENABLED=false`. Après configuration :

1. Activer `PIPELINE_ENABLED=true`, laisser les notifications désactivées et effectuer
   une première exécution. Vérifier collecte, profils et scores dans les logs.
2. Activer `LLM_ENABLED=true` lorsque la clé et l'endpoint Qwen sont renseignés.
3. Activer `NOTIFICATIONS_ENABLED=true` pour les envois Telegram.

Sans profils privés ou base PostgreSQL, le point d'entrée cloud refuse l'exécution
active. Il ne remplace pas silencieusement les CV par un profil public d'exemple.
Les images préchargées utilisent `EMBEDDING_LOCAL_FILES_ONLY=true` : pour changer de
modèle/révision, mettre à jour la configuration du build et reconstruire l'image,
ou autoriser explicitement le téléchargement à l'exécution.

## Alternative GitHub Actions

`daily.yml` possède un déclencheur quotidien et manuel, mais reste inactif tant que
la variable de dépôt `SCHEDULER_BACKEND` ne vaut pas `github`.
Renseigner les mêmes secrets, puis les variables `NOTIFICATIONS_ENABLED` et
`LLM_ENABLED` selon l'état souhaité.

Ne pas activer simultanément les deux planificateurs. Le verrou PostgreSQL protège
les écritures concurrentes, mais choisir une seule source de planification réduit
les appels externes et simplifie les diagnostics.

## Vérification Docker

```powershell
docker build -t ai-job-hunter .
docker run --rm ai-job-hunter python -m app demo
docker run --rm ai-job-hunter python -m app evaluate
docker run --rm --env-file .env.neon ai-job-hunter
```

La dernière commande utilise la configuration cloud ; ajouter `PROFILES_JSON` et les
variables d'activation dans ce fichier si nécessaire. Ne pas les ajouter au dépôt.
Le Dockerfile utilise Python 3.11, les versions runtime figées et un utilisateur non-root.
Il n'expose aucun port.

Le daemon Docker local était arrêté et son lancement a été refusé par le contrôle
automatique de cette session. La construction locale n'est donc pas revendiquée.
Le workflow CI prévoit une construction et une démo du conteneur sur un runner Linux.
Son résultat doit être vérifié sur GitHub avant de qualifier l'image de validée.

## Sources de configuration vérifiées

- [Cron jobs Render](https://render.com/docs/cronjobs)
- [Spécification Blueprint](https://render.com/docs/blueprint-spec)
- [Plans de calcul Render](https://render.com/docs/compute-plans)
- [Variables et secrets Render](https://render.com/docs/configure-environment-variables)
- [SQLAlchemy et Neon](https://neon.com/docs/guides/sqlalchemy)

Les contrats et prix peuvent évoluer. Une validation du schéma n'est pas une preuve
que les secrets, droits Git, builds, connexions et envois externes fonctionnent.
