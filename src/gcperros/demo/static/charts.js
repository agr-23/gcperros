// Lo esperado acumulado en el tiempo —xG en fútbol, puntos esperados en
// baloncesto— y la tabla de estadísticas del deporte (sport.js). Escucha el
// mismo flujo que el marcador (`gcperros:state`) y dibuja en SVG a mano: sin
// librerías, para que la demo funcione sin conexión.
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

// Techo «redondo» del eje, en pasos del deporte: 0,5 de xG o 20 puntos.
const ceiling = (value, step) => Math.max(2 * step, Math.ceil(value / step) * step);

function drawXg(teams) {
  const svg = document.getElementById("xg-chart");
  svg.replaceChildren();
  const { minutes, ticks, estimateStep: step } = GCP.config;
  const maxMinute = Math.max(minutes, ...history.map((point) => point.minute));
  const top = ceiling(Math.max(0, ...history.flatMap((point) => teams.map((t) => point.xg[t]))), step);
  const x = (minute) => PAD.left + ((W - PAD.left - PAD.right) * minute) / maxMinute;
  const y = (xg) => H - PAD.bottom - ((H - PAD.top - PAD.bottom) * xg) / top;

  for (let tick = 0; tick <= top + 1e-9; tick += step) {
    svg.append(el("line", { x1: PAD.left, x2: W - PAD.right, y1: y(tick), y2: y(tick), class: "grid" }));
    const label = step < 1 ? tick.toFixed(1) : String(tick);
    svg.append(el("text", { x: PAD.left - 6, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, label));
  }
  for (const minute of ticks) {
    svg.append(el("text", { x: x(minute), y: H - 8, class: "tick", "text-anchor": "middle" }, `${minute}'`));
  }
  teams.forEach((team, index) => {
    // Escalonada: sólo cambia cuando hay un tiro.
    let path = "";
    history.forEach((point, i) => {
      const px = x(point.minute);
      const py = y(point.xg[team] ?? 0);
      path += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
    });
    svg.append(el("path", { d: path, class: index === 0 ? "home" : "away" }));
  });
}

// Las filas las pone el deporte (sport.js). El tercer campo es el indicador que
// se puede trazar (trace.js); un cociente, como el acierto en el pase, no tiene
// linaje propio y no lo lleva.

function drawStats(teams, indicators) {
  const body = document.getElementById("stats-body");
  body.replaceChildren(
    ...GCP.config.stats.map(([label, value, indicator]) => {
      const row = document.createElement("tr");
      const cells = [teams[0], null, teams[1]].map((team) => {
        const cell = document.createElement(team === null ? "th" : "td");
        cell.textContent = team === null ? label : value(indicators[team]);
        if (team !== null && indicator) {
          Object.assign(cell.dataset, { indicator, team });
          cell.tabIndex = 0;
        }
        return cell;
      });
      row.append(...cells);
      return row;
    }),
  );
}

let lastTeams = [];

// La historia que el servidor guardó antes de abrir la página (#96): va
// delante de lo que ya se dibujó en vivo, sin pisarlo.
document.addEventListener("gcperros:history", ({ detail: points }) => {
  if (lastTeams.length !== 2) return;
  const first = history.length ? history[0].minute : Infinity;
  const estimate = GCP.config.estimate;
  const earlier = points
    .filter((point) => point.minute < first && lastTeams.every((t) => point.indicators[t]))
    .map((point) => ({
      minute: point.minute,
      xg: Object.fromEntries(lastTeams.map((t) => [t, point.indicators[t][estimate]])),
    }));
  history.unshift(...earlier.filter((p, i) => earlier[i + 1]?.minute !== p.minute));
  drawXg(lastTeams);
});

document.addEventListener("gcperros:state", ({ detail: state }) => {
  if (state.teams.length !== 2) return;
  lastTeams = state.teams;
  const estimate = GCP.config.estimate;
  const xg = Object.fromEntries(state.teams.map((t) => [t, state.indicators[t][estimate]]));
  const last = history.at(-1);
  if (!last || last.minute !== state.clock.minute || state.clock.phase === "final") {
    history.push({ minute: state.clock.minute, xg });
  } else {
    last.xg = xg;
  }
  drawXg(state.teams);
  drawStats(state.teams, state.indicators);
});
