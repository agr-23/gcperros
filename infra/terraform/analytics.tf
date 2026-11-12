###############################################################################
# Capa analítica histórica en BigQuery — Modelo Estrella (HU-22, HU-23)
#
# Tablas de hechos para eventos y señales con distinción explícita de
# event_time vs ingestion_time, particionadas por event_time y clusterizadas
# por match_id y market (o event_type) para optimizar consultas de benchmark.
#
# Multideporte (#94): una dimensión `dim_sport` y una columna `sport` en el
# partido y en los hechos. Todo lo que se añade es NULLABLE, porque es la única
# forma de añadir una columna a una tabla que ya existe; una fila sin deporte es
# de fútbol, que era el único deporte cuando se escribió. Los hechos del
# baloncesto comparten tabla con los del fútbol: el mismo sobre que comparten
# sus flujos, con las columnas de cada deporte vacías en el otro.
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

resource "google_bigquery_table" "dim_sport" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "dim_sport"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "sport", type = "STRING", mode = "REQUIRED", description = "Clave del deporte (football, basketball, american_football), la de --sport." },
    { name = "sport_name", type = "STRING", mode = "REQUIRED", description = "Nombre del deporte." },
    { name = "events_stream", type = "STRING", mode = "REQUIRED", description = "Flujo de sus eventos (match-events, basketball-events)." },
    { name = "odds_stream", type = "STRING", mode = "REQUIRED", description = "Flujo de sus cuotas (odds-updates, basketball-odds)." },
    { name = "periods", type = "INTEGER", mode = "REQUIRED", description = "Periodos reglamentarios: 2 partes o 4 cuartos." },
    { name = "period_minutes", type = "INTEGER", mode = "REQUIRED", description = "Duración de cada periodo, en minutos." }
  ])
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
    { name = "match_date", type = "DATE", mode = "REQUIRED", description = "Fecha del encuentro." },
    { name = "sport", type = "STRING", mode = "NULLABLE", description = "FK a dim_sport. Vacío en los partidos anteriores al segundo deporte: fútbol." }
  ])
}

resource "google_bigquery_table" "dim_market" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "dim_market"
  project             = var.project_id
  deletion_protection = var.raw_table_deletion_protection
  labels              = local.common_labels

  schema = jsonencode([
    { name = "market", type = "STRING", mode = "REQUIRED", description = "Clave del mercado (1x2, over_under_2_5, moneyline, total_points)." },
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
    { name = "period", type = "INTEGER", mode = "NULLABLE", description = "Periodo: parte (1 o 2) en fútbol, cuarto o prórroga en baloncesto." },
    { name = "time_window_15m", type = "STRING", mode = "NULLABLE", description = "Ventana temporal de 15m (ej. 00-15)." },
    { name = "xg", type = "FLOAT", mode = "NULLABLE", description = "Goles esperados en remates/goles." },
    { name = "x", type = "FLOAT", mode = "NULLABLE", description = "Coordenada X en campo o cancha." },
    { name = "y", type = "FLOAT", mode = "NULLABLE", description = "Coordenada Y en campo o cancha." },
    # Multideporte (#94). NULLABLE, y vacías en el deporte que no las tiene.
    { name = "sport", type = "STRING", mode = "NULLABLE", description = "FK a dim_sport. Vacío en los hechos anteriores al segundo deporte: fútbol." },
    { name = "points_value", type = "INTEGER", mode = "NULLABLE", description = "Lo que vale un tiro de baloncesto: 2 o 3; 1 el tiro libre." },
    { name = "made", type = "BOOLEAN", mode = "NULLABLE", description = "Si el tiro o el tiro libre entró." },
    { name = "expected_points", type = "FLOAT", mode = "NULLABLE", description = "Puntos esperados del tiro (modelo ep-1.0.0)." }
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
    { name = "lineage_event_count", type = "INTEGER", mode = "NULLABLE", description = "Cuántos eventos se plegaron en la huella." },
    { name = "sport", type = "STRING", mode = "NULLABLE", description = "FK a dim_sport (#94). Vacío en las señales anteriores al segundo deporte: fútbol." }
  ])
}
