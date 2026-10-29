// Trazabilidad en pantalla (HU-18): cualquier cifra marcada con
// data-indicator se puede pulsar, y se abre de dónde sale, con su huella. Las
// señales del feed (data-signal) también (historia #25).
"use strict";

const NAMES = {
  goals: "Goles", shots: "Remates", total_xg: "xG", passes: "Pases",
  completed_passes: "Pases completados", fouls: "Faltas", red_cards: "Rojas",
};
const TYPES = {
  goal: "gol", shot: "remate", pass: "pase", foul: "falta", red_card: "roja",
  possession_change: "cambio de posesión",
};

function line(text, cls) {
  const node = document.createElement("p");
  node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

async function openTrace(indicator, team) {
  const dialog = document.getElementById("trace");
  const body = dialog.querySelector(".trace-body");
  const [matchId] = await (await fetch("/api/matches")).json();
  const url = `/api/matches/${encodeURIComponent(matchId)}/trace/${indicator}/${encodeURIComponent(team)}`;
  const trace = await (await fetch(url)).json();

  const value = indicator === "total_xg" ? trace.value.toFixed(2) : trace.value;
  const models = Object.entries(trace.model_versions).map(([m, v]) => `${m} ${v}`).join(", ");
  const list = document.createElement("ol");
  list.className = "trace-events";
  for (const event of trace.events.slice(0, 40)) {
    const item = document.createElement("li");
    item.textContent = `${event.minute}'  ${TYPES[event.event_type] ?? event.event_type}`;
    list.append(item);
  }

  body.replaceChildren(
    line(`${team} · ${NAMES[indicator] ?? indicator} = ${value}`, "trace-title"),
    line(
      trace.verified
        ? `✓ Huella verificada: los ${trace.events.length} eventos de abajo son exactamente los que formaron el número.`
        : "✗ La huella no cuadra: los eventos reconstruidos no son los que contó el motor.",
      trace.verified ? "trace-ok" : "trace-ko",
    ),
    line(`Huella ${trace.lineage.digest} · contrato ${trace.contract_version}${models ? ` · modelo ${models}` : ""}`, "trace-meta"),
    list,
    ...(trace.events.length > 40 ? [line(`… y ${trace.events.length - 40} más.`, "trace-meta")] : []),
  );
  dialog.showModal();
}

async function openSignalTrace(index) {
  const dialog = document.getElementById("trace");
  const [matchId] = await (await fetch("/api/matches")).json();
  const response = await fetch(`/api/matches/${encodeURIComponent(matchId)}/signals/${Number(index)}/trace`);
  if (!response.ok) return;
  const trace = await response.json();

  const list = document.createElement("ol");
  list.className = "trace-events";
  for (const event of trace.events) {
    const item = document.createElement("li");
    item.textContent = `${event.minute}'  ${TYPES[event.event_type] ?? event.event_type} ${event.team}`;
    list.append(item);
  }
  const price = document.createElement("li");
  price.textContent = `${trace.odds_update.minute}'  cuota de ${trace.operator}`;
  list.append(price);

  dialog.querySelector(".trace-body").replaceChildren(
    line(`Señal · ${trace.operator} · ${trace.market} ${trace.outcome}`, "trace-title"),
    line(
      trace.verified
        ? `✓ Huella verificada: el modelo partió del estado que fijan estos eventos y la cuota de ${trace.operator}.`
        : "✗ La huella no cuadra: lo reconstruido no es lo que usó el detector.",
      trace.verified ? "trace-ok" : "trace-ko",
    ),
    line(`Huella ${trace.lineage.digest} · modelo ${trace.model_version}`, "trace-meta"),
    list,
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
