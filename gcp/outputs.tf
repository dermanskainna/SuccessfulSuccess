output "artifact_registry_url" {
  description = "The URL of the Artifact Registry Docker repository."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.api_repo.repository_id}"
}

output "cloud_run_url" {
  description = "The public HTTPS URL of the Cloud Run FastAPI backend service."
  value       = google_cloud_run_v2_service.api_service.uri
}

output "cloud_sql_connection_name" {
  description = "The connection name of the Cloud SQL PostgreSQL instance (project:region:instance)."
  value       = google_sql_database_instance.db_instance.connection_name
}
