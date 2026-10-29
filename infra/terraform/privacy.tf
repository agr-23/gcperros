###############################################################################
# Datos de usuario (historia #27)
#
# Lo único del sistema con una persona real detrás: las sesiones y los mercados
# que siguen, ya seudonimizados en la frontera (governance/privacy.py), y la
# clave que permite reidentificarlos. Los permisos traducen la matriz de acceso
# de governance/access.py, y tests/test_access_terraform.py comprueba que no se
# contradigan: quien puede leer las sesiones no puede tocar la clave.
#
# Los responsables humanos llegan por variable (grupos o usuarios), nunca
# escritos aquí: el repositorio no guarda direcciones de nadie.
###############################################################################

# La frontera que seudonimiza: necesita la clave y publica el resultado, pero
# no puede leer lo publicado. Es la única identidad que ve la clave y una
# sesión a la vez, y sólo durante el instante en que la seudonimiza.
resource "google_service_account" "user_activity_ingest" {
  account_id   = "${local.prefix}gcperros-user-ingest"
  display_name = "Frontera de la actividad de usuario (${var.environment})"
  description  = "Seudonimiza sesiones y preferencias al llegar y publica el resultado."
  project      = var.project_id

  depends_on = [google_project_service.this]
}

resource "google_pubsub_topic" "user_activity" {
  name    = "${local.prefix}user-activity"
  project = var.project_id
  labels  = merge(local.common_labels, { personal_data = "pseudonymized" })

  # Minimización: un día basta para entregar el mensaje. Los flujos deportivos
  # retienen más porque son sintéticos; éste no.
  message_retention_duration = "86400s"

  dynamic "message_storage_policy" {
    for_each = length(var.allowed_persistence_regions) > 0 ? [1] : []
    content {
      allowed_persistence_regions = var.allowed_persistence_regions
    }
  }

  depends_on = [google_project_service.this]
}

# Publicar no es leer: la frontera escribe en el topic y no puede suscribirse.
resource "google_pubsub_topic_iam_member" "user_activity_ingest_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.user_activity.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.user_activity_ingest.email}"
}

# Arquitectura administra la actividad (matriz: manage). Nadie más la lee.
resource "google_pubsub_topic_iam_member" "user_activity_architecture" {
  for_each = toset(var.architecture_members)

  project = var.project_id
  topic   = google_pubsub_topic.user_activity.name
  role    = "roles/pubsub.admin"
  member  = each.value
}

# Sólo el contenedor de la clave. El valor se carga a mano fuera de Terraform:
# un `google_secret_manager_secret_version` lo dejaría escrito en el estado.
resource "google_secret_manager_secret" "pseudonym_key" {
  secret_id = "${local.prefix}pseudonym-key"
  project   = var.project_id
  labels    = merge(local.common_labels, { personal_data = "reidentification-key" })

  replication {
    auto {}
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_iam_member" "pseudonym_key_ingest_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.pseudonym_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.user_activity_ingest.email}"
}

# Gobernanza administra la clave (matriz: manage) y no tiene acceso al topic.
resource "google_secret_manager_secret_iam_member" "pseudonym_key_governance" {
  for_each = toset(var.governance_members)

  project   = var.project_id
  secret_id = google_secret_manager_secret.pseudonym_key.secret_id
  role      = "roles/secretmanager.admin"
  member    = each.value
}
