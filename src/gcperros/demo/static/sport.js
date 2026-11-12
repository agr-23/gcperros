// Lo que cada deporte pone en pantalla (#92). El resto de scripts leen de aquí
// en vez de suponer el fútbol: qué es el marcador, cómo se lee el reloj, qué
// resultados tiene el mercado de ganador y qué estadísticas se enseñan.
"use strict";

const BALL_SVGS = {
  football:
    '<svg class="sport-ball-svg" viewBox="0 0 24 24" fill="none">' +
    '<circle cx="12" cy="12" r="10.5" fill="#f8fafc" stroke="#1e293b" stroke-width="1.4"/>' +
    '<polygon points="12,7.5 15.8,10.2 14.3,14.6 9.7,14.6 8.2,10.2" fill="#1e293b"/>' +
    '<line x1="12" y1="7.5" x2="12" y2="1.5" stroke="#1e293b" stroke-width="1.3"/>' +
    '<line x1="15.8" y1="10.2" x2="22" y2="8" stroke="#1e293b" stroke-width="1.3"/>' +
    '<line x1="14.3" y1="14.6" x2="18.5" y2="20" stroke="#1e293b" stroke-width="1.3"/>' +
    '<line x1="9.7" y1="14.6" x2="5.5" y2="20" stroke="#1e293b" stroke-width="1.3"/>' +
    '<line x1="8.2" y1="10.2" x2="2" y2="8" stroke="#1e293b" stroke-width="1.3"/>' +
    '</svg>',
  basketball:
    '<svg class="sport-ball-svg" viewBox="0 0 24 24" fill="none">' +
    '<circle cx="12" cy="12" r="10.5" fill="#ea580c" stroke="#1e293b" stroke-width="1.4"/>' +
    '<line x1="1.5" y1="12" x2="22.5" y2="12" stroke="#1e293b" stroke-width="1.3"/>' +
    '<line x1="12" y1="1.5" x2="12" y2="22.5" stroke="#1e293b" stroke-width="1.3"/>' +
    '<path d="M 4.5 4.5 C 8.5 8.5 8.5 15.5 4.5 19.5" stroke="#1e293b" stroke-width="1.3" fill="none"/>' +
    '<path d="M 19.5 4.5 C 15.5 8.5 15.5 15.5 19.5 19.5" stroke="#1e293b" stroke-width="1.3" fill="none"/>' +
    '</svg>',
  american_football:
    '<svg class="sport-ball-svg" viewBox="0 0 24 24" fill="none">' +
    '<g transform="rotate(-35 12 12)">' +
    '<ellipse cx="12" cy="12" rx="10.5" ry="6.2" fill="#85371b" stroke="#1e293b" stroke-width="1.3"/>' +
    '<path d="M 3.8 8.5 C 4.8 10 4.8 14 3.8 15.5" stroke="#f8fafc" stroke-width="1.2" fill="none"/>' +
    '<path d="M 20.2 8.5 C 19.2 10 19.2 14 20.2 15.5" stroke="#f8fafc" stroke-width="1.2" fill="none"/>' +
    '<line x1="7.5" y1="12" x2="16.5" y2="12" stroke="#f8fafc" stroke-width="1.4"/>' +
    '<line x1="9.5" y1="9.5" x2="9.5" y2="14.5" stroke="#f8fafc" stroke-width="1.3"/>' +
    '<line x1="12" y1="9" x2="12" y2="15" stroke="#f8fafc" stroke-width="1.3"/>' +
    '<line x1="14.5" y1="9.5" x2="14.5" y2="14.5" stroke="#f8fafc" stroke-width="1.3"/>' +
    '</g></svg>',
};

const pad2 = (n) => String(n).padStart(2, "0");

const SPORTS = {
  football: {
    label: "Fútbol",
    icon: "⚽",
    svg: BALL_SVGS.football,
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
    h2h: {
      homeWins: 5,
      draws: 2,
      awayWins: 3,
      homeAvg: "2.1",
      awayAvg: "1.4",
      unit: "goles/p",
      insight: "El Real Madrid ha marcado primero en 7 de los últimos 10 clásicos directos. Tasa de 'Ambos Marcan': 80%.",
    },
    pastMatches: [
      { home: "ATM", away: "SEV", score: "2 – 0", date: "Ayer", venue: "Metropolitano, Madrid" },
      { home: "BET", away: "VAL", score: "1 – 1", date: "10 Nov", venue: "Benito Villamarín, Sevilla" },
      { home: "RSO", away: "ATH", score: "0 – 1", date: "9 Nov", venue: "Reale Arena, San Sebastián" },
      { home: "VIL", away: "CEL", score: "3 – 1", date: "8 Nov", venue: "La Cerámica, Villarreal" },
    ],
    upcomingMatches: [
      { home: "JUV", away: "INT", time: "20:45", date: "Mañana", venue: "Allianz Stadium, Turín" },
      { home: "LIV", away: "MCI", time: "17:30", date: "Sáb 15", venue: "Anfield, Liverpool" },
      { home: "PSG", away: "MAR", time: "21:00", date: "Dom 16", venue: "Parc des Princes, París" },
      { home: "BAY", away: "DOR", time: "18:30", date: "Dom 16", venue: "Allianz Arena, Múnich" },
    ],
  },
  basketball: {
    label: "Baloncesto",
    icon: "🏀",
    svg: BALL_SVGS.basketball,
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
    h2h: {
      homeWins: 6,
      draws: 0,
      awayWins: 4,
      homeAvg: "108.4",
      awayAvg: "103.2",
      unit: "pts/p",
      insight: "Boston promedia +5.2 rebotes ofensivos jugando en el TD Garden en los últimos 10 choques directos.",
    },
    pastMatches: [
      { home: "DEN", away: "GSW", score: "114 – 109", date: "Ayer", venue: "Ball Arena, Denver" },
      { home: "MIL", away: "PHI", score: "118 – 116", date: "10 Nov", venue: "Fiserv Forum, Milwaukee" },
      { home: "DAL", away: "PHX", score: "105 – 101", date: "9 Nov", venue: "American Airlines, Dallas" },
      { home: "MIA", away: "NYK", score: "98 – 95", date: "8 Nov", venue: "Kaseya Center, Miami" },
    ],
    upcomingMatches: [
      { home: "LAL", away: "BOS", time: "21:30", date: "Mañana", venue: "Crypto.com, Los Ángeles" },
      { home: "OKC", away: "MIN", time: "20:00", date: "Sáb 15", venue: "Paycom Center, Oklahoma" },
      { home: "CLE", away: "IND", time: "19:00", date: "Sáb 15", venue: "Rocket Mortgage, Cleveland" },
      { home: "SAC", away: "MEM", time: "21:00", date: "Dom 16", venue: "Golden 1, Sacramento" },
    ],
  },
};

// El fútbol americano (sección 22) no tiene cuotas: `market: false` esconde el
// mercado y las señales en vez de enseñarlos vacíos.
SPORTS.american_football = {
  label: "Fútbol americano",
  icon: "🏈",
  svg: BALL_SVGS.american_football,
  market: false,
  headline: "points",
  estimate: "kick_expected_points",
  estimateTitle: "Puntos esperados de las patadas, acumulados",
  estimateName: "Puntos esperados de patadas",
  estimateStep: 3,
  estimateDigits: 1,
  minutes: 60,
  ticks: [0, 15, 30, 45, 60],
  outcomes: [],
  lateness: 15,
  signalHint: "",
  markets: {},
  outcomeNames: {},
  halftimeAfter: 2,
  phases: { previa: "saque inicial", descanso: "entre cuartos", final: "final" },
  clock: (clock) => {
    const left = clock.phase === "descanso" ? 0 : Math.max(0, Math.round(clock.game_clock_s ?? 0));
    const period = clock.period > 4 ? "PR" : `Q${clock.period}`;
    return `${period} · ${pad2(Math.floor(left / 60))}:${pad2(left % 60)}`;
  },
  stats: [
    ["Puntos esperados de patadas", (s) => s.kick_expected_points.toFixed(1), "kick_expected_points"],
    ["Touchdowns", (s) => s.touchdowns, "touchdowns"],
    ["Goles de campo", (s) => `${s.field_goals_made}/${s.field_goals_attempted}`, "field_goals_made"],
    ["Jugadas", (s) => s.plays, "plays"],
    ["Yardas", (s) => s.yards, "yards"],
    ["Pérdidas", (s) => s.turnovers, "turnovers"],
    ["Despejes", (s) => s.punts, "punts"],
    ["Tiempos muertos", (s) => s.timeouts, "timeouts"],
  ],
  h2h: {
    homeWins: 5,
    draws: 0,
    awayWins: 3,
    homeAvg: "27.5",
    awayAvg: "24.1",
    unit: "pts/p",
    insight: "Kansas City ha cubierto la línea en 4 de las últimas 5 visitas de Buffalo a Arrowhead.",
  },
  pastMatches: [
    { home: "BAL", away: "CIN", score: "35 – 34", date: "Jueves", venue: "M&T Bank, Baltimore" },
    { home: "DET", away: "GB", score: "24 – 14", date: "10 Nov", venue: "Ford Field, Detroit" },
    { home: "PHI", away: "DAL", score: "34 – 6", date: "9 Nov", venue: "Lincoln Financial, Filadelfia" },
    { home: "PIT", away: "WAS", score: "28 – 27", date: "8 Nov", venue: "Acrisure Stadium, Pittsburgh" },
  ],
  upcomingMatches: [
    { home: "KC", away: "BUF", time: "16:25", date: "Dom 16", venue: "Highmark, Orchard Park" },
    { home: "SF", away: "SEA", time: "16:05", date: "Dom 16", venue: "Levi's, Santa Clara" },
    { home: "HOU", away: "DAL", time: "20:15", date: "Lun 17", venue: "AT&T Stadium, Arlington" },
    { home: "MIN", away: "TEN", time: "13:00", date: "Dom 16", venue: "Nissan Stadium, Nashville" },
  ],
};

// El partido que se está viendo. Lo fija app.js al arrancar; lo leen el resto.
window.GCP = { matchId: null, sport: "football", config: SPORTS.football };

function phaseLabel(config, clock) {
  if (config.phases[clock.phase]) {
    // En baloncesto, el descanso entre el segundo y el tercer cuarto es el largo.
    if (clock.phase === "descanso" && (config.halftimeAfter ?? 2) === clock.period) return "descanso";
    return config.phases[clock.phase];
  }
  const [, number] = clock.phase.split("-");
  return Number(number) > 4 ? `prórroga ${Number(number) - 4}` : `${number}.º cuarto`;
}
