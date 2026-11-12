// Trazabilidad en pantalla (HU-18): cualquier cifra marcada con
// data-indicator se puede pulsar, y se abre de dónde sale, con su huella. Las
// señales del feed (data-signal) también (historia #25).
"use strict";

const NAMES = {
  goals: "Goles", shots: "Remates", total_xg: "xG", passes: "Pases",
  completed_passes: "Pases completados", fouls: "Faltas", red_cards: "Rojas",
  points: "Puntos", expected_points: "Puntos esperados", two_made: "Tiros de 2 anotados",
  three_made: "Triples anotados", free_throws_made: "Tiros libres anotados",
  offensive_rebounds: "Rebotes ofensivos", defensive_rebounds: "Rebotes defensivos",
  turnovers: "Pérdidas", timeouts: "Tiempos muertos",
};
const TYPES = {
  goal: "gol", shot: "remate", pass: "pase", foul: "falta", red_card: "roja",
  possession_change: "cambio de posesión", free_throw: "tiro libre", rebound: "rebote",
  turnover: "pérdida", timeout: "tiempo muerto",
};
// En baloncesto no se remata: se tira.
const typeName = (type) => (GCP.sport === "basketball" && type === "shot" ? "tiro" : TYPES[type] ?? type);
// El partido que se está viendo, no el primero: con el selector hay dos (#92).
const currentMatch = () => encodeURIComponent(GCP.matchId);

function node(tag, text, cls) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (cls) element.className = cls;
  return element;
}

// La huella entera no se lee: se enseñan sus extremos y el resto va en el título.
const shortDigest = (digest) => `${digest.slice(0, 8)}…${digest.slice(-6)}`;
const side = (team) => (team === document.getElementById("home-name").textContent ? "home" : "away");

function header(kicker, title, value, team) {
  const head = node("div", undefined, "trace-head");
  head.append(node("span", kicker, `trace-chip ${team ? side(team) : ""}`), node("span", title, "trace-title"));
  if (value !== undefined) head.append(node("span", value, "trace-value"));
  return head;
}

function verdict(ok, yes, no) {
  return node("p", ok ? `✓ ${yes}` : `✗ ${no}`, `trace-verdict ${ok ? "ok" : "ko"}`);
}

function facts(pairs) {
  const list = node("dl", undefined, "trace-facts");
  for (const [label, value, title] of pairs) {
    const dd = node("dd", value);
    if (title) dd.title = title;
    const pair = node("div");
    pair.append(node("dt", label), dd);
    list.append(pair);
  }
  return list;
}

// Una fila por evento: minuto, qué fue y, si lo hay, cuánto aportó, con una
// barra proporcional para que se vea qué tiros pesaron más (#99).
function timeline(rows) {
  const list = node("ol", undefined, "trace-events");
  const top = Math.max(...rows.map((row) => Math.abs(row.amount ?? 0)), 1e-9);
  for (const { minute, what, amount, label } of rows) {
    const item = node("li");
    item.append(node("span", `${minute}'`, "when"), node("span", what, "what"));
    if (label !== undefined) {
      const bar = node("span", label, "amount");
      bar.style.setProperty("--w", `${Math.round((100 * Math.abs(amount)) / top)}%`);
      item.append(bar);
    }
    list.append(item);
  }
  return list;
}

async function openTrace(indicator, team) {
  const dialog = document.getElementById("trace");
  const url = `/api/matches/${currentMatch()}/trace/${indicator}/${encodeURIComponent(team)}`;
  const trace = await (await fetch(url)).json();

  const estimate = indicator === GCP.config.estimate;
  const digits = estimate ? GCP.config.estimateDigits : 0;
  const models = Object.values(trace.model_versions).join(", ");
  const rows = trace.events.map((event) => ({
    minute: event.minute,
    what: typeName(event.event_type),
    amount: event.contribution,
    label: event.contribution == null ? undefined : `+${event.contribution.toFixed(estimate ? 2 : 0)}`,
  }));

  dialog.querySelector(".trace-body").replaceChildren(
    header(team, NAMES[indicator] ?? indicator, trace.value.toFixed(digits), team),
    verdict(
      trace.verified,
      `Huella verificada: estos ${trace.events.length} eventos son exactamente los que formaron el número.`,
      "La huella no cuadra: los eventos reconstruidos no son los que contó el motor.",
    ),
    facts([
      ["Eventos", String(trace.events.length)],
      ["Contrato", trace.contract_version],
      ...(models ? [["Modelo", models]] : []),
      ["Huella", shortDigest(trace.lineage.digest), trace.lineage.digest],
    ]),
    timeline(rows),
    node("p", "Cada evento, aplicado solo, aporta lo de la derecha: la suma es el número.", "trace-foot"),
  );
  dialog.showModal();
}

// El modelo frente al precio del operador, en dos barras: la separación se ve.
function versus(model, market) {
  const box = node("div", undefined, "trace-versus");
  for (const [label, value, cls] of [["Modelo", model, "vs-model"], ["Mercado", market, "vs-market"]]) {
    const row = node("div", undefined, `vs-row ${cls}`);
    const bar = node("span", undefined, "vs-bar");
    bar.style.setProperty("--w", `${Math.round(100 * value)}%`);
    row.append(node("span", label, "vs-label"), bar, node("span", `${Math.round(100 * value)}%`, "vs-num"));
    box.append(row);
  }
  const gap = Math.round(100 * Math.abs(model - market));
  box.append(node("p", `${gap} puntos de separación; el umbral es ${Math.round(100 * GCP.config.threshold)}.`, "vs-gap"));
  return box;
}

async function openSignalTrace(index) {
  const dialog = document.getElementById("trace");
  const response = await fetch(`/api/matches/${currentMatch()}/signals/${Number(index)}/trace`);
  if (!response.ok) return;
  const trace = await response.json();

  const rows = trace.events.map((event) => ({ minute: event.minute, what: `${typeName(event.event_type)} · ${event.team}` }));
  rows.push({ minute: trace.odds_update.minute, what: `cuota de ${trace.operator}` });
  const market = GCP.config.markets[trace.market] ?? trace.market;

  dialog.querySelector(".trace-body").replaceChildren(
    header(trace.operator, `${market} · ${GCP.config.outcomeNames[trace.outcome] ?? trace.outcome}`),
    versus(trace.model_probability, trace.market_probability),
    verdict(
      trace.verified,
      `Huella verificada: el modelo partió del estado que fijan estos eventos y la cuota de ${trace.operator}.`,
      "La huella no cuadra: lo reconstruido no es lo que usó el detector.",
    ),
    facts([
      ["Modelo", trace.model_version],
      ["Huella", shortDigest(trace.lineage.digest), trace.lineage.digest],
    ]),
    timeline(rows),
  );
  dialog.showModal();
}

function trigger(event) {
  const signal = event.target.closest?.("[data-signal]");
  if (signal) {
    event.preventDefault();
    openSignalTrace(signal.dataset.signal);
    return;
  }
  const node = event.target.closest?.("[data-indicator]");
  if (!node || !node.dataset.team) return;
  event.preventDefault();
  openTrace(node.dataset.indicator, node.dataset.team);
}

document.addEventListener("click", trigger);
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") trigger(event);
});
