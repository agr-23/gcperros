// Lo que cada deporte pone en pantalla (#92). El resto de scripts leen de aquí
// en vez de suponer el fútbol: qué es el marcador, cómo se lee el reloj, qué
// resultados tiene el mercado de ganador y qué estadísticas se enseñan.
"use strict";

const pad2 = (n) => String(n).padStart(2, "0");

const SPORTS = {
  football: {
    label: "Fútbol",
    icon: "⚽",
    headline: "goals",
    estimate: "total_xg",
    estimateTitle: "Goles esperados (xG) acumulados",
    estimateName: "xG",
    estimateStep: 0.5,
    estimateDigits: 2,
    minutes: 90,
    ticks: [0, 15, 30, 45, 60, 75, 90],
    outcomes: [["home", "Local"], ["draw", "Empate"], ["away", "Visitante"]],
    // Umbral declarado de la señal (HU-19), para marcar las celdas que lo cruzan.
    threshold: 0.05,
    lateness: 10,
    signalHint:
      "Un operador se separa del modelo más de 5 puntos: casi siempre, un precio que no se actualizó tras un gol o una expulsión.",
    markets: { "1x2": "1X2", over_under_2_5: "Goles" },
    outcomeNames: { home: "local", draw: "empate", away: "visitante", over: "más de 2,5", under: "menos de 2,5" },
    phases: { previa: "previa", "parte-1": "primera parte", descanso: "descanso", "parte-2": "segunda parte", final: "final" },
    clock: (clock) => `${clock.minute}'`,
    stats: [
      ["Remates", (s) => s.shots, "shots"],
      ["xG", (s) => s.total_xg.toFixed(2), "total_xg"],
      ["Pases", (s) => s.passes, "passes"],
      ["Acierto en el pase", (s) => (s.passes ? `${Math.round((100 * s.completed_passes) / s.passes)}%` : "—")],
      ["Faltas", (s) => s.fouls, "fouls"],
      ["Rojas", (s) => s.red_cards, "red_cards"],
    ],
    fixtures: {
      past: [
        { home: "ATM", away: "SEV", score: "2 — 0", date: "Ayer · Finalizado", xg: "1.84 vs 0.62" },
        { home: "BET", away: "VAL", score: "1 — 1", date: "Ayer · Finalizado", xg: "1.12 vs 0.98" },
        { home: "RSO", away: "ATH", score: "0 — 1", date: "Hace 2 días", xg: "0.75 vs 1.40" },
        { home: "VIL", away: "CEL", score: "3 — 1", date: "Hace 2 días", xg: "2.10 vs 0.88" },
      ],
      upcoming: [
        { home: "RMA", away: "BAR", date: "Mañana · 21:00", meta: "El Clásico · J28", odds: "2.10 | 3.40 | 3.20" },
        { home: "GIR", away: "MLL", date: "Sábado · 16:15", meta: "Montilivi", odds: "1.85 | 3.60 | 4.20" },
        { home: "OSA", away: "ALV", date: "Sábado · 18:30", meta: "El Sadar", odds: "2.25 | 3.10 | 3.50" },
        { home: "RAY", away: "GET", date: "Domingo · 14:00", meta: "Vallecas", odds: "2.40 | 3.00 | 3.10" },
      ]
    }
  },
  basketball: {
    label: "Baloncesto",
    icon: "🏀",
    headline: "points",
    estimate: "expected_points",
    estimateTitle: "Puntos esperados acumulados",
    estimateName: "Puntos esperados",
    estimateStep: 20,
    estimateDigits: 1,
    minutes: 40,
    ticks: [0, 10, 20, 30, 40],
    outcomes: [["home", "Local"], ["away", "Visitante"]],
    // El umbral del baloncesto, elegido con la misma regla que el del fútbol (#90).
    threshold: 0.10,
    lateness: 15,
    signalHint:
      "Un operador se separa del modelo más de 10 puntos: casi siempre, un precio que no se actualizó tras una canasta.",
    markets: { moneyline: "Ganador", total_points: "Total" },
    outcomeNames: { home: "local", away: "visitante", over: "más de la línea", under: "menos de la línea" },
    phases: { previa: "salto inicial", descanso: "entre cuartos", final: "final" },
    clock: (clock) => {
      // Entre cuartos el reloj está a cero, no en el último evento del cuarto.
      const left = clock.phase === "descanso" ? 0 : Math.max(0, Math.round(clock.game_clock_s ?? 0));
      const period = clock.period > 4 ? `PR${clock.period - 4}` : `Q${clock.period}`;
      return `${period} · ${pad2(Math.floor(left / 60))}:${pad2(left % 60)}`;
    },
    stats: [
      ["Puntos esperados", (s) => s.expected_points.toFixed(1), "expected_points"],
      ["Tiros de 2", (s) => `${s.two_made}/${s.two_attempted}`, "two_made"],
      ["Triples", (s) => `${s.three_made}/${s.three_attempted}`, "three_made"],
      ["Tiros libres", (s) => `${s.free_throws_made}/${s.free_throws_attempted}`, "free_throws_made"],
      ["Rebotes ofensivos", (s) => s.offensive_rebounds, "offensive_rebounds"],
      ["Rebotes defensivos", (s) => s.defensive_rebounds, "defensive_rebounds"],
      ["Pérdidas", (s) => s.turnovers, "turnovers"],
      ["Faltas", (s) => s.fouls, "fouls"],
      ["Tiempos muertos", (s) => s.timeouts, "timeouts"],
    ],
    fixtures: {
      past: [
        { home: "BOS", away: "MIA", score: "114 — 102", date: "Ayer · Finalizado", xg: "xP 111.4 vs 104.2" },
        { home: "DEN", away: "LAL", score: "108 — 106", date: "Ayer · Finalizado", xg: "xP 107.8 vs 105.1" },
        { home: "MIL", away: "NYK", score: "98 — 105", date: "Hace 2 días", xg: "xP 100.2 vs 103.9" },
        { home: "PHX", away: "GSW", score: "122 — 118", date: "Hace 2 días", xg: "xP 119.5 vs 120.1" },
      ],
      upcoming: [
        { home: "BOS", away: "GSW", date: "Hoy · 20:30", meta: "Boston", odds: "1.65 | 2.30" },
        { home: "LAL", away: "LAC", date: "Mañana · 22:00", meta: "Los Ángeles", odds: "1.92 | 1.92" },
        { home: "DAL", away: "OKC", date: "Viernes · 20:00", meta: "Dallas", odds: "2.15 | 1.74" },
        { home: "MIN", away: "DEN", date: "Sábado · 21:00", meta: "Minneapolis", odds: "1.80 | 2.05" },
      ]
    }
  },
};

// El partido que se está viendo. Lo fija app.js al arrancar; lo leen el resto.
window.GCP = { matchId: null, sport: "football", config: SPORTS.football };

function phaseLabel(config, clock) {
  if (config.phases[clock.phase]) {
    // En baloncesto, el descanso entre el segundo y el tercer cuarto es el largo.
    if (clock.phase === "descanso" && GCP.sport === "basketball" && clock.period === 2) return "descanso";
    return config.phases[clock.phase];
  }
  const [, number] = clock.phase.split("-");
  return Number(number) > 4 ? `prórroga ${Number(number) - 4}` : `${number}.º cuarto`;
}
