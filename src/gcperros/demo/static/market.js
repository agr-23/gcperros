// Mercado frente a modelo, y el feed de señales. Lo que el cliente compra:
// ver cuándo un operador sigue con un precio viejo. Escucha el mismo flujo
// que el marcador (`gcperros:state`).
"use strict";

const MW = 640;
const MH = 200;
const MPAD = { left: 36, right: 12, top: 10, bottom: 24 };
const OPERATOR_CLASSES = ["op-a", "op-b", "op-c"];
// Resultados, umbral, minutos y nombres los pone el deporte (sport.js).
const tape = [];

const pct = (p) => `${Math.round(100 * p)}%`;

function svgNode(name, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function drawWinChart(operators) {
  const svg = document.getElementById("win-chart");
  svg.replaceChildren();
  const { minutes, ticks } = GCP.config;
  const maxMinute = Math.max(minutes, ...tape.map((point) => point.minute));
  const x = (minute) => MPAD.left + ((MW - MPAD.left - MPAD.right) * minute) / maxMinute;
  const y = (p) => MH - MPAD.bottom - (MH - MPAD.top - MPAD.bottom) * p;

  for (const p of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(svgNode("line", { x1: MPAD.left, x2: MW - MPAD.right, y1: y(p), y2: y(p), class: "grid" }));
    svg.append(svgNode("text", { x: MPAD.left - 6, y: y(p) + 4, class: "tick", "text-anchor": "end" }, pct(p)));
  }
  for (const minute of ticks) {
    svg.append(svgNode("text", { x: x(minute), y: MH - 6, class: "tick", "text-anchor": "middle" }, `${minute}'`));
  }
  const line = (pick, cls) => {
    const points = tape.filter((point) => pick(point) !== undefined);
    if (points.length === 0) return;
    const d = points.map((point, i) => `${i ? "L" : "M"}${x(point.minute)},${y(pick(point))}`).join("");
    svg.append(svgNode("path", { d, class: cls }));
  };
  operators.forEach((op, i) => line((point) => point.operators[op]?.home, OPERATOR_CLASSES[i % 3]));
  line((point) => point.model.home, "model");
}

function drawBook(market, operators) {
  const head = document.getElementById("book-head");
  head.replaceChildren(
    ...["", "Modelo", ...operators].map((label) => {
      const cell = document.createElement("th");
      cell.textContent = label;
      return cell;
    }),
  );
  document.getElementById("book-body").replaceChildren(
    ...GCP.config.outcomes.map(([outcome, label]) => {
      const row = document.createElement("tr");
      const name = document.createElement("th");
      name.textContent = label;
      const model = document.createElement("td");
      model.className = "model";
      model.textContent = pct(market.model[outcome]);
      row.append(name, model);
      for (const op of operators) {
        const priced = market.operators[op][outcome];
        const cell = document.createElement("td");
        cell.textContent = pct(priced);
        cell.classList.toggle("stale", Math.abs(market.model[outcome] - priced) >= GCP.config.threshold);
        row.append(cell);
      }
      return row;
    }),
  );
}

function drawSignals(market) {
  document.getElementById("signal-count").textContent = market.total_signals;
  document.getElementById("signal-list").replaceChildren(
    ...market.signals.map((signal) => {
      const item = document.createElement("li");
      const { markets, outcomeNames } = GCP.config;
      const label = markets[signal.market] ?? signal.market;
      // Sólo textContent: lo que llega del servidor nunca se interpreta como HTML.
      const parts = [
        ["when", `${Math.floor(signal.minute)}'`],
        ["what", `${signal.operator} · ${label} ${outcomeNames[signal.outcome] ?? signal.outcome}`],
        ["nums", `modelo ${pct(signal.model_probability)} · mercado ${pct(signal.market_probability)}`],
      ];
      for (const [cls, text] of parts) {
        const span = document.createElement("span");
        span.className = cls;
        span.textContent = text;
        item.append(span);
      }
      item.classList.add(signal.divergence > 0 ? "up" : "down");
      // Pulsable: abre de qué eventos y qué cuota sale (trace.js).
      item.dataset.signal = signal.index;
      item.tabIndex = 0;
      return item;
    }),
  );
}

let lastOperators = [];

// Lo que el mercado ya hizo antes de abrir la página (#96), delante de la cinta.
document.addEventListener("gcperros:history", ({ detail: points }) => {
  const first = tape.length ? tape[0].minute : Infinity;
  const earlier = points.filter((point) => point.model && point.minute < first);
  tape.unshift(...earlier.filter((p, i) => earlier[i + 1]?.minute !== p.minute));
  if (lastOperators.length) drawWinChart(lastOperators);
});

document.addEventListener("gcperros:state", ({ detail: state }) => {
  const market = state.market;
  if (!market) return;
  const operators = Object.keys(market.operators);
  lastOperators = operators;
  const point = { minute: state.clock.minute, model: market.model, operators: market.operators };
  if (tape.length && tape.at(-1).minute === point.minute) tape[tape.length - 1] = point;
  else tape.push(point);

  drawWinChart(operators);
  if (operators.length) drawBook(market, operators);
  drawSignals(market);
});
