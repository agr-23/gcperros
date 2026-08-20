variable "project_id" {
  description = "ID del proyecto de GCP."
  type        = string
}

variable "service_name" {
  description = "Nombre del servicio de Cloud Run."
  type        = string
}

variable "region" {
  description = "Región donde se despliega el servicio (por ejemplo us-central1)."
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Imagen del contenedor. Ejemplo: us-central1-docker.pkg.dev/proyecto/repo/app:v1"
  type        = string
}

variable "container_port" {
  description = "Puerto donde escucha el contenedor."
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "CPU asignada por instancia (1, 2, 4...)."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memoria asignada por instancia (512Mi, 1Gi, 2Gi...)."
  type        = string
  default     = "512Mi"
}

variable "cpu_idle" {
  description = "Si es true, la CPU se asigna solo durante la atención de peticiones."
  type        = bool
  default     = true
}

variable "startup_cpu_boost" {
  description = "Asigna CPU adicional durante el arranque de la instancia."
  type        = bool
  default     = true
}

variable "min_instances" {
  description = "Número mínimo de instancias. 0 permite escalar a cero."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Número máximo de instancias."
  type        = number
  default     = 5
}

variable "concurrency" {
  description = "Máximo de peticiones simultáneas por instancia."
  type        = number
  default     = 80
}

variable "timeout_seconds" {
  description = "Tiempo máximo de una petición en segundos."
  type        = number
  default     = 300
}

variable "execution_environment" {
  description = "Entorno de ejecución: EXECUTION_ENVIRONMENT_GEN1 o EXECUTION_ENVIRONMENT_GEN2."
  type        = string
  default     = "EXECUTION_ENVIRONMENT_GEN2"
}

variable "ingress" {
  description = "Control de ingreso: INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY o INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "env_vars" {
  description = "Variables de entorno en texto plano."
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Variables de entorno tomadas de Secret Manager. Ejemplo: { API_KEY = { secret = \"api-key\", version = \"latest\" } }"
  type = map(object({
    secret  = string
    version = optional(string, "latest")
  }))
  default = {}
}

variable "startup_probe_path" {
  description = "Ruta HTTP para el startup probe. null para omitirlo."
  type        = string
  default     = null
}

variable "liveness_probe_path" {
  description = "Ruta HTTP para el liveness probe. null para omitirlo."
  type        = string
  default     = null
}

variable "service_account_email" {
  description = "Correo de una service account existente. Si es null, el módulo crea una dedicada."
  type        = string
  default     = null
}

variable "runtime_project_roles" {
  description = "Roles de proyecto asignados a la service account creada por el módulo."
  type        = list(string)
  default = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ]
}

variable "allow_public_access" {
  description = "Si es true, permite invocaciones sin autenticación (allUsers)."
  type        = bool
  default     = false
}

variable "invoker_members" {
  description = "Miembros IAM que pueden invocar el servicio de forma autenticada."
  type        = list(string)
  default     = []
}

variable "deletion_protection" {
  description = "Protección contra borrado del servicio."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Etiquetas aplicadas al servicio."
  type        = map(string)
  default     = {}
}
