"""Publicación hacia el broker, con reintento y registro (HU-10)."""

from __future__ import annotations

import json
import logging

import pytest

from gcperros.core.contracts import MatchEvent
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.generators.odds import simulate_odds
from gcperros.publishing.publisher import (
    MATCH_EVENTS_TOPIC,
    ODDS_UPDATES_TOPIC,
    PublishError,
    RetryPolicy,
    StreamPublisher,
)
from gcperros.publishing.transport import InMemoryTransport, TransportError

CONFIG = MatchConfig(match_id="match-0010", home_team="RMA", away_team="BAR")
SEED = 20260826


def _publisher(transport: InMemoryTransport, max_attempts: int | None = None) -> StreamPublisher:
    """Publicador cuya espera no cuesta tiempo real."""
    return StreamPublisher(
        transport,
        policy=RetryPolicy(max_attempts=max_attempts) if max_attempts else None,
        sleep=lambda _: None,
    )


@pytest.fixture(scope="module")
def events() -> list[MatchEvent]:
    return simulate_match(SEED, CONFIG)


###############################################################################
# Cada flujo va a su topic
###############################################################################


def test_match_events_go_to_their_own_topic(events: list[MatchEvent]) -> None:
    transport = InMemoryTransport()
    _publisher(transport).publish_match_events(events)

    assert len(transport.messages) == len(events)
    assert {topic for topic, _, _ in transport.messages} == {MATCH_EVENTS_TOPIC}


def test_odds_updates_go_to_their_own_topic(events: list[MatchEvent]) -> None:
    updates = simulate_odds(SEED, events)
    transport = InMemoryTransport()
    _publisher(transport).publish_odds_updates(updates)

    assert len(transport.messages) == len(updates)
    assert {topic for topic, _, _ in transport.messages} == {ODDS_UPDATES_TOPIC}


def test_the_two_streams_never_share_a_topic(events: list[MatchEvent]) -> None:
    """Son dos contratos distintos y viajan por canales distintos."""
    transport = InMemoryTransport()
    publisher = _publisher(transport)
    publisher.publish_match_events(events)
    publisher.publish_odds_updates(simulate_odds(SEED, events))

    assert set(publisher.stats.by_topic) == {MATCH_EVENTS_TOPIC, ODDS_UPDATES_TOPIC}


def test_the_payload_is_the_contract_verbatim(events: list[MatchEvent]) -> None:
    """Lo que viaja es exactamente lo que se persistirá en la capa Raw."""
    transport = InMemoryTransport()
    _publisher(transport).publish_match_events(events[:5])

    for event, (_, payload, _) in zip(events[:5], transport.messages, strict=True):
        assert payload.decode("utf-8") == event.to_json()
        assert json.loads(payload)["event_id"] == event.event_id


def test_attributes_allow_filtering_without_opening_the_payload(
    events: list[MatchEvent],
) -> None:
    """Los atributos son lo que permite a una suscripción filtrar por tipo."""
    transport = InMemoryTransport()
    _publisher(transport).publish_match_events(events[:20])

    for event, (_, _, attributes) in zip(events[:20], transport.messages, strict=True):
        assert attributes["event_type"] == event.event_type
        assert attributes["match_id"] == event.match_id


###############################################################################
# Reintento
###############################################################################


def test_a_transient_failure_is_retried_until_it_works(events: list[MatchEvent]) -> None:
    transport = InMemoryTransport(fail_times=3)
    publisher = _publisher(transport, max_attempts=5)

    publisher.publish_match_events(events[:1])

    assert publisher.stats.published == 1
    assert publisher.stats.retries == 3
    assert publisher.stats.failed == 0
    assert len(transport.messages) == 1


def test_a_permanent_failure_stops_the_run(events: list[MatchEvent]) -> None:
    """Agotados los intentos se para: perder un evento en silencio sería peor."""
    transport = InMemoryTransport(fail_times=99)
    publisher = _publisher(transport, max_attempts=3)

    with pytest.raises(PublishError, match="3 intentos"):
        publisher.publish_match_events(events[:1])

    assert publisher.stats.published == 0
    assert publisher.stats.failed == 1
    assert publisher.stats.retries == 3


def test_the_failure_cause_survives_in_the_exception_chain(
    events: list[MatchEvent],
) -> None:
    transport = InMemoryTransport(fail_times=99)

    with pytest.raises(PublishError) as raised:
        _publisher(transport, max_attempts=2).publish_match_events(events[:1])

    assert isinstance(raised.value.__cause__, TransportError)


def test_failures_are_logged_with_their_cause(
    events: list[MatchEvent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La historia pide registro, no sólo reintento."""
    transport = InMemoryTransport(fail_times=2)

    with caplog.at_level(logging.WARNING):
        _publisher(transport, max_attempts=5).publish_match_events(events[:1])

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "fallo al publicar" in warnings[0].message


def test_giving_up_is_logged_as_an_error(
    events: list[MatchEvent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = InMemoryTransport(fail_times=99)

    with caplog.at_level(logging.ERROR), pytest.raises(PublishError):
        _publisher(transport, max_attempts=2).publish_match_events(events[:1])

    assert any(record.levelno == logging.ERROR for record in caplog.records)


###############################################################################
# Política de espera
###############################################################################


def test_the_wait_grows_with_each_attempt() -> None:
    policy = RetryPolicy(initial_backoff_s=1.0, multiplier=2.0, max_backoff_s=100.0)
    waits = [policy.backoff_for(attempt) for attempt in range(1, 6)]

    assert waits == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_the_wait_is_capped() -> None:
    policy = RetryPolicy(initial_backoff_s=1.0, multiplier=10.0, max_backoff_s=5.0)
    assert policy.backoff_for(9) == 5.0


def test_an_impossible_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="al menos un intento"):
        RetryPolicy(max_attempts=0)

    with pytest.raises(ValueError, match="no pueden ser negativas"):
        RetryPolicy(initial_backoff_s=-1.0)

    with pytest.raises(ValueError, match="crecer la espera"):
        RetryPolicy(multiplier=0.5)


def test_waiting_happens_between_attempts(events: list[MatchEvent]) -> None:
    """Se comprueba que se espera de verdad, sin gastar el tiempo de la espera."""
    waited: list[float] = []
    transport = InMemoryTransport(fail_times=2)
    publisher = StreamPublisher(
        transport,
        policy=RetryPolicy(max_attempts=5, initial_backoff_s=1.0),
        sleep=waited.append,
    )

    publisher.publish_match_events(events[:1])

    assert len(waited) == 2
    assert all(delay > 0 for delay in waited)


###############################################################################
# Ciclo de vida
###############################################################################


def test_closing_the_publisher_closes_the_transport() -> None:
    transport = InMemoryTransport()
    publisher = _publisher(transport)

    assert transport.closed is False
    publisher.close()
    assert transport.closed is True


def test_statistics_start_empty() -> None:
    stats = _publisher(InMemoryTransport()).stats

    assert stats.published == 0
    assert stats.retries == 0
    assert stats.retry_rate == 0.0
