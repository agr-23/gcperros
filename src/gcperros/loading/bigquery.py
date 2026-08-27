"""Adaptador real hacia la tabla Raw de BigQuery.

Deliberadamente delgado, por el mismo motivo que los demás adaptadores reales
del proyecto: traduce la llamada y convierte cualquier fallo del cliente en
``SinkError``, que es lo único que el cargador sabe interpretar. La librería
cliente es una dependencia opcional y se importa de forma diferida.
"""

from __future__ import annotations

from gcperros.loading.sink import RawRecord, SinkError


class BigQueryRawSink:
    """Inserta lotes de registros crudos en una tabla Raw de BigQuery."""

    __slots__ = ("_client", "_table_ref")

    def __init__(self, project_id: str, dataset: str, table: str) -> None:
        """Crea el cliente de BigQuery.

        Args:
            project_id: Proyecto de GCP donde vive el dataset.
            dataset: Dataset que contiene la tabla Raw (``infra/terraform``
                lo declara con el mismo nombre que espera este cliente).
            table: Tabla del flujo (``match_events_raw`` u
                ``odds_updates_raw``).

        Raises:
            RuntimeError: Si falta la librería cliente.
        """
        try:
            from google.cloud import bigquery
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "falta google-cloud-bigquery. Instálalo con: pip install -e '.[bigquery]'"
            ) from error

        self._client = bigquery.Client(project=project_id)
        self._table_ref = f"{project_id}.{dataset}.{table}"

    def write(self, records: list[RawRecord]) -> None:
        """Inserta el lote mediante streaming insert.

        Se usa ``insert_rows_json`` con ``row_ids`` iguales al
        ``message_id`` de cada registro: es una deduplicación de mejor
        esfuerzo que BigQuery aplica en una ventana corta, y protege contra
        que un reintento del propio cargador —no una redelivery del
        broker— duplique una fila. No sustituye ninguna deduplicación aguas
        abajo: si Pub/Sub entrega el mismo mensaje dos veces con más tiempo
        de separación, las dos entregas producen dos filas, a propósito. Ver
        ``docs/decisiones-de-diseno.md``, sección 10.

        Raises:
            SinkError: Si BigQuery rechazó alguna fila del lote.
        """
        if not records:
            return

        rows = [record.to_bigquery_row() for record in records]
        row_ids = [record.message_id for record in records]

        try:
            errors = self._client.insert_rows_json(self._table_ref, rows, row_ids=row_ids)
        except Exception as error:
            raise SinkError(f"BigQuery rechazó la inserción: {error}") from error

        if errors:
            raise SinkError(f"BigQuery rechazó {len(errors)} fila(s) del lote: {errors}")

    def close(self) -> None:
        """Cierra el cliente."""
        self._client.close()
