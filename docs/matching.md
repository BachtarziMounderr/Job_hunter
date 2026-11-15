# Moteur de matching et limites

## Pipeline déterministe

Le score final est une somme pondérée : sémantique 35 %, compétences 25 %,
expérience 20 %, formation 10 %, localisation 10 %. `SCORE_WEIGHTS` accepte un
objet JSON ; la somme des poids doit valoir un. Chaque composante est sur 100.
Ces valeurs et le seuil de notification sont des hypothèses à calibrer.

Le modèle multilingue est `paraphrase-multilingual-MiniLM-L12-v2`, avec une révision
fixée et configurable. Le calcul s'effectue sur CPU dans Python. Les textes longs
sont découpés selon la fenêtre de tokens du modèle ; les vecteurs des fenêtres sont
moyennés puis normalisés. La cosinus est calculée avec NumPy. Les cosinus négatives
sont ramenées à zéro pour la composante sémantique ; ce score n'est pas une probabilité.

Les embeddings sont mis en cache par version de modèle et empreinte du texte. Le
snapshot de matching conserve la version du modèle, les poids et une empreinte des
règles Python. Modifier les règles ou le profil produit une nouvelle révision.
Les lectures et écritures sont regroupées pour éviter une requête réseau par score.

Le backend `tfidf` est un baseline lexical explicite utilisant scikit-learn. Il sert
à la démonstration et aux tests hors réseau. Il n'est jamais choisi automatiquement
pour masquer une panne du modèle multilingue et ne fournit pas la même représentation.

## Compétences et classifications

Un lexique versionné détecte les compétences et leurs alias anglais/français avec
des frontières de tokens. Le taux est la proportion de compétences observées dans
l'offre qui sont attestées par ce profil. Une absence d'exigences détectées donne
un score neutre de 50. Les tags de source ne sont pas considérés automatiquement
comme des compétences requises.

La méthode ne distingue pas encore parfaitement « obligatoire » et « souhaitable »,
ni toutes les négations. « Non attestée par ce CV » ne signifie pas « compétence
absente chez le candidat ». Le lexique est fini et peut manquer des technologies.

Les familles de métiers et les niveaux de séniorité sont détectés par règles
inspectables. Les titres senior/lead et les exigences d'expérience nettement trop
élevées bloquent l'envoi. Les années de freelance du profil constituent une indication,
pas une équivalence garantie avec les années d'expérience salariée demandées.
Les diplômes sont comparés par niveaux détectés ; les formulations facultatives ou
les alternatives diplôme/expérience nécessitent encore une calibration.

## Géographie : trois états

`eligible`, `ineligible` et `unknown` sont séparés. Les offres remote doivent indiquer
un périmètre explicite : monde, pays ou région reconnue. EMEA comprend l'Algérie ;
EU/Europe, USA-only et Canada-only ne l'incluent pas. Les exclusions explicites et
les phrases imposant une résidence priment sur un label plus large. Une autorisation
de travail requise mais non configurée entraîne une vérification manuelle.

Une adresse de bureau ne devient pas une restriction remote par simple présence
dans le texte. À l'inverse, un simple booléen `remote=true` ne permet pas de conclure
à une éligibilité mondiale. Les régions/pays non reconnus restent inconnus. Les règles
actuelles visent principalement le profil résidant en Algérie ; la table des régions
n'est pas un annuaire géopolitique exhaustif pour tous les pays.

La géographie est une règle bloquante indépendante du score total : un score élevé
ne compense pas une incompatibilité ou une inconnue. Les hypothèses de résidence et
d'autorisation de travail doivent être vérifiées dans les profils privés.

## Évaluation

```powershell
.\.venv\Scripts\python.exe -m app evaluate --backend tfidf
.\.venv\Scripts\python.exe -m app evaluate --output reports/evaluation_semantic.json
```

Le jeu initial comporte 22 paires offre/profil synthétiques, six positives et seize
négatives. Les labels ont été rédigés pendant l'implémentation et restent à relire par
le candidat. Les deux backends ont atteint précision/rappel/F1 de 1 sur ces cas simples.
Ce résultat vérifie le câblage et quelques règles ; il ne mesure pas la qualité réelle
d'un moteur de recommandation et ne constitue pas une validation scientifique.

La prochaine évaluation doit annoter des offres réelles, inclure les cas ambigus et
les erreurs, séparer calibration et test, puis mesurer aussi la pertinence du top-k.
Aucune métrique issue du jeu synthétique ne doit être présentée comme une performance
sur le marché réel de l'emploi.
