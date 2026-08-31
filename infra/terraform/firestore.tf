###############################################################################
# Servicio: Firestore — estado vivo por partido (HU-15)
#
# Una única base de datos en modo nativo, y ninguna colección declarada: a
# diferencia de una tabla de BigQuery, una colección de Firestore no se crea
# de antemano — aparece sola en cuanto el motor escribe el primer documento
# en `live_matches/{match_id}` (la colección la fija
# `gcperros.firestore.publisher.LIVE_MATCHES_COLLECTION`, en código, no aquí).
# Terraform sólo declara la base de datos que la contiene y quién puede
# escribir en ella.
#
# Modo nativo, y no modo Datastore, a propósito: es el que trae los listeners
# en tiempo real (`onSnapshot`) sobre los que se apoya todo el diseño de la
# historia — con modo Datastore el dashboard tendría que volver a sondear, que
# es exactamente lo que esta historia existe para evitar. Ver
# ``docs/decisiones-de-diseno.md``, sección 11.
###############################################################################

resource "google_firestore_database" "live_state" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location_id
  type        = "FIRESTORE_NATIVE"

  # GCP permite como mucho una base de datos Firestore llamada "(default)"
  # por proyecto; es también la que asume `FirestoreDocumentStore` cuando no
  # se le indica otra. Bases con nombre propio (una función más nueva de
  # Firestore) no hacen falta todavía: nada en el proyecto necesita separar
  # el estado vivo en más de una base de datos.
  #
  # `deletion_policy` protege contra un `terraform destroy` accidental, igual
  # que `deletion_protection` en las tablas Raw de BigQuery (HU-14): el
  # estado vivo puede reconstruirse desde la capa Raw en caso de necesidad,
  # pero no hay razón para arriesgarlo por un descuido de quien ejecuta
  # Terraform.
  deletion_policy = var.firestore_deletion_policy

  depends_on = [google_project_service.this]
}

# Quién puede escribir el documento de un partido. `roles/datastore.user` es
# el nombre correcto pese a las apariencias: Firestore en modo nativo es la
# evolución del producto Datastore, y hereda su catálogo de roles de IAM — no
# hay un `roles/firestore.user` aparte.
#
# El permiso se concede a nivel de proyecto y no de base de datos: a
# diferencia de un dataset de BigQuery, Firestore no tiene un recurso IAM
# propio por base de datos en este proveedor todavía, y con una sola base de
# datos en el proyecto la diferencia práctica es ninguna.
resource "google_project_iam_member" "engine_firestore_writer" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.engine.email}"

  depends_on = [google_firestore_database.live_state]
}
