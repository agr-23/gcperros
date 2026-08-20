###############################################################################
# Servicio: Pub/Sub — capa de ingestión
#
# El módulo `modules/pubsub` es el que entregó el profesor, sin modificar.
# Se invoca una vez por flujo con `for_each` sobre `local.streams`: la misma
# definición reutilizada produce dos topics independientes, cada uno con su
# suscripción pull, su suscripción push opcional y su topic de dead letter.
# Agregar un tercer flujo es agregar una entrada al mapa, no copiar un bloque.
###############################################################################

module "pubsub" {
  source   = "./modules/pubsub"
  for_each = local.streams

  project_id = var.project_id
  topic_name = "${local.prefix}${each.key}"

  topic_message_retention_duration = var.topic_message_retention_duration
  allowed_persistence_regions      = var.allowed_persistence_regions

  # Los mensajes que el motor no logra procesar tras N intentos no se pierden
  # ni bloquean la suscripción: quedan en `<topic>-dead-letter` para inspección.
  # Es el complemento operativo del repositorio de eventos inválidos de HU-16,
  # que atiende el rechazo por contrato; esto atiende el fallo por proceso.
  create_dead_letter_topic = true

  subscriptions = local.subscriptions_by_stream[each.key]

  # Quién puede publicar en el topic: solo los generadores sintéticos.
  topic_iam_bindings = {
    "roles/pubsub.publisher" = [
      "serviceAccount:${google_service_account.stream_publisher.email}",
    ]
  }

  # Quién puede consumir cada suscripción. El cargador de la capa Raw solo ve
  # su propia suscripción pull; no tiene alcance sobre la del motor.
  subscription_iam_bindings = {
    "${local.prefix}${each.key}-raw" = {
      "roles/pubsub.subscriber" = [
        "serviceAccount:${google_service_account.raw_loader.email}",
      ]
    }
  }

  # La etiqueta `contract_version` deja el contrato de datos vigente visible
  # en la propia infraestructura y en el reporte de facturación (HU-16).
  labels = merge(local.common_labels, {
    stream           = each.key
    contract_version = each.value.contract_version
  })

  depends_on = [google_project_service.this]
}
