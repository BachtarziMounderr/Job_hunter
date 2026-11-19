# Centre de contrôle React + FastAPI

Le dashboard rassemble les offres disponibles, les candidatures faites, les postes
mis de côté et les bilans des recherches. Il utilise la même base Neon que GitHub
Actions. Les données de suivi sont persistantes : fermer le navigateur ou arrêter
le backend ne supprime pas les statuts.

## Démarrer

Dans PowerShell à la racine du projet :

```powershell
.\scripts\start-dashboard.ps1
```

Puis ouvre **http://127.0.0.1:8000**. Le script prépare les dépendances manquantes,
construit React et démarre FastAPI. `Ctrl+C` arrête le serveur.
Une fois le projet installé, tu peux aussi double-cliquer **Start Dashboard.cmd**.

Les fichiers privés `.env` puis `.env.neon` sont chargés par le backend ; les
variables système gardent la priorité. La seconde configuration fournit la base
Neon existante. Les migrations Alembic sont appliquées au démarrage, avec l'URL
directe pour les migrations. Aucune clé n'est envoyée au navigateur.

Installation manuelle :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-api.lock -e '.[api,postgres]'
npm --prefix frontend ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m scripts.dashboard
```

## Utiliser le suivi

- **Offres disponibles** contient un seul exemplaire de chaque poste compatible,
  avec le CV conseillé, le score, les compétences et les réserves.
- **Candidater** enregistre le statut « Candidature faite », puis ouvre la fiche
  de recrutement dans un nouvel onglet. Si l'enregistrement échoue, l'offre reste
  disponible et un message d'erreur s'affiche.
- **Candidatures faites** conserve la date du classement. Ce statut correspond au
  clic sur le bouton ; le programme ne peut pas confirmer que tu as terminé le
  formulaire externe. **Remettre disponible** permet d'annuler ce classement.
- L'icône d'archive range un poste dans **Offres mises de côté**. Tu peux le restaurer.
- **Historique des recherches** affiche le bilan, le nombre de nouvelles offres
  et les éventuelles sources indisponibles.
- Le champ de recherche, le filtre par CV et le tri s'appliquent aux résultats.
  **Ajoutées aujourd'hui** affiche les nouvelles entrées dans le suivi.

Une offre retirée de son site n'apparaît plus parmi les disponibles après une
collecte complète de cette source. Une candidature faite reste dans l'historique.
Une collecte partielle ne permet pas d'inférer qu'une annonce a disparu.

## Une seule proposition par offre

Chaque opportunité a une identité persistante fondée sur l'entreprise, le titre
et la ville normalisée. L'URL de candidature permet aussi de reconnaître un poste
dont le titre a été modifié. Les orientations de CV et les sources peuvent varier
sans recréer le même poste dans le dashboard.

Le premier lancement importe les scores déjà enregistrés et les anciens envois.
Ces anciennes offres restent accessibles, mais ne sont pas annoncées à nouveau.
Les rapports Telegram suivants contiennent uniquement les offres pas encore
annoncées. S'il n'y en a aucune, le bilan l'indique sans répéter les anciens liens.
Une réponse Telegram perdue met l'envoi en quarantaine pour éviter un doublon.

Les offres non traitées restent dans les disponibles : elles ne sont pas créées
à nouveau chaque jour. Leur date d'ajout reste la même. Une nouvelle collecte ne
réinitialise jamais une candidature faite ou un classement manuel.

Deux recrutements distincts avec exactement la même entreprise, le même titre et
la même ville peuvent être rapprochés par cette règle volontairement conservatrice.
Les intitulés très différents ou une entreprise non précisée peuvent nécessiter
un rapprochement manuel ultérieur.

## Actualisation quotidienne

GitHub Actions reste le planificateur : `0 11 * * *`, soit **12 h en Algérie**.
Il collecte, compare les offres avec les CV, met à jour Neon et enregistre le bilan.
Il fonctionne même lorsque ton PC est éteint. GitHub peut retarder un démarrage.

Quand il est ouvert, le dashboard relit les données toutes les 30 secondes et à
ton retour sur l'onglet. **Actualiser** recharge les résultats ; ce bouton ne lance
pas une nouvelle collecte. Tu peux lancer une recherche manuelle dans GitHub
Actions → Daily discovery → Run workflow. Le mode `daily` conserve la protection
contre deux bilans quotidiens confirmés pour la même date algérienne.

Le backend local sert uniquement le centre de contrôle. Il n'ajoute pas un second
planificateur, ce qui évite les collectes concurrentes et les doubles notifications.
Il est lié à `127.0.0.1` : aucun hébergement public ni abonnement n'est ajouté.
Pour une utilisation distante, prévoir séparément l'hébergement et l'authentification.

## Développement

```powershell
.\.venv\Scripts\python.exe -m scripts.dashboard
# Dans un autre terminal :
npm --prefix frontend run dev
```

Vite relaie `/api` vers le backend local. L'interface et l'API de production sont
servies sur la même origine. Les écritures exigent un jeton de protection obtenu
depuis l'API et les origines étrangères sont refusées.

Les principales routes sont `GET /api/dashboard` et
`POST /api/opportunities/{id}/status`. La liste est filtrée et paginée côté serveur.
Les réponses contiennent les données des offres et les scores, jamais les CV,
les clés de fournisseur ou les URLs de connexion à la base.
