// Mercado frente a modelo, y el feed de señales. Lo que el cliente compra:
// ver cuándo un operador sigue con un precio viejo. Escucha el mismo flujo
// que el marcador (`gcperros:state`).
"use strict";

const MW = 640;
const MH = 200;
const MPAD = { left: 36, right: 12, top: 10, bottom: 24 };
const OPERATOR_CLASSES = ["op-a", "op-b", "op-c"];
const OUTCOMES = [["home", "Local"], ["draw", "Empate"], ["away", "Visitante"]];
// El umbral declarado de la señal (HU-19), para marcar las celdas que lo cruzan.
const THRESHOLD = 0.05;
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
  const maxMinute = Math.max(90, ...tape.map((point) => point.minute));
  const x = (minute) => MPAD.left + ((MW - MPAD.left - MPAD.right) * minute) / maxMinute;
  const y = (p) => MH - MPAD.bottom - (MH - MPAD.top - MPAD.bottom) * p;

  for (const p of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(svgNode("line", { x1: MPAD.left, x2: MW - MPAD.right, y1: y(p), y2: y(p), class: "grid" }));
    svg.append(svgNode("text", { x: MPAD.left - 6, y: y(p) + 4, class: "tick", "text-anchor": "end" }, pct(p)));
  }
  for (const minute of [0, 15, 30, 45, 60, 75, 90]) {
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
    ...OUTCOMES.map(([outcome, label]) => {
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
        cell.classList.toggle("stale", Math.abs(market.model[outcome] - priced) >= THRESHOLD);
        row.append(cell);
      }
      return row;
    }),
  );
}

const OUTCOME_NAMES = { home: "local", draw: "empate", away: "visitante", over: "más de 2,5", under: "menos de 2,5" };

function drawSignals(market) {
  document.getElementById("signal-count").textContent = market.total_signals;
  document.getElementById("signal-list").replaceChildren(
    ...market.signals.map((signal) => {
      const item = document.createElement("li");
      const label = signal.market === "1x2" ? "1X2" : "Goles";
      // Sólo textContent: lo que llega del servidor nunca se interpreta como HTML.
      const parts = [
        ["when", `${Math.floor(signal.minute)}'`],
        ["what", `${signal.operator} · ${label} ${OUTCOME_NAMES[signal.outcome] ?? signal.outcome}`],
        ["nums", `modelo ${pct(signal.model_probability)} · mercado ${pct(signal.market_probability)}`],
      ];
      for (const [cls, text] of parts) {
        const span = document.createElement("span");
        span.className = cls;
        span.textContent = text;
        item.append(span);
      }
      item.classList.add(signal.divergence > 0 ? "up" : "down");
      return item;
    }),
  );
}

document.addEventListener("gcperros:state", ({ detail: state }) => {
  const market = state.market;
  if (!market) return;
  const operators = Object.keys(market.operators);
  const point = { minute: state.clock.minute, model: market.model, operators: market.operators };
  if (tape.length && tape.at(-1).minute === point.minute) tape[tape.length - 1] = point;
  else tape.push(point);

  drawWinChart(operators);
  if (operators.length) drawBook(market, operators);
  drawSignals(market);
});
