# Vérification du connecteur Arbeitnow

Relevé effectué le **15 novembre 2026**. Aucune authentification utilisée.

## Sources primaires consultées

- https://www.arbeitnow.com/blog/job-board-api
- https://documenter.getpostman.com/view/18545278/UVJbJdKh
- https://www.arbeitnow.com/api/job-board-api
- https://www.arbeitnow.com/robots.txt
- https://www.arbeitnow.com/terms (section 11 : API)

L'article officiel présente une API publique sans clé et renvoie vers Postman. La
page Postman est accessible, mais son contenu dynamique n'a pas été extrait ; le
contrat utilisé ici a été vérifié directement sur la réponse JSON de l'API.

## Observations HTTP

Un GET de l'endpoint public a renvoyé HTTP 200, `application/json`, et 300 annonces.
L'enveloppe contient `data`, `links`, `meta`. Un élément réel contenait les clés :

```text
slug, company_name, title, description, remote, url,
tags, job_types, location, created_at
```

`created_at` est un timestamp Unix numérique. `description` contient du HTML.
`remote` est booléen. `links.next` indiquait la page 2. Les métadonnées décrivent
une pagination `?page=N` et une actualisation horaire ; il s'agit d'informations
fournisseur, pas d'une garantie de disponibilité.

`robots.txt` autorisait les chemins ordinaires, avec une exclusion pour un paramètre
de suivi. Le connecteur n'utilise que l'API documentée. Les conditions de l'API
demandent un lien retour vers Arbeitnow et permettent la révocation d'accès. Ce
document ne constitue pas une analyse juridique des droits de republication.

## Politique du connecteur

Une page par défaut ; maximum configurable limité à dix. Pas de collecte sur les
pages individuelles, de concurrence HTTP ou de scraping HTML. Au plus trois essais
par page par défaut, uniquement pour les erreurs de transport et statuts transitoires
408/429/500/502/503/504. Les autres erreurs et redirections arrêtent cette source.

Le backoff est exponentiel. `Retry-After` en secondes ou date HTTP est pris en compte.
Un délai demandé supérieur à une minute fait arrêter la source plutôt que réessayer
trop tôt. Une pause configurable sépare les pages. L'URL de chaque requête est
reconstruite depuis l'endpoint fixe : une URL reçue dans les données ne peut pas
rediriger la collecte vers un autre hôte.

L'attribution figure dans le README et dans les résultats de `jobs`. L'exécution
locale vise un usage personnel. Une éventuelle interface publique devra conserver
cette attribution et faire réexaminer les conditions actuelles du fournisseur.
