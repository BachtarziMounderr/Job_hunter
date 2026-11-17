# Connecter les alertes emploi à Gmail

Cette configuration se fait une seule fois. Ensuite, GitHub Actions lit les
alertes reçues et envoie les résultats sur Telegram, même lorsque ton PC est éteint.
Job Hunter ne se connecte pas à LinkedIn ou Emploitic et ne suit pas les liens de
suivi des emails. La connexion Gmail de ChatGPT est indépendante de celle du projet.

## 1. Créer les alertes de recherche

Depuis le dossier du projet, avec l'environnement Python actif :

```powershell
python -m app alert-plan
```

Ouvre `private/alert-plan.html`. Les recherches proposées viennent des trois
orientations de tes CV, en français et en anglais. Vérifie **Algérie** dans le
champ localisation de chaque plateforme et active les alertes email quotidiennes.
Le plan respecte la limite de 20 alertes LinkedIn actives.
Les emails d'EmploiPartner et AlgerieJob sont également pris en charge ; la
 disponibilité et l'activation de leurs alertes se vérifient sur leurs sites.

## 2. Ranger les emails dans un libellé Gmail

Crée le libellé **JobHunter/Alerts**. Dans Gmail → Paramètres → Filtres et adresses
bloquées → Créer un filtre, utilise les domaines des alertes effectivement reçues :

```text
{from:linkedin.com from:emploitic.com from:emploipartner.com from:algeriejob.com}
```

Applique le libellé aux messages correspondants. Pour LinkedIn, affine le filtre
avec l'expéditeur exact d'une alerte emploi (« Filtrer les messages similaires »),
afin que les notifications du réseau ne consomment pas le quota de lecture.
Applique aussi le filtre aux anciennes alertes si tu veux les inclure au premier test.

Le collecteur exige ce libellé et vérifie les domaines des expéditeurs et des liens
d'annonces. Il ne change ni les libellés ni l'état lu/non lu, et n'envoie aucun email.

## 3. Créer un client OAuth Google

1. Ouvre [Google Cloud Console](https://console.cloud.google.com/) et crée ou
   sélectionne un projet personnel, par exemple **Job Hunter**.
2. Dans **API et services → Bibliothèque**, active **Gmail API**.
3. Dans **Google Auth Platform**, configure le nom de l'application, ton adresse
   de contact et l'audience. Pour un compte Gmail personnel, choisis **External**.
   En mode **Testing**, ajoute ton adresse Gmail dans les utilisateurs de test.
4. Dans **Clients**, crée un client OAuth de type **Application de bureau / Desktop app**.
5. Télécharge le JSON et enregistre-le dans le projet sous
   `private/google-client.json`.

L'autorisation demandée est `gmail.readonly`. Google l'accorde sur toute la boîte
mail ; c'est le code du projet qui limite les lectures au libellé choisi. Tu peux
utiliser une boîte dédiée aux recherches d'emploi.

**Pour une utilisation durable :** les jetons d'une application External laissée
en mode Testing expirent normalement après sept jours avec les permissions Gmail.
Vérifie le statut de publication avant l'autorisation définitive. Google prévoit
une exemption de vérification publique pour certains usages personnels ; les
règles d'une organisation peuvent être différentes.

Références : [OAuth pour applications de bureau](https://developers.google.com/identity/protocols/oauth2/native-app),
[expiration des jetons](https://developers.google.com/identity/protocols/oauth2),
[exemption pour usage personnel](https://support.google.com/cloud/answer/13464323).

## 4. Autoriser la lecture une fois sur ton PC

Dans PowerShell, à la racine du projet :

```powershell
.\.venv\Scripts\python.exe scripts/setup_gmail.py --client private/google-client.json
```

Connecte-toi au compte qui reçoit les alertes et valide l'autorisation Google.
Le script utilise une adresse de retour locale, avec vérifications state et PKCE.
Il crée `private/gmail-oauth.json` et met à jour le `.env` local automatiquement,
sans afficher les jetons ou le secret du client. Ces fichiers sont exclus de Git
et de l'image Docker. Ne les envoie pas dans le chat.

Pour vérifier ensuite :

```powershell
.\.venv\Scripts\python.exe -m app doctor
.\.venv\Scripts\python.exe -m app collect --source alerts
```

Un libellé absent, une autorisation expirée ou une erreur du fournisseur sont
signalés. Une boîte sans alerte reconnue peut produire zéro annonce sans erreur.

## 5. Activer la lecture dans GitHub Actions

Dans le dépôt GitHub → **Settings → Secrets and variables → Actions** :

| Emplacement | Nom | Valeur |
| --- | --- | --- |
| Repository secret | `GMAIL_OAUTH_JSON` | Tout le contenu de `private/gmail-oauth.json` |
| Repository variable | `GMAIL_ENABLED` | `true` |
| Repository variable | `GMAIL_LABEL` | `JobHunter/Alerts` |

Les identifiants vont dans **Secrets**. Aucun mot de passe LinkedIn, cookie ou
profil de navigateur n'est nécessaire.

Puis ouvre **Actions → Daily discovery → Run workflow**, sélectionne
**smoke-test** et lance le test. Le résultat et le statut d'exécution arrivent sur
Telegram. Les prochaines recherches quotidiennes utilisent automatiquement Gmail.

Le collecteur lit les 14 derniers jours, avec une limite de messages par recherche.
Les identifiants stables et l'historique Neon limitent les répétitions. Une alerte
arrivée après midi sera examinée à l'exécution suivante. Les extraits d'email sont
signalés **À VÉRIFIER**, car ils ne fournissent pas toujours la fiche complète.
