// «Por qué confiar»: pinta los informes que escribieron las CLI, sin
// recalcular nada. Si falta uno, lo dice y enseña cómo generarlo.
"use strict";

// Los escenarios de estrés del harness (engine.harness.STRESS_SCENARIOS): van
// más allá de lo comprometido y existen para encontrar dónde se rompe.
const STRESS = new Set(["retardo-fuerte", "retardo-extremo"]);
const pct = (value, digits = 1) => `${(100 * value).toFixed(digits)}%`;
const fmt = new Intl.NumberFormat("es-ES");

function cell(tag, text, cls) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function table(headers, rows) {
  const wrap = cell("div", "", "table-wrap");
  const t = cell("table", "", "trust-table");
  const head = document.createElement("tr");
  head.append(...headers.map((h) => cell("th", h)));
  t.append(head);
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.append(...row.map(([text, cls]) => cell("td", text, cls)));
    t.append(tr);
  }
  wrap.append(t);
  return wrap;
}

const verdict = (passed, yes = "pasa", no = "no pasa") => [passed ? yes : no, passed ? "ok" : "ko"];

function validacion(report) {
  const committed = report.scenarios.filter((s) => !STRESS.has(s.name));
  const stress = report.scenarios.filter((s) => STRESS.has(s.name));
  const all = committed.every((s) => s.passed);
  const rows = (list) =>
    list.map((s) => [
      [s.name],
      [fmt.format(s.dropped_late)],
      [pct(s.timeliness, 2)],
      [pct(s.possession_share, 2)],
      [s.total_xg.toFixed(3)],
      verdict(s.passed),
    ]);
  const headers = ["Escenario", "Tardíos", "A tiempo", "Δ posesión", "Δ xG", ""];
  return [
    cell("p", `${committed.filter((s) => s.passed).length} de ${committed.length} escenarios comprometidos dentro de los umbrales (posesión < 1 %, xG < 0,05, goles y eventos exactos).`, all ? "headline ok" : "headline ko"),
    table(headers, rows(committed)),
    cell("p", "Más allá de lo prometido: retardos de red de 5 y 10 s de media. Se informan para saber dónde está el límite, no se exigen.", "aside"),
    table(headers, rows(stress)),
  ];
}

function carga(report) {
  return [
    cell("p", `${fmt.format(Math.round(report.capacity_events_per_s))} eventos por segundo antes de saturar, en la máquina donde se midió. Un partido emite 0,2.`, "headline ok"),
    table(
      ["Eventos/s", "Uso del motor", "p95", "Cola máx.", ""],
      report.rates.map((r) => [
        [fmt.format(r.rate_events_per_s)],
        [pct(r.utilization, 0)],
        [`${(1000 * r.p95_s).toFixed(2)} ms`],
        [fmt.format(r.max_backlog)],
        verdict(!r.saturated, "sostiene", "satura"),
      ]),
    ),
  ];
}

const DIMENSIONS = { completeness: "Completitud", uniqueness: "Unicidad", timeliness: "Oportunidad" };

function calidad(report) {
  return [
    cell("p", report.passed ? "Todas las reglas por encima de su umbral." : "Alguna regla por debajo de su umbral.", report.passed ? "headline ok" : "headline ko"),
    table(
      ["Dimensión", "Medido", "Mínimo", "Sobre", ""],
      report.measurements.map((m) => [
        [DIMENSIONS[m.dimension] ?? m.dimension],
        [pct(m.value, 2)],
        [pct(m.minimum, 0)],
        [`${fmt.format(m.total)} mensajes`],
        verdict(m.passed),
      ]),
    ),
  ];
}

const RENDER = { validacion, carga, calidad };

async function start() {
  const available = await (await fetch("/api/reports")).json();
  for (const [name, render] of Object.entries(RENDER)) {
    const body = document.querySelector(`#${name} .body`);
    if (!available[name]) {
      body.replaceChildren(cell("p", "Este informe todavía no se ha generado. El comando está debajo.", "missing"));
      continue;
    }
    body.replaceChildren(...render(await (await fetch(`/api/reports/${name}`)).json()));
  }
}

start();
