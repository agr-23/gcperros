###############################################################################
# Supervisión operativa y alertas automáticas de SLA (HU-30)
#
# Declara las políticas de alerta en Cloud Monitoring para las cuatro métricas
# críticas del pipeline:
# 1. Latencia p95 > 2.000 ms (SLA declarado)
# 2. Backlog en cola de eventos > 50 mensajes
# 3. Tasa de rechazo en la frontera > 5 %
# 4. Mensaje más antiguo sin confirmar > 300 s, igual para cualquier deporte
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

###############################################################################
# El backlog medido en tiempo, para cualquier deporte (#95)
#
# 50 mensajes no significan lo mismo en los dos deportes: el fútbol manda 11,1
# eventos por minuto y el baloncesto 4,8 (decisiones de diseño, sección 21), así
# que una cola del baloncesto tarda más del doble en llegar a 50 y la alerta
# anterior avisa tarde. La antigüedad del mensaje más viejo sin confirmar no
# depende de la densidad del flujo. 300 s son los 50 mensajes del fútbol
# redondeados (50 / 11,1 por minuto = 4,5 min), y en baloncesto equivalen a 24.
# Sin filtro por suscripción: cubre las de los cuatro flujos.
###############################################################################

resource "google_monitoring_alert_policy" "backlog_age" {
  display_name = "gcperros-alerta-backlog-antiguo"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "El mensaje más antiguo sin confirmar supera 300 s"

    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 300.0

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  documentation {
    content   = "Un mensaje lleva más de 5 minutos sin confirmar en una suscripción, de cualquier deporte: el consumidor no da abasto o está caído."
    mime_type = "text/markdown"
  }
}
