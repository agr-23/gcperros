variable "project_id" {
  description = "ID del proyecto de GCP."
  type        = string
}

variable "topic_name" {
  description = "Nombre del topic de Pub/Sub."
  type        = string
}

variable "topic_message_retention_duration" {
  description = "Tiempo que el topic retiene los mensajes publicados (en segundos, formato '600s')."
  type        = string
  default     = "86400s"
}

variable "allowed_persistence_regions" {
  description = "Regiones donde se permite persistir los mensajes. Lista vacía = sin restricción."
  type        = list(string)
  default     = []
}

variable "create_dead_letter_topic" {
  description = "Crea un topic y una suscripción de mensajes muertos asociados al topic principal."
  type        = bool
  default     = true
}

variable "subscriptions" {
  description = <<-EOT
    Mapa de suscripciones. La clave es el nombre de la suscripción.
    Si push_endpoint es null la suscripción es de tipo pull.
  EOT
  type = map(object({
    push_endpoint              = optional(string)
    push_service_account_email = optional(string)
    push_audience              = optional(string)
    ack_deadline_seconds       = optional(number, 20)
    message_retention_duration = optional(string, "604800s")
    retain_acked_messages      = optional(bool, false)
    enable_message_ordering    = optional(bool, false)
    filter                     = optional(string)
    max_delivery_attempts      = optional(number, 5)
    minimum_backoff            = optional(string, "10s")
    maximum_backoff            = optional(string, "600s")
    expiration_ttl             = optional(string, "")
  }))
  default = {}
}

variable "topic_iam_bindings" {
  description = "Mapa de rol a lista de miembros aplicado al topic."
  type        = map(list(string))
  default     = {}
}

variable "subscription_iam_bindings" {
  description = "Mapa de nombre de suscripción a { rol = [miembros] }."
  type        = map(map(list(string)))
  default     = {}
}

variable "labels" {
  description = "Etiquetas aplicadas a los recursos de Pub/Sub."
  type        = map(string)
  default     = {}
}
