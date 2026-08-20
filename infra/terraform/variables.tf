###############################################################################
# Variables de entrada de la raíz
###############################################################################

variable "project_id" {
  description = "ID del proyecto de GCP (no el nombre ni el número). Ej: futbol-rt-471203."
  type        = string
}

variable "region" {
  description = "Región por defecto para los recursos regionales."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Nombre del ambiente: dev, qa o prod."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "qa", "prod"], var.environment)
    error_message = "environment debe ser dev, qa o prod."
  }
}

variable "resource_prefix" {
  description = <<-EOT
    Prefijo opcional para los nombres de topics y suscripciones.

    Por defecto va vacío: los topics se llaman exactamente `match-events` y
    `odds-updates`, que son los nombres fijados por el contrato de datos y
    que los generadores (HU-10) y el motor (HU-11/12) usan literalmente.
    El aislamiento entre ambientes se hace por proyecto de GCP, no por
    prefijo de recurso. Ver README, sección "Nombres de los topics".
  EOT
  type        = string
  default     = ""
}

variable "enable_apis" {
  description = "Habilita automáticamente las APIs necesarias en el proyecto."
  type        = bool
  default     = true
}

variable "topic_message_retention_duration" {
  description = <<-EOT
    Tiempo que el topic retiene los mensajes ya confirmados, en formato "600s".
    Habilita `seek` (reproducir un tramo del partido sin volver a publicarlo),
    útil para depurar el motor contra el mismo tráfico. Cuesta almacenamiento:
    24 h es suficiente para un partido y mantiene el gasto en el nivel gratuito.
  EOT
  type        = string
  default     = "86400s"
}

variable "allowed_persistence_regions" {
  description = <<-EOT
    Regiones donde Pub/Sub puede persistir los mensajes. Lista vacía = sin
    restricción (Google elige). Fijarla a la región del proyecto documenta la
    residencia del dato, exigible bajo la Ley 1581 cuando el flujo deje de ser
    sintético. Ej: ["us-central1"].
  EOT
  type        = list(string)
  default     = []
}

###############################################################################
# Motor analítico (Cloud Run) — HU-11 / HU-12, aún sin imagen desplegada.
#
# Mientras `engine_push_endpoint` sea null, las suscripciones push no se crean
# y la capa de ingestión queda operando solo con las suscripciones pull. Al
# desplegar el motor basta con poner su URL aquí: no hay que tocar el código.
###############################################################################

variable "engine_push_endpoint" {
  description = "URL HTTPS base del motor en Cloud Run (sin la ruta). null = no crear suscripciones push."
  type        = string
  default     = null
}

variable "engine_push_path" {
  description = "Ruta del endpoint que recibe las entregas push de Pub/Sub."
  type        = string
  default     = "/pubsub/push"
}

variable "engine_service_name" {
  description = <<-EOT
    Nombre del servicio de Cloud Run que aloja el motor. Cuando se indica junto
    con `engine_push_endpoint`, Terraform le concede `roles/run.invoker` a la
    service account que firma las entregas push. null = no conceder nada.
  EOT
  type        = string
  default     = null
}

variable "engine_ack_deadline_seconds" {
  description = "Segundos que Pub/Sub espera el ack del motor antes de reintentar la entrega."
  type        = number
  default     = 30
}

variable "engine_max_delivery_attempts" {
  description = "Intentos de entrega antes de derivar el mensaje al topic de dead letter."
  type        = number
  default     = 5
}
