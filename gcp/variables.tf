variable "project_id" {
  description = "The GCP project ID to deploy resources into."
  type        = string
  default     = "successfulsuccess-inna-2026"
}

variable "region" {
  description = "The GCP region for regional resources (Cloud Run, Cloud SQL, Artifact Registry)."
  type        = string
  default     = "us-central1"
}

variable "project_name" {
  description = "Application and resource naming prefix."
  type        = string
  default     = "successfulsuccess"
}

variable "api_image" {
  description = "Docker image for Cloud Run API service."
  type        = string
  default     = "us-central1-docker.pkg.dev/successfulsuccess-inna-2026/successfulsuccess-repo/api:v1"
}

variable "cognito_user_pool_id" {
  description = "AWS Cognito User Pool ID for JWT authentication (hybrid architecture)."
  type        = string
  default     = "us-east-1_3S0UCWv42"
}

variable "cognito_client_id" {
  description = "AWS Cognito App Client ID for JWT authentication."
  type        = string
  default     = "3rfpq2s4rhl2ap2n49lvpu0k35"
}

variable "cognito_region" {
  description = "AWS region hosting the Cognito User Pool."
  type        = string
  default     = "us-east-1"
}

variable "app_timezone" {
  description = "Application timezone for meetings business logic."
  type        = string
  default     = "Europe/Kyiv"
}

variable "cors_origins" {
  description = "Comma-separated list of allowed CORS origins for FastAPI."
  type        = string
  default     = "http://localhost:3000,https://successfulsuccess-inna-2026.web.app,https://successfulsuccess-inna-2026.firebaseapp.com"
}

variable "log_level" {
  description = "Logging level for the FastAPI application."
  type        = string
  default     = "INFO"
}
