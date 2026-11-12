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
  // Lo de estrés no se aprueba ni se suspende: se dice si se mantuvo o se rompió.
  const rows = (list, yes = "pasa", no = "no pasa") =>
    list.map((s) => [
      [s.name],
      [fmt.format(s.dropped_late)],
      [pct(s.timeliness, 2)],
      [pct(s.possession_share, 2)],
      [s.total_xg.toFixed(3)],
      verdict(s.passed, yes, no),
    ]);
  const headers = ["Escenario", "Tardíos", "A tiempo", "Δ posesión", "Δ xG", ""];
  return [
    cell("p", `${committed.filter((s) => s.passed).length} de ${committed.length} escenarios comprometidos dentro de los umbrales (posesión < 1 %, xG < 0,05, goles y eventos exactos).`, all ? "headline ok" : "headline ko"),
    table(headers, rows(committed)),
    cell("p", "Más allá de lo prometido: retardos de red de 5 y 10 s de media. Se informan para saber dónde está el límite, no se exigen.", "aside"),
    table(headers, rows(stress, "aguanta", "se rompe")),
  ];
}

const SPORT_NAMES = { football: "Fútbol", basketball: "Baloncesto", american_football: "Fútbol americano" };

// La tabla de B5: cada deporte en una columna, cada cifra en una fila (#99).
function comparacion(report) {
  const sec = (value) => `${value.toFixed(1).replace(".", ",")} s`;
  const metrics = [
    ["Eventos por minuto", (r) => r.events_per_minute.toFixed(1).replace(".", ",")],
    ["Margen de la marca de agua", (r) => `${r.declared_margin_s} s`],
    ["Escenarios comprometidos", (r) => `${r.committed_passed}/${r.committed_total}`, (r) => r.passed],
    ["Oportunidad (peor partido)", (r) => pct(r.timeliness, 2)],
    ["Separación de posesión (máx.)", (r) => r.possession_gap.toFixed(4).replace(".", ",")],
    ["Latencia p50 / p95", (r) => `${sec(r.latency_p50_s)} / ${sec(r.latency_p95_s)}`],
    ["Capacidad del motor", (r) => (r.capacity_events_per_s ? `${fmt.format(Math.round(r.capacity_events_per_s))} ev/s` : "—")],
  ];
  const all = report.every((r) => r.passed);
  return [
    cell("p", all ? "Los dos deportes cumplen todos sus escenarios comprometidos, medidos con la misma vara." : "Algún deporte no cumple un escenario comprometido.", all ? "headline ok" : "headline ko"),
    table(
      ["", ...report.map((r) => SPORT_NAMES[r.sport] ?? r.sport)],
      metrics.map(([label, value, ok]) => [[label], ...report.map((r) => [value(r), ok ? (ok(r) ? "ok" : "ko") : undefined])]),
    ),
    cell("p", "El baloncesto manda menos de la mitad de eventos por minuto, así que la marca de agua avanza menos a menudo y la latencia se duplica: la pone la densidad del flujo, no el motor.", "aside"),
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

const DIMENSIONS = {
  completeness: "Completitud", validity: "Validez", uniqueness: "Unicidad",
  timeliness: "Oportunidad", consistency: "Consistencia",
};

// Una columna por deporte medido: el de fútbol siempre, el de baloncesto si está.
function calidad(report, basketball) {
  const reports = [["Fútbol", report], ...(basketball ? [["Baloncesto", basketball]] : [])];
  const passed = reports.every(([, r]) => r.passed);
  const measured = (r, dimension) => r.measurements.find((m) => m.dimension === dimension);
  const cellFor = (m) => (m ? [`${pct(m.value, 2)} de ${fmt.format(m.total)}`, m.passed ? "ok" : "ko"] : ["sin datos"]);
  return [
    cell("p", passed ? "Todas las reglas por encima de su umbral." : "Alguna regla por debajo de su umbral.", passed ? "headline ok" : "headline ko"),
    table(
      ["Dimensión", "Mínimo", ...reports.map(([name]) => name)],
      report.measurements.map((m) => [
        [DIMENSIONS[m.dimension] ?? m.dimension],
        [pct(m.minimum, 0)],
        ...reports.map(([, r]) => cellFor(measured(r, m.dimension))),
      ]),
    ),
  ];
}

// El resumen de arriba: una cifra por pregunta, con su color.
const KPI = {
  validacion: (r) => {
    const committed = r.scenarios.filter((s) => !STRESS.has(s.name));
    return [`${committed.filter((s) => s.passed).length}/${committed.length}`, committed.every((s) => s.passed)];
  },
  carga: (r) => [fmt.format(Math.round(r.capacity_events_per_s)), true],
  calidad: (r) => [`${r.measurements.filter((m) => m.passed).length}/${r.measurements.length}`, r.passed],
};

function fillKpi(name, report) {
  const tile = document.querySelector(`.kpi[data-report="${name}"]`);
  if (!tile) return;
  const [value, ok] = KPI[name](report);
  tile.querySelector("b").textContent = value;
  tile.dataset.state = ok ? "ok" : "ko";
}

const RENDER = { validacion, comparacion, carga, calidad };

async function start() {
  const available = await (await fetch("/api/reports")).json();
  const load = async (name) => (available[name] ? (await fetch(`/api/reports/${name}`)).json() : null);
  const basketball = await load("calidad-baloncesto");
  for (const [name, render] of Object.entries(RENDER)) {
    const body = document.querySelector(`#${name} .body`);
    const report = await load(name);
    if (!report) {
      body.replaceChildren(cell("p", "Este informe todavía no se ha generado. El comando está debajo.", "missing"));
      continue;
    }
    body.replaceChildren(...render(report, basketball));
    if (KPI[name]) fillKpi(name, report);
  }
}

start();
