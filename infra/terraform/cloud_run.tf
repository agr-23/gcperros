###############################################################################
# El motor en Cloud Run, si se indica `engine_image` (la del Dockerfile). Su URL
# alimenta las suscripciones push (locals.tf) y su nombre, el permiso de
# Pub/Sub para invocarlo (iam.tf). Corre con la identidad del motor.
###############################################################################

resource "google_cloud_run_v2_service" "engine" {
  count = var.engine_image != null ? 1 : 0

  name     = local.engine_service_name
  project  = var.project_id
  location = var.region
  labels   = local.common_labels

  template {
    service_account = google_service_account.engine.email

    scaling {
      min_instance_count = var.engine_min_instances
      max_instance_count = var.engine_max_instances
    }

    containers {
      image = var.engine_image

      ports {
        container_port = var.engine_container_port
      }

      resources {
        limits = {
          cpu    = var.engine_cpu
          memory = var.engine_memory
        }
      }

      # PORT lo pone Cloud Run; el proyecto, para el cliente de Firestore.
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      dynamic "env" {
        for_each = var.engine_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      startup_probe {
        http_get {
          path = var.engine_health_path
        }
      }

      liveness_probe {
        http_get {
          path = var.engine_health_path
        }
      }
    }
  }

  depends_on = [google_project_service.this]
}
