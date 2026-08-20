###############################################################################
# Módulo: Cloud Run (API v2)
# Crea un servicio de Cloud Run con service account dedicada, escalado,
# variables de entorno (planas y desde Secret Manager) e IAM de invocación.
###############################################################################

# Service account de ejecución del servicio. Se crea solo si no se entrega una.
resource "google_service_account" "runtime" {
  count = var.service_account_email == null ? 1 : 0

  account_id   = "${var.service_name}-sa"
  display_name = "Service account de ejecución para ${var.service_name}"
  project      = var.project_id
}

locals {
  runtime_service_account = coalesce(
    var.service_account_email,
    try(google_service_account.runtime[0].email, null)
  )
}

resource "google_cloud_run_v2_service" "this" {
  name                = var.service_name
  project             = var.project_id
  location            = var.region
  ingress             = var.ingress
  labels              = var.labels
  deletion_protection = var.deletion_protection

  template {
    service_account                  = local.runtime_service_account
    timeout                          = "${var.timeout_seconds}s"
    max_instance_request_concurrency = var.concurrency
    execution_environment            = var.execution_environment

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      ports {
        name           = "http1"
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # cpu_idle = true -> solo se factura CPU durante la petición.
        cpu_idle          = var.cpu_idle
        startup_cpu_boost = var.startup_cpu_boost
      }

      dynamic "env" {
        for_each = var.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env_vars
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }

      dynamic "startup_probe" {
        for_each = var.startup_probe_path == null ? [] : [1]
        content {
          initial_delay_seconds = 5
          period_seconds        = 10
          failure_threshold     = 3
          timeout_seconds       = 3
          http_get {
            path = var.startup_probe_path
            port = var.container_port
          }
        }
      }

      dynamic "liveness_probe" {
        for_each = var.liveness_probe_path == null ? [] : [1]
        content {
          period_seconds    = 30
          failure_threshold = 3
          timeout_seconds   = 3
          http_get {
            path = var.liveness_probe_path
            port = var.container_port
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    # La imagen suele actualizarla el pipeline de CI/CD, no Terraform.
    ignore_changes = [client, client_version]
  }
}

# Acceso público sin autenticación (útil para APIs abiertas o demos).
resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.allow_public_access ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.this.location
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Invocadores autenticados (por ejemplo, la SA que usa Pub/Sub para el push).
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)

  project  = var.project_id
  location = google_cloud_run_v2_service.this.location
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = each.value
}

# Roles a nivel de proyecto para la service account de ejecución.
resource "google_project_iam_member" "runtime_roles" {
  for_each = var.service_account_email == null ? toset(var.runtime_project_roles) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${local.runtime_service_account}"
}
