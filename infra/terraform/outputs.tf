###############################################################################
# Salidas de la raíz
#
# Estas salidas son el contrato entre la infraestructura y el resto del
# proyecto: los generadores y el cargador Raw leen de aquí los identificadores
# que necesitan, en lugar de llevarlos escritos a mano en el código.
###############################################################################

output "topics" {
  description = "Flujo -> ID completo del topic (projects/<proyecto>/topics/<nombre>)."
  value       = { for name, mod in module.pubsub : name => mod.topic_id }
}

output "topic_names" {
  description = "Flujo -> nombre corto del topic, tal como lo usan los generadores."
  value       = { for name, mod in module.pubsub : name => mod.topic_name }
}

output "subscriptions" {
  description = "Flujo -> { nombre de suscripción -> ID }."
  value       = { for name, mod in module.pubsub : name => mod.subscription_ids }
}

output "dead_letter_topics" {
  description = "Flujo -> topic de mensajes muertos."
  value       = { for name, mod in module.pubsub : name => mod.dead_letter_topic_id }
}

output "publisher_service_account" {
  description = "Service account que deben suplantar los generadores para publicar."
  value       = google_service_account.stream_publisher.email
}

output "raw_loader_service_account" {
  description = "Service account que debe suplantar el cargador de la capa Raw."
  value       = google_service_account.raw_loader.email
}

output "engine_push_subscriptions_enabled" {
  description = "Indica si las suscripciones push hacia el motor están activas."
  value       = local.push_enabled
}
