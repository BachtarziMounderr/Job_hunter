# Sources vérifiées

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
