"""Línea de comandos de la demostración: ``gcperros-demo`` (#30).

Simula el partido de la semilla y lo sirve en vivo en ``http://127.0.0.1:8000``.
No necesita red ni cuenta de GCP: la misma semilla da la misma demo en clase
que en casa.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import uvicorn

from gcperros.demo.market import MarketTape
from gcperros.demo.replay import AmericanFootballReplay, BasketballReplay, MatchReplay
from gcperros.demo.server import DEFAULT_SPEED, LiveSource, create_app
from gcperros.engine.basketball_market import BASKETBALL_THRESHOLD, BasketballMarketReader
from gcperros.generators.american_football import (
    AmericanFootballConfig,
    simulate_american_football,
)
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.basketball_odds import simulate_basketball_odds
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds

#: Partido de exhibición. La semilla de referencia del proyecto (20260826) da un
#: 4-0 con 1,8 de xG, que ocurre en uno de cada veinte partidos y es lo primero
#: que preguntaría alguien que sabe de apuestas. Esta da un 2-1 con remontada,
#: goles en las dos partes, xG de 1,93 contra 1,03 y dos expulsiones.
SHOWCASE_SEED = 65

#: Partido de baloncesto de exhibición (#92): con esta semilla, los dos equipos
#: se pasan el liderato, hay rachas que acaban en tiempo muerto y se decide en
#: el último cuarto.
BASKETBALL_SHOWCASE_SEED = 65

#: El partido de fútbol americano de la demo: igualado hasta el último cuarto.
AMERICAN_FOOTBALL_SHOWCASE_SEED = 65


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos."""
    parser = argparse.ArgumentParser(
        prog="gcperros-demo",
        description="Sirve un partido simulado en vivo para enseñarlo a un cliente.",
    )
    parser.add_argument("--seed", type=int, default=SHOWCASE_SEED, help="Semilla del partido.")
    parser.add_argument("--home", default="RMA", help="Equipo local.")
    parser.add_argument("--away", default="BAR", help="Equipo visitante.")
    parser.add_argument(
        "--sport",
        choices=("todos", "ambos", "football", "basketball", "american_football"),
        default="todos",
        help="Qué deporte servir. Con los dos, la página trae un selector (#92).",
    )
    parser.add_argument("--basketball-home", default="BOS", help="Local del baloncesto.")
    parser.add_argument("--basketball-away", default="LAL", help="Visitante del baloncesto.")
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_SPEED,
        help="Minutos de partido por minuto real.",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        help="Carpeta con los informes JSON de validacion, carga y calidad.",
    )
    parser.add_argument(
        "--random-seeds",
        action="store_true",
        help="Genera partidos con semillas aleatorias en todos los deportes.",
    )
    parser.add_argument("--basketball-seed", type=int, help="Semilla específica del baloncesto.")
    parser.add_argument(
        "--american-football-seed",
        type=int,
        help="Semilla específica del fútbol americano.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.speed <= 0.0:
        parser.error("la velocidad debe ser positiva")

    if args.random_seeds:
        args.seed = secrets.randbelow(90000) + 1000
        if args.basketball_seed is None:
            args.basketball_seed = secrets.randbelow(90000) + 1000
        if args.american_football_seed is None:
            args.american_football_seed = secrets.randbelow(90000) + 1000

    sources: list[LiveSource] = []
    if args.sport in {"todos", "ambos", "football"}:
        sources.append(_football(args))
    if args.sport in {"todos", "ambos", "basketball"}:
        sources.append(_basketball(args))
    if args.sport in {"todos", "american_football"}:
        sources.append(_american_football(args))
    for source in sources:
        print(
            f"partido={source.match_id} deporte={source.sport} velocidad=x{args.speed:g} "
            f"estado=http://{args.host}:{args.port}/api/matches/{source.match_id}/state",
            file=sys.stderr,
        )
    reports_dir = args.reports or (Path("reports") if Path("reports").is_dir() else None)
    app = create_app(sources, reports_dir=reports_dir)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _football(args: argparse.Namespace) -> LiveSource:
    config = MatchConfig(match_id=f"demo-{args.seed}", home_team=args.home, away_team=args.away)
    events = simulate_match(args.seed, config)
    market = MarketTape(events, simulate_odds(args.seed, events))
    return LiveSource(MatchReplay(events), speed=args.speed, market=market)


def _basketball(args: argparse.Namespace) -> LiveSource:
    """El partido de baloncesto, al mismo ritmo de cuarto que el fútbol de parte."""
    teams = (args.basketball_home, args.basketball_away)
    seed = (
        args.basketball_seed
        if args.basketball_seed is not None
        else (args.seed if args.sport == "basketball" else BASKETBALL_SHOWCASE_SEED)
    )
    config = BasketballConfig(match_id=f"demo-bkb-{seed}", home_team=teams[0], away_team=teams[1])
    events = simulate_basketball(seed, config)
    market = MarketTape(
        events,
        simulate_basketball_odds(seed, events, teams),
        threshold=BASKETBALL_THRESHOLD,
        reader=BasketballMarketReader(*teams),
    )
    return LiveSource(BasketballReplay(events, teams), speed=args.speed, market=market)


def _american_football(args: argparse.Namespace) -> LiveSource:
    """El tercer deporte, sin cuotas: el marcador, la posesión y lo esperado (sección 22)."""
    seed = (
        args.american_football_seed
        if args.american_football_seed is not None
        else (args.seed if args.sport == "american_football" else AMERICAN_FOOTBALL_SHOWCASE_SEED)
    )
    teams = ("KC", "BUF")
    config = AmericanFootballConfig(f"demo-nfl-{seed}", *teams)
    events = simulate_american_football(seed, config)
    return LiveSource(AmericanFootballReplay(events, teams), speed=args.speed)


if __name__ == "__main__":
    raise SystemExit(main())
