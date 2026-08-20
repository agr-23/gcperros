variable "project_id" {
  description = "ID del proyecto de GCP donde se crea el bucket."
  type        = string
}

variable "bucket_name" {
  description = "Nombre del bucket. Debe ser único en todo GCP."
  type        = string
}

variable "location" {
  description = "Ubicación del bucket (por ejemplo: US, EU, us-central1)."
  type        = string
  default     = "us-central1"
}

variable "storage_class" {
  description = "Clase de almacenamiento: STANDARD, NEARLINE, COLDLINE o ARCHIVE."
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"], var.storage_class)
    error_message = "storage_class debe ser STANDARD, NEARLINE, COLDLINE o ARCHIVE."
  }
}

variable "force_destroy" {
  description = "Si es true, permite destruir el bucket aunque contenga objetos. Úsalo con cuidado."
  type        = bool
  default     = false
}

variable "versioning_enabled" {
  description = "Habilita el versionado de objetos."
  type        = bool
  default     = true
}

variable "public_access_prevention" {
  description = "Prevención de acceso público: enforced o inherited."
  type        = string
  default     = "enforced"
}

variable "retention_period_seconds" {
  description = "Período de retención en segundos. null para no aplicar política de retención."
  type        = number
  default     = null
}

variable "lifecycle_rules" {
  description = "Reglas de ciclo de vida del bucket. action_type acepta Delete o SetStorageClass."
  type = list(object({
    action_type           = string
    action_storage_class  = optional(string)
    age                   = optional(number)
    num_newer_versions    = optional(number)
    with_state            = optional(string)
    matches_storage_class = optional(list(string))
  }))
  default = []
}

variable "iam_bindings" {
  description = "Mapa de rol IAM a lista de miembros. Ejemplo: { \"roles/storage.objectViewer\" = [\"serviceAccount:sa@proyecto.iam.gserviceaccount.com\"] }"
  type        = map(list(string))
  default     = {}
}

variable "notification_topic_id" {
  description = "ID del topic de Pub/Sub que recibe notificaciones de objetos. null para deshabilitar."
  type        = string
  default     = null
}

variable "notification_event_types" {
  description = "Tipos de evento que disparan la notificación."
  type        = list(string)
  default     = ["OBJECT_FINALIZE"]
}

variable "labels" {
  description = "Etiquetas aplicadas al bucket."
  type        = map(string)
  default     = {}
}
