# Sources vérifiées

## Périmètre actuel : Algérie uniquement (novembre 2026)

- **Yassir** : API publique Lever, localisations algériennes sélectionnées avant
  persistance et matching. Les autres pays du même tableau d'offres sont exclus.
- **AYRADE** : pages officielles de recrutement ; robots.txt consulté, chemins et
  redirections limités au domaine officiel, requêtes bornées et espacées.
- **Greenhouse** : connecteur disponible pour ajouter des tableaux d'entreprises
  vérifiés dans `config/career_sources.json` ; aucune entreprise non vérifiée n'est activée.
- **LinkedIn / Emploitic / EmploiPartner / AlgerieJob** : alertes personnelles lues
  via Gmail, après activation par le candidat. Aucun robot de connexion LinkedIn,
  cookie ou mot de passe de ces plateformes n'est utilisé. Voir [Gmail](gmail-setup.md).

Les tableaux d'entreprises sont maintenus dans `config/career_sources.json`.
Les offres absentes d'un snapshot complet sans erreur peuvent être expirées ;
un résultat tronqué, mal formé ou indisponible ne déclenche pas cette opération.
Une annonce ancienne encore affichée est signalée pour vérification plutôt que
présentée automatiquement comme une opportunité récente.

Documentation : [Lever](https://github.com/lever/postings-api),
[Greenhouse](https://docs.greenhouse.io/job-board.html),
[Yassir](https://yassir.com/career/jobs/), [AYRADE](https://www.ayrade.com/recrutement/).

## Sources historiques, désactivées pour les recherches réelles

Les sections suivantes documentent les anciennes fixtures et intégrations.
Arbeitnow et Jobicy ne sont plus interrogés par la commande de recherche réelle,
et leurs lignes historiques sont exclues du matching Algérie.

## Arbeitnow

Le connecteur initial reste disponible. Voir [arbeitnow.md](arbeitnow.md) pour le
contrat, les conditions et la vérification initiale. Une page par défaut, avec un
nombre de pages borné. La couverture reste principalement européenne et ne suffit
pas à couvrir les opportunités algériennes.

## Jobicy

L'API publique actuelle est `https://jobicy.com/api/jobs`. La documentation officielle
décrit une pagination par `nextCursor`, des offres récentes, les champs `jobGeo`,
`jobLevel`, `jobDescription` et une URL canonique Jobicy. L'interface et les réponses
réelles ont été vérifiées le 15 novembre 2026 ; 200 offres ont été collectées sur deux
pages. Le connecteur conserve le nom de source et le lien canonique.

- [Documentation officielle](https://jobicy.com/jobs-rss-feed)
- [Référence publiée par Jobicy](https://github.com/Jobicy/remote-jobs-api)
- [Politique robots consultée](https://jobicy.com/robots.txt)

Le cache local empêche une nouvelle synchronisation pendant une heure, y compris
après un échec partiel. Les curseurs sont transmis comme des valeurs opaques à
l'endpoint fixe, sans suivre de liens reçus. L'absence d'une offre dans la fenêtre
récente ne déclenche pas son expiration automatique.

Le cache local d'une machine ne se partage pas avec une autre instance. Choisir un
seul planificateur quotidien évite les synchronisations simultanées. La documentation
et les taxonomies doivent être revérifiées avant d'ajouter des filtres de source.

## Sources non activées

Remotive a une API documentée, mais son `robots.txt` consulté interdit `/api/*`.
Elle n'a donc pas été activée automatiquement. Emploitic, Greenhouse, Lever et les
sites d'entreprises algériennes restent à intégrer après vérification de chaque accès.
Le projet ne revendique pas encore une couverture complète du marché algérien.

Les fixtures sous `examples/` sont fictives et clairement identifiées. Elles ne sont
pas des offres auxquelles candidater. Les annonces réelles et les caches sont exclus
du dépôt public.
