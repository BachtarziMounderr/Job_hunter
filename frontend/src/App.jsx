import React, { useCallback, useEffect, useRef, useState } from "react";

const viewNames = {
  available: "Offres disponibles",
  applied: "Candidatures faites",
  dismissed: "Offres mises de côté",
  history: "Historique des recherches",
};
const runNames = {
  success: "Terminée",
  partial: "Partielle",
  failure: "En échec",
  running: "En cours",
};
const formatter = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Africa/Algiers",
});
const date = (value) =>
  value ? formatter.format(new Date(value)) : "Non précisée";

function Icon({ name, size = 20 }) {
  const paths = {
    briefcase: "M8 7V4h8v3M3 7h18v14H3zM3 12h18M11 10h2v5h-2",
    grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    check: "m5 12 4 4L19 6",
    clock: "M12 8v5l3 2M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0",
    search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    refresh:
      "M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3",
    archive: "M3 3h18v5H3zM5 8v13h14V8M9 12h6",
    pin: "M12 22s8-8 8-14a8 8 0 0 0-16 0c0 6 8 14 8 14M15 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    close: "m6 6 12 12M6 18 18 6",
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.briefcase} />
    </svg>
  );
}

function Run({ run }) {
  const collection = run.details?.collection;
  return (
    <li className="run-row">
      <span className={`run-dot ${run.status}`} />
      <div>
        <strong>
          {run.mode === "bootstrap"
            ? "Import des résultats existants"
            : "Recherche en Algérie"}
        </strong>
        <p>{date(run.started_at)}</p>
        {collection ? (
          <p>
            {collection.records_received} annonces ·{" "}
            {run.details.new_count ?? 0} nouvelle(s) offre(s)
          </p>
        ) : null}
        {run.details?.error ? (
          <p className="error-text">{run.details.error}</p>
        ) : null}
      </div>
      <span className={`run-status ${run.status}`}>
        {runNames[run.status] || run.status}
      </span>
    </li>
  );
}

function Job({ job, busy, onState, onApply }) {
  const [expanded, setExpanded] = useState(false);
  const company = job.company || "Entreprise";
  return (
    <article className="job-card">
      <div className="job-heading">
        <div className="company-mark" aria-hidden="true">
          {company.slice(0, 2).toUpperCase()}
        </div>
        <div className="job-title">
          <p className="company-name">{company}</p>
          <h2>{job.title}</h2>
          <p className="job-location">
            <Icon name="pin" size={14} /> {job.location || "Algérie"}
          </p>
        </div>
        <div className="job-score">
          <strong>
            {job.score.toFixed(1)}
            <small>/100</small>
          </strong>
          <span>Compatibilité</span>
        </div>
      </div>
      <div className="job-tags">
        <span className="profile-tag">{job.best_profile}</span>
        <span
          className={
            job.category === "recommended" ? "recommended-tag" : "review-tag"
          }
        >
          {job.category === "recommended" ? "Recommandée" : "À vérifier"}
        </span>
        <span className="added-date">
          Ajoutée le{" "}
          {new Date(job.discovered_at).toLocaleDateString("fr-FR", {
            timeZone: "Africa/Algiers",
          })}
        </span>
      </div>
      <div className="skills">
        {job.matched_skills.slice(0, 5).map((skill) => (
          <span key={skill}>{skill}</span>
        ))}
        {!job.matched_skills.length ? (
          <span>Compétences à confirmer sur la fiche</span>
        ) : null}
      </div>
      {job.review_reasons.length ? (
        <p className="job-note">{job.review_reasons[0]}</p>
      ) : null}
      {job.status === "applied" ? (
        <p className="applied-date">
          <Icon name="check" size={15} /> Candidature marquée le{" "}
          {date(job.applied_at)}
        </p>
      ) : null}
      {expanded ? (
        <div className="job-details" id={`details-${job.id}`}>
          <h3>Avant de candidater</h3>
          <p>
            Le score est un indice de compatibilité, pas une probabilité
            d’embauche.
          </p>
          <ul>
            {(job.review_reasons.length
              ? job.review_reasons
              : ["Aucune réserve détectée par les critères configurés."]
            ).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          {job.missing_skills.length ? (
            <p>
              <strong>Compétences à confirmer :</strong>{" "}
              {job.missing_skills.join(", ")}.
            </p>
          ) : null}
          <h3>Comparaison avec tes profils</h3>
          <div className="profile-comparisons">
            {job.profiles.map((profile) => (
              <div key={profile.name}>
                <span>{profile.name}</span>
                <strong>{profile.total_score.toFixed(1)}/100</strong>
                <small>
                  {profile.exclusion_codes.length
                    ? "Critère bloquant"
                    : profile.review_reasons.length
                      ? "À vérifier"
                      : "Compatible"}
                </small>
              </div>
            ))}
          </div>
          <p className="source-line">
            Source : {job.source} · Dernière présence :{" "}
            {date(job.source_last_seen_at)}
          </p>
          <p className="source-line">Publication : {date(job.published_at)}</p>
        </div>
      ) : null}
      <div className="job-footer">
        <button
          className="details-button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={`details-${job.id}`}
        >
          {expanded ? "Réduire les détails" : "Voir les détails"}
        </button>
        <div className="job-actions">
          {job.status === "available" ? (
            <>
              <button
                className="icon-button"
                disabled={busy}
                onClick={() => onState(job, "dismissed")}
                title="Mettre de côté"
                aria-label={`Mettre de côté ${job.title}`}
              >
                <Icon name="archive" size={18} />
              </button>
              <a
                className={`apply-button ${busy ? "disabled" : ""}`}
                href={job.application_url}
                target="_blank"
                rel="noreferrer noopener"
                aria-disabled={busy}
                onClick={(event) => onApply(event, job)}
              >
                {busy ? "Enregistrement…" : "Candidater"}
                <Icon name="briefcase" size={16} />
              </a>
            </>
          ) : (
            <>
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => onState(job, "available")}
              >
                {busy ? "Enregistrement…" : "Remettre disponible"}
              </button>
              <a
                className="offer-link"
                href={job.application_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                Revoir l’offre
              </a>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

export default function App() {
  const [view, setView] = useState("available");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [profile, setProfile] = useState("");
  const [newOnly, setNewOnly] = useState(false);
  const [sort, setSort] = useState("score");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(new Set());
  const [toast, setToast] = useState("");
  const [refreshed, setRefreshed] = useState(null);
  const abort = useRef(null);
  const latest = useRef(0);
  const locks = useRef(new Set());
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(q);
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [q]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  const load = useCallback(async () => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const requestId = ++latest.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        status: view === "history" ? "available" : view,
        q: query,
        profile,
        new_only: String(newOnly && view === "available"),
        sort,
        page: String(page),
      });
      const response = await fetch(`/api/dashboard?${params}`, {
        signal: controller.signal,
      });
      const value = await response.json();
      if (!response.ok)
        throw new Error(value.detail || "Impossible de charger les résultats.");
      if (requestId === latest.current) {
        setData(value);
        setError("");
        setRefreshed(new Date());
      }
    } catch (err) {
      if (err.name !== "AbortError")
        setError(err.message || "Connexion au backend indisponible.");
    } finally {
      if (requestId === latest.current) setLoading(false);
    }
  }, [view, query, profile, newOnly, sort, page]);
  useEffect(() => {
    load();
    return () => abort.current?.abort();
  }, [load]);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible" && !locks.current.size) load();
    };
    const timer = setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);

  async function change(job, status) {
    const response = await fetch(`/api/opportunities/${job.id}/status`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Job-Hunter-CSRF": data.csrf_token,
      },
      body: JSON.stringify({ status }),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.detail || "Le changement n’a pas été enregistré.");
    return result;
  }
  async function action(job, status, popup = null) {
    if (locks.current.has(job.id)) {
      popup?.close();
      return;
    }
    locks.current.add(job.id);
    setBusy(new Set(locks.current));
    abort.current?.abort();
    ++latest.current;
    try {
      const result = await change(job, status);
      if (status === "applied") {
        if (popup) popup.location.href = result.application_url;
        else window.location.assign(result.application_url);
      }
      setToast(
        status === "applied"
          ? "Offre déplacée dans « Candidatures faites »."
          : status === "available"
            ? "Offre remise dans les disponibles."
            : "Offre mise de côté.",
      );
      await load();
    } catch (err) {
      popup?.close();
      setError(err.message);
    } finally {
      locks.current.delete(job.id);
      setBusy(new Set(locks.current));
      setLoading(false);
    }
  }
  function apply(event, job) {
    event.preventDefault();
    if (locks.current.has(job.id)) return;
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    action(job, "applied", popup);
  }
  function navigate(next) {
    setView(next);
    setPage(1);
    setQ("");
    setQuery("");
    setProfile("");
    setNewOnly(false);
  }
  const stats = data?.stats || {
    available: 0,
    applied: 0,
    dismissed: 0,
    new_today: 0,
  };
  const lastRun = data?.history[0];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Job Hunter, accueil">
          <span className="brand-icon">
            <Icon name="briefcase" size={24} />
          </span>
          <span>
            Job Hunter<small>Ton espace de candidature</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="country-mark">DZ</span>
          <div>
            Marché algérien<small>Veille personnelle</small>
          </div>
        </div>
        <nav aria-label="Navigation principale">
          {[
            ["available", "grid"],
            ["applied", "check"],
            ["dismissed", "archive"],
            ["history", "clock"],
          ].map(([key, icon]) => (
            <button
              key={key}
              className={`nav-item ${view === key ? "active" : ""}`}
              onClick={() => navigate(key)}
              aria-current={view === key ? "page" : undefined}
            >
              <Icon name={icon} />
              <span>{viewNames[key]}</span>
              {key !== "history" ? <strong>{stats[key]}</strong> : null}
            </button>
          ))}
        </nav>
        <div className="schedule-sidebar">
          <Icon name="clock" />
          <strong>Chaque jour à midi</strong>
          <p>Les recherches continuent même lorsque ton PC est éteint.</p>
          <span>Heure d’Algérie</span>
        </div>
        <div className="sidebar-bottom">
          <span className="connection-dot" />
          {error ? "Connexion à vérifier" : "Espace personnel"}
          <small>React + FastAPI</small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            Centre de contrôle <span className="topbar-divider">/</span>{" "}
            <strong>{viewNames[view]}</strong>
          </span>
          <span className="topbar-country">Algérie uniquement</span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="today-label">
                {new Intl.DateTimeFormat("fr-FR", {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                  timeZone: "Africa/Algiers",
                }).format(new Date())}
              </p>
              <h1>
                {view === "available"
                  ? "Tes prochaines candidatures"
                  : viewNames[view]}
              </h1>
              <p>
                {view === "available"
                  ? "Des offres réunies pour tes profils. Une seule proposition par poste."
                  : view === "applied"
                    ? "Les offres dont tu as ouvert le lien pour candidater."
                    : view === "dismissed"
                      ? "Les postes que tu as choisis de garder de côté."
                      : "Le déroulement de ta veille, recherche après recherche."}
              </p>
            </div>
            <button
              className="refresh-button"
              onClick={load}
              disabled={loading}
            >
              <Icon name="refresh" size={17} />
              {loading ? "Actualisation…" : "Actualiser"}
            </button>
          </div>
          <section className="stat-strip" aria-label="Suivi des opportunités">
            <div>
              <span>Ajoutées aujourd’hui</span>
              <strong>{data ? stats.new_today : "—"}</strong>
              <small>De nouvelles entrées dans ton suivi</small>
            </div>
            <div>
              <span>Offres disponibles</span>
              <strong>{data ? stats.available : "—"}</strong>
              <small>Prêtes à être examinées</small>
            </div>
            <div>
              <span>Candidatures faites</span>
              <strong>{data ? stats.applied : "—"}</strong>
              <small>Classées depuis le bouton Candidater</small>
            </div>
          </section>
          {error ? (
            <div className="error-banner" role="alert">
              <strong>Une action demande ton attention.</strong>
              <p>{error}</p>
              <button onClick={load}>Réessayer</button>
            </div>
          ) : null}
          <div className="content-grid">
            <section className="results-section" aria-label={viewNames[view]}>
              {view === "history" ? (
                <div className="history-panel">
                  <h2>Les dernières recherches</h2>
                  {data?.history.length ? (
                    <ul className="run-list">
                      {data.history.map((run) => (
                        <Run key={run.id} run={run} />
                      ))}
                    </ul>
                  ) : (
                    <div className="empty-state">
                      <Icon name="clock" size={28} />
                      <h3>La prochaine recherche apparaîtra ici</h3>
                      <p>
                        La veille est programmée à 12 h en Algérie. Son bilan
                        sera enregistré automatiquement.
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className="filter-panel">
                    <div className="search-field">
                      <Icon name="search" size={19} />
                      <input
                        aria-label="Rechercher une offre"
                        placeholder="Poste, entreprise ou ville…"
                        value={q}
                        onChange={(event) => setQ(event.target.value)}
                      />
                    </div>
                    <select
                      aria-label="Filtrer par profil"
                      value={profile}
                      onChange={(event) => {
                        setProfile(event.target.value);
                        setPage(1);
                      }}
                    >
                      <option value="">Tous mes profils</option>
                      {data?.profiles.map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="result-toolbar">
                    <div>
                      {view === "available" ? (
                        <>
                          <button
                            className={!newOnly ? "chip selected" : "chip"}
                            onClick={() => {
                              setNewOnly(false);
                              setPage(1);
                            }}
                          >
                            Toutes les disponibles
                          </button>
                          <button
                            className={newOnly ? "chip selected" : "chip"}
                            onClick={() => {
                              setNewOnly(true);
                              setPage(1);
                            }}
                          >
                            Ajoutées aujourd’hui
                          </button>
                        </>
                      ) : (
                        <span>{data?.total ?? 0} offre(s)</span>
                      )}
                    </div>
                    <select
                      aria-label="Trier les offres"
                      value={sort}
                      onChange={(event) => {
                        setSort(event.target.value);
                        setPage(1);
                      }}
                    >
                      <option value="score">Par pertinence</option>
                      <option value="recent">Plus récentes</option>
                    </select>
                  </div>
                  {!data && loading ? (
                    <div className="empty-state" role="status">
                      <Icon name="refresh" size={28} />
                      <h3>Chargement de ton espace</h3>
                      <p>Connexion aux résultats enregistrés…</p>
                    </div>
                  ) : null}
                  {data?.items.map((job) => (
                    <Job
                      key={job.id}
                      job={job}
                      busy={busy.has(job.id)}
                      onState={action}
                      onApply={apply}
                    />
                  ))}
                  {data && !data.items.length ? (
                    <div className="empty-state">
                      <Icon
                        name={view === "applied" ? "briefcase" : "search"}
                        size={32}
                      />
                      <h3>
                        {view === "applied"
                          ? "Ta première candidature commence ici"
                          : newOnly
                            ? "Pas de nouvelle entrée aujourd’hui"
                            : "Aucune offre dans cette sélection"}
                      </h3>
                      <p>
                        {view === "applied"
                          ? "Clique sur Candidater depuis une offre disponible. Elle sera classée dans cet espace."
                          : "Les offres déjà connues ne sont pas proposées à nouveau. Tu peux aussi modifier tes filtres."}
                      </p>
                      {view === "applied" ? (
                        <button
                          className="secondary-button"
                          onClick={() => navigate("available")}
                        >
                          Voir les offres disponibles
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  {data && data.total > data.limit ? (
                    <div className="pagination">
                      <button
                        disabled={page <= 1 || loading}
                        onClick={() => setPage((v) => v - 1)}
                      >
                        Précédent
                      </button>
                      <span>
                        Page {page} sur {Math.ceil(data.total / data.limit)}
                      </span>
                      <button
                        disabled={page * data.limit >= data.total || loading}
                        onClick={() => setPage((v) => v + 1)}
                      >
                        Suivant
                      </button>
                    </div>
                  ) : null}
                  {view === "applied" ? (
                    <p className="tracking-note">
                      Le classement est enregistré à l’ouverture du lien. Il ne
                      confirme pas l’envoi du formulaire sur le site de
                      recrutement. Utilise « Remettre disponible » si
                      nécessaire.
                    </p>
                  ) : null}
                </>
              )}
            </section>
            <aside className="activity-column">
              <section className="daily-card">
                <div className="daily-icon">
                  <Icon name="clock" size={23} />
                </div>
                <h2>Ta veille est programmée</h2>
                <p className="daily-time">
                  12:00 <span>chaque jour</span>
                </p>
                <p>
                  La recherche alimente automatiquement cet espace. GitHub peut
                  retarder son démarrage.
                </p>
                <div className="next-run">
                  <span>Prochain créneau</span>
                  <strong>{date(data?.schedule.next_run)}</strong>
                  <small>Africa/Algiers</small>
                </div>
              </section>
              <section className="activity-card">
                <div className="section-heading">
                  <h2>Dernière recherche</h2>
                  <button onClick={() => navigate("history")}>
                    Historique
                  </button>
                </div>
                {lastRun ? (
                  <ul className="run-list">
                    <Run run={lastRun} />
                  </ul>
                ) : (
                  <p className="muted">
                    Le premier bilan sera affiché après la prochaine recherche.
                  </p>
                )}
                <p className="sync-time">
                  Dashboard actualisé{" "}
                  {refreshed
                    ? refreshed.toLocaleTimeString("fr-FR", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "…"}
                </p>
              </section>
              <section className="source-card">
                <h2>Ce que tu explores</h2>
                <p>
                  <span className="source-dot" /> Yassir · site carrière
                </p>
                <p>
                  <span className="source-dot" /> AYRADE · site carrière
                </p>
                <div className="source-divider" />
                <p className="muted">LinkedIn et Emploitic</p>
                <small>
                  {data?.sources.gmail_enabled
                    ? "Lecture des alertes Gmail activée."
                    : "En attente de la configuration des alertes Gmail."}
                </small>
                <p className="coverage-note">
                  Les résultats couvrent les sources connectées, pas tout le
                  marché algérien.
                </p>
              </section>
            </aside>
          </div>
          <footer>
            Les scores aident à choisir les fiches à lire. La décision de
            candidater reste la tienne.
          </footer>
        </main>
      </div>
      {toast ? (
        <div className="toast" role="status">
          <Icon name="check" size={19} />
          <span>{toast}</span>
          <button
            onClick={() => setToast("")}
            aria-label="Fermer la notification"
          >
            <Icon name="close" size={17} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
