###############################################################################
# Valores calculados, nombres de recursos y definición de los dos flujos
###############################################################################

locals {
  # Prefijo opcional. Vacío por defecto: ver variables.tf > resource_prefix.
  prefix = var.resource_prefix == "" ? "" : "${var.resource_prefix}-"

  common_labels = {
    environment = var.environment
    managed_by  = "terraform"
    application = "gcperros"
  }

  #############################################################################
  # Capa de ingestión: los dos flujos de la arquitectura.
  #
  # Cada fuente tiene su propia dinámica temporal —los eventos de juego llegan
  # cada ~3 s de forma regular, las cuotas llegan en ráfagas reactivas— y por
  # eso viajan en topics separados y no en uno solo con un campo de tipo:
  # se escalan, se retienen y se auditan por separado.
  #############################################################################
  streams = {
    "match-events" = {
      contract_version = "v1"
      producer         = "Generador de eventos de partido (HU-8)"
      description      = "Acciones del partido: pases, tiros, goles, faltas, cambios de posesión."
    }

    "odds-updates" = {
      contract_version = "v1"
      producer         = "Generador de cuotas sintéticas (HU-9)"
      description      = "Actualizaciones de cuotas por mercado, reactivas a los eventos del partido."
    }
  }

  # El motor solo se conecta por push cuando ya existe su URL de Cloud Run.
  push_enabled         = var.engine_push_endpoint != null
  pubsub_invoker_email = one(google_service_account.pubsub_invoker[*].email)
  engine_push_url      = local.push_enabled ? "${trimsuffix(var.engine_push_endpoint, "/")}${var.engine_push_path}" : null

  #############################################################################
  # Suscripciones por flujo.
  #
  # Nota sobre `enable_message_ordering = false`: es una decisión, no un olvido.
  # Activar las claves de ordenamiento de Pub/Sub serializaría la entrega y
  # ocultaría exactamente el fenómeno que el motor debe resolver por sí mismo
  # —el desorden temporal— mediante marcas de agua sobre `event_time` (HU-12).
  # El desorden es premisa de diseño del proyecto, no un defecto a suprimir en
  # el broker.
  #############################################################################

  # Suscripción pull: la consume el cargador de la capa Raw de BigQuery (HU-14).
  # 7 días de retención dan margen para reprocesar un partido sin regenerarlo.
  raw_subscriptions = {
    for name, cfg in local.streams : name => {
      "${local.prefix}${name}-raw" = {
        push_endpoint              = null
        push_service_account_email = null
        push_audience              = null
        ack_deadline_seconds       = 60
        message_retention_duration = "604800s"
        retain_acked_messages      = false
        enable_message_ordering    = false
        filter                     = null
        max_delivery_attempts      = 5
        minimum_backoff            = "10s"
        maximum_backoff            = "600s"
        expiration_ttl             = ""
      }
    }
  }

  # Suscripción push hacia el motor analítico. El `for ... if` la deja fuera
  # del plan mientras no exista la URL del servicio.
  engine_subscriptions = {
    for name, cfg in local.streams : name => {
      for sub_name, sub in {
        "${local.prefix}${name}-engine" = {
          push_endpoint              = local.engine_push_url
          push_service_account_email = local.pubsub_invoker_email
          push_audience              = var.engine_push_endpoint
          ack_deadline_seconds       = var.engine_ack_deadline_seconds
          message_retention_duration = "604800s"
          retain_acked_messages      = false
          enable_message_ordering    = false
          filter                     = null
          max_delivery_attempts      = var.engine_max_delivery_attempts
          minimum_backoff            = "10s"
          maximum_backoff            = "600s"
          expiration_ttl             = ""
        }
      } : sub_name => sub if local.push_enabled
    }
  }

  subscriptions_by_stream = {
    for name, cfg in local.streams : name => merge(
      local.raw_subscriptions[name],
      local.engine_subscriptions[name],
    )
  }
}
