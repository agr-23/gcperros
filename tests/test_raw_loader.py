"""El cargador de la capa Raw: extrae, persiste y confirma (HU-14)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from gcperros.loading.raw_loader import RawLoader
from gcperros.loading.sink import InMemoryRawSink, RawRecord, SinkError
from gcperros.loading.subscriber import InMemorySubscriber, PulledMessage

FIXED_INSTANT = datetime(2026, 8, 26, 21, 0, 0, tzinfo=UTC)


def _message(
    ack_id: str,
    message_id: str = "msg-1",
    payload: bytes = b'{"event_id":"e1"}',
    attributes: dict[str, str] | None = None,
) -> PulledMessage:
    return PulledMessage(
        ack_id=ack_id,
        message_id=message_id,
        publish_time=FIXED_INSTANT,
        data=payload,
        attributes=attributes or {},
    )


def _loader(subscriber: InMemorySubscriber, sink: InMemoryRawSink) -> RawLoader:
    return RawLoader(subscriber, sink, "match-events", clock=lambda: FIXED_INSTANT)


###############################################################################
# El recorrido feliz: extraer, persistir, confirmar
###############################################################################


def test_a_successful_poll_persists_and_acknowledges() -> None:
    subscriber = InMemorySubscriber([_message("ack-1")])
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    loaded = loader.poll()

    assert loaded == 1
    assert len(sink.records) == 1
    assert subscriber.acked == ["ack-1"]
    assert loader.stats.pulled == 1
    assert loader.stats.loaded == 1
    assert loader.stats.failed == 0


def test_an_empty_pull_is_not_an_error() -> None:
    loader = _loader(InMemorySubscriber([]), InMemoryRawSink())

    assert loader.poll() == 0
    assert loader.stats.pulled == 0
    assert loader.stats.empty_polls == 1


def test_the_payload_is_stored_verbatim() -> None:
    """Lo que llega al broker es exactamente lo que se persiste, sin interpretarlo."""
    payload = b'{"event_id":"e1","attrs":{"xg":0.2}}'
    subscriber = InMemorySubscriber([_message("ack-1", payload=payload)])
    sink = InMemoryRawSink()
    _loader(subscriber, sink).poll()

    record = sink.records[0]
    assert record.payload == payload.decode("utf-8")
    assert record.stream == "match-events"
    assert record.message_id == "msg-1"


def test_undecodable_bytes_are_stored_with_replacement_and_not_dropped() -> None:
    """Igual que la frontera de ingestión: la capa Raw no descarta basura, la archiva."""
    subscriber = InMemorySubscriber([_message("ack-1", payload=b"\xff\xfe not utf-8")])
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    loaded = loader.poll()

    assert loaded == 1
    assert len(sink.records) == 1


def test_attributes_travel_untouched() -> None:
    subscriber = InMemorySubscriber(
        [_message("ack-1", attributes={"event_type": "shot", "match_id": "match-0001"})]
    )
    sink = InMemoryRawSink()
    _loader(subscriber, sink).poll()

    assert sink.records[0].attributes == {"event_type": "shot", "match_id": "match-0001"}


###############################################################################
# Nada se deduplica ni se filtra: es trabajo de otra capa
###############################################################################


def test_a_redelivered_duplicate_is_persisted_again() -> None:
    """La capa Raw promete el flujo tal como llegó, con sus repeticiones incluidas."""
    subscriber = InMemorySubscriber(
        [_message("ack-1", message_id="same-id"), _message("ack-2", message_id="same-id")]
    )
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    loader.drain()

    assert len(sink.records) == 2
    assert {record.message_id for record in sink.records} == {"same-id"}


###############################################################################
# El fallo de escritura no confirma el lote
###############################################################################


def test_a_write_failure_leaves_the_batch_unacknowledged() -> None:
    subscriber = InMemorySubscriber([_message("ack-1")])
    sink = InMemoryRawSink(fail_times=1)
    loader = _loader(subscriber, sink)

    loaded = loader.poll()

    assert loaded == 0
    assert subscriber.acked == []
    assert loader.stats.failed == 1
    assert loader.stats.loaded == 0
    # El mensaje sigue «en vuelo»: no se confirmó, así que un sondeo posterior
    # tampoco lo vería salvo que el propio doble simule la redelivery. Lo que
    # sí es observable aquí es que nunca se llamó a `ack`.


def test_write_failures_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    subscriber = InMemorySubscriber([_message("ack-1")])
    sink = InMemoryRawSink(fail_times=1)

    with caplog.at_level(logging.ERROR):
        _loader(subscriber, sink).poll()

    assert any("no se pudo persistir" in record.message for record in caplog.records)


def test_a_transient_failure_recovers_on_the_next_poll() -> None:
    """Tras el fallo, un reintento posterior (con el mensaje reentregado) sí progresa."""
    subscriber = InMemorySubscriber([_message("ack-1")])
    sink = InMemoryRawSink(fail_times=1)
    loader = _loader(subscriber, sink)

    assert loader.poll() == 0  # primer intento: falla la escritura

    # Simula la redelivery de Pub/Sub: el mismo mensaje vuelve a ofrecerse.
    subscriber = InMemorySubscriber([_message("ack-1")])
    loader = RawLoader(subscriber, sink, "match-events", clock=lambda: FIXED_INSTANT)
    assert loader.poll() == 1

    assert len(sink.records) == 1
    assert subscriber.acked == ["ack-1"]


###############################################################################
# `drain`: agota lo disponible y se detiene
###############################################################################


def test_drain_consumes_every_available_batch() -> None:
    messages = [_message(f"ack-{i}", message_id=f"msg-{i}") for i in range(5)]
    subscriber = InMemorySubscriber(messages)
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    stats = loader.drain(max_messages=2)

    assert stats.loaded == 5
    assert len(sink.records) == 5
    assert subscriber.pending_count == 0


def test_drain_stops_without_polling_forever() -> None:
    loader = _loader(InMemorySubscriber([]), InMemoryRawSink())

    stats = loader.drain()

    assert stats.pulled == 0
    assert stats.empty_polls >= 1


###############################################################################
# `run_forever`: sondeo continuo con espera entre ciclos vacíos
###############################################################################


def test_run_forever_waits_between_empty_polls() -> None:
    subscriber = InMemorySubscriber([_message("ack-1")])
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    waited: list[float] = []
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 3  # dos vueltas: una con mensaje, dos vacías

    loader.run_forever(idle_backoff_s=1.5, sleep=waited.append, stop=stop)

    assert loader.stats.loaded == 1
    assert waited  # hubo al menos una espera tras un sondeo vacío
    assert all(wait == 1.5 for wait in waited)


###############################################################################
# Ciclo de vida
###############################################################################


def test_closing_the_loader_closes_both_collaborators() -> None:
    subscriber = InMemorySubscriber([])
    sink = InMemoryRawSink()
    loader = _loader(subscriber, sink)

    loader.close()

    assert subscriber.closed is True
    assert sink.closed is True


###############################################################################
# `RawRecord`: la forma exacta de lo persistido
###############################################################################


def test_the_bigquery_row_carries_the_full_envelope() -> None:
    record = RawRecord(
        stream="match-events",
        message_id="msg-1",
        publish_time=FIXED_INSTANT,
        payload='{"event_id":"e1"}',
        attributes={"event_type": "shot"},
        loaded_at=FIXED_INSTANT,
    )

    row = record.to_bigquery_row()

    assert row["message_id"] == "msg-1"
    assert row["stream"] == "match-events"
    assert row["payload"] == '{"event_id":"e1"}'
    assert json.loads(str(row["attributes"])) == {"event_type": "shot"}
    assert row["publish_time"] == "2026-08-26T21:00:00.000Z"
    assert row["loaded_at"] == "2026-08-26T21:00:00.000Z"


def test_empty_attributes_are_stored_as_null_not_an_empty_object() -> None:
    record = RawRecord(
        stream="odds-updates",
        message_id="msg-2",
        publish_time=FIXED_INSTANT,
        payload="{}",
        attributes={},
        loaded_at=FIXED_INSTANT,
    )

    assert record.to_bigquery_row()["attributes"] is None


###############################################################################
# El destino en memoria
###############################################################################


def test_the_in_memory_sink_raises_sink_error_while_failures_remain() -> None:
    sink = InMemoryRawSink(fail_times=2)
    record = RawRecord("match-events", "m1", FIXED_INSTANT, "{}", {}, FIXED_INSTANT)

    with pytest.raises(SinkError):
        sink.write([record])
    with pytest.raises(SinkError):
        sink.write([record])
    sink.write([record])  # al tercer intento, acepta

    assert len(sink.records) == 1
