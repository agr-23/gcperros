"""El motor de siempre con el tercer deporte (sección 22).

Deduplicación, marca de agua y posesión no cambian ni una línea: el fútbol
americano entra con su estado inyectado y se mide con la misma vara que los
otros dos, con el margen que sus datos eligieron.
"""

from __future__ import annotations

from gcperros.core.american_football_stats import summarize_american_football
from gcperros.engine.american_football_state import american_football_engine
from gcperros.generators.american_football import simulate_american_football
from gcperros.governance.traceability import audit


def test_the_live_state_projects_to_the_batch_summary() -> None:
    events = simulate_american_football(7)

    live = american_football_engine().process_all(events).summary

    assert live == summarize_american_football(events)


def test_every_number_explains_where_it_comes_from() -> None:
    engine = american_football_engine()
    engine.process_all(simulate_american_football(7))

    trail = audit(engine.state)
    kicks = [e for e in trail.explanations if e.indicator == "kick_expected_points"]

    assert kicks and all(e.model_versions == {"kick": "kick-1.0.0"} for e in kicks)
    assert all(e.lineage.event_count > 0 for e in trail.explanations if e.value)
