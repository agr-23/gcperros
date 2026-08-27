###############################################################################
# Habilitación de las APIs requeridas
# Sin estas APIs activas, los recursos fallan con error 403 SERVICE_DISABLED.
#
# Se habilita únicamente lo que esta capa usa hoy. Cloud Run y Firestore se
# agregan en las historias que los introducen (HU-15), para que el proyecto
# no acumule superficie habilitada sin recurso que la justifique.
###############################################################################

locals {
  required_apis = [
    "pubsub.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "bigquery.googleapis.com", # capa Raw (HU-14)
  ]
}

resource "google_project_service" "this" {
  for_each = var.enable_apis ? toset(local.required_apis) : toset([])

  project = var.project_id
  service = each.value

  # No deshabilitamos las APIs al destruir: otros recursos podrían usarlas.
  disable_on_destroy         = false
  disable_dependent_services = false
}
