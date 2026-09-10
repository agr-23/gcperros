###############################################################################
# Artifact Registry — repositorio de la imagen del motor
#
# Condicional a `create_artifact_registry`: por defecto el repositorio se
# asume gestionado fuera de esta raíz (por ejemplo, por el pipeline de CI que
# construye y publica la imagen). Activarlo aquí es cómodo para quien quiera
# que `terraform apply` cree también el sitio donde `docker push` publica.
###############################################################################

resource "google_artifact_registry_repository" "engine" {
  count = var.create_artifact_registry ? 1 : 0

  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository_id
  format        = "DOCKER"
  description   = "Imágenes del motor analítico de GCPerros (HU-11/12/13)."
  labels        = local.common_labels

  depends_on = [google_project_service.this]
}
