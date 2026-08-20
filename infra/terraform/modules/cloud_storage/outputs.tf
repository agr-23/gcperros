output "bucket_name" {
  description = "Nombre del bucket creado."
  value       = google_storage_bucket.this.name
}

output "bucket_url" {
  description = "URL gs:// del bucket."
  value       = google_storage_bucket.this.url
}

output "bucket_self_link" {
  description = "Self link del bucket."
  value       = google_storage_bucket.this.self_link
}
