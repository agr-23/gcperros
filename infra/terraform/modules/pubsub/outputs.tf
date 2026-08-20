output "topic_id" {
  description = "ID completo del topic (projects/<proyecto>/topics/<nombre>)."
  value       = google_pubsub_topic.this.id
}

output "topic_name" {
  description = "Nombre corto del topic."
  value       = google_pubsub_topic.this.name
}

output "dead_letter_topic_id" {
  description = "ID del topic de mensajes muertos, si fue creado."
  value       = var.create_dead_letter_topic ? google_pubsub_topic.dead_letter[0].id : null
}

output "subscription_ids" {
  description = "Mapa nombre -> ID de cada suscripción creada."
  value       = { for k, v in google_pubsub_subscription.this : k => v.id }
}
