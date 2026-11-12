"""El motor detrás del endpoint push de Pub/Sub, como lo usaría Pub/Sub (Cloud Run)."""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from gcperros.core.contracts import MatchEvent
from gcperros.firestore.store import InMemoryDocumentStore
from gcperros.generators.basketball import BasketballConfig, simulate_basketball
from gcperros.generators.match import MatchConfig, simulate_match
from gcperros.governance.quarantine import InMemoryInvalidStore
from gcperros.service.app import EngineService, create_service, stream_of

FOOTBALL = simulate_match(65, MatchConfig(match_id="srv-fb", home_team="RMA", away_team="BAR"))
BASKETBALL = simulate_basketball(65, BasketballConfig("srv-bk", "BOS", "LAL"))


def _envelope(message: str, stream: str = "match-events") -> dict[str, object]:
    return {
        "message": {"data": base64.b64encode(message.encode()).decode(), "messageId": "1"},
        "subscription": f"projects/demo/subscriptions/{stream}-engine",
    }


def _client(
    store: InMemoryDocumentStore, invalid: InMemoryInvalidStore | None = None
) -> TestClient:
    return TestClient(create_service(EngineService(store, invalid)))


def _deliver(client: TestClient, events: list[MatchEvent], stream: str) -> list[int]:
    return [
        client.post("/pubsub/push", json=_envelope(e.to_json(), stream)).status_code for e in events
    ]


def test_both_sports_are_served_side_by_side_and_repeats_count_once() -> None:
    store, twice = InMemoryDocumentStore(), InMemoryDocumentStore()
    client = _client(store)

    assert set(_deliver(client, FOOTBALL[:300], "match-events")) == {204}
    _deliver(client, BASKETBALL[:200], "basketball-events")
    _deliver(_client(twice), [e for e in FOOTBALL[:300] for _ in range(2)], "match-events")

    assert set(store.documents) == {"srv-fb", "srv-bk"}
    assert store.documents["srv-fb"]["teams"] == ["RMA", "BAR"]
    assert store.documents["srv-fb"]["indicators"] == twice.documents["srv-fb"]["indicators"]
    assert client.get("/healthz").json() == {"status": "ok", "matches": 2}


def test_a_contract_breach_is_acknowledged_and_archived_not_retried() -> None:
    store, invalid = InMemoryDocumentStore(), InMemoryInvalidStore()
    client = _client(store, invalid)
    shot = json.loads(next(e for e in BASKETBALL if e.event_type == "shot").to_json())
    shot["attrs"]["points_value"] = 4

    breach = client.post("/pubsub/push", json=_envelope(json.dumps(shot), "basketball-events"))
    odds = client.post("/pubsub/push", json=_envelope("{no cierra", "odds-updates"))

    assert (breach.status_code, odds.status_code) == (204, 204)
    assert len(invalid.records) == 2 and not store.documents


@pytest.mark.parametrize(
    "envelope",
    [{"message": {}}, {"subscription": "x"}, _envelope("{}", "user-clicks")],
    ids=["sin-datos", "sin-mensaje", "flujo-desconocido"],
)
def test_a_malformed_envelope_is_a_configuration_error(envelope: dict[str, object]) -> None:
    assert _client(InMemoryDocumentStore()).post("/pubsub/push", json=envelope).status_code == 400


def test_a_failed_write_asks_for_a_retry_and_the_retry_writes_it() -> None:
    """El reintento es una repetición que el motor descarta: el documento se escribe igual."""
    store = InMemoryDocumentStore(fail_times=1)
    client = _client(store)
    failed = next(e for e in FOOTBALL if _deliver(client, [e], "match-events") == [500])
    assert "srv-fb" not in store.documents

    assert _deliver(client, [failed], "match-events") == [204]
    assert "srv-fb" in store.documents


def test_the_stream_comes_from_the_engine_subscription_with_or_without_prefix() -> None:
    assert stream_of("projects/p/subscriptions/basketball-odds-engine") == "basketball-odds"
    assert stream_of("projects/p/subscriptions/dev-match-events-engine") == "match-events"
    with pytest.raises(ValueError, match="no es la suscripción"):
        stream_of("projects/p/subscriptions/match-events-raw")
