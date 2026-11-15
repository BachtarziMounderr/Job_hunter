# Décisions d'architecture — sprint 1

Le brief demande une progression par sprints. Cette version livre la collecte et la
persistance, et prépare les contrats nécessaires au matching. Elle ne télécharge pas
de modèle NLP et ne démarre aucun serveur. La contrainte ajoutée est une exécution
locale immédiate, avec hébergement et authentification reportés.

## Adaptation locale

SQLite est le stockage par défaut parce qu'il ne demande ni service à installer ni
identifiant. SQLAlchemy 2 utilise des types compatibles avec PostgreSQL ; Alembic est
la seule voie de création du schéma, en local comme pour une future base distante.
Le pilote psycopg est un extra facultatif. La portabilité SQL est vérifiable hors
ligne ; l'exécution PostgreSQL devra être testée lorsque cette base sera configurée.

## Frontières

`collectors/` gère l'accès HTTP et expose `CollectionResult`, qui décrit aussi les
échecs partiels et la troncature. `processing/` nettoie et transforme les données.
Les schémas Pydantic expriment les invariants de domaine. `database/` gère les écritures
et les lectures SQL. `pipeline.py` relie un connecteur à son normaliseur et délimite
les transactions. `cli.py` fournit un usage vérifiable sans interface supplémentaire.

L'isolation des exceptions inconnues se fait uniquement à la frontière d'un connecteur :
un adaptateur tiers peut échouer sans empêcher la collecte des autres sources. Les
diagnostics exposent la classe de l'erreur, jamais le contenu reçu ni des secrets.
Les échecs de base sont signalés et la transaction correspondante est annulée.

## Identité et duplications

L'identité primaire d'une annonce est son couple source/identifiant externe. L'empreinte
de contenu exclut cette identité et les timestamps d'observation. Elle comprend le
titre, l'entreprise, la description, le lieu, le mode distant, le type d'emploi, les
tags et l'URL. La casse de l'URL est préservée, car le chemin peut être sensible à la
casse. L'empreinte est volontairement conservatrice : pas de fuzzy matching au sprint 1.

Plutôt que supprimer la provenance d'une copie trouvée sous un autre identifiant,
`duplicate_of_id` pointe vers l'annonce canonique. Les groupes touchés sont recalculés
après chaque lot, y compris l'ancien groupe lorsqu'une annonce change de contenu.
Les consultations filtrent les copies. La prochaine couche de notifications devra
sélectionner les offres canoniques et respecter les historiques lors d'un regroupement.

Les contraintes SQL protègent les identités et l'historique futur de notification.
La couche actuelle suppose un seul processus d'écriture. La résolution des conflits
concurrents et la déduplication floue sont des améliorations futures explicites.

## Inconnues et faits

Un tag de job board n'est pas forcément une compétence requise. Une annonce marquée
distante n'est pas forcément ouverte au monde entier. Une adresse de bureau n'est
pas une liste de pays éligibles. Les champs correspondants restent `unknown`, `null`
ou vides quand le fournisseur ne les fournit pas. Les classifications et règles
géographiques appartiendront au moteur Python du sprint 2.

Le statut `expired` est disponible, mais on ne l'applique pas automatiquement : une
page limitée ou une panne ne prouve pas qu'une offre a été retirée. Une future politique
pourra utiliser une date d'expiration explicite ou plusieurs observations complètes.

## Données historiques

`job_matches` prévoit une unicité sur l'offre, le profil, leurs empreintes et la version
du moteur. `details` pourra contenir les sous-scores et raisons déjà calculés.
`notifications` prévoit une unicité offre/profil/canal, des tentatives et un état.
Ces tables sont prêtes sans simuler de calculs ou d'envois. La conservation du texte
complet de chaque ancienne version d'annonce n'est pas implémentée.

## Dépendances et évolutions

HTTPX, Pydantic, SQLAlchemy et Alembic suffisent au sprint 1. Les autres dépendances
du brief seront introduites au moment de leur usage. Pas de framework web, de file
de messages, d'architecture asynchrone ou de compte cloud nécessaire à ce stade.

Les sources suivantes devront chacune faire l'objet d'une vérification d'interface
et de conditions avant implémentation. Arbeitnow constitue un test de la chaîne de
collecte ; sa couverture actuelle ne satisfait pas encore l'objectif Algérie/remote.
