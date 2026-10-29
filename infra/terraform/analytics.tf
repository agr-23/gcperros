###############################################################################
# Capa analítica histórica en BigQuery — Modelo Estrella (HU-22, HU-23)
#
# Tablas de hechos para eventos y señales con distinción explícita de
# event_time vs ingestion_time, particionadas por event_time y clusterizadas
# por match_id y market (o event_type) para optimizar consultas de benchmark.
###############################################################################

locals {
  analytics_dataset_id = "gcperros_analytics"
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id  = local.analytics_dataset_id
  project     = var.project_id
  location    = var.raw_dataset_location
  description = "Capa histórica analítica: modelo estrella (HU-22) y optimización física (HU-23)."
  labels      = local.common_labels
  depends_on  = [google_project_service.this]
}

resource "google_bigquery_table" "dim_match" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "dim_match"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "match_id", type = "STRING", mode = "REQUIRED", description = "ID único del partido." },
    { name = "matchday", type = "INTEGER", mode = "REQUIRED", description = "Jornada del torneo." },
    { name = "season", type = "STRING", mode = "REQUIRED", description = "Temporada deportiva." },
    { name = "home_team", type = "STRING", mode = "REQUIRED", description = "Código del equipo local." },
    { name = "away_team", type = "STRING", mode = "REQUIRED", description = "Código del equipo visitante." },
    { name = "match_date", type = "DATE", mode = "REQUIRED", description = "Fecha del encuentro." }
  ])
}

resource "google_bigquery_table" "dim_market" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "dim_market"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "market", type = "STRING", mode = "REQUIRED", description = "Clave del mercado (1x2, over_under_2_5)." },
    { name = "market_name", type = "STRING", mode = "REQUIRED", description = "Nombre descriptivo del mercado." },
    { name = "outcomes", type = "STRING", mode = "REPEATED", description = "Resultados posibles." },
    { name = "market_type", type = "STRING", mode = "REQUIRED", description = "Tipo de mercado." }
  ])
}

resource "google_bigquery_table" "dim_operator" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "dim_operator"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "operator_id", type = "STRING", mode = "REQUIRED", description = "ID del operador (OP-A, OP-B, OP-C)." },
    { name = "operator_name", type = "STRING", mode = "REQUIRED", description = "Nombre del operador." }
  ])
}

resource "google_bigquery_table" "fact_match_events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "fact_match_events"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  time_partitioning {
    type  = "DAY"
    field = "event_time"
  }

  clustering = ["match_id", "event_type"]

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED", description = "ID único del evento." },
    { name = "match_id", type = "STRING", mode = "REQUIRED", description = "FK a dim_match." },
    { name = "team", type = "STRING", mode = "REQUIRED", description = "Equipo que realiza la acción." },
    { name = "event_type", type = "STRING", mode = "REQUIRED", description = "Tipo de evento." },
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED", description = "Tiempo de ocurrencia del evento." },
    { name = "ingestion_time", type = "TIMESTAMP", mode = "REQUIRED", description = "Tiempo de carga en el almacén." },
    { name = "minute", type = "INTEGER", mode = "NULLABLE", description = "Minuto de partido." },
    { name = "second", type = "INTEGER", mode = "NULLABLE", description = "Segundo dentro del minuto." },
    { name = "period", type = "INTEGER", mode = "NULLABLE", description = "Periodo reglamentario (1 o 2)." },
    { name = "time_window_15m", type = "STRING", mode = "NULLABLE", description = "Ventana temporal de 15m (ej. 00-15)." },
    { name = "xg", type = "FLOAT", mode = "NULLABLE", description = "Goles esperados en remates/goles." },
    { name = "x", type = "FLOAT", mode = "NULLABLE", description = "Coordenada X en campo." },
    { name = "y", type = "FLOAT", mode = "NULLABLE", description = "Coordenada Y en campo." }
  ])
}

resource "google_bigquery_table" "fact_market_signals" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "fact_market_signals"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  time_partitioning {
    type  = "DAY"
    field = "event_time"
  }

  clustering = ["match_id", "market"]

  schema = jsonencode([
    { name = "signal_id", type = "STRING", mode = "REQUIRED", description = "ID único de la señal." },
    { name = "match_id", type = "STRING", mode = "REQUIRED", description = "FK a dim_match." },
    { name = "operator", type = "STRING", mode = "REQUIRED", description = "FK a dim_operator." },
    { name = "market", type = "STRING", mode = "REQUIRED", description = "FK a dim_market." },
    { name = "outcome", type = "STRING", mode = "REQUIRED", description = "Resultado evaluado (home, draw, away, etc)." },
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED", description = "Instante de detección de la señal." },
    { name = "ingestion_time", type = "TIMESTAMP", mode = "REQUIRED", description = "Instante de carga en el almacén." },
    { name = "minute", type = "FLOAT", mode = "NULLABLE", description = "Minuto de juego al emitir señal." },
    { name = "time_window_15m", type = "STRING", mode = "NULLABLE", description = "Ventana temporal de 15m." },
    { name = "model_probability", type = "FLOAT", mode = "REQUIRED", description = "Probabilidad estimada por modelo." },
    { name = "market_probability", type = "FLOAT", mode = "REQUIRED", description = "Probabilidad implícita del mercado." },
    { name = "divergence", type = "FLOAT", mode = "REQUIRED", description = "Divergencia con signo (modelo - mercado)." },
    { name = "magnitude", type = "FLOAT", mode = "REQUIRED", description = "Magnitud absoluta de la divergencia." },
    # Procedencia de la señal (historia #25). NULLABLE: es la única forma de
    # añadir una columna a una tabla de BigQuery que ya existe.
    { name = "model_version", type = "STRING", mode = "NULLABLE", description = "Versión del modelo que calculó la probabilidad." },
    { name = "lineage_digest", type = "STRING", mode = "NULLABLE", description = "Huella de los eventos y la cuota que produjeron la señal." },
    { name = "lineage_event_count", type = "INTEGER", mode = "NULLABLE", description = "Cuántos eventos se plegaron en la huella." }
  ])
}
