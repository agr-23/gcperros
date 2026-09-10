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

###############################################################################
# Capa histórica Raw en BigQuery — HU-14
###############################################################################

variable "raw_dataset_id" {
  description = <<-EOT
    Nombre del dataset de BigQuery que contiene las tablas Raw. Debe coincidir
    con `--dataset` en `gcperros-load-raw` (por defecto, `gcperros_raw`).
  EOT
  type        = string
  default     = "gcperros_raw"
}

variable "raw_dataset_location" {
  description = <<-EOT
    Ubicación del dataset. BigQuery la fija al crearlo y no se puede cambiar
    después sin recrear el dataset; por defecto multi-región de EE. UU. para
    quedar dentro del nivel gratuito durante el proyecto.
  EOT
  type        = string
  default     = "US"
}

variable "raw_partition_expiration_ms" {
  description = <<-EOT
    Milisegundos que una partición sobrevive antes de expirar. `null` = nunca
    expira, que es la premisa de la capa histórica (acumular desde el Sprint 1
    y no perder nada). Se deja como variable y no como constante porque un
    ambiente de pruebas sí puede querer expirar particiones viejas para no
    acumular costo de almacenamiento sin necesidad.
  EOT
  type        = number
  default     = null
}

variable "raw_table_deletion_protection" {
  description = <<-EOT
    Impide que `terraform destroy` borre las tablas Raw. Se desactiva sólo en
    ambientes desechables (por ejemplo, para recrear el dataset durante el
    desarrollo); en producción debe quedar en `true`.
  EOT
  type        = bool
  default     = true
}

###############################################################################
# Estado vivo en Firestore — HU-15
###############################################################################

variable "firestore_location_id" {
  description = <<-EOT
    Ubicación de la base de datos Firestore. No admite cualquier región de
    GCP: Firestore restringe sus bases a una lista propia de ubicaciones
    (regionales o multi-región). `nam5` es la multi-región de Norteamérica,
    la recomendada por defecto y la que Google documenta como elegible para
    el nivel gratuito. Firestore la fija al crear la base y no se puede
    cambiar después sin recrearla.
  EOT
  type        = string
  default     = "nam5"
}

variable "firestore_deletion_policy" {
  description = <<-EOT
    Qué hace `terraform destroy` con la base de datos: `ABANDON` la retira
    del estado de Terraform sin borrar los datos (el valor seguro, por
    defecto); `DELETE` sí la elimina de verdad, útil sólo en un ambiente
    desechable donde recrear la base de datos completa es aceptable.
  EOT
  type        = string
  default     = "ABANDON"

  validation {
    condition     = contains(["ABANDON", "DELETE"], var.firestore_deletion_policy)
    error_message = "firestore_deletion_policy debe ser \"ABANDON\" o \"DELETE\"."
  }
}

##################################################
# Motor analítico (Cloud Run) — despliegue propio
##################################################

variable "engine_image" {
  description = <<-EOT
    Imagen del motor en Artifact Registry, ej:
    us-central1-docker.pkg.dev/<proyecto>/gcperros/engine:v1

    null (por defecto) = no desplegar Cloud Run desde esta raíz. Sigue siendo
    válido apuntar `engine_push_endpoint` a un servicio desplegado por otro
    medio; las dos rutas conviven, ver locals.tf.
  EOT
  type        = string
  default     = null
}

variable "engine_container_port" {
  description = "Puerto en el que escucha el contenedor del motor."
  type        = number
  default     = 8080
}

variable "engine_health_path" {
  description = "Ruta de healthcheck del motor, usada en startup y liveness probe."
  type        = string
  default     = "/healthz"
}

variable "engine_min_instances" {
  description = "Instancias mínimas del motor. 0 permite escalar a cero entre partidos."
  type        = number
  default     = 0
}

variable "engine_max_instances" {
  description = "Instancias máximas del motor."
  type        = number
  default     = 3
}

variable "engine_cpu" {
  description = "CPU por instancia del motor."
  type        = string
  default     = "1"
}

variable "engine_memory" {
  description = "Memoria por instancia del motor."
  type        = string
  default     = "512Mi"
}

variable "engine_env_vars" {
  description = "Variables de entorno adicionales del motor, en texto plano."
  type        = map(string)
  default     = {}
}

variable "create_artifact_registry" {
  description = <<-EOT
    Crea el repositorio de Artifact Registry donde vive la imagen del motor.
    En false porque el repositorio puede preexistir o gestionarse por otra
    parte del pipeline de CI/CD; en true, esta raíz lo declara y lo posee.
  EOT
  type        = bool
  default     = false
}

variable "artifact_registry_repository_id" {
  description = "Nombre del repositorio de Artifact Registry para la imagen del motor."
  type        = string
  default     = "gcperros"
}
