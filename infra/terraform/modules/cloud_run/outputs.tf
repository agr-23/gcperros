output "service_name" {
  description = "Nombre del servicio de Cloud Run."
  value       = google_cloud_run_v2_service.this.name
}

output "service_uri" {
  description = "URL pública (HTTPS) del servicio."
  value       = google_cloud_run_v2_service.this.uri
}

output "service_id" {
  description = "ID completo del servicio."
  value       = google_cloud_run_v2_service.this.id
}

output "service_account_email" {
  description = "Service account con la que se ejecuta el servicio."
  value       = local.runtime_service_account
}

output "latest_ready_revision" {
  description = "Última revisión lista para recibir tráfico."
  value       = google_cloud_run_v2_service.this.latest_ready_revision
}
