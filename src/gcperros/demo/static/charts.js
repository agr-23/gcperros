// xG acumulado en el tiempo y tabla de estadísticas. Escucha el mismo flujo
// que el marcador (`gcperros:state`) y dibuja en SVG a mano: sin librerías,
// para que la demo funcione sin conexión.
"use strict";

const SVG = "http://www.w3.org/2000/svg";
const W = 640;
const H = 220;
const PAD = { left: 36, right: 12, top: 12, bottom: 26 };
const history = [];

function el(name, attrs, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

// Techo «redondo» del eje: 0,5 en 0,5 hasta donde llegue el xG.
const ceiling = (value) => Math.max(1, Math.ceil(value * 2) / 2);

function drawXg(teams) {
  const svg = document.getElementById("xg-chart");
  svg.replaceChildren();
  const maxMinute = Math.max(90, ...history.map((point) => point.minute));
  const top = ceiling(Math.max(0, ...history.flatMap((point) => teams.map((t) => point.xg[t]))));
  const x = (minute) => PAD.left + ((W - PAD.left - PAD.right) * minute) / maxMinute;
  const y = (xg) => H - PAD.bottom - ((H - PAD.top - PAD.bottom) * xg) / top;

  for (let tick = 0; tick <= top + 1e-9; tick += 0.5) {
    svg.append(el("line", { x1: PAD.left, x2: W - PAD.right, y1: y(tick), y2: y(tick), class: "grid" }));
    svg.append(el("text", { x: PAD.left - 6, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, tick.toFixed(1)));
  }
  for (const minute of [0, 15, 30, 45, 60, 75, 90]) {
    svg.append(el("text", { x: x(minute), y: H - 8, class: "tick", "text-anchor": "middle" }, `${minute}'`));
  }
  teams.forEach((team, index) => {
    // Escalonada: el xG sólo cambia cuando hay un remate.
    let path = "";
    history.forEach((point, i) => {
      const px = x(point.minute);
      const py = y(point.xg[team] ?? 0);
      path += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
    });
    svg.append(el("path", { d: path, class: index === 0 ? "home" : "away" }));
  });
}

const ROWS = [
  ["Remates", (s) => s.shots],
  ["xG", (s) => s.total_xg.toFixed(2)],
  ["Pases", (s) => s.passes],
  ["Acierto en el pase", (s) => (s.passes ? `${Math.round((100 * s.completed_passes) / s.passes)}%` : "—")],
  ["Faltas", (s) => s.fouls],
  ["Rojas", (s) => s.red_cards],
];

function drawStats(teams, indicators) {
  const body = document.getElementById("stats-body");
  body.replaceChildren(
    ...ROWS.map(([label, value]) => {
      const row = document.createElement("tr");
      const cells = [teams[0], null, teams[1]].map((team) => {
        const cell = document.createElement(team === null ? "th" : "td");
        cell.textContent = team === null ? label : value(indicators[team]);
        return cell;
      });
      row.append(...cells);
      return row;
    }),
  );
}

document.addEventListener("gcperros:state", ({ detail: state }) => {
  if (state.teams.length !== 2) return;
  const xg = Object.fromEntries(state.teams.map((t) => [t, state.indicators[t].total_xg]));
  const last = history.at(-1);
  if (!last || last.minute !== state.clock.minute || state.clock.phase === "final") {
    history.push({ minute: state.clock.minute, xg });
  } else {
    last.xg = xg;
  }
  drawXg(state.teams);
  drawStats(state.teams, state.indicators);
});
