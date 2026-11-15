# État de livraison — 15 novembre 2026

> Archive du sprint 1. La version actuelle et son guide figurent dans le README
> et dans [setup-fr.md](setup-fr.md).

Le sprint 1 est livré en mode local. Le dépôt Git est initialisé dans ce dossier,
sans dépôt distant, publication ni commit automatique. La configuration `.qodo`
préexistante est conservée et ignorée par Git.

## Vérifications exécutées

| Vérification | Résultat observé |
|---|---|
| Installation éditable `.[dev,postgres]` | Réussie dans `.venv`, Python 3.11.9 |
| Pytest | 46 tests réussis |
| Couverture des instructions `app` | 98 % ; ce chiffre ne garantit pas l'absence de bugs |
| Ruff lint | Réussi |
| Ruff format | Conforme |
| `pip check` | Aucune dépendance cassée |
| Migrations SQLite | Montée, descente, remontée et absence de dérive testées |
| Génération SQL PostgreSQL | Réussie hors ligne, sans connexion |
| `check-db` local | `SELECT 1` exécuté avec succès sur SQLite |
| Première collecte réelle Arbeitnow | 300 reçues, 300 insérées, aucune invalide |
| Deuxième collecte réelle Arbeitnow | 300 mises à jour, aucune insertion |
| Consultation locale | `jobs` et `stats` exécutés avec succès |

La base réelle est `data/job_hunter.db`, ignorée par Git. Une page a été collectée à
chaque exécution ; la limite volontaire apparaît dans le rapport. Ces annonces ne
sont ni filtrées ni classées pour le candidat. Leur disponibilité peut évoluer.

## Ce qui attend la prochaine étape

Le sprint 2 doit implémenter le moteur Python : embeddings multilingues configurables,
similarité cosinus, extraction de compétences, séniorité, éducation, règles
géographiques, pondération configurable, explications structurées et évaluation sur
des annotations manuelles. Aucune de ces décisions ne sera déléguée à un LLM.

L'éligibilité géographique inconnue doit empêcher toute future notification automatique
jusqu'à clarification suffisante. La résidence et les autorisations de travail du
profil doivent être vérifiées avant d'utiliser le futur moteur de filtrage.

Telegram, Groq, Docker, le planificateur quotidien et la connexion Neon restent pour
les sprints suivants. Leurs identifiants ne sont pas nécessaires pour utiliser la
livraison locale. Aucune action n'attend actuellement une permission utilisateur.

Avant de publier une version hébergée, il faudra tester PostgreSQL sur une vraie base,
vérifier les sources et leurs conditions à cette date, puis configurer les secrets
hors du dépôt. La génération SQL hors ligne ne valide ni le réseau, ni TLS, ni les
droits, ni l'exécution des migrations sur une instance PostgreSQL réelle.
