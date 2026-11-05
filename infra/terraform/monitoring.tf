###############################################################################
# Supervisión operativa y alertas automáticas de SLA (HU-30)
#
# Declara las políticas de alerta en Cloud Monitoring para las cuatro métricas
# críticas del pipeline:
# 1. Latencia p95 > 2.000 ms (SLA declarado)
# 2. Backlog en cola de eventos > 50 mensajes
# 3. Tasa de rechazo en la frontera > 5 %
###############################################################################

resource "google_monitoring_alert_policy" "p95_latency_sla" {
  display_name = "gcperros-alerta-latencia-p95-sla"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Latencia p95 por encima del SLA de 2s"

    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 2000.0

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_PERCENTILE_95"
      }
    }
  }

  documentation {
    content   = "La latencia p95 del motor supera el SLA de 2 segundos declarado en HU-30."
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "backlog_threshold" {
  display_name = "gcperros-alerta-backlog-alto"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Mensajes sin procesar en cola Pub/Sub superan 50"

    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 50.0

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  documentation {
    content   = "El backlog acumulado en Pub/Sub supera los 50 eventos (riesgo de saturación del consumidor)."
    mime_type = "text/markdown"
  }
}
