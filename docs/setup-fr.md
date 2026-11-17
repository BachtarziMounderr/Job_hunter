# Utilisation : veille Algérie avec tes trois CV

Version 0.3 : consulter le [déploiement à midi](deploy-algeria.md) et la
[connexion Gmail initiale](gmail-setup.md). `python -m app alert-plan` prépare
les recherches à enregistrer. Arbeitnow et Jobicy sont désactivés pour les recherches réelles.

## Import des CV

Les PDF restent dans le dossier local et sont exclus de Git et des images Docker.
Le manifeste `profiles/resume_manifest.json` associe chaque fichier à son orientation.
L'import crée trois fichiers privés sous `profiles/private/` : AI Engineer,
Data Science et Full Stack. Les compétences proviennent du texte de chaque CV ;
le profil commun fournit les objectifs de séniorité, la résidence et les langues.
Vérifie ces valeurs, notamment `residence_country` et les autorisations de travail.

## Installation et lancement

Depuis PowerShell dans le dossier du projet :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e '.[dev,postgres,ml]'
.\.venv\Scripts\python.exe -m app init-db
.\.venv\Scripts\python.exe -m app import-cvs
.\.venv\Scripts\python.exe -m app profiles
.\.venv\Scripts\python.exe -m app run
```

L'environnement, l'import et la base locale ont déjà été préparés sur cette machine.
`run` collecte, compare chaque offre aux trois CV, sauvegarde les scores et prépare
les messages sans les envoyer. Le premier calcul peut prendre plusieurs minutes sur
CPU ; les embeddings sont ensuite réutilisés depuis `data/embeddings/`.

Pour consulter les meilleures offres éligibles ou les blocages :

```powershell
.\.venv\Scripts\python.exe -m app match --limit 10
.\.venv\Scripts\python.exe -m app match --include-blocked --limit 20 --output reports/matches.json
.\.venv\Scripts\python.exe -m app stats
```

Un résultat vide est possible : le système n'abaisse pas le seuil pour fabriquer des
recommandations. Les annonces senior, hors métier ou géographiquement incompatibles
ne sont pas envoyées. Une éligibilité inconnue reste à examiner manuellement.

## Compléter Telegram et Qwen

### Si la clé vient de console.groq.com

Il s'agit d'une clé **Groq**, à utiliser avec ces paramètres :

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-20b
LLM_ENABLED=true
```

L'URL est celle documentée par [Groq](https://console.groq.com/docs/openai). Le modèle
par défaut figure dans son [catalogue de production](https://console.groq.com/docs/models).
Une clé Groq ne s'utilise pas sur un endpoint Alibaba/QwenCloud. Les champs Qwen
ci-dessous concernent uniquement un compte Qwen direct, avec `LLM_PROVIDER=qwen`.

Le fichier local `.env` existe et contient les champs vides. Ne le publie pas.

| Variable | Valeur à fournir |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Jeton fourni par BotFather |
| `TELEGRAM_CHAT_ID` | Identifiant du chat qui recevra les opportunités |
| `QWEN_API_KEY` | Clé de ton fournisseur Qwen |
| `QWEN_BASE_URL` | URL compatible Chat Completions de ton compte, jusqu'à `/v1` |
| `QWEN_MODEL` | Identifiant exact accessible avec ta clé, par défaut `qwen-plus` |
| `LLM_ENABLED` | `true` pour activer les résumés Qwen |

Le compte Telegram ne nécessite **ni API ID ni API hash** : le Bot API utilise
seulement le jeton et le chat cible. Ouvre une conversation avec ton bot et envoie
`/start` avant le premier envoi. Cette version ne traite pas les commandes du bot.

Pour trouver `TELEGRAM_CHAT_ID` sans exposer le jeton dans une URL de navigateur :

1. Renseigner uniquement `TELEGRAM_BOT_TOKEN` dans `.env`.
2. Envoyer `/start job_hunter_setup` dans une conversation privée avec ton bot.
3. Exécuter :

```powershell
.\.venv\Scripts\python.exe scripts/telegram_chat_id.py
```

Copier la ligne `TELEGRAM_CHAT_ID=...` affichée dans `.env`. Le script lit les mises
à jour sans les confirmer et sans envoyer de message. Si le bot utilise déjà un
webhook, il le conserve et explique pourquoi la lecture via `getUpdates` est indisponible.

Le fournisseur Qwen reste configurable : les domaines diffèrent selon le compte,
la région et le fournisseur. Ne copie pas un endpoint de compte tiers. Utilise
[la documentation de ton fournisseur](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope).
Ne mets pas `/chat/completions` à la fin de `QWEN_BASE_URL` ; le client l'ajoute.

```powershell
.\.venv\Scripts\python.exe -m app doctor
.\.venv\Scripts\python.exe -m app notify
.\.venv\Scripts\python.exe -m app notify --send
# Collecter puis envoyer les nouvelles opportunités :
.\.venv\Scripts\python.exe -m app run --notify
```

`doctor` vérifie la base et la présence des paramètres ; il ne prouve pas que les
clés sont valides. `notify` seul prépare les messages. `--send` et `run --notify`
appellent réellement Telegram. Sans opportunité admissible, aucun appel de résumé
ou d'envoi n'est effectué. Qwen peut tomber en panne sans empêcher le résumé Python.
`llm_ready` et `llm_provider` décrivent la configuration du fournisseur actif ;
`qwen_ready` concerne uniquement la configuration Qwen directe.

## Règles de notification

Le seuil initial est 65/100. Au plus dix nouvelles opportunités par journée
`Africa/Algiers`, tous CV confondus. Une offre est regroupée autour de son meilleur
CV admissible, avec les scores des autres orientations admissibles dans le message.

Une réservation en base précède l'envoi. Une réponse Telegram perdue laisse l'état
`uncertain` ou `sending` : le système ne renvoie pas automatiquement ce message.
Cela évite les doublons mais ne garantit pas une livraison exactement une fois.
Les rejets explicites et erreurs de connexion sans envoi ont des tentatives bornées.
Le plafond quotidien et les cooldowns sont vérifiés avant un nouvel essai.

## PostgreSQL déjà préparé

Le fichier privé `.env.neon` contient les URL de la base dédiée dans la branche
`job-hunter`. `DATABASE_URL` utilise le pooler ; `MIGRATION_DATABASE_URL` utilise
la connexion directe pour Alembic. Le contenu de ce fichier ne doit jamais être copié
dans une issue, un commit ou une capture d'écran.

```powershell
.\.venv\Scripts\python.exe -m app --env-file .env.neon check-db
.\.venv\Scripts\python.exe -m app --env-file .env.neon doctor
.\.venv\Scripts\python.exe -m app --env-file .env.neon match --limit 10
```

Le choix `--env-file` précède la sous-commande. SQLite reste le stockage local par
défaut ; cette option sélectionne explicitement la base distante. Les fichiers `.env`
ne se combinent pas automatiquement : pour un envoi depuis Neon, ajoute aussi les
variables Telegram/Qwen nécessaires à `.env.neon`, ou injecte-les par environnement.

## Export privé pour le cloud

```powershell
.\.venv\Scripts\python.exe -m app export-profiles
```

Cette commande crée `private/profiles.json`, ignoré par Git. Sa totalité constitue
la valeur du secret `PROFILES_JSON` sur l'hébergeur. Les PDF n'ont pas à être envoyés
sur GitHub ni incorporés dans l'image. Qwen reçoit des extraits d'offre, des raisons
et scores calculés, pas les CV complets ni les coordonnées du candidat.

La procédure d'hébergement actuelle est dans [deploy-algeria.md](deploy-algeria.md).
