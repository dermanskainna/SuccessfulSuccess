# =============================================================================
# SuccessfulSuccess Core: GCP Cloud Infrastructure
# =============================================================================

# -----------------------------------------------------------------------------
# 1. Google APIs Activation
# -----------------------------------------------------------------------------
locals {
  services = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# -----------------------------------------------------------------------------
# 2. Artifact Registry (Docker Images)
# -----------------------------------------------------------------------------
resource "google_artifact_registry_repository" "api_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "${var.project_name}-repo"
  description   = "Docker repository for ${var.project_name} services"
  format        = "DOCKER"

  depends_on = [google_project_service.apis["artifactregistry.googleapis.com"]]
}

# -----------------------------------------------------------------------------
# 3. Service Account & IAM Roles for Cloud Run API
# -----------------------------------------------------------------------------
resource "google_service_account" "api_sa" {
  project      = var.project_id
  account_id   = "${var.project_name}-api-sa"
  display_name = "${var.project_name} Cloud Run API Service Account"

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# -----------------------------------------------------------------------------
# 4. Cloud SQL (PostgreSQL 16) Database
# -----------------------------------------------------------------------------
resource "random_id" "db_suffix" {
  byte_length = 4
}

resource "google_sql_database_instance" "db_instance" {
  project             = var.project_id
  name                = "${var.project_name}-pg-${random_id.db_suffix.hex}"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    disk_size         = 10
    disk_type         = "PD_SSD"
    activation_policy = "ALWAYS"

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.apis["sqladmin.googleapis.com"]]
}

resource "google_sql_database" "app_db" {
  project  = var.project_id
  name     = var.project_name
  instance = google_sql_database_instance.db_instance.name
}

resource "random_password" "db_password" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "google_sql_user" "app_user" {
  project  = var.project_id
  name     = "appuser"
  instance = google_sql_database_instance.db_instance.name
  password = random_password.db_password.result
}

# -----------------------------------------------------------------------------
# 5. Secret Manager (Database Connection URL)
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "${var.project_name}-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis["secretmanager.googleapis.com"]]
}

resource "google_secret_manager_secret_version" "database_url_val" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = "postgresql+asyncpg://${google_sql_user.app_user.name}:${random_password.db_password.result}@/${google_sql_database.app_db.name}?host=/cloudsql/${google_sql_database_instance.db_instance.connection_name}"
}

# -----------------------------------------------------------------------------
# 6. Cloud Run v2 Service (FastAPI Backend)
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "api_service" {
  project  = var.project_id
  name     = "${var.project_name}-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.db_instance.connection_name]
      }
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }


      env {
        name  = "APP_TIMEZONE"
        value = var.app_timezone
      }

      env {
        name  = "CORS_ORIGINS"
        value = var.cors_origins
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "RUN_MIGRATIONS_ON_START"
        value = "false"
      }

      # AWS Cognito integration for Hybrid Auth Mode
      env {
        name  = "COGNITO_USER_POOL_ID"
        value = var.cognito_user_pool_id
      }

      env {
        name  = "COGNITO_CLIENT_ID"
        value = var.cognito_client_id
      }

      env {
        name  = "COGNITO_REGION"
        value = var.cognito_region
      }

      # Sensitive database connection string injected securely from Secret Manager
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis["run.googleapis.com"],
    google_project_iam_member.cloudsql_client,
    google_project_iam_member.secret_accessor,
    google_secret_manager_secret_version.database_url_val,
  ]
}

# Public access for Cloud Run service (invoker role for allUsers)
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api_service.location
  name     = google_cloud_run_v2_service.api_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
