###############################################################################
# Módulo: Cloud Storage
# Crea un bucket con acceso uniforme, prevención de acceso público,
# versionado opcional, reglas de ciclo de vida e IAM a nivel de bucket.
###############################################################################

resource "google_storage_bucket" "this" {
  name          = var.bucket_name
  project       = var.project_id
  location      = var.location
  storage_class = var.storage_class
  force_destroy = var.force_destroy
  labels        = var.labels

  # Buenas prácticas de seguridad: sin ACLs heredadas y sin exposición pública.
  uniform_bucket_level_access = true
  public_access_prevention    = var.public_access_prevention

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.lifecycle_rules
    content {
      action {
        type          = lifecycle_rule.value.action_type
        storage_class = try(lifecycle_rule.value.action_storage_class, null)
      }
      condition {
        age                   = try(lifecycle_rule.value.age, null)
        num_newer_versions    = try(lifecycle_rule.value.num_newer_versions, null)
        with_state            = try(lifecycle_rule.value.with_state, null)
        matches_storage_class = try(lifecycle_rule.value.matches_storage_class, null)
      }
    }
  }

  dynamic "retention_policy" {
    for_each = var.retention_period_seconds == null ? [] : [1]
    content {
      retention_period = var.retention_period_seconds
      is_locked        = false
    }
  }
}

# Notificaciones del bucket hacia un topic de Pub/Sub (opcional).
resource "google_storage_notification" "this" {
  count = var.notification_topic_id == null ? 0 : 1

  bucket         = google_storage_bucket.this.name
  topic          = var.notification_topic_id
  payload_format = "JSON_API_V1"
  event_types    = var.notification_event_types
}

# Aplanamos el mapa rol -> [miembros] en pares individuales.
locals {
  iam_pairs = flatten([
    for role, members in var.iam_bindings : [
      for member in members : {
        key    = "${role}::${member}"
        role   = role
        member = member
      }
    ]
  ])
}

resource "google_storage_bucket_iam_member" "this" {
  for_each = { for pair in local.iam_pairs : pair.key => pair }

  bucket = google_storage_bucket.this.name
  role   = each.value.role
  member = each.value.member
}
