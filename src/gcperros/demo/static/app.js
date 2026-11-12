// Pantalla «En vivo». Sólo conoce el contrato de /api: el documento de
// Firestore más reloj, posesión, retenidos y deporte. No sabe nada del motor.
"use strict";

const $ = (id) => document.getElementById(id);

function setSplit(id, share, home, away) {
  const bar = $(id);
  const total = (share[home] ?? 0) + (share[away] ?? 0);
  const homePct = total > 0 ? Math.round((100 * share[home]) / total) : 50;
  const [homeBar, awayBar] = bar.children;
  homeBar.style.flexBasis = `${homePct}%`;
  awayBar.style.flexBasis = `${100 - homePct}%`;
  homeBar.textContent = total > 0 ? `${homePct}%` : "";
  awayBar.textContent = total > 0 ? `${100 - homePct}%` : "";
}

// Puntos por cuarto, en baloncesto: Q1…Q4 y las prórrogas que haya.
function renderQuarters(state, home, away) {
  const table = $("quarters");
  table.hidden = !state.periods;
  if (!state.periods) return;
  const count = Math.max(4, ...[home, away].map((team) => state.periods[team]?.length ?? 0));
  const labels = Array.from({ length: count }, (_, i) => (i < 4 ? `Q${i + 1}` : `PR${i - 3}`));
  const cell = (tag, text, cls) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  $("quarters-head").replaceChildren(cell("th", ""), ...labels.map((label) => cell("th", label)));
  $("quarters-body").replaceChildren(
    ...[[home, "home"], [away, "away"]].map(([team, side]) => {
      const row = document.createElement("tr");
      const points = state.periods[team] ?? [];
      row.append(cell("th", team, side), ...labels.map((_, i) => cell("td", points[i] ?? "–")));
      return row;
    }),
  );
}

function render(state) {
  const config = GCP.config;
  const [home, away] = state.teams.length === 2 ? state.teams : ["", ""];
  const score = (team) => state.indicators[team]?.[config.headline] ?? 0;

  $("match-id").textContent = state.match_id;
  $("home-name").textContent = home || "Local";
  $("away-name").textContent = away || "Visitante";
  for (const [id, team] of [["home-goals", home], ["away-goals", away]]) {
    $(id).textContent = score(team);
    $(id).dataset.team = team;
    $(id).dataset.indicator = config.headline;
  }
  $("minute").textContent = config.clock(state.clock);
  $("phase").textContent = phaseLabel(config, state.clock);
  $("pending").textContent = state.pending;
  setSplit("running", state.possession.running_share, home, away);
  setSplit("window", state.possession.window_share, home, away);
  renderQuarters(state, home, away);

  // Para que las piezas siguientes (gráficas, señales) escuchen el mismo flujo.
  document.dispatchEvent(new CustomEvent("gcperros:state", { detail: state }));
}

function setLink(state, text) {
  $("link").dataset.state = state;
  $("link").textContent = text;
}

// El selector: un enlace por partido. Cambiar de deporte recarga la página, así
// cada pantalla empieza limpia y no mezcla la cinta de un partido con la de otro.
function renderSelector(sports, current) {
  $("sports").replaceChildren(
    ...sports.map(({ match_id: matchId, sport }) => {
      const link = document.createElement("a");
      const config = SPORTS[sport] ?? SPORTS.football;
      link.href = `?partido=${encodeURIComponent(matchId)}`;
      link.textContent = `${config.icon} ${config.label}`;
      if (matchId === current) link.setAttribute("aria-current", "true");
      return link;
    }),
  );
  $("sports").hidden = sports.length < 2;
}

function applySport(sport) {
  const config = SPORTS[sport] ?? SPORTS.football;
  Object.assign(GCP, { sport, config });
  document.body.dataset.sport = sport;
  $("signal-hint").textContent = config.signalHint;
  $("estimate-title").textContent = config.estimateTitle;
  $("held").title =
    `La marca de agua retiene cada evento hasta que llega otro más de ${config.lateness} s ` +
    "posterior: así ningún evento atrasado reordena el pasado. Cuenta aquí, a la vista, en vez de esconderse.";
}

async function start() {
  const sports = await (await fetch("/api/sports")).json();
  const wanted = new URLSearchParams(location.search).get("partido");
  const chosen = sports.find((entry) => entry.match_id === wanted) ?? sports[0];
  GCP.matchId = chosen.match_id;
  applySport(chosen.sport);
  renderSelector(sports, chosen.match_id);

  const source = new EventSource(`/api/matches/${encodeURIComponent(GCP.matchId)}/stream`);
  source.onopen = () => setLink("live", "en vivo");
  let seeded = false;
  source.onmessage = (message) => {
    const state = JSON.parse(message.data);
    render(state);
    // Quien llega tarde ve las gráficas desde el principio (#96): el primer
    // estado ya llevó al servidor hasta ahora, así que su historia está entera.
    if (!seeded) {
      seeded = true;
      loadHistory();
    }
    // El servidor cierra el canal al final; sin esto el navegador
    // reconectaría solo y repetiría el final una y otra vez.
    if (state.clock.phase === "final") {
      source.close();
      setLink("ended", "partido terminado");
    }
  };
  source.onerror = () => {
    if (source.readyState !== EventSource.CLOSED) setLink("lost", "reconectando");
  };
}

async function loadHistory() {
  const response = await fetch(`/api/matches/${encodeURIComponent(GCP.matchId)}/history`);
  if (!response.ok) return;
  const points = await response.json();
  document.dispatchEvent(new CustomEvent("gcperros:history", { detail: points }));
}

start().catch(() => setLink("lost", "sin conexión con el servidor"));
