###############################################################################
# Servicio: BigQuery — capa histórica Raw (HU-14)
#
# Una tabla por flujo, con exactamente el sobre que persiste el cargador
# (`gcperros.loading.sink.RawRecord.to_bigquery_row`) y nada más: la promesa
# de la historia es guardar el mensaje sin transformar, y una tabla con
# columnas derivadas del contenido de `payload` sería ya una transformación.
#
# El esquema vive aquí, como recurso de infraestructura, y no en el código
# Python: es la contraparte natural de la decisión que ya sostiene
# `core/schema.py` (ver `docs/decisiones-de-diseno.md`, sección 7) — el
# cargador no decide la forma de la tabla, sólo la rellena.
###############################################################################

resource "google_bigquery_dataset" "raw" {
  dataset_id  = var.raw_dataset_id
  project     = var.project_id
  location    = var.raw_dataset_location
  description = "Capa histórica Raw: cada mensaje de match-events y odds-updates, sin transformar (HU-14)."

  # Tiempo que una tabla del dataset conserva una partición antes de
  # expirarla automáticamente. Vacío (el valor por defecto de la variable)
  # significa "para siempre": es la premisa de la capa histórica, que existe
  # justamente para no depender de la retención de 7 días de la suscripción.
  default_partition_expiration_ms = var.raw_partition_expiration_ms

  labels = local.common_labels

  depends_on = [google_project_service.this]
}

# Quién puede insertar filas y ejecutar los jobs de streaming insert. Es la
# única identidad con permiso de escritura: ni el publicador ni el motor
# tocan esta capa.
resource "google_bigquery_dataset_iam_member" "raw_loader_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.raw.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.raw_loader.email}"
}

resource "google_project_iam_member" "raw_loader_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.raw_loader.email}"
}

###############################################################################
# Una tabla por flujo.
#
# `for_each` sobre `local.streams` (la misma fuente de verdad que usa
# `pubsub.tf`) en vez de dos bloques de recurso calcados: agregar un tercer
# flujo sigue siendo agregar una entrada al mapa, no copiar una tabla.
###############################################################################

locals {
  raw_tables = {
    for name, cfg in local.streams : name => {
      table_id = replace(name, "-", "_")
    }
  }
}

resource "google_bigquery_table" "raw" {
  for_each = local.raw_tables

  dataset_id = google_bigquery_dataset.raw.dataset_id
  table_id   = "${each.value.table_id}_raw"
  project    = var.project_id

  # Particionada por la marca de ingestión y no por `event_time`: es la única
  # de las tres marcas de tiempo del registro (`publish_time`, `event_time`
  # dentro de `payload`, `loaded_at`) que nunca varía con un reproceso ni con
  # el reloj de otro sistema. Partir por ella es lo que mantiene acotado el
  # costo de una consulta reciente sin tener que abrir `payload` para
  # calcularla.
  time_partitioning {
    type          = "DAY"
    field         = "loaded_at"
    expiration_ms = var.raw_partition_expiration_ms
  }

  # Agrupar por flujo basta: la tabla ya está separada por flujo en el
  # dataset lógico de la aplicación (una tabla por flujo), así que el
  # clustering aquí sólo ayuda a quien filtre además por `message_id` al
  # investigar un mensaje concreto.
  clustering = ["message_id"]

  schema = jsonencode([
    {
      name        = "message_id"
      type        = "STRING"
      mode        = "REQUIRED"
      description = "Identificador que Pub/Sub asignó al mensaje. Estable entre entregas: dos filas con el mismo message_id vienen del mismo mensaje, entregado más de una vez."
    },
    {
      name        = "publish_time"
      type        = "TIMESTAMP"
      mode        = "REQUIRED"
      description = "Cuándo se publicó el mensaje, según el broker."
    },
    {
      name        = "stream"
      type        = "STRING"
      mode        = "REQUIRED"
      description = "Flujo de origen (match-events u odds-updates), redundante con la tabla pero útil si algún día se consolidan."
    },
    {
      name        = "payload"
      type        = "STRING"
      mode        = "REQUIRED"
      description = "Carga útil cruda, exactamente como la escribió el productor. No se valida ni se interpreta: es la promesa de la capa Raw."
    },
    {
      name        = "attributes"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Atributos del mensaje de Pub/Sub, serializados como JSON. Nulo si el mensaje no traía ninguno."
    },
    {
      name        = "loaded_at"
      type        = "TIMESTAMP"
      mode        = "REQUIRED"
      description = "Cuándo lo persistió el cargador. Columna de partición: es la única marca de tiempo del registro que no varía con un reproceso."
    },
  ])

  labels = merge(local.common_labels, {
    stream = each.key
  })

  # Evita que un `terraform destroy` accidental se lleve por delante datos
  # históricos: el mismo criterio que ya aplica el proyecto en otros
  # recursos con estado que no se regenera solo.
  deletion_protection = var.raw_table_deletion_protection

  depends_on = [google_project_service.this]
}
