# Lire les résultats et candidater

La veille quotidienne envoie **un seul document HTML sur Telegram**, accompagné
d'un résumé court et de boutons vers les huit premières annonces à explorer.
Le rapport contient **toutes les offres analysées**, y compris celles déjà vues.
Les messages techniques de réussite CI et Daily discovery sont masqués par défaut.
Les échecs et annulations restent signalés sur Telegram.

## Ouvrir le rapport

Télécharge `latest.html` depuis le message Telegram et ouvre-le dans ton navigateur.
Sur ordinateur, une copie locale est disponible dans `reports/latest.html` après
la génération du rapport. Aucun compte ni serveur web n'est nécessaire pour le lire.
Si l'aperçu Telegram ne permet pas les filtres, ouvre le fichier dans un navigateur.
Sans JavaScript, les annonces et leurs liens restent lisibles.

1. Choisis **Full Stack**, **Data Science** ou **AI Engineer** dans « Profil conseillé ».
2. Lis les pistes de l'onglet **À explorer**, classées par pertinence.
3. Déplie **Pourquoi ce résultat ?** pour voir les réserves et les comparaisons
   avec les autres CV.
4. Clique sur **Voir l'offre et postuler**. Tu accèdes au site de recrutement et
   peux y envoyer le CV correspondant. Le programme n'envoie aucune candidature.

Les boutons sous le message Telegram donnent aussi un accès direct aux annonces.
Les autres offres restent disponibles dans le fichier joint.

## Comprendre les catégories

| Catégorie | Interprétation |
| --- | --- |
| Recommandée | Les critères configurés sont satisfaits, sans réserve détectée, et le score atteint le seuil de recommandation (65/100 par défaut). |
| À vérifier | Une piste compatible, avec une information manquante, une publication ancienne, une exigence à confirmer ou un score plus faible. Elle reste consultable et peut justifier une candidature après lecture. |
| Écartée | Un critère bloque la sélection, ou le score est trop faible. L'annonce et les motifs restent disponibles dans l'onglet correspondant. |

**Un score de 77,5/100 ne signifie pas 77,5 % de chances d'être recruté.** C'est un
indice calculé à partir du texte, des compétences, de l'expérience, de la formation
et de la localisation. Un poste peut dépasser 65 et rester « À vérifier ».

« Publication ancienne » signifie que l'entreprise liste encore l'annonce, mais
que son ancienneté impose de vérifier l'ouverture du recrutement. « Expérience non
précisée » signifie que le texte n'a pas permis de la confirmer ; ce n'est pas un refus.

## Comprendre les anciens compteurs

Dans le résultat du 17 novembre 2026 :

- **74 annonces** : celles remontées par les deux sites d'entreprises.
- **10 offres analysées** : les postes conservés dans tes métiers après filtrage.
- **30 comparaisons** : 10 offres comparées à chacun de tes 3 profils.
- **0 recommandation ferme** et **7 pistes à vérifier** : sept postes sont à lire,
  même si aucun n'a été sélectionné sans réserve.
- **Comparaisons exclues pour métier/expérience** : cela concernait un couple
  offre–profil, pas forcément l'offre pour tous tes CV. Les motifs pouvaient se cumuler.

Le nouveau rapport présente d'abord les postes et les actions possibles. La
couverture des sources et les limites restent accessibles en bas du document.
Une source indisponible peut laisser apparaître des offres conservées auparavant ;
le rapport le signale et affiche la date de dernière présence dans la source.
La présence dans une source ne garantit pas que le recrutement soit encore ouvert.

## Régénérer un rapport local

Avec la base et les profils configurés dans ton environnement :

```powershell
python -m app report
python -m app report --send
```

`report` utilise les annonces enregistrées, sans nouvelle collecte. `--send` envoie
un seul document Telegram. Pour une nouvelle collecte avec rapport :

```powershell
python -m app run --notify
```

Le mode quotidien conserve la protection contre les doublons de rapport par date.
Une livraison Telegram incertaine n'est pas renvoyée automatiquement.
`NOTIFICATION_FORMAT=individual` réactive l'ancien comportement par offre ; le
workflow GitHub quotidien impose désormais `digest`.
La variable GitHub `TELEGRAM_WORKFLOW_SUCCESSES=true` permet de réactiver les
messages techniques de réussite si nécessaire.

## Étape suivante : candidatures

La lecture du rapport et les liens de candidature fonctionnent dès maintenant.
Une future automatisation devra suivre séparément l'état de chaque candidature
et s'adapter au site cible. Les envois de CV et formulaires ne sont pas activés
dans cette version.
