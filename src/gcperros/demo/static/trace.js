// Trazabilidad en pantalla (HU-18): cualquier cifra marcada con
// data-indicator se puede pulsar, y se abre de dónde sale, con su huella.
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

function trigger(event) {
  const node = event.target.closest?.("[data-indicator]");
  if (!node || !node.dataset.team) return;
  event.preventDefault();
  openTrace(node.dataset.indicator, node.dataset.team);
}

document.addEventListener("click", trigger);
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") trigger(event);
});
