"""Cargador de la capa Raw de BigQuery (HU-14).

Consume las suscripciones pull de ``match-events`` y ``odds-updates`` y
persiste cada mensaje **sin transformar** en su tabla Raw correspondiente, de
modo que la capa histórica empiece a acumular datos desde que existe tráfico
real, en vez de construirse de una sola vez al final del proyecto.

Es deliberadamente el consumidor más simple posible: no deduplica, no
reordena, no interpreta ``attrs``. Esas tres cosas son trabajo del motor
(``gcperros.engine``, HU-11/HU-12) sobre el estado *vivo* de un partido; la
capa Raw existe precisamente para conservar lo que el motor descarta o
resume, y un cargador que ya limpiara lo que recibe dejaría de servir para
ese propósito. Ver ``docs/decisiones-de-diseno.md``, sección 10.

Estructura, en el mismo orden que ``gcperros.publishing``, que resuelve el
problema simétrico:

- ``subscriber.py``  — protocolo de extracción (``PullSubscriber``) y su doble
  en memoria, para pruebas y para el modo de ensayo.
- ``pubsub.py``       — adaptador real hacia Pub/Sub (suscripción pull).
- ``sink.py``         — protocolo de persistencia (``RawSink``) y su doble en
  memoria, más la forma exacta de un registro Raw (``RawRecord``).
- ``bigquery.py``     — adaptador real hacia BigQuery.
- ``raw_loader.py``   — el propio cargador: extrae, persiste y confirma.
- ``cli.py``          — ``gcperros-load-raw``.
"""

from __future__ import annotations
