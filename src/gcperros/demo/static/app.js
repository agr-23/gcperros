// Pantalla «En vivo». Sólo conoce el contrato de /api: el documento de
// Firestore más reloj, posesión y retenidos. No sabe nada del motor.
"use strict";

const $ = (id) => document.getElementById(id);

const PHASES = {
  previa: "previa",
  "parte-1": "primera parte",
  descanso: "descanso",
  "parte-2": "segunda parte",
  final: "final",
};

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

function render(state) {
  const [home, away] = state.teams.length === 2 ? state.teams : ["", ""];
  const goals = (team) => state.indicators[team]?.goals ?? 0;

  $("match-id").textContent = state.match_id;
  $("home-name").textContent = home || "Local";
  $("away-name").textContent = away || "Visitante";
  $("home-goals").textContent = goals(home);
  $("away-goals").textContent = goals(away);
  $("home-goals").dataset.team = home;
  $("away-goals").dataset.team = away;
  $("minute").textContent = `${state.clock.minute}'`;
  $("phase").textContent = PHASES[state.clock.phase] ?? state.clock.phase;
  $("pending").textContent = state.pending;
  setSplit("running", state.possession.running_share, home, away);
  setSplit("window", state.possession.window_share, home, away);

  // Para que las piezas siguientes (gráficas, señales) escuchen el mismo flujo.
  document.dispatchEvent(new CustomEvent("gcperros:state", { detail: state }));
}

function setLink(state, text) {
  $("link").dataset.state = state;
  $("link").textContent = text;
}

async function start() {
  const [matchId] = await (await fetch("/api/matches")).json();
  const source = new EventSource(`/api/matches/${encodeURIComponent(matchId)}/stream`);

  source.onopen = () => setLink("live", "en vivo");
  source.onmessage = (message) => {
    const state = JSON.parse(message.data);
    render(state);
    // El servidor cierra el canal al pitido final; sin esto el navegador
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

start().catch(() => setLink("lost", "sin conexión con el servidor"));
