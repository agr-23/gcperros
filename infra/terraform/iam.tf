###############################################################################
# Identidades de la capa de ingestión
#
# Una service account por rol funcional, con privilegio mínimo y sin llaves
# descargadas: los procesos locales se autentican por suplantación
# (--impersonate-service-account), de modo que no existe ningún secreto que
# pueda terminar versionado en el repositorio.
#
# Los permisos concretos NO se declaran aquí: se pasan al módulo de Pub/Sub
# en pubsub.tf, para que cada permiso quede junto al recurso que protege.
###############################################################################

# Publica en los dos topics. La usan los generadores sintéticos (HU-10), que
# corren fuera de GCP: el MVP se desarrolla y depura a costo cero.
resource "google_service_account" "stream_publisher" {
  account_id   = "${local.prefix}gcperros-publisher"
  display_name = "Generadores sintéticos → Pub/Sub (${var.environment})"
  description  = "Publica eventos de partido y actualizaciones de cuotas en los topics de ingestión."
  project      = var.project_id

  depends_on = [google_project_service.this]
}

# Consume las suscripciones pull y persiste sin transformar en BigQuery Raw
# (HU-14). Separada de la anterior para que un compromiso del generador no
# habilite lectura del flujo, ni al revés.
resource "google_service_account" "raw_loader" {
  account_id   = "${local.prefix}gcperros-raw-loader"
  display_name = "Cargador de la capa Raw (${var.environment})"
  description  = "Consume las suscripciones pull y persiste los eventos crudos en BigQuery."
  project      = var.project_id

  depends_on = [google_project_service.this]
}

# Firma el token OIDC de las entregas push hacia Cloud Run. Solo existe cuando
# el motor ya está desplegado: sin servicio que invocar, la identidad sobra.
resource "google_service_account" "pubsub_invoker" {
  count = local.push_enabled ? 1 : 0

  account_id   = "${local.prefix}gcperros-ps-invoker"
  display_name = "Invocador del motor desde Pub/Sub (${var.environment})"
  description  = "Identidad con la que Pub/Sub firma las entregas push al motor analítico."
  project      = var.project_id

  depends_on = [google_project_service.this]
}

# Permite que Pub/Sub invoque el endpoint de push del motor. El servicio de
# Cloud Run se declara en la historia que despliega el motor; hasta entonces
# esta autorización no tiene destino y por eso viaja junto a la SA.
resource "google_cloud_run_v2_service_iam_member" "engine_invoker" {
  count = local.push_enabled && var.engine_service_name != null ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.engine_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.pubsub_invoker_email}"
}
