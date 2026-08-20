###############################################################################
# Módulo: Pub/Sub
# Crea un topic, sus suscripciones (pull o push) y, opcionalmente,
# un topic de mensajes muertos (dead letter) con su suscripción de retención.
###############################################################################

resource "google_pubsub_topic" "this" {
  name                       = var.topic_name
  project                    = var.project_id
  labels                     = var.labels
  message_retention_duration = var.topic_message_retention_duration

  dynamic "message_storage_policy" {
    for_each = length(var.allowed_persistence_regions) > 0 ? [1] : []
    content {
      allowed_persistence_regions = var.allowed_persistence_regions
    }
  }
}

# Topic de mensajes muertos: recibe lo que no pudo procesarse tras N intentos.
resource "google_pubsub_topic" "dead_letter" {
  count = var.create_dead_letter_topic ? 1 : 0

  name    = "${var.topic_name}-dead-letter"
  project = var.project_id
  labels  = var.labels
}

# Suscripción que retiene los mensajes muertos para inspección manual.
resource "google_pubsub_subscription" "dead_letter" {
  count = var.create_dead_letter_topic ? 1 : 0

  name    = "${var.topic_name}-dead-letter-sub"
  project = var.project_id
  topic   = google_pubsub_topic.dead_letter[0].id
  labels  = var.labels

  message_retention_duration = "604800s" # 7 días
  retain_acked_messages      = true
  ack_deadline_seconds       = 60
  expiration_policy {
    ttl = "" # nunca expira
  }
}

resource "google_pubsub_subscription" "this" {
  for_each = var.subscriptions

  name    = each.key
  project = var.project_id
  topic   = google_pubsub_topic.this.id
  labels  = var.labels

  ack_deadline_seconds       = each.value.ack_deadline_seconds
  message_retention_duration = each.value.message_retention_duration
  retain_acked_messages      = each.value.retain_acked_messages
  enable_message_ordering    = each.value.enable_message_ordering
  filter                     = each.value.filter

  # Suscripción push: se define solo si se entrega un endpoint HTTP.
  dynamic "push_config" {
    for_each = each.value.push_endpoint == null ? [] : [1]
    content {
      push_endpoint = each.value.push_endpoint

      dynamic "oidc_token" {
        for_each = each.value.push_service_account_email == null ? [] : [1]
        content {
          service_account_email = each.value.push_service_account_email
          audience              = coalesce(each.value.push_audience, each.value.push_endpoint)
        }
      }
    }
  }

  dynamic "dead_letter_policy" {
    for_each = var.create_dead_letter_topic ? [1] : []
    content {
      dead_letter_topic     = google_pubsub_topic.dead_letter[0].id
      max_delivery_attempts = each.value.max_delivery_attempts
    }
  }

  retry_policy {
    minimum_backoff = each.value.minimum_backoff
    maximum_backoff = each.value.maximum_backoff
  }

  expiration_policy {
    ttl = each.value.expiration_ttl
  }
}

# IAM sobre el topic (por ejemplo, roles/pubsub.publisher para un servicio).
locals {
  topic_iam_pairs = flatten([
    for role, members in var.topic_iam_bindings : [
      for member in members : {
        key    = "${role}::${member}"
        role   = role
        member = member
      }
    ]
  ])

  subscription_iam_pairs = flatten([
    for sub_name, bindings in var.subscription_iam_bindings : [
      for role, members in bindings : [
        for member in members : {
          key          = "${sub_name}::${role}::${member}"
          subscription = sub_name
          role         = role
          member       = member
        }
      ]
    ]
  ])
}

resource "google_pubsub_topic_iam_member" "this" {
  for_each = { for pair in local.topic_iam_pairs : pair.key => pair }

  project = var.project_id
  topic   = google_pubsub_topic.this.name
  role    = each.value.role
  member  = each.value.member
}

resource "google_pubsub_subscription_iam_member" "this" {
  for_each = { for pair in local.subscription_iam_pairs : pair.key => pair }

  project      = var.project_id
  subscription = google_pubsub_subscription.this[each.value.subscription].name
  role         = each.value.role
  member       = each.value.member
}

# Permite que el servicio interno de Pub/Sub publique en el dead letter topic
# y confirme mensajes en la suscripción de origen.
data "google_project" "this" {
  project_id = var.project_id
}

locals {
  pubsub_service_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  count = var.create_dead_letter_topic ? 1 : 0

  project = var.project_id
  topic   = google_pubsub_topic.dead_letter[0].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  for_each = var.create_dead_letter_topic ? var.subscriptions : {}

  project      = var.project_id
  subscription = google_pubsub_subscription.this[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}
