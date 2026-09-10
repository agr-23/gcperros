"""Posesión acumulada y por ventana móvil (HU-20).

Lo que promete la historia: la posesión medida como tiempo, en dos lecturas
—todo el partido y los últimos cinco minutos—, y una ventana que cierra cuando
la marca de agua pasa su borde derecho y **no vuelve a abrirse**.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gcperros.core.contracts import EventType, MatchEvent
from gcperros.core.possession import (
    MAX_IN_PLAY_GAP_S,
    POSSESSION_WINDOW_S,
    PossessionTracker,
    possession_totals,
)
from gcperros.engine.pipeline import MatchEngine
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.perturbation import inject_disorder, inject_duplicates

BASE = datetime(2026, 8, 26, 19, 0, 0, tzinfo=UTC)
CONFIG = MatchConfig(match_id="match-0020", home_team="RMA", away_team="BAR")
SEED = 20260826


def _event(second: float, team: str, event_type: EventType = "pass") -> MatchEvent:
    """Evento mínimo situado a ``second`` segundos del saque inicial."""
    return MatchEvent(
        event_id=f"e{second}-{team}-{event_type}",
        event_time=BASE + timedelta(seconds=second),
        match_id="match-0020",
        team=team,
        event_type=event_type,
        attrs={},
    )


def _feed(tracker: PossessionTracker, events: list[MatchEvent]) -> None:
    for event in events:
        tracker.apply(event)


###############################################################################
# La posesión se mide en tiempo, no en veces
###############################################################################


def test_possession_goes_to_whoever_holds_the_ball() -> None:
    tracker = PossessionTracker()
    _feed(
        tracker,
        [
            _event(0, "RMA", "possession_change"),
            _event(4, "RMA"),
            _event(8, "BAR", "possession_change"),
            _event(10, "BAR"),
        ],
    )

    seconds = tracker.snapshot().running_seconds
    assert seconds["RMA"] == pytest.approx(8.0)
    assert seconds["BAR"] == pytest.approx(2.0)


def test_holding_the_ball_longer_beats_recovering_it_more_often() -> None:
    """La distinción que motiva la historia: veces y tiempo no son lo mismo."""
    tracker = PossessionTracker()
    _feed(
        tracker,
        [
            _event(0, "RMA", "possession_change"),
            _event(5, "RMA"),
            _event(9, "RMA"),  # RMA encadena una posesión larga
            _event(9, "BAR", "possession_change"),
            _event(11, "BAR", "possession_change"),  # BAR recupera dos veces
            _event(13, "BAR"),
        ],
    )

    seconds = tracker.snapshot().running_seconds
    assert seconds["RMA"] > seconds["BAR"]


def test_nothing_is_credited_before_the_first_possession_change() -> None:
    """Sin saber quién tiene el balón no se puede atribuir nada."""
    tracker = PossessionTracker()
    _feed(tracker, [_event(0, "RMA"), _event(5, "RMA")])

    assert tracker.snapshot().in_play_seconds == 0.0


def test_a_stoppage_belongs_to_nobody() -> None:
    """El descanso no puede regalarle quince minutos a quien tuviera el balón."""
    tracker = PossessionTracker()
    _feed(
        tracker,
        [
            _event(0, "RMA", "possession_change"),
            _event(5, "RMA"),
            _event(905, "RMA"),  # 900 s después: el partido estaba parado
        ],
    )

    assert tracker.snapshot().running_seconds["RMA"] == pytest.approx(5.0)


def test_the_threshold_separates_play_from_dead_ball() -> None:
    """El umbral cae en la banda vacía entre el juego y el balón parado."""
    assert MAX_IN_PLAY_GAP_S > 8.0, "tiene que admitir la duración de un pase"
    assert MAX_IN_PLAY_GAP_S < 14.0, "no puede admitir un saque de banda"


###############################################################################
# Ventanas
###############################################################################


def test_time_is_split_between_the_windows_it_crosses() -> None:
    """Una posesión a caballo de dos ventanas se reparte, no se regala entera.

    Las ventanas se anclan al primer evento del flujo, así que aquí el borde
    entre la ventana 0 y la 1 cae en el segundo 10.
    """
    tracker = PossessionTracker(window_s=10.0)
    _feed(
        tracker,
        [
            _event(0, "RMA"),  # fija el origen de las ventanas
            _event(6, "RMA", "possession_change"),
            _event(14, "RMA"),
        ],
    )

    windows = tracker.close_through(BASE + timedelta(seconds=100))
    assert windows[0].seconds["RMA"] == pytest.approx(4.0)  # de 6 a 10
    assert windows[1].seconds["RMA"] == pytest.approx(4.0)  # de 10 a 14


def test_a_window_closes_only_when_the_watermark_passes_it() -> None:
    tracker = PossessionTracker(window_s=10.0)
    _feed(tracker, [_event(0, "RMA", "possession_change"), _event(5, "RMA")])

    assert tracker.close_through(BASE + timedelta(seconds=9)) == []

    closed = tracker.close_through(BASE + timedelta(seconds=10))
    assert [window.index for window in closed] == [0]


def test_a_closed_window_never_reopens() -> None:
    """La promesa literal de la historia."""
    tracker = PossessionTracker(window_s=10.0)
    _feed(tracker, [_event(0, "RMA", "possession_change"), _event(5, "RMA")])

    closed = tracker.close_through(BASE + timedelta(seconds=60))
    assert closed[0].seconds["RMA"] == pytest.approx(5.0)

    # Un evento que caería dentro de esa ventana ya no la toca.
    tracker.apply(_event(7, "RMA"))
    again = tracker.close_through(BASE + timedelta(seconds=60))

    assert again == [], "una ventana cerrada no se vuelve a emitir"
    assert closed[0].seconds["RMA"] == pytest.approx(5.0)


def test_closed_windows_are_contiguous() -> None:
    """La serie temporal no puede tener huecos, aunque alguna ventana esté vacía."""
    tracker = PossessionTracker(window_s=10.0)
    _feed(tracker, [_event(0, "RMA", "possession_change"), _event(5, "RMA")])

    closed = tracker.close_through(BASE + timedelta(seconds=45))
    assert [window.index for window in closed] == [0, 1, 2, 3]


def test_an_empty_window_reports_no_share_instead_of_dividing_by_zero() -> None:
    tracker = PossessionTracker(window_s=10.0)
    _feed(tracker, [_event(0, "RMA", "possession_change"), _event(5, "RMA")])

    empty = tracker.close_through(BASE + timedelta(seconds=45))[2]
    assert empty.in_play_seconds == 0.0
    assert empty.share == {}


def test_window_share_adds_up_to_one() -> None:
    tracker = PossessionTracker(window_s=60.0)
    _feed(
        tracker,
        [
            _event(0, "RMA", "possession_change"),
            _event(6, "BAR", "possession_change"),
            _event(12, "BAR"),
        ],
    )

    window = tracker.close_through(BASE + timedelta(seconds=120))[0]
    assert sum(window.share.values()) == pytest.approx(1.0)


def test_invalid_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="anchura"):
        PossessionTracker(window_s=0)

    with pytest.raises(ValueError, match="hueco"):
        PossessionTracker(max_in_play_gap_s=-1)


###############################################################################
# Integración con el motor
###############################################################################


def test_the_engine_matches_the_batch_reference() -> None:
    """El camino incremental tiene que dar lo mismo que recorrer el flujo entero."""
    events = simulate_match(SEED, CONFIG)
    result = MatchEngine().process_all(events)

    assert result.possession.running_seconds == possession_totals(events)


def test_possession_survives_a_hostile_broker() -> None:
    """Con duplicados y desorden, la posesión sigue siendo la del flujo limpio."""
    events = simulate_match(SEED, CONFIG)
    duplicated, _ = inject_duplicates(events, seed=3, rate=0.15)
    delivered, _ = inject_disorder(duplicated, seed=11)

    result = MatchEngine(allowed_lateness_s=30.0).process_all(delivered)

    assert result.possession.running_seconds == possession_totals(events)


def test_the_engine_emits_five_minute_windows() -> None:
    events = simulate_match(SEED, CONFIG)
    result = MatchEngine().process_all(events)

    assert len(result.possession_windows) > 15
    for window in result.possession_windows:
        assert (window.end - window.start).total_seconds() == POSSESSION_WINDOW_S


def test_windows_close_in_order_and_without_gaps() -> None:
    events = simulate_match(SEED, CONFIG)
    windows = MatchEngine().process_all(events).possession_windows

    assert [window.index for window in windows] == list(range(len(windows)))


def test_the_window_shows_what_the_average_hides() -> None:
    """La razón de ser de la historia, comprobada sobre un partido real.

    Si ninguna ventana se apartara del acumulado, la ventana móvil no aportaría
    nada y la historia no tendría sentido.
    """
    events = simulate_match(SEED, CONFIG)
    result = MatchEngine().process_all(events)

    overall = result.possession.running_share["RMA"]
    played = [w for w in result.possession_windows if w.in_play_seconds > 0]
    swings = [abs(window.share["RMA"] - overall) for window in played]

    assert max(swings) > 0.10, "alguna ventana debe apartarse del promedio"


@pytest.mark.statistical
def test_in_play_time_is_plausible() -> None:
    """El tiempo atribuido debe parecerse al de un partido, no al del reloj.

    La referencia del fútbol real está entre 55 y 60 minutos. El generador tiene
    un modelo de balón parado más ligero, así que sale algo por encima; el rango
    de la prueba lo admite pero descartaría atribuir el partido entero.
    """
    for seed in range(6):
        events = simulate_match(seed, CONFIG)
        minutes = MatchEngine().process_all(events).possession.in_play_seconds / 60

        assert 50 < minutes < 75, f"semilla {seed}: {minutes:.1f} min atribuidos"


@pytest.mark.statistical
def test_neither_team_dominates_by_construction() -> None:
    """El generador es simétrico: la posesión no puede salir sesgada de fábrica."""
    shares = []
    for seed in range(10):
        events = simulate_match(seed, CONFIG)
        shares.append(MatchEngine().process_all(events).possession.running_share["RMA"])

    assert 0.45 < sum(shares) / len(shares) < 0.55
